"""
backend/models.py

Módulo retrocompatível. Re-exporta modelos de backend.db.models.
"""

from backend.db.models import (
    Category,
    JobRun,
    OutboundMessage,
    ProcessedMessage,
    Recurrence,
    Transaction,
    TransactionEvent,
)

__all__ = [
    "Category",
    "JobRun",
    "OutboundMessage",
    "ProcessedMessage",
    "Recurrence",
    "Transaction",
    "TransactionEvent",
]
