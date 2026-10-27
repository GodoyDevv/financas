from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from .categories import (
    get_valid_category_names,
    normalize_category_name,
    resolve_canonical_name,
)
from .database import get_db
from .dates_and_money import month_range, to_decimal, today_br
from .models import Category, Recurrence, Transaction
from .parser import parse_text_message
from .schemas import (
    CategoryMetric,
    CategoryResponse,
    CategoryUpdate,
    FinancialSummary,
    MessageParseRequest,
    MessageParseResponse,
    MetricsResponse,
    RecurrenceCreate,
    RecurrenceResponse,
    RecurrenceUpdate,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)
from .services import clamp_day_in_month, criar_parcelamento, ensure_recurrences

router = APIRouter(prefix="/api", tags=["Transactions & Metrics"])


@router.get("/transactions", response_model=list[TransactionResponse])
def get_transactions(
    tipo: str | None = None,
    author: str | None = Query(None, description="Filtra por autor (ex: Bruno, Letícia)"),
    channel: str | None = Query(
        None, description="Filtra por canal (ex: whatsapp_text, whatsapp_audio, dashboard)"
    ),
    mes: str | None = Query(None, description="Mês no formato YYYY-MM (ex: 2026-10)"),
    db: Session = Depends(get_db),
):
    """
    Retorna a lista de transações.
    Se 'mes' for fornecido (ex: '2026-10'):
      - Materializa de forma idempotente as recorrências para o mês.
      - Filtra estritamente por intervalo de data do mês (data >= inicio AND data < fim).
    """
    if mes:
        try:
            inicio, fim = month_range(mes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Materialização preguiçosa de recorrências ativas
        ensure_recurrences(db, mes)

        query = db.query(Transaction).filter(
            (Transaction.data >= inicio) & (Transaction.data < fim)
        )
    else:
        query = db.query(Transaction)

    if tipo:
        query = query.filter(Transaction.tipo == tipo.lower())

    if author:
        query = query.filter(Transaction.author == author)

    if channel:
        query = query.filter(Transaction.channel == channel)

    rows = query.order_by(desc(Transaction.id)).all()
    return rows


@router.post("/transactions", response_model=TransactionResponse)
def create_transaction(transaction: TransactionCreate, db: Session = Depends(get_db)):
    """Cadastra um novo registro de receita, despesa fixa ou despesa variável."""
    valid_types = ["receita", "despesa_fixa", "despesa_variavel"]
    clean_tipo = transaction.tipo.lower()

    if clean_tipo == "despesa":
        clean_tipo = "despesa_variavel"

    if clean_tipo not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo inválido. Escolha um dos seguintes: {', '.join(valid_types)}",
        )

    # Canal e autor para chamadas da API/Dashboard
    author_val = transaction.author.strip() if transaction.author else None
    channel_val = (
        transaction.channel
        if transaction.channel and transaction.channel != "unknown"
        else "dashboard"
    )

    # Dual-write: source recebe author ou channel para não quebrar compatibilidade
    source_val = transaction.source.strip() if transaction.source else (author_val or channel_val)

    # Validação e resolução de categoria (Requisito 4):
    # Se vier do dashboard/API e for desconhecida -> 422 com lista válida
    canonical_name = resolve_canonical_name(transaction.categoria)
    if not canonical_name:
        valid_cats = get_valid_category_names()
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Categoria '{transaction.categoria}' não é válida.",
                "valid_categories": valid_cats,
            },
        )

    norm_name = normalize_category_name(canonical_name)
    cat_db = db.query(Category).filter(Category.normalized_name == norm_name).first()
    if not cat_db:
        # Se categoria canônica não estiver na tabela, cria de forma resiliente
        cat_db = Category(
            name=canonical_name,
            normalized_name=norm_name,
            tipo="receita" if clean_tipo == "receita" else "despesa",
            ativo=True,
        )
        db.add(cat_db)
        db.commit()
        db.refresh(cat_db)

    # Criação via serviço único de parcelamento (atômico e com identidade UUID)
    base_tx_dict = {
        "tipo": clean_tipo,
        "valor": to_decimal(transaction.valor),
        "categoria": cat_db.name,
        "category_id": cat_db.id,
        "data": transaction.data,
        "descricao": transaction.descricao.strip() if transaction.descricao else "",
        "author": author_val,
        "channel": channel_val,
        "source": source_val,
        "vencimento": transaction.vencimento.strip() if transaction.vencimento else None,
    }

    parcelas_count = transaction.parcelas or 1
    criadas = criar_parcelamento(db, base_tx_dict, parcelas=parcelas_count)
    return criadas[0]


@router.put("/transactions/{trans_id}", response_model=TransactionResponse)
def update_transaction(
    trans_id: int, transaction: TransactionUpdate, db: Session = Depends(get_db)
):
    """Atualiza um registro existente de receita, despesa fixa ou despesa variável."""
    existing = db.query(Transaction).filter(Transaction.id == trans_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Transação não encontrada")

    valid_types = ["receita", "despesa_fixa", "despesa_variavel"]

    if transaction.tipo is not None:
        new_tipo = transaction.tipo.lower()
        if new_tipo == "despesa":
            new_tipo = "despesa_variavel"
        if new_tipo not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo inválido. Escolha um dos seguintes: {', '.join(valid_types)}",
            )
        existing.tipo = new_tipo

    if transaction.valor is not None:
        existing.valor = to_decimal(transaction.valor)
    if transaction.categoria is not None:
        canonical_name = resolve_canonical_name(transaction.categoria)
        if not canonical_name:
            valid_cats = get_valid_category_names()
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"Categoria '{transaction.categoria}' não é válida.",
                    "valid_categories": valid_cats,
                },
            )
        norm_name = normalize_category_name(canonical_name)
        cat_db = db.query(Category).filter(Category.normalized_name == norm_name).first()
        if not cat_db:
            cat_db = Category(
                name=canonical_name,
                normalized_name=norm_name,
                tipo="receita" if existing.tipo == "receita" else "despesa",
                ativo=True,
            )
            db.add(cat_db)
            db.commit()
            db.refresh(cat_db)
        existing.categoria = cat_db.name
        existing.category_id = cat_db.id
    if transaction.data is not None:
        existing.data = transaction.data
    if transaction.descricao is not None:
        existing.descricao = transaction.descricao.strip()
    if transaction.author is not None:
        existing.author = transaction.author.strip() if transaction.author else None
        # Atualiza source se author for fornecido
        if existing.author:
            existing.source = existing.author
    if transaction.channel is not None:
        existing.channel = transaction.channel
    if transaction.source is not None:
        existing.source = transaction.source.strip()
    if transaction.vencimento is not None:
        existing.vencimento = transaction.vencimento.strip()

    # Requisito 5: Editar uma instância marca editado_manual=True
    if existing.recurrence_id is not None:
        existing.editado_manual = True

    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/transactions/{trans_id}")
def delete_transaction(
    trans_id: int,
    escopo: str = Query("uma", description="Escopo de exclusão: 'uma', 'grupo' ou 'futuras'"),
    todas_parcelas: bool = Query(
        False, description="[DEPRECATED] Compatibilidade reversa; mapeia para escopo='grupo'"
    ),
    db: Session = Depends(get_db),
):
    """
    Remove uma transação pelo seu ID ou suas parcelas associadas via parcela_grupo_id.
    Escopos:
    - 'uma': apaga exclusivamente a transação {trans_id}.
    - 'grupo': apaga todas as parcelas do mesmo grupo (parcela_grupo_id).
    - 'futuras': apaga da parcela atual em diante (parcela_num >= atual) do mesmo grupo.
    Elimina totalmente a dependência de regex na descrição.
    """
    existing = db.query(Transaction).filter(Transaction.id == trans_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Transação não encontrada")

    # Mapeamento do parâmetro legado todas_parcelas
    modo_escopo = "grupo" if todas_parcelas else escopo.lower()

    deleted_count = 1

    if existing.parcela_grupo_id and modo_escopo in ["grupo", "futuras"]:
        if modo_escopo == "grupo":
            siblings = (
                db.query(Transaction)
                .filter(Transaction.parcela_grupo_id == existing.parcela_grupo_id)
                .all()
            )
        else:  # modo_escopo == "futuras"
            siblings = (
                db.query(Transaction)
                .filter(
                    Transaction.parcela_grupo_id == existing.parcela_grupo_id,
                    Transaction.parcela_num >= (existing.parcela_num or 1),
                )
                .all()
            )

        deleted_count = len(siblings)
        for row in siblings:
            db.delete(row)
        db.commit()
        return {
            "message": f"{deleted_count} parcelas removidas com sucesso (escopo: {modo_escopo})",
            "deleted_count": deleted_count,
        }

    # Exclusão simples de item único
    db.delete(existing)
    db.commit()
    return {"message": "Transação removida com sucesso", "deleted_count": 1}


@router.get("/summary", response_model=FinancialSummary)
def get_summary(
    mes: str | None = Query(None, description="Mês no formato YYYY-MM (ex: 2026-10)"),
    db: Session = Depends(get_db),
):
    """Resumo consolidado por tipos, opcionalmente filtrado por mês."""
    query = db.query(Transaction.tipo, func.sum(Transaction.valor).label("total"))
    if mes:
        try:
            inicio, fim = month_range(mes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Materialização preguiçosa de recorrências ativas
        ensure_recurrences(db, mes)

        query = query.filter((Transaction.data >= inicio) & (Transaction.data < fim))

    totals = query.group_by(Transaction.tipo).all()

    total_receitas = Decimal("0.00")
    total_despesas_fixas = Decimal("0.00")
    total_despesas_variaveis = Decimal("0.00")

    for row in totals:
        t = str(row[0]).lower() if row[0] else ""
        val = to_decimal(row[1])
        if t == "receita":
            total_receitas += val
        elif t == "despesa_fixa":
            total_despesas_fixas += val
        elif t in ["despesa_variavel", "despesa"]:
            total_despesas_variaveis += val

    total_despesas = total_despesas_fixas + total_despesas_variaveis
    saldo_livre = total_receitas - total_despesas

    return {
        "total_receitas": total_receitas,
        "total_despesas_fixas": total_despesas_fixas,
        "total_despesas_variaveis": total_despesas_variaveis,
        "total_despesas": total_despesas,
        "saldo_livre": saldo_livre,
    }


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(
    mes: str | None = Query(None, description="Mês no formato YYYY-MM (ex: 2026-10)"),
    db: Session = Depends(get_db),
):
    """
    Retorna métricas para Planejamento Financeiro Doméstico (Geral ou Mensal):
    - Se 'mes' fornecido (ex: 2026-10):
      materializa recorrências e calcula estritamente sobre as transações daquele mês.
    """
    query_totals = db.query(
        Transaction.tipo,
        func.sum(Transaction.valor).label("total"),
        func.count(Transaction.id).label("qtd"),
    )
    if mes:
        try:
            inicio, fim = month_range(mes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Materialização preguiçosa de recorrências ativas
        ensure_recurrences(db, mes)

        query_totals = query_totals.filter((Transaction.data >= inicio) & (Transaction.data < fim))
    totals = query_totals.group_by(Transaction.tipo).all()

    receitas_totais = Decimal("0.00")
    contas_fixas = Decimal("0.00")
    gastos_whatsapp = Decimal("0.00")
    total_transacoes = 0

    for row in totals:
        t = str(row[0]).lower() if row[0] else ""
        val = to_decimal(row[1])
        qtd = int(row[2] or 0)
        total_transacoes += qtd

        if t == "receita":
            receitas_totais += val
        elif t == "despesa_fixa":
            contas_fixas += val
        elif t in ["despesa_variavel", "despesa"]:
            gastos_whatsapp += val

    total_despesas = contas_fixas + gastos_whatsapp
    saldo_livre = receitas_totais - total_despesas

    # Distribuição de despesas por categoria
    cat_query = (
        db.query(
            Category.id.label("cat_id"),
            Category.name.label("cat_name"),
            Category.budget.label("cat_budget"),
            func.sum(Transaction.valor).label("total"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .filter(Transaction.tipo.in_(["despesa_fixa", "despesa_variavel", "despesa"]))
    )

    if mes:
        cat_query = cat_query.filter((Transaction.data >= inicio) & (Transaction.data < fim))

    cat_rows = (
        cat_query.group_by(Category.id, Category.name, Category.budget)
        .order_by(desc(func.sum(Transaction.valor)))
        .all()
    )

    categorias = []
    base_calc = float(total_despesas) if total_despesas > Decimal("0.00") else 1.0
    for row in cat_rows:
        cat_total = to_decimal(row.total)
        cat_budget = to_decimal(row.cat_budget) if row.cat_budget is not None else None
        percentual = (
            round((float(cat_total) / base_calc) * 100, 1)
            if total_despesas > Decimal("0.00")
            else 0.0
        )

        percentual_budget = None
        if cat_budget and cat_budget > Decimal("0.00"):
            percentual_budget = round((float(cat_total) / float(cat_budget)) * 100, 1)

        categorias.append(
            CategoryMetric(
                categoria=row.cat_name,
                category_id=row.cat_id,
                total=cat_total,
                budget=cat_budget,
                percentual=percentual,
                percentual_budget=percentual_budget,
            )
        )

    return MetricsResponse(
        receitas_totais=receitas_totais,
        contas_fixas=contas_fixas,
        gastos_whatsapp=gastos_whatsapp,
        total_despesas=total_despesas,
        saldo_livre=saldo_livre,
        total_transacoes=total_transacoes,
        categorias=categorias,
    )


@router.get("/categories", response_model=list[CategoryResponse])
def get_categories(
    mes: str | None = Query(
        None, description="Mês no formato YYYY-MM para calcular gasto e percentual do orçamento"
    ),
    ativo: bool | None = Query(None, description="Filtrar categorias ativas/inativas"),
    db: Session = Depends(get_db),
):
    """
    Retorna a lista de categorias cadastradas com informações de orçamento (budget),
    gasto acumulado no mês (se informado) e percentual do orçamento atingido.
    """
    query = db.query(Category)
    if ativo is not None:
        query = query.filter(Category.ativo == ativo)
    categories = query.order_by(Category.id).all()

    # Se mes foi passado, calcula o gasto de cada categoria no mês
    spend_by_cat = {}
    if mes:
        try:
            inicio, fim = month_range(mes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Materialização preguiçosa de recorrências ativas
        ensure_recurrences(db, mes)

        spend_rows = (
            db.query(Transaction.category_id, func.sum(Transaction.valor).label("gasto"))
            .filter(
                Transaction.tipo.in_(["despesa_fixa", "despesa_variavel", "despesa"]),
                (Transaction.data >= inicio) & (Transaction.data < fim),
            )
            .group_by(Transaction.category_id)
            .all()
        )

        for r in spend_rows:
            if r.category_id:
                spend_by_cat[r.category_id] = to_decimal(r.gasto)

    res = []
    for cat in categories:
        gasto = spend_by_cat.get(cat.id, Decimal("0.00"))
        pct_budget = None
        if cat.budget and to_decimal(cat.budget) > Decimal("0.00"):
            pct_budget = round((float(gasto) / float(cat.budget)) * 100, 1)

        res.append(
            CategoryResponse(
                id=cat.id,
                name=cat.name,
                nome=cat.name,
                tipo=cat.tipo,
                budget=to_decimal(cat.budget) if cat.budget is not None else None,
                ativo=cat.ativo,
                gasto_mes=gasto,
                percentual_budget=pct_budget,
            )
        )
    return res


@router.put("/categories/{cat_id}", response_model=CategoryResponse)
def update_category(cat_id: int, payload: CategoryUpdate, db: Session = Depends(get_db)):
    """Atualiza dados da categoria: budget, ativo e/ou nome."""
    category = db.query(Category).filter(Category.id == cat_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    if payload.name is not None:
        new_name = payload.name.strip()
        new_norm = normalize_category_name(new_name)
        # Verifica se já existe outra categoria com esse normalized_name
        conflict = (
            db.query(Category)
            .filter(Category.normalized_name == new_norm, Category.id != cat_id)
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=400,
                detail=f"Já existe uma categoria cadastrada com o nome '{conflict.name}'.",
            )
        category.name = new_name
        category.normalized_name = new_norm
        # Sincroniza também as transações associadas
        db.query(Transaction).filter(Transaction.category_id == cat_id).update(
            {"categoria": new_name}, synchronize_session=False
        )

    if payload.budget is not None:
        category.budget = to_decimal(payload.budget) if payload.budget is not None else None

    if payload.ativo is not None:
        category.ativo = payload.ativo

    db.commit()
    db.refresh(category)

    pct_budget = None
    if category.budget and to_decimal(category.budget) > Decimal("0.00"):
        pct_budget = 0.0

    return CategoryResponse(
        id=category.id,
        name=category.name,
        nome=category.name,
        tipo=category.tipo,
        budget=to_decimal(category.budget) if category.budget is not None else None,
        ativo=category.ativo,
        gasto_mes=Decimal("0.00"),
        percentual_budget=pct_budget,
    )


@router.post("/recurrences", response_model=RecurrenceResponse)
def create_recurrence(payload: RecurrenceCreate, db: Session = Depends(get_db)):
    """Cria uma nova regra de recorrência mensal (receita ou despesa fixa) e materializa o mês atual."""
    valid_types = ["receita", "despesa_fixa"]
    clean_tipo = payload.tipo.lower()
    if clean_tipo not in valid_types:
        raise HTTPException(
            status_code=400, detail=f"Tipo inválido. Escolha: {', '.join(valid_types)}"
        )

    canonical_name = resolve_canonical_name(payload.categoria)
    if not canonical_name:
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Categoria '{payload.categoria}' não é válida.",
                "valid_categories": get_valid_category_names(),
            },
        )
    norm_name = normalize_category_name(canonical_name)
    cat_db = db.query(Category).filter(Category.normalized_name == norm_name).first()
    if not cat_db:
        cat_db = Category(
            name=canonical_name,
            normalized_name=norm_name,
            tipo="receita" if clean_tipo == "receita" else "despesa",
            ativo=True,
        )
        db.add(cat_db)
        db.commit()
        db.refresh(cat_db)

    # Início sempre truncado no primeiro dia do mês
    inicio_mes = payload.inicio.replace(day=1)
    fim_mes = payload.fim.replace(day=1) if payload.fim else None

    rec = Recurrence(
        tipo=clean_tipo,
        descricao=payload.descricao.strip(),
        valor=to_decimal(payload.valor),
        category_id=cat_db.id,
        author=payload.author.strip() if payload.author else None,
        dia_do_mes=payload.dia_do_mes,
        inicio=inicio_mes,
        fim=fim_mes,
        ativo=payload.ativo,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    # Materializa automaticamente para o mês atual se a regra estiver ativa nele
    hoje = today_br()
    mes_atual_str = hoje.strftime("%Y-%m")
    ensure_recurrences(db, mes_atual_str)

    return RecurrenceResponse(
        id=rec.id,
        tipo=rec.tipo,
        descricao=rec.descricao,
        valor=rec.valor,
        category_id=rec.category_id,
        categoria=cat_db.name,
        author=rec.author,
        dia_do_mes=rec.dia_do_mes,
        inicio=rec.inicio,
        fim=rec.fim,
        ativo=rec.ativo,
    )


@router.get("/recurrences", response_model=list[RecurrenceResponse])
def get_recurrences(
    tipo: str | None = None, ativo: bool | None = None, db: Session = Depends(get_db)
):
    """Lista as regras de recorrência cadastradas."""
    query = db.query(Recurrence)
    if tipo:
        query = query.filter(Recurrence.tipo == tipo.lower())
    if ativo is not None:
        query = query.filter(Recurrence.ativo == ativo)
    recs = query.order_by(Recurrence.id.asc()).all()

    res = []
    for r in recs:
        cat_name = r.category_rel.name if r.category_rel else "Outros"
        res.append(
            RecurrenceResponse(
                id=r.id,
                tipo=r.tipo,
                descricao=r.descricao,
                valor=r.valor,
                category_id=r.category_id,
                categoria=cat_name,
                author=r.author,
                dia_do_mes=r.dia_do_mes,
                inicio=r.inicio,
                fim=r.fim,
                ativo=r.ativo,
            )
        )
    return res


@router.patch("/recurrences/{rec_id}", response_model=RecurrenceResponse)
def update_recurrence(rec_id: int, payload: RecurrenceUpdate, db: Session = Depends(get_db)):
    """
    Atualiza uma regra de recorrência do mês atual em diante:
    - Atualiza a regra base (Recurrence).
    - Atualiza as instâncias futuras NÃO editadas manualmente (editado_manual=False e competencia >= mes_atual).
    - Meses passados e instâncias editadas manualmente NÃO são alterados.
    """
    rec = db.query(Recurrence).filter(Recurrence.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recorrência não encontrada")

    primeiro_dia_mes_atual = today_br().replace(day=1)

    if payload.descricao is not None:
        rec.descricao = payload.descricao.strip()
    if payload.valor is not None:
        rec.valor = to_decimal(payload.valor)
    if payload.dia_do_mes is not None:
        rec.dia_do_mes = payload.dia_do_mes
    if payload.ativo is not None:
        rec.ativo = payload.ativo
    if payload.fim is not None:
        rec.fim = payload.fim.replace(day=1)
    if payload.author is not None:
        rec.author = payload.author.strip() if payload.author else None

    if payload.categoria is not None:
        canonical_name = resolve_canonical_name(payload.categoria)
        if not canonical_name:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"Categoria '{payload.categoria}' não é válida.",
                    "valid_categories": get_valid_category_names(),
                },
            )
        norm_name = normalize_category_name(canonical_name)
        cat_db = db.query(Category).filter(Category.normalized_name == norm_name).first()
        if not cat_db:
            cat_db = Category(
                name=canonical_name,
                normalized_name=norm_name,
                tipo="receita" if rec.tipo == "receita" else "despesa",
                ativo=True,
            )
            db.add(cat_db)
            db.commit()
            db.refresh(cat_db)
        rec.category_id = cat_db.id

    # Sincroniza instâncias do mês atual em diante que NÃO foram editadas manualmente
    instancias_futuras = (
        db.query(Transaction)
        .filter(
            Transaction.recurrence_id == rec.id,
            Transaction.competencia >= primeiro_dia_mes_atual,
            Transaction.editado_manual == False,
        )
        .all()
    )

    cat_name = rec.category_rel.name if rec.category_rel else "Outros"

    for inst in instancias_futuras:
        if payload.descricao is not None:
            inst.descricao = rec.descricao
        if payload.valor is not None:
            inst.valor = rec.valor
        if payload.author is not None:
            inst.author = rec.author
        if payload.categoria is not None:
            inst.categoria = cat_name
            inst.category_id = rec.category_id
        if payload.dia_do_mes is not None and inst.competencia:
            inst.data = clamp_day_in_month(
                inst.competencia.year, inst.competencia.month, rec.dia_do_mes
            )
            if inst.tipo == "despesa_fixa":
                inst.vencimento = f"Dia {rec.dia_do_mes}"

    db.commit()
    db.refresh(rec)

    return RecurrenceResponse(
        id=rec.id,
        tipo=rec.tipo,
        descricao=rec.descricao,
        valor=rec.valor,
        category_id=rec.category_id,
        categoria=cat_name,
        author=rec.author,
        dia_do_mes=rec.dia_do_mes,
        inicio=rec.inicio,
        fim=rec.fim,
        ativo=rec.ativo,
    )


@router.delete("/recurrences/{rec_id}")
def delete_recurrence(rec_id: int, db: Session = Depends(get_db)):
    """
    Encerra a regra de recorrência:
    - Define fim = mês anterior ao mês atual.
    - Remove apenas instâncias futuras NÃO editadas manualmente.
    """
    rec = db.query(Recurrence).filter(Recurrence.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recorrência não encontrada")

    primeiro_dia_mes_atual = today_br().replace(day=1)
    mes_anterior = (primeiro_dia_mes_atual.replace(day=1) - timedelta(days=1)).replace(day=1)

    rec.fim = mes_anterior
    rec.ativo = False

    # Remove instâncias futuras não editadas
    futuras = (
        db.query(Transaction)
        .filter(
            Transaction.recurrence_id == rec.id,
            Transaction.competencia >= primeiro_dia_mes_atual,
            Transaction.editado_manual == False,
        )
        .all()
    )

    removed_count = len(futuras)
    for f in futuras:
        db.delete(f)

    db.commit()
    return {
        "message": f"Recorrência {rec_id} encerrada com sucesso. {removed_count} instâncias futuras removidas.",
        "removed_future_instances": removed_count,
    }


@router.post("/parse-message", response_model=MessageParseResponse)
def parse_message(payload: MessageParseRequest):
    """
    Processa mensagens em linguagem natural (WhatsApp ou chat)
    e infere tipo (receita, despesa_fixa, despesa_variavel), valor, categoria e parcelas.
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Mensagem não pode ser vazia")

    parsed = parse_text_message(payload.message)
    if not parsed:
        raise HTTPException(
            status_code=422, detail="Nenhum valor financeiro ou transação identificada na mensagem."
        )
    return MessageParseResponse(**parsed)
