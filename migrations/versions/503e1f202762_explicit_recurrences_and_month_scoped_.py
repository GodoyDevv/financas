"""explicit recurrences and month-scoped totals

Revision ID: 503e1f202762
Revises: face6b836ff4
Create Date: 2026-10-24 21:55:55.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "503e1f202762"
down_revision: str | None = "face6b836ff4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect_name = bind.dialect.name
    is_sqlite = dialect_name == "sqlite"

    tables = insp.get_table_names()

    # 1. Criação da tabela recurrences (se não existir)
    if "recurrences" not in tables:
        op.create_table(
            "recurrences",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("tipo", sa.String(20), nullable=False),
            sa.Column("descricao", sa.String(200), nullable=False),
            sa.Column("valor", sa.Numeric(12, 2), nullable=False),
            sa.Column(
                "category_id",
                sa.Integer(),
                sa.ForeignKey("categories.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("author", sa.String(40), nullable=True),
            sa.Column("dia_do_mes", sa.Integer(), nullable=False),
            sa.Column("inicio", sa.Date(), nullable=False),
            sa.Column("fim", sa.Date(), nullable=True),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        )

    # 2. Adicionar colunas de recorrência em transactions
    tx_cols = [c["name"] for c in insp.get_columns("transactions")]
    tx_indexes = [ix["name"] for ix in insp.get_indexes("transactions")]

    if is_sqlite:
        with op.batch_alter_table("transactions") as batch_op:
            if "recurrence_id" not in tx_cols:
                batch_op.add_column(
                    sa.Column(
                        "recurrence_id",
                        sa.Integer(),
                        sa.ForeignKey("recurrences.id"),
                        nullable=True,
                    )
                )
            if "competencia" not in tx_cols:
                batch_op.add_column(sa.Column("competencia", sa.Date(), nullable=True))
            if "editado_manual" not in tx_cols:
                batch_op.add_column(
                    sa.Column(
                        "editado_manual", sa.Boolean(), nullable=False, server_default=sa.false()
                    )
                )
            if "ix_transactions_recurrence_id" not in tx_indexes:
                batch_op.create_index("ix_transactions_recurrence_id", ["recurrence_id"])
            if "uq_transactions_recurrence_competencia" not in tx_indexes:
                batch_op.create_index(
                    "uq_transactions_recurrence_competencia",
                    ["recurrence_id", "competencia"],
                    unique=True,
                )
    else:
        if "recurrence_id" not in tx_cols:
            op.add_column(
                "transactions",
                sa.Column(
                    "recurrence_id", sa.Integer(), sa.ForeignKey("recurrences.id"), nullable=True
                ),
            )
        if "competencia" not in tx_cols:
            op.add_column("transactions", sa.Column("competencia", sa.Date(), nullable=True))
        if "editado_manual" not in tx_cols:
            op.add_column(
                "transactions",
                sa.Column(
                    "editado_manual", sa.Boolean(), nullable=False, server_default=sa.false()
                ),
            )
        if "ix_transactions_recurrence_id" not in tx_indexes:
            op.create_index("ix_transactions_recurrence_id", "transactions", ["recurrence_id"])
        if "uq_transactions_recurrence_competencia" not in tx_indexes:
            op.create_index(
                "uq_transactions_recurrence_competencia",
                "transactions",
                ["recurrence_id", "competencia"],
                unique=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect_name = bind.dialect.name
    is_sqlite = dialect_name == "sqlite"

    tx_indexes = [ix["name"] for ix in insp.get_indexes("transactions")]
    tx_cols = [c["name"] for c in insp.get_columns("transactions")]
    tables = insp.get_table_names()

    if is_sqlite:
        with op.batch_alter_table("transactions") as batch_op:
            if "uq_transactions_recurrence_competencia" in tx_indexes:
                batch_op.drop_index("uq_transactions_recurrence_competencia")
            if "ix_transactions_recurrence_id" in tx_indexes:
                batch_op.drop_index("ix_transactions_recurrence_id")
            if "editado_manual" in tx_cols:
                batch_op.drop_column("editado_manual")
            if "competencia" in tx_cols:
                batch_op.drop_column("competencia")
            if "recurrence_id" in tx_cols:
                batch_op.drop_column("recurrence_id")
    else:
        if "uq_transactions_recurrence_competencia" in tx_indexes:
            op.drop_index("uq_transactions_recurrence_competencia", table_name="transactions")
        if "ix_transactions_recurrence_id" in tx_indexes:
            op.drop_index("ix_transactions_recurrence_id", table_name="transactions")
        if "editado_manual" in tx_cols:
            op.drop_column("transactions", "editado_manual")
        if "competencia" in tx_cols:
            op.drop_column("transactions", "competencia")
        if "recurrence_id" in tx_cols:
            op.drop_column("transactions", "recurrence_id")

    if "recurrences" in tables:
        op.drop_table("recurrences")
