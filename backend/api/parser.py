"""
backend/api/parser.py

Router FastAPI para inferência/parse determinístico e NLP de mensagens em linguagem natural.
"""

from fastapi import APIRouter, HTTPException

from backend.parser import parse_text_message
from backend.schemas import MessageParseRequest, MessageParseResponse

router = APIRouter(prefix="", tags=["Parser"])


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
