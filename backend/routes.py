from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .api.summary import router as summary_router
from .api.transactions import router as transactions_router
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
    CategoryResponse,
    CategoryUpdate,
    MessageParseRequest,
    MessageParseResponse,
    RecurrenceCreate,
    RecurrenceResponse,
    RecurrenceUpdate,
)
from .services import clamp_day_in_month, ensure_recurrences

router = APIRouter(prefix="/api", tags=["Transactions & Metrics"])


router.include_router(transactions_router)
router.include_router(summary_router)


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
            raise HTTPException(status_code=400, detail=str(e)) from e

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
            not Transaction.editado_manual,
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
            not Transaction.editado_manual,
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
