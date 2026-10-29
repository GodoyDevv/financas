"""
backend/routes.py

Agregador de rotas da API pública (/api).
Delega todos os subdomínios para seus respectivos sub-routers em backend/api/.
"""

from fastapi import APIRouter

from .api.categories import router as categories_router
from .api.parser import router as parser_router
from .api.recurrences import router as recurrences_router
from .api.summary import get_metrics
from .api.summary import router as summary_router
from .api.transactions import router as transactions_router

router = APIRouter(prefix="/api", tags=["API"])

router.include_router(transactions_router)
router.include_router(summary_router)
router.include_router(categories_router)
router.include_router(recurrences_router)
router.include_router(parser_router)

__all__ = ["get_metrics", "router"]
