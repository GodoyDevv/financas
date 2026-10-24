from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_

from .database import get_db, engine, Base
from .models import Transaction, Category
from .dates_and_money import to_decimal, month_range, today_br
from .schemas import (
    TransactionCreate, 
    TransactionUpdate, 
    TransactionResponse, 
    FinancialSummary, 
    MetricsResponse, 
    CategoryMetric,
    MessageParseRequest,
    MessageParseResponse
)
from .parser import parse_text_message

router = APIRouter(prefix="/api", tags=["Transactions & Metrics"])

@router.get("/transactions", response_model=List[TransactionResponse])
def get_transactions(
    tipo: Optional[str] = None, 
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

    new_item = Transaction(
        tipo=clean_tipo,
        valor=to_decimal(transaction.valor),
        categoria=transaction.categoria.strip(),
        data=transaction.data,
        descricao=transaction.descricao.strip() if transaction.descricao else "",
        source=transaction.source or "Manual",
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
        existing.categoria = transaction.categoria.strip()
    if transaction.data is not None:
        existing.data = transaction.data
    if transaction.descricao is not None:
        existing.descricao = transaction.descricao.strip()
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
        Transaction.categoria,
        func.sum(Transaction.valor).label("total")
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
        Transaction.categoria
    ).order_by(
        desc(func.sum(Transaction.valor))
    ).all()
    
    categorias = []
    base_calc = float(total_despesas) if total_despesas > Decimal("0.00") else 1.0
    for row in cat_rows:
        cat_total = to_decimal(row[1])
        percentual = round((float(cat_total) / base_calc) * 100, 1) if total_despesas > Decimal("0.00") else 0.0
        categorias.append(CategoryMetric(
            categoria=row[0],
            total=cat_total,
            percentual=percentual
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
