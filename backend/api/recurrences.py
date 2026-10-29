"""
backend/api/recurrences.py

Router FastAPI para gerenciamento de regras de recorrência mensal.
Validação de entrada, autorização, chamadas de serviço e commit de transações.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.categories import get_valid_category_names
from backend.database import get_db
from backend.dates_and_money import to_decimal, today_br
from backend.repositories.category_repo import CategoryRepository
from backend.repositories.recurrence_repo import RecurrenceRepository
from backend.repositories.transaction_repo import TransactionRepository
from backend.schemas import RecurrenceCreate, RecurrenceResponse, RecurrenceUpdate
from backend.services.recurrences import RecurrenceService, ensure_recurrences

router = APIRouter(prefix="", tags=["Recurrences"])


@router.post("/recurrences", response_model=RecurrenceResponse)
def create_recurrence(payload: RecurrenceCreate, db: Session = Depends(get_db)):
    """Cria uma nova regra de recorrência mensal (receita ou despesa fixa) e materializa o mês atual."""
    rec_repo = RecurrenceRepository(db)
    tx_repo = TransactionRepository(db)
    cat_repo = CategoryRepository(db)
    service = RecurrenceService(rec_repo, tx_repo, cat_repo)

    try:
        rec = service.create_recurrence(
            tipo=payload.tipo,
            descricao=payload.descricao,
            valor=payload.valor,
            categoria=payload.categoria,
            dia_do_mes=payload.dia_do_mes,
            author=payload.author,
            inicio=payload.inicio,
            fim=payload.fim,
        )
        db.commit()
        db.refresh(rec)
    except ValueError as e:
        msg = str(e)
        if "Categoria" in msg:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": msg,
                    "valid_categories": get_valid_category_names(),
                },
            ) from e
        raise HTTPException(status_code=400, detail=msg) from e

    # Materialização imediata para o mês corrente
    mes_atual_str = today_br().strftime("%Y-%m")
    ensure_recurrences(db, mes_atual_str)

    cat_name = rec.category_rel.name if rec.category_rel else "Outros"
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


@router.get("/recurrences", response_model=list[RecurrenceResponse])
def get_recurrences(
    apenas_ativas: bool = Query(True, description="Filtrar apenas recorrências ativas"),
    db: Session = Depends(get_db),
):
    """Lista todas as regras de recorrência cadastradas."""
    rec_repo = RecurrenceRepository(db)
    tx_repo = TransactionRepository(db)
    cat_repo = CategoryRepository(db)
    service = RecurrenceService(rec_repo, tx_repo, cat_repo)

    recs = service.list_recurrences(apenas_ativas=apenas_ativas)
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
    - Atualiza as instâncias futuras NÃO editadas manualmente.
    """
    rec_repo = RecurrenceRepository(db)
    tx_repo = TransactionRepository(db)
    cat_repo = CategoryRepository(db)
    service = RecurrenceService(rec_repo, tx_repo, cat_repo)

    valor_dec = to_decimal(payload.valor) if payload.valor is not None else None

    try:
        rec = service.update_recurrence(
            rec_id=rec_id,
            descricao=payload.descricao,
            valor=valor_dec,
            dia_do_mes=payload.dia_do_mes,
            ativo=payload.ativo,
            fim=payload.fim,
            author=payload.author,
            categoria=payload.categoria,
        )
        db.commit()
        db.refresh(rec)
    except ValueError as e:
        msg = str(e)
        if "não encontrada" in msg:
            raise HTTPException(status_code=404, detail=msg) from e
        if "Categoria" in msg:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": msg,
                    "valid_categories": get_valid_category_names(),
                },
            ) from e
        raise HTTPException(status_code=400, detail=msg) from e

    cat_name = rec.category_rel.name if rec.category_rel else "Outros"
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
    rec_repo = RecurrenceRepository(db)
    tx_repo = TransactionRepository(db)
    cat_repo = CategoryRepository(db)
    service = RecurrenceService(rec_repo, tx_repo, cat_repo)

    try:
        _, removed_count = service.delete_recurrence(rec_id)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {
        "message": f"Recorrência {rec_id} encerrada com sucesso. {removed_count} instâncias futuras removidas.",
        "removed_future_instances": removed_count,
    }
