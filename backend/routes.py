from fastapi import APIRouter, HTTPException

from .api.categories import router as categories_router
from .api.recurrences import router as recurrences_router
from .api.summary import get_metrics
from .api.summary import router as summary_router
from .api.transactions import router as transactions_router
from .parser import parse_text_message
from .schemas import (
    MessageParseRequest,
    MessageParseResponse,
)

router = APIRouter(prefix="/api", tags=["Transactions & Metrics"])


router.include_router(transactions_router)
router.include_router(summary_router)
router.include_router(categories_router)
router.include_router(recurrences_router)


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


__all__ = ["get_metrics", "router"]
