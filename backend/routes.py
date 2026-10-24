from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_

from .database import get_db, engine, Base
from .models import Transaction, Category
from .dates_and_money import to_decimal, month_range, today_br
from .categories import (
    normalize_category_name,
    resolve_canonical_name,
    get_valid_category_names,
    CANONICAL_CATEGORIES
)
from .schemas import (
    TransactionCreate, 
    TransactionUpdate, 
    TransactionResponse, 
    FinancialSummary, 
    MetricsResponse, 
    CategoryMetric,
    CategoryResponse,
    CategoryUpdate,
    MessageParseRequest,
    MessageParseResponse
)
from .parser import parse_text_message

router = APIRouter(prefix="/api", tags=["Transactions & Metrics"])

@router.get("/transactions", response_model=List[TransactionResponse])
def get_transactions(
    tipo: Optional[str] = None, 
    author: Optional[str] = Query(None, description="Filtra por autor (ex: Bruno, Letícia)"),
    channel: Optional[str] = Query(None, description="Filtra por canal (ex: whatsapp_text, whatsapp_audio, dashboard)"),
    mes: Optional[str] = Query(None, description="Mês no formato YYYY-MM (ex: 2026-10)"),
    db: Session = Depends(get_db)
):
    """
    Retorna a lista de transações.
    Se 'mes' for fornecido (ex: '2026-10'):
      - Mantém as receitas e contas fixas recorrentes (base do orçamento doméstico).
      - Filtra as despesas variáveis para exibir APENAS as que caem naquele mês (data >= inicio AND data < fim).
    """
    query = db.query(Transaction)
    
    if mes:
        try:
            inicio, fim = month_range(mes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        query = query.filter(
            or_(
                Transaction.tipo.in_(["receita", "despesa_fixa"]),
                (Transaction.data >= inicio) & (Transaction.data < fim)
            )
        )
    
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
            detail=f"Tipo inválido. Escolha um dos seguintes: {', '.join(valid_types)}"
        )

    # Canal e autor para chamadas da API/Dashboard
    author_val = transaction.author.strip() if transaction.author else None
    channel_val = transaction.channel if transaction.channel and transaction.channel != "unknown" else "dashboard"
    
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
                "valid_categories": valid_cats
            }
        )

    norm_name = normalize_category_name(canonical_name)
    cat_db = db.query(Category).filter(Category.normalized_name == norm_name).first()
    if not cat_db:
        # Se categoria canônica não estiver na tabela, cria de forma resiliente
        cat_db = Category(
            name=canonical_name,
            normalized_name=norm_name,
            tipo="receita" if clean_tipo == "receita" else "despesa",
            ativo=True
        )
        db.add(cat_db)
        db.commit()
        db.refresh(cat_db)

    new_item = Transaction(
        tipo=clean_tipo,
        valor=to_decimal(transaction.valor),
        categoria=cat_db.name,
        category_id=cat_db.id,
        data=transaction.data,
        descricao=transaction.descricao.strip() if transaction.descricao else "",
        author=author_val,
        channel=channel_val,
        source=source_val,
        vencimento=transaction.vencimento.strip() if transaction.vencimento else None
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item

@router.put("/transactions/{trans_id}", response_model=TransactionResponse)
def update_transaction(
    trans_id: int, 
    transaction: TransactionUpdate, 
    db: Session = Depends(get_db)
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
                detail=f"Tipo inválido. Escolha um dos seguintes: {', '.join(valid_types)}"
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
                    "valid_categories": valid_cats
                }
            )
        norm_name = normalize_category_name(canonical_name)
        cat_db = db.query(Category).filter(Category.normalized_name == norm_name).first()
        if not cat_db:
            cat_db = Category(
                name=canonical_name,
                normalized_name=norm_name,
                tipo="receita" if existing.tipo == "receita" else "despesa",
                ativo=True
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

    db.commit()
    db.refresh(existing)
    return existing

@router.delete("/transactions/{trans_id}")
def delete_transaction(
    trans_id: int,
    todas_parcelas: bool = Query(False, description="Se True, remove todas as parcelas associadas ao mesmo item"),
    db: Session = Depends(get_db)
):
    """
    Remove uma transação pelo seu ID.
    Se 'todas_parcelas=True' e a descrição tiver padrão de parcelamento 'Item (X/N)',
    remove todas as parcelas 'Item (1/N)'..'(N/N)' daquele grupo.
    """
    import re
    existing = db.query(Transaction).filter(Transaction.id == trans_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Transação não encontrada")

    deleted_count = 1
    if todas_parcelas and existing.descricao:
        match = re.match(r"^(.*?)\s*\(\d+/(\d+)\)\s*$", existing.descricao.strip())
        if match:
            base_desc = match.group(1).strip()
            total_n = match.group(2)
            pattern = f"{base_desc} (%/{total_n})"
            sibling_rows = db.query(Transaction).filter(
                Transaction.tipo == existing.tipo,
                Transaction.valor == existing.valor,
                Transaction.descricao.like(pattern)
            ).all()
            if sibling_rows:
                deleted_count = len(sibling_rows)
                for row in sibling_rows:
                    db.delete(row)
                db.commit()
                return {
                    "message": f"{deleted_count} parcelas de '{base_desc}' removidas com sucesso",
                    "deleted_count": deleted_count
                }

    db.delete(existing)
    db.commit()
    return {"message": "Transação removida com sucesso", "deleted_count": deleted_count}

@router.get("/summary", response_model=FinancialSummary)
def get_summary(
    mes: Optional[str] = Query(None, description="Mês no formato YYYY-MM (ex: 2026-10)"),
    db: Session = Depends(get_db)
):
    """Resumo consolidado por tipos, opcionalmente filtrado por mês."""
    query = db.query(
        Transaction.tipo,
        func.sum(Transaction.valor).label("total")
    )
    if mes:
        try:
            inicio, fim = month_range(mes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        query = query.filter(
            or_(
                Transaction.tipo.in_(["receita", "despesa_fixa"]),
                (Transaction.data >= inicio) & (Transaction.data < fim)
            )
        )
    
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
        "saldo_livre": saldo_livre
    }

@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(
    mes: Optional[str] = Query(None, description="Mês no formato YYYY-MM (ex: 2026-10)"),
    db: Session = Depends(get_db)
):
    """
    Retorna métricas para Planejamento Financeiro Doméstico (Geral ou Mensal):
    - Se 'mes' fornecido (ex: 2026-10):
      calcula sobre as receitas e contas fixas recorrentes + gastos/parcelas que caem naquele mês.
    """
    query_totals = db.query(
        Transaction.tipo,
        func.sum(Transaction.valor).label("total"),
        func.count(Transaction.id).label("qtd")
    )
    if mes:
        try:
            inicio, fim = month_range(mes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        query_totals = query_totals.filter(
            or_(
                Transaction.tipo.in_(["receita", "despesa_fixa"]),
                (Transaction.data >= inicio) & (Transaction.data < fim)
            )
        )
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
    cat_query = db.query(
        Category.id.label("cat_id"),
        Category.name.label("cat_name"),
        Category.budget.label("cat_budget"),
        func.sum(Transaction.valor).label("total")
    ).join(
        Transaction, Transaction.category_id == Category.id
    ).filter(
        Transaction.tipo.in_(["despesa_fixa", "despesa_variavel", "despesa"])
    )

    if mes:
        cat_query = cat_query.filter(
            or_(
                Transaction.tipo == "despesa_fixa",
                (Transaction.data >= inicio) & (Transaction.data < fim)
            )
        )
    
    cat_rows = cat_query.group_by(
        Category.id, Category.name, Category.budget
    ).order_by(
        desc(func.sum(Transaction.valor))
    ).all()
    
    categorias = []
    base_calc = float(total_despesas) if total_despesas > Decimal("0.00") else 1.0
    for row in cat_rows:
        cat_total = to_decimal(row.total)
        cat_budget = to_decimal(row.cat_budget) if row.cat_budget is not None else None
        percentual = round((float(cat_total) / base_calc) * 100, 1) if total_despesas > Decimal("0.00") else 0.0
        
        percentual_budget = None
        if cat_budget and cat_budget > Decimal("0.00"):
            percentual_budget = round((float(cat_total) / float(cat_budget)) * 100, 1)

        categorias.append(CategoryMetric(
            categoria=row.cat_name,
            category_id=row.cat_id,
            total=cat_total,
            budget=cat_budget,
            percentual=percentual,
            percentual_budget=percentual_budget
        ))

    return MetricsResponse(
        receitas_totais=receitas_totais,
        contas_fixas=contas_fixas,
        gastos_whatsapp=gastos_whatsapp,
        total_despesas=total_despesas,
        saldo_livre=saldo_livre,
        total_transacoes=total_transacoes,
        categorias=categorias
    )

@router.get("/categories", response_model=List[CategoryResponse])
def get_categories(
    mes: Optional[str] = Query(None, description="Mês no formato YYYY-MM para calcular gasto e percentual do orçamento"),
    ativo: Optional[bool] = Query(None, description="Filtrar categorias ativas/inativas"),
    db: Session = Depends(get_db)
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

        spend_rows = db.query(
            Transaction.category_id,
            func.sum(Transaction.valor).label("gasto")
        ).filter(
            Transaction.tipo.in_(["despesa_fixa", "despesa_variavel", "despesa"]),
            or_(
                Transaction.tipo == "despesa_fixa",
                (Transaction.data >= inicio) & (Transaction.data < fim)
            )
        ).group_by(Transaction.category_id).all()

        for r in spend_rows:
            if r.category_id:
                spend_by_cat[r.category_id] = to_decimal(r.gasto)

    res = []
    for cat in categories:
        gasto = spend_by_cat.get(cat.id, Decimal("0.00"))
        pct_budget = None
        if cat.budget and to_decimal(cat.budget) > Decimal("0.00"):
            pct_budget = round((float(gasto) / float(cat.budget)) * 100, 1)

        res.append(CategoryResponse(
            id=cat.id,
            name=cat.name,
            nome=cat.name,
            tipo=cat.tipo,
            budget=to_decimal(cat.budget) if cat.budget is not None else None,
            ativo=cat.ativo,
            gasto_mes=gasto,
            percentual_budget=pct_budget
        ))
    return res

@router.put("/categories/{cat_id}", response_model=CategoryResponse)
def update_category(
    cat_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db)
):
    """Atualiza dados da categoria: budget, ativo e/ou nome."""
    category = db.query(Category).filter(Category.id == cat_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    if payload.name is not None:
        new_name = payload.name.strip()
        new_norm = normalize_category_name(new_name)
        # Verifica se já existe outra categoria com esse normalized_name
        conflict = db.query(Category).filter(
            Category.normalized_name == new_norm,
            Category.id != cat_id
        ).first()
        if conflict:
            raise HTTPException(
                status_code=400,
                detail=f"Já existe uma categoria cadastrada com o nome '{conflict.name}'."
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
        percentual_budget=pct_budget
    )

@router.post("/parse-message", response_model=MessageParseResponse)
def parse_message(payload: MessageParseRequest):
    """
    Processa mensagens em linguagem natural (WhatsApp ou chat)
    e infere tipo (receita, despesa_fixa, despesa_variavel), valor, categoria e parcelas.
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Mensagem não pode ser vazia")
    
    parsed = parse_text_message(payload.message)
    return MessageParseResponse(**parsed)
