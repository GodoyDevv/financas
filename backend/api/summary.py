"""
backend/api/summary.py

Router FastAPI para os endpoints /api/summary e /api/metrics.
Delega toda a consolidação ao SummaryService.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas import FinancialSummary, MetricsResponse
from backend.services.summary import SummaryService

router = APIRouter(tags=["Summary & Metrics"])


@router.get("/summary", response_model=FinancialSummary)
def get_summary(
    mes: str | None = Query(None, description="Mês no formato YYYY-MM (ex: 2026-10)"),
    db: Session = Depends(get_db),
):
    service = SummaryService(db)
    try:
        data = service.get_month_summary(mes=mes)
        db.commit()
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(
    mes: str | None = Query(None, description="Mês no formato YYYY-MM (ex: 2026-10)"),
    db: Session = Depends(get_db),
):
    service = SummaryService(db)
    try:
        data = service.get_month_metrics(mes=mes)
        db.commit()
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
