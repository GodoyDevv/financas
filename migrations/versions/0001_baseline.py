"""baseline: create categories and transactions tables idempotently

Revision ID: 0001_baseline
Revises: 
Create Date: 2026-10-23 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001_baseline'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Em execuções offline (--sql), inspector de conexão ao vivo não está disponível
    has_categories = False
    has_transactions = False
    if hasattr(bind, "engine") or not getattr(bind, "is_mock", False):
        try:
            inspector = sa.inspect(bind)
            has_categories = inspector.has_table("categories")
            has_transactions = inspector.has_table("transactions")
        except Exception:
            pass

    # 1. Tabela categories
    if not has_categories:
        op.create_table(
            "categories",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("budget", sa.Float(), nullable=True, server_default=sa.text("0.0")),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        )
        op.create_index(op.f("ix_categories_id"), "categories", ["id"], unique=False)
        op.create_index(op.f("ix_categories_name"), "categories", ["name"], unique=True)

    # 2. Tabela transactions
    if not has_transactions:
        op.create_table(
            "transactions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tipo", sa.String(), nullable=False),
            sa.Column("valor", sa.Float(), nullable=False),
            sa.Column("categoria", sa.String(), nullable=False),
            sa.Column("data", sa.String(), nullable=False),
            sa.Column("descricao", sa.String(), nullable=True),
            sa.Column("source", sa.String(), nullable=True, server_default=sa.text("'Manual'")),
            sa.Column("vencimento", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("category_id", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(
                ["category_id"],
                ["categories.id"],
                name=op.f("fk_transactions_category_id_categories")
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        )
        op.create_index(op.f("ix_transactions_id"), "transactions", ["id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    has_categories = True
    has_transactions = True
    if hasattr(bind, "engine") or not getattr(bind, "is_mock", False):
        try:
            inspector = sa.inspect(bind)
            has_categories = inspector.has_table("categories")
            has_transactions = inspector.has_table("transactions")
        except Exception:
            pass

    if has_transactions:
        op.drop_table("transactions")

    if has_categories:
        op.drop_table("categories")
