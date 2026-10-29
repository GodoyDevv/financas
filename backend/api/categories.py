"""
backend/api/categories.py

Router FastAPI para o gerenciamento de categorias e orçamentos.
Validação de entrada, autorização, chamadas de serviço e commit de transações.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.dates_and_money import month_range, to_decimal
from backend.repositories.category_repo import CategoryRepository
from backend.repositories.transaction_repo import TransactionRepository
from backend.schemas import CategoryResponse, CategoryUpdate
from backend.services import ensure_recurrences
from backend.services.categories import CategoryService

router = APIRouter(prefix="", tags=["Categories"])


@router.get("/categories", response_model=list[CategoryResponse])
def get_categories(
    mes: str | None = Query(
        None, description="Mês no formato YYYY-MM para calcular gasto e percentual do orçamento"
    ),
    ativo: bool | None = Query(None, description="Filtrar categorias ativas/inativas"),
    db: Session = Depends(get_db),
):
    """
    Retorna a lista de categorias cadastradas com informações de orçamento (budget),
    gasto acumulado no mês (se informado) e percentual do orçamento atingido.
    """
    inicio, fim = None, None
    if mes:
        try:
            inicio, fim = month_range(mes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        # Materialização preguiçosa de recorrências ativas
        ensure_recurrences(db, mes)

    cat_repo = CategoryRepository(db)
    tx_repo = TransactionRepository(db)
    service = CategoryService(cat_repo, tx_repo)

    items = service.list_categories_with_budget(
        start_date=inicio,
        end_date=fim,
        ativo=ativo,
    )
    return [CategoryResponse(**item) for item in items]


@router.put("/categories/{cat_id}", response_model=CategoryResponse)
def update_category(cat_id: int, payload: CategoryUpdate, db: Session = Depends(get_db)):
    """Atualiza dados da categoria: budget, ativo e/ou nome."""
    cat_repo = CategoryRepository(db)
    tx_repo = TransactionRepository(db)
    service = CategoryService(cat_repo, tx_repo)

    budget_val = to_decimal(payload.budget) if payload.budget is not None else None

    try:
        category = service.update_category(
            cat_id=cat_id,
            name=payload.name,
            budget=budget_val,
            ativo=payload.ativo,
        )
        db.commit()
        db.refresh(category)
    except ValueError as e:
        msg = str(e)
        if "não encontrada" in msg:
            raise HTTPException(status_code=404, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e

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
        percentual_budget=pct_budget,
    )
