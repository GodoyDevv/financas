"""
backend/repositories/__init__.py

Exportações públicas da camada de repositórios.
"""

from .category_repo import CategoryRepository
from .outbound_message_repo import OutboundMessageRepository
from .recurrence_repo import RecurrenceRepository
from .transaction_event_repo import TransactionEventRepository
from .transaction_repo import TransactionRepository

__all__ = [
    "CategoryRepository",
    "OutboundMessageRepository",
    "RecurrenceRepository",
    "TransactionEventRepository",
    "TransactionRepository",
]
