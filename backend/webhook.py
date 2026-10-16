import logging
from typing import Optional, Tuple
from fastapi import APIRouter, HTTPException, Depends
from sqlite3 import Connection
from .parser import parse_financial_payload, parse_text_message
from .routes import get_db

logger = logging.getLogger("fintrack.webhook")

webhook_router = APIRouter(prefix="/webhook", tags=["Webhook"])

# Mapeamento dos telefones do casal
PHONE_USERS = {
    "5511967154115": "Bruno",
    "11967154115": "Bruno",
    "5511946165996": "Letícia",
    "11946165996": "Letícia"
}

def identify_user_name(phone: Optional[str]) -> str:
    """Retorna o nome do usuário identificado pelo telefone ou 'WhatsApp'."""
    if not phone:
        return "WhatsApp"
    # Remove caracteres não numéricos
    clean_phone = "".join(filter(str.isdigit, phone))
    for p_key, name in PHONE_USERS.items():
        if clean_phone.endswith(p_key) or p_key.endswith(clean_phone):
            return name
    return f"WhatsApp ({phone})"

def extract_evolution_message(payload: dict) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extrai remetente, nome do usuário e texto bruto de mensagens individuais ou de grupos
    vindos da Evolution API v1/v2.
    Retorna (sender_phone, user_name, raw_text).
    """
    if not isinstance(payload, dict):
        return None, None, None

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    # 1. Trata se a mensagem foi enviada pelo próprio número que conectou
    key = data.get("key") or payload.get("key")
    is_from_me = False
    if isinstance(key, dict) and key.get("fromMe") is True:
        is_from_me = True

    # 2. Identificação do remetente real (suporta grupos @g.us e conversas diretas @s.whatsapp.net)
    sender = None
    if isinstance(key, dict):
        sender = key.get("participant") or key.get("remoteJid")
    if not sender:
        sender = data.get("participant") or data.get("sender") or data.get("remoteJid") or payload.get("sender")

    # Se a mensagem foi enviada pelo próprio dono da conta (fromMe)
    if is_from_me:
        sender = "5511967154115"

    if sender and isinstance(sender, str):
        sender = sender.split("@")[0].split(":")[0]

    user_name = identify_user_name(sender)

    # 3. Extração do texto da mensagem
    raw_text = None
    msg_obj = data.get("message")
    if isinstance(msg_obj, dict):
        raw_text = (
            msg_obj.get("conversation")
            or (msg_obj.get("extendedTextMessage", {}).get("text") if isinstance(msg_obj.get("extendedTextMessage"), dict) else None)
            or (msg_obj.get("imageMessage", {}).get("caption") if isinstance(msg_obj.get("imageMessage"), dict) else None)
            or (msg_obj.get("videoMessage", {}).get("caption") if isinstance(msg_obj.get("videoMessage"), dict) else None)
        )

    if not raw_text:
        raw_text = data.get("text") or data.get("body") or payload.get("text") or payload.get("message")
        if isinstance(raw_text, dict):
            raw_text = raw_text.get("conversation") or raw_text.get("text")

    if raw_text and isinstance(raw_text, str):
        raw_text = raw_text.strip()
    else:
        raw_text = None

    return sender, user_name, raw_text

@webhook_router.post("/whatsapp")
@webhook_router.post("")
def receive_webhook(payload: dict, db: Connection = Depends(get_db)):
    """
    Processa webhooks da Evolution API e gateways WhatsApp.
    - Extrai telefone do remetente e o texto da mensagem.
    - Executa o parser em linguagem natural (parser.py).
    - Persiste com 100% de segurança no SQLite como despesa_variavel (ou tipo inferido).
    """
    sender, user_name, raw_text = extract_evolution_message(payload)
    
    parsed_data = None
    if raw_text:
        # Processamento via parser de linguagem natural
        parsed_data = parse_text_message(raw_text)
        # O requisito especifica salvar o resultado como despesa_variavel
        if parsed_data:
            parsed_data["tipo"] = "despesa_variavel"
            parsed_data["source"] = user_name
    else:
        # Fallback para payload financeiro estruturado direto
        parsed_data = parse_financial_payload(payload)
        if parsed_data:
            parsed_data["tipo"] = "despesa_variavel"
            parsed_data["source"] = user_name

    if not parsed_data or parsed_data.get("valor", 0) <= 0:
        # Resposta amigável para eventos que não contenham transação financeira ou texto válido
        return {
            "status": "ignored",
            "detail": "Nenhuma despesa identificada na mensagem recebida ou evento irrelevante",
            "sender": sender,
            "user": user_name
        }

    # Persistência segura no banco SQLite garantindo integridade de todos os registros anteriores
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
        "sender": sender,
        "transaction": parsed_data
    }