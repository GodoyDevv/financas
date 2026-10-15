from fastapi import APIRouter, HTTPException, Depends
from sqlite3 import Connection
from .parser import parse_financial_payload
from .routes import get_db

webhook_router = APIRouter(prefix="/webhook", tags=["Webhook"])

@webhook_router.post("/whatsapp")
@webhook_router.post("")
def receive_webhook(payload: dict, db: Connection = Depends(get_db)):
    """
    Recebe webhooks de mensagens ou eventos do WhatsApp Bot / Gateway
    e cadastra diretamente como transação (padrão: despesa_variavel, source: WhatsApp).
    Disponível tanto em /webhook/whatsapp quanto em /webhook.
    """
    parsed_data = parse_financial_payload(payload)
    if not parsed_data:
        raise HTTPException(status_code=400, detail="Payload inválido para processamento de transação financeira")
        
    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO transactions (tipo, valor, categoria, data, descricao, source, vencimento)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        parsed_data["tipo"], 
        parsed_data["valor"], 
        parsed_data["categoria"], 
        parsed_data["data"], 
        parsed_data["descricao"],
        parsed_data.get("source", "WhatsApp"),
        parsed_data.get("vencimento")
    ))
    db.commit()
    
    return {
        "status": "success", 
        "id": cursor.lastrowid,
        "transaction": parsed_data
    }