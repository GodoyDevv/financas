"""
backend/api/transactions.py

Router FastAPI para o recurso /api/transactions.
Exclusivamente focado em validação de entrada, chamada ao serviço,
controle transacional e serialização de saída.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.categories import get_valid_category_names
from backend.database import get_db
from backend.schemas import (
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)
from backend.services.transactions import TransactionService

router = APIRouter(tags=["Transactions"])


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
    service = TransactionService(db)
    try:
        rows = service.list_transactions(mes=mes, tipo=tipo, author=author, channel=channel)
        db.commit()
        return rows
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/transactions", response_model=TransactionResponse)
def create_transaction(transaction: TransactionCreate, db: Session = Depends(get_db)):
    service = TransactionService(db)
    try:
        tx_data = transaction.model_dump()
        criadas = service.create_transaction(tx_data)
        db.commit()
        for t in criadas:
            db.refresh(t)
        return criadas[0]
    except ValueError as e:
        msg = str(e)
        if "não é válida" in msg:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"Categoria '{transaction.categoria}' não é válida.",
                    "valid_categories": get_valid_category_names(),
                },
            ) from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.put("/transactions/{trans_id}", response_model=TransactionResponse)
def update_transaction(
    trans_id: int, transaction: TransactionUpdate, db: Session = Depends(get_db)
):
    service = TransactionService(db)
    try:
        update_data = transaction.model_dump(exclude_unset=True)
        updated = service.update_transaction(trans_id, update_data)
        db.commit()
        db.refresh(updated)
        return updated
    except KeyError as e:
        raise HTTPException(status_code=404, detail="Transação não encontrada") from e
    except ValueError as e:
        msg = str(e)
        if "não é válida" in msg:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": f"Categoria '{transaction.categoria}' não é válida.",
                    "valid_categories": get_valid_category_names(),
                },
            ) from e
        raise HTTPException(status_code=400, detail=msg) from e


@router.delete("/transactions/{trans_id}")
def delete_transaction(
    trans_id: int,
    escopo: str = Query("uma", description="Escopo de exclusão: 'uma', 'grupo' ou 'futuras'"),
    todas_parcelas: bool = Query(
        False, description="[DEPRECATED] Compatibilidade reversa; mapeia para escopo='grupo'"
    ),
    db: Session = Depends(get_db),
):
    service = TransactionService(db)
    modo_escopo = "grupo" if todas_parcelas else escopo.lower()
    try:
        count = service.delete_transaction(trans_id, escopo=modo_escopo)
        db.commit()
        if modo_escopo in ["grupo", "futuras"] and count > 1:
            return {
                "message": f"{count} parcelas removidas com sucesso (escopo: {modo_escopo})",
                "deleted_count": count,
            }
        return {"message": "Transação removida com sucesso", "deleted_count": count}
    except KeyError as e:
        raise HTTPException(status_code=404, detail="Transação não encontrada") from e
