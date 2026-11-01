"""
backend/repositories/transaction_event_repo.py

Repositório para trilha de auditoria e ciclo de vida de transações.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import TransactionEvent


class TransactionEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def record_event(
        self,
        transaction_id: int,
        action: str,  # created, updated, deleted, restored
        actor: str | None = None,
        channel: str = "unknown",
        diff: dict | None = None,
    ) -> TransactionEvent:
        event = TransactionEvent(
            transaction_id=transaction_id,
            action=action,
            actor=actor,
            channel=channel,
            diff=diff,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def list_by_transaction_id(self, transaction_id: int) -> Sequence[TransactionEvent]:
        stmt = (
            select(TransactionEvent)
            .where(TransactionEvent.transaction_id == transaction_id)
            .order_by(TransactionEvent.created_at.asc())
        )
        return self.db.execute(stmt).scalars().all()

    def get_last_event_by_action(
        self, action: str, actor: str | None = None
    ) -> TransactionEvent | None:
        stmt = select(TransactionEvent).where(TransactionEvent.action == action)
        if actor:
            stmt = stmt.where(TransactionEvent.actor == actor)
        stmt = stmt.order_by(TransactionEvent.created_at.desc(), TransactionEvent.id.desc())
        return self.db.execute(stmt).scalars().first()
