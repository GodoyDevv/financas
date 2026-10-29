"""
backend/repositories/recurrence_repo.py

Consultas e persistência de dados para Recurrence usando SQLAlchemy Session.
Sem regras de negócio nem commits explícitos.
"""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Recurrence


class RecurrenceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, rec_id: int) -> Recurrence | None:
        stmt = select(Recurrence).where(Recurrence.id == rec_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(self, apenas_ativas: bool = False) -> Sequence[Recurrence]:
        stmt = select(Recurrence)
        if apenas_ativas:
            stmt = stmt.where(Recurrence.ativo.is_(True))
        stmt = stmt.order_by(Recurrence.dia_do_mes.asc(), Recurrence.id.asc())
        return self.db.execute(stmt).scalars().all()

    def list_active_for_month(self, target_month_start: date) -> Sequence[Recurrence]:
        """
        Retorna regras ativas que cobrem o mês indicado:
        inicio <= target_month_start e (fim is None or fim >= target_month_start)
        """
        stmt = select(Recurrence).where(
            Recurrence.ativo.is_(True),
            Recurrence.inicio <= target_month_start,
            (Recurrence.fim.is_(None)) | (Recurrence.fim >= target_month_start),
        )
        return self.db.execute(stmt).scalars().all()

    def add(self, recurrence: Recurrence) -> Recurrence:
        self.db.add(recurrence)
        self.db.flush()
        return recurrence

    def delete(self, recurrence: Recurrence) -> None:
        self.db.delete(recurrence)
        self.db.flush()
