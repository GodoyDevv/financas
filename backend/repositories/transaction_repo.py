"""
backend/repositories/transaction_repo.py

Consultas e persistência de dados para Transaction usando SQLAlchemy Session.
Sem regras de negócio nem commits explícitos.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.db.models import Transaction


class TransactionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, trans_id: int) -> Transaction | None:
        stmt = select(Transaction).where(Transaction.id == trans_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_date_range(
        self,
        start_date: date,
        end_date: date,
        tipo: str | None = None,
        category_id: int | None = None,
    ) -> Sequence[Transaction]:
        stmt = select(Transaction).where(
            Transaction.data >= start_date,
            Transaction.data < end_date,
        )
        if tipo:
            stmt = stmt.where(Transaction.tipo == tipo)
        if category_id:
            stmt = stmt.where(Transaction.category_id == category_id)

        stmt = stmt.order_by(Transaction.data.desc(), Transaction.id.desc())
        return self.db.execute(stmt).scalars().all()

    def list_by_group_id(self, group_id: str) -> Sequence[Transaction]:
        stmt = (
            select(Transaction)
            .where(Transaction.parcela_grupo_id == group_id)
            .order_by(Transaction.parcela_num.asc())
        )
        return self.db.execute(stmt).scalars().all()

    def add(self, transaction: Transaction) -> Transaction:
        self.db.add(transaction)
        self.db.flush()
        return transaction

    def add_all(self, transactions: list[Transaction]) -> list[Transaction]:
        self.db.add_all(transactions)
        self.db.flush()
        return transactions

    def delete(self, transaction: Transaction) -> None:
        self.db.delete(transaction)
        self.db.flush()

    def delete_by_group_id(self, group_id: str) -> int:
        stmt = delete(Transaction).where(Transaction.parcela_grupo_id == group_id)
        result = self.db.execute(stmt)
        self.db.flush()
        return result.rowcount or 0

    def get_totals_by_type_in_range(
        self, start_date: date, end_date: date
    ) -> dict[str, Decimal]:
        """Agrega a soma de valores por tipo no intervalo de datas."""
        stmt = (
            select(Transaction.tipo, func.coalesce(func.sum(Transaction.valor), Decimal("0.00")))
            .where(Transaction.data >= start_date, Transaction.data < end_date)
            .group_by(Transaction.tipo)
        )
        rows = self.db.execute(stmt).all()
        return {r[0]: Decimal(str(r[1])) for r in rows}
