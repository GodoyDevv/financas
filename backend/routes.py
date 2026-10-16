from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from .database import get_db, engine, Base
from .models import Transaction
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

# Garante a criação de tabelas
Base.metadata.create_all(bind=engine)

@router.get("/transactions", response_model=List[TransactionResponse])
def get_transactions(
    tipo: Optional[str] = None, 
    db: Session = Depends(get_db)
):
    """
    Retorna a lista de transações com ordenação cronológica decrescente (id decrescente).
    Permite filtrar opcionalmente por tipo: 'receita', 'despesa_fixa' ou 'despesa_variavel'.
    """
    query = db.query(Transaction)
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
        valor=abs(float(transaction.valor)),
        categoria=transaction.categoria.strip(),
        data=str(transaction.data),
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
        existing.valor = abs(float(transaction.valor))
    if transaction.categoria is not None:
        existing.categoria = transaction.categoria.strip()
    if transaction.data is not None:
        existing.data = str(transaction.data)
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
def delete_transaction(trans_id: int, db: Session = Depends(get_db)):
    """Remove uma transação pelo seu ID."""
    existing = db.query(Transaction).filter(Transaction.id == trans_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Transação não encontrada")
    db.delete(existing)
    db.commit()
    return {"message": "Transação removida com sucesso"}

@router.get("/summary", response_model=FinancialSummary)
def get_summary(db: Session = Depends(get_db)):
    """Resumo consolidado por tipos."""
    totals = db.query(
        Transaction.tipo,
        func.sum(Transaction.valor).label("total")
    ).group_by(Transaction.tipo).all()
    
    total_receitas = 0.0
    total_despesas_fixas = 0.0
    total_despesas_variaveis = 0.0
    
    for row in totals:
        t = str(row[0]).lower() if row[0] else ""
        val = float(row[1] or 0.0)
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
def get_metrics(db: Session = Depends(get_db)):
    """
    Retorna métricas para Planejamento Financeiro Doméstico:
    - receitas_totais: Entradas fixas / salários
    - contas_fixas: Contas recorrentes (luz, água, aluguel, condomínio, assinaturas)
    - gastos_whatsapp: Gastos do dia a dia (despesas variáveis / WhatsApp)
    - total_despesas: contas_fixas + gastos_whatsapp
    - saldo_livre: receitas_totais - total_despesas
    - total_transacoes: contagem geral de registros
    - categorias: distribuição percentual sobre as despesas totais
    """
    totals = db.query(
        Transaction.tipo,
        func.sum(Transaction.valor).label("total"),
        func.count(Transaction.id).label("qtd")
    ).group_by(Transaction.tipo).all()
    
    receitas_totais = 0.0
    contas_fixas = 0.0
    gastos_whatsapp = 0.0
    total_transacoes = 0

    for row in totals:
        t = str(row[0]).lower() if row[0] else ""
        val = float(row[1] or 0.0)
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
    cat_rows = db.query(
        Transaction.categoria,
        func.sum(Transaction.valor).label("total")
    ).filter(
        Transaction.tipo.in_(["despesa_fixa", "despesa_variavel", "despesa"])
    ).group_by(
        Transaction.categoria
    ).order_by(
        desc(func.sum(Transaction.valor))
    ).all()
    
    categorias = []
    base_calc = total_despesas if total_despesas > 0 else 1.0
    for row in cat_rows:
        cat_total = float(row[1] or 0.0)
        percentual = round((cat_total / base_calc) * 100, 1) if total_despesas > 0 else 0.0
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
    e infere tipo (receita, despesa_fixa, despesa_variavel), valor e categoria.
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Mensagem não pode ser vazia")
    
    parsed = parse_text_message(payload.message)
    return MessageParseResponse(**parsed)