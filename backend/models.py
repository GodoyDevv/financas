"""
backend/models.py

Módulo retrocompatível. Re-exporta modelos de backend.db.models.
"""

from backend.db.models import Category, ProcessedMessage, Recurrence, Transaction

__all__ = ["Category", "ProcessedMessage", "Recurrence", "Transaction"]
