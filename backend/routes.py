from fastapi import APIRouter, HTTPException, Depends
from sqlite3 import Connection
import sqlite3
from typing import List, Optional
from datetime import datetime
from pathlib import Path
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

DB_PATH = "fintrack.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# Inicializa tabela com os campos necessários e popula dados iniciais se estiver vazia
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL, -- receita, despesa_fixa, despesa_variavel
            valor REAL NOT NULL,
            categoria TEXT NOT NULL,
            data TEXT NOT NULL,
            descricao TEXT,
            source TEXT DEFAULT 'Manual',
            vencimento TEXT
        )
    """)
    conn.commit()

    # Se o banco acabou de ser criado (ex: novo deploy ou restart na nuvem), restaura os dados
    cursor.execute("SELECT count(*) FROM transactions")
    count = cursor.fetchone()[0]
    if count == 0:
        json_path = Path(__file__).resolve().parent / "initial_data.json"
        if json_path.exists():
            try:
                import json
                with open(json_path, "r", encoding="utf-8") as f:
                    seed_items = json.load(f)
                for item in seed_items:
                    cursor.execute("""
                        INSERT INTO transactions (tipo, valor, categoria, data, descricao, source, vencimento)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        item.get("tipo"),
                        item.get("valor"),
                        item.get("categoria"),
                        item.get("data"),
                        item.get("descricao"),
                        item.get("source", "Manual"),
                        item.get("vencimento")
                    ))
                conn.commit()
            except Exception as e:
                pass
    conn.close()

init_db()

@router.get("/transactions", response_model=List[TransactionResponse])
def get_transactions(
    tipo: Optional[str] = None, 
    db: Connection = Depends(get_db)
):
    """
    Retorna a lista de transações com ordenação cronológica decrescente.
    Permite filtrar opcionalmente por tipo: 'receita', 'despesa_fixa' ou 'despesa_variavel'.
    """
    cursor = db.cursor()
    if tipo:
        cursor.execute(
            "SELECT id, tipo, valor, categoria, data, descricao, source, vencimento FROM transactions WHERE tipo = ? ORDER BY id DESC",
            (tipo.lower(),)
        )
    else:
        cursor.execute("SELECT id, tipo, valor, categoria, data, descricao, source, vencimento FROM transactions ORDER BY id DESC")
    
    rows = cursor.fetchall()
    return [dict(row) for row in rows]

@router.post("/transactions", response_model=TransactionResponse)
def create_transaction(transaction: TransactionCreate, db: Connection = Depends(get_db)):
    """Cadastra um novo registro de receita, despesa fixa ou despesa variável."""
    valid_types = ["receita", "despesa_fixa", "despesa_variavel"]
    clean_tipo = transaction.tipo.lower()
    
    # Compatibilidade caso venha apenas 'despesa'
    if clean_tipo == "despesa":
        clean_tipo = "despesa_variavel"

    if clean_tipo not in valid_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Tipo inválido. Escolha um dos seguintes: {', '.join(valid_types)}"
        )

    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO transactions (tipo, valor, categoria, data, descricao, source, vencimento)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        clean_tipo, 
        abs(float(transaction.valor)), 
        transaction.categoria.strip(), 
        str(transaction.data), 
        transaction.descricao.strip() if transaction.descricao else "",
        transaction.source or "Manual",
        transaction.vencimento.strip() if transaction.vencimento else None
    ))
    db.commit()
    trans_id = cursor.lastrowid
    
    return {
        "id": trans_id,
        "tipo": clean_tipo,
        "valor": abs(float(transaction.valor)),
        "categoria": transaction.categoria.strip(),
        "data": transaction.data,
        "descricao": transaction.descricao,
        "source": transaction.source or "Manual",
        "vencimento": transaction.vencimento
    }

@router.put("/transactions/{trans_id}", response_model=TransactionResponse)
def update_transaction(
    trans_id: int, 
    transaction: TransactionUpdate, 
    db: Connection = Depends(get_db)
):
    """Atualiza um registro existente de receita, despesa fixa ou despesa variável."""
    cursor = db.cursor()
    cursor.execute("SELECT id, tipo, valor, categoria, data, descricao, source, vencimento FROM transactions WHERE id = ?", (trans_id,))
    existing = cursor.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Transação não encontrada")
    
    current_data = dict(existing)
    valid_types = ["receita", "despesa_fixa", "despesa_variavel"]
    
    new_tipo = transaction.tipo.lower() if transaction.tipo is not None else current_data["tipo"]
    if new_tipo == "despesa":
        new_tipo = "despesa_variavel"
    if new_tipo not in valid_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Tipo inválido. Escolha um dos seguintes: {', '.join(valid_types)}"
        )
        
    new_valor = abs(float(transaction.valor)) if transaction.valor is not None else current_data["valor"]
    new_categoria = transaction.categoria.strip() if transaction.categoria is not None else current_data["categoria"]
    new_data = str(transaction.data) if transaction.data is not None else current_data["data"]
    new_descricao = transaction.descricao.strip() if transaction.descricao is not None else current_data["descricao"]
    new_source = transaction.source.strip() if transaction.source is not None else current_data["source"]
    new_vencimento = transaction.vencimento.strip() if transaction.vencimento is not None else current_data["vencimento"]

    cursor.execute("""
        UPDATE transactions
        SET tipo = ?, valor = ?, categoria = ?, data = ?, descricao = ?, source = ?, vencimento = ?
        WHERE id = ?
    """, (
        new_tipo,
        new_valor,
        new_categoria,
        new_data,
        new_descricao,
        new_source,
        new_vencimento,
        trans_id
    ))
    db.commit()

    return {
        "id": trans_id,
        "tipo": new_tipo,
        "valor": new_valor,
        "categoria": new_categoria,
        "data": new_data,
        "descricao": new_descricao,
        "source": new_source,
        "vencimento": new_vencimento
    }

@router.delete("/transactions/{trans_id}")
def delete_transaction(trans_id: int, db: Connection = Depends(get_db)):
    """Remove uma transação pelo seu ID."""
    cursor = db.cursor()
    cursor.execute("DELETE FROM transactions WHERE id = ?", (trans_id,))
    db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Transação não encontrada")
    return {"message": "Transação removida com sucesso"}

@router.get("/summary", response_model=FinancialSummary)
def get_summary(db: Connection = Depends(get_db)):
    """Resumo consolidado por tipos."""
    cursor = db.cursor()
    cursor.execute("SELECT tipo, SUM(valor) as total FROM transactions GROUP BY tipo")
    rows = cursor.fetchall()
    
    total_receitas = 0.0
    total_despesas_fixas = 0.0
    total_despesas_variaveis = 0.0
    
    for row in rows:
        t = str(row["tipo"]).lower()
        val = float(row["total"] or 0.0)
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
def get_metrics(db: Connection = Depends(get_db)):
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
    cursor = db.cursor()

    # Totais por tipo
    cursor.execute("SELECT tipo, SUM(valor) as total, COUNT(*) as qtd FROM transactions GROUP BY tipo")
    totals = cursor.fetchall()
    
    receitas_totais = 0.0
    contas_fixas = 0.0
    gastos_whatsapp = 0.0
    total_transacoes = 0

    for row in totals:
        t = str(row["tipo"]).lower()
        val = float(row["total"] or 0.0)
        qtd = int(row["qtd"] or 0)
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
    cursor.execute("""
        SELECT categoria, SUM(valor) as total
        FROM transactions
        WHERE tipo IN ('despesa_fixa', 'despesa_variavel', 'despesa')
        GROUP BY categoria
        ORDER BY total DESC
    """)
    cat_rows = cursor.fetchall()
    
    categorias = []
    base_calc = total_despesas if total_despesas > 0 else 1.0
    for row in cat_rows:
        cat_total = float(row["total"] or 0.0)
        percentual = round((cat_total / base_calc) * 100, 1) if total_despesas > 0 else 0.0
        categorias.append(CategoryMetric(
            categoria=row["categoria"],
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