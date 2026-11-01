"""
backend/repositories/transaction_repo.py

Consultas e persistência de dados para Transaction usando SQLAlchemy Session.
Sem regras de negócio nem commits explícitos.
Garante que todas as consultas respeitem o filtro de soft delete (deleted_at IS NULL).
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend.db.models import Transaction


def active_transactions_filter() -> ColumnElement[bool]:
    """Helper único que garante que transações com soft delete nunca sejam retornadas."""
    return Transaction.deleted_at.is_(None)


class TransactionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, trans_id: int, include_deleted: bool = False) -> Transaction | None:
        stmt = select(Transaction).where(Transaction.id == trans_id)
        if not include_deleted:
            stmt = stmt.where(active_transactions_filter())
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_date_range(
        self,
        start_date: date,
        end_date: date,
        tipo: str | None = None,
        category_id: int | None = None,
        include_deleted: bool = False,
    ) -> Sequence[Transaction]:
        stmt = select(Transaction).where(
            Transaction.data >= start_date,
            Transaction.data < end_date,
        )
        if not include_deleted:
            stmt = stmt.where(active_transactions_filter())
        if tipo:
            stmt = stmt.where(Transaction.tipo == tipo)
        if category_id:
            stmt = stmt.where(Transaction.category_id == category_id)

        stmt = stmt.order_by(Transaction.data.desc(), Transaction.id.desc())
        return self.db.execute(stmt).scalars().all()

    def list_by_group_id(
        self, group_id: str, include_deleted: bool = False
    ) -> Sequence[Transaction]:
        stmt = select(Transaction).where(Transaction.parcela_grupo_id == group_id)
        if not include_deleted:
            stmt = stmt.where(active_transactions_filter())
        stmt = stmt.order_by(Transaction.parcela_num.asc())
        return self.db.execute(stmt).scalars().all()

    def add(self, transaction: Transaction) -> Transaction:
        self.db.add(transaction)
        self.db.flush()
        return transaction

    def add_all(self, transactions: list[Transaction]) -> list[Transaction]:
        self.db.add_all(transactions)
        self.db.flush()
        return transactions

    def hard_delete(self, transaction: Transaction) -> None:
        """Exclusão física definitiva (usada exclusivamente pelo expurgo de segurança purge_old)."""
        self.db.delete(transaction)
        self.db.flush()

    def delete(self, transaction: Transaction) -> None:
        """Compatibilidade: deleção física."""
        self.hard_delete(transaction)

    def delete_by_group_id(self, group_id: str) -> int:
        stmt = delete(Transaction).where(Transaction.parcela_grupo_id == group_id)
        result = self.db.execute(stmt)
        self.db.flush()
        return result.rowcount or 0

    def update_category_name_for_transactions(self, category_id: int, new_name: str) -> int:
        """Atualiza a string desnormalizada categoria para todas as transações ativas com a FK category_id."""
        stmt = (
            update(Transaction)
            .where(
                Transaction.category_id == category_id,
                active_transactions_filter(),
            )
            .values(categoria=new_name)
        )
        result = self.db.execute(stmt)
        self.db.flush()
        return result.rowcount or 0

    def get_totals_by_type_in_range(self, start_date: date, end_date: date) -> dict[str, Decimal]:
        """Agrega a soma de valores por tipo no intervalo de datas respeitando soft delete."""
        stmt = (
            select(Transaction.tipo, func.coalesce(func.sum(Transaction.valor), Decimal("0.00")))
            .where(
                Transaction.data >= start_date,
                Transaction.data < end_date,
                active_transactions_filter(),
            )
            .group_by(Transaction.tipo)
        )
        rows = self.db.execute(stmt).all()
        return {r[0]: Decimal(str(r[1])) for r in rows}

    def get_expenses_by_category_in_range(
        self, start_date: date, end_date: date
    ) -> dict[int, Decimal]:
        """Agrega o total de despesas por category_id no intervalo de datas respeitando soft delete."""
        stmt = (
            select(
                Transaction.category_id,
                func.coalesce(func.sum(Transaction.valor), Decimal("0.00")),
            )
            .where(
                Transaction.tipo.in_(["despesa_fixa", "despesa_variavel", "despesa"]),
                Transaction.data >= start_date,
                Transaction.data < end_date,
                active_transactions_filter(),
            )
            .group_by(Transaction.category_id)
        )
        rows = self.db.execute(stmt).all()
        return {r[0]: Decimal(str(r[1])) for r in rows if r[0] is not None}
