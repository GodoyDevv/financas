"""
backend/repositories/outbound_message_repo.py

Repositório para rastreamento de mensagens ativas enviadas pelo bot (anti-loop).
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import OutboundMessage


class OutboundMessageRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_message_id(self, message_id: str) -> OutboundMessage | None:
        stmt = select(OutboundMessage).where(OutboundMessage.message_id == message_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def exists(self, message_id: str) -> bool:
        stmt = select(OutboundMessage.id).where(OutboundMessage.message_id == message_id)
        return self.db.execute(stmt).first() is not None

    def add(
        self,
        message_id: str,
        kind: str,
        ref_type: str | None = None,
        ref_id: str | None = None,
        remote_jid: str | None = None,
    ) -> OutboundMessage:
        msg = OutboundMessage(
            message_id=message_id,
            kind=kind,
            ref_type=ref_type,
            ref_id=str(ref_id) if ref_id is not None else None,
            remote_jid=remote_jid,
        )
        self.db.add(msg)
        self.db.flush()
        return msg

    def list_by_ref(self, ref_type: str, ref_id: str) -> Sequence[OutboundMessage]:
        stmt = (
            select(OutboundMessage)
            .where(
                OutboundMessage.ref_type == ref_type,
                OutboundMessage.ref_id == str(ref_id),
            )
            .order_by(OutboundMessage.created_at.desc())
        )
        return self.db.execute(stmt).scalars().all()
