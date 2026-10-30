"""idempotent processed messages and source message id

Revision ID: b7a1f8c2e4d9
Revises: 503e1f202762
Create Date: 2026-10-29 22:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7a1f8c2e4d9"
down_revision: str | None = "503e1f202762"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    # 1. Criação da tabela processed_messages
    if "processed_messages" not in tables:
        op.create_table(
            "processed_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("message_id", sa.String(128), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'received'")),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
            sa.Column("error_code", sa.String(100), nullable=True),
            sa.Column("replied", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("payload", sa.JSON(), nullable=True),
        )
        op.create_index("ix_processed_messages_id", "processed_messages", ["id"])
        op.create_index("ix_processed_messages_message_id", "processed_messages", ["message_id"], unique=True)
        op.create_index("ix_processed_messages_status", "processed_messages", ["status"])
        op.create_index("ix_processed_messages_next_attempt_at", "processed_messages", ["next_attempt_at"])

    # 2. Adiciona coluna source_message_id na tabela transactions
    if "transactions" in tables:
        tx_cols = [c["name"] for c in insp.get_columns("transactions")]
        if "source_message_id" not in tx_cols:
            dialect = bind.dialect.name
            if dialect == "postgresql":
                op.add_column("transactions", sa.Column("source_message_id", sa.String(128), nullable=True))
                op.create_index(
                    "uq_transactions_source_message_id",
                    "transactions",
                    ["source_message_id"],
                    unique=True,
                )
            else:
                with op.batch_alter_table("transactions") as batch_op:
                    batch_op.add_column(sa.Column("source_message_id", sa.String(128), nullable=True))
                    batch_op.create_index(
                        "uq_transactions_source_message_id",
                        ["source_message_id"],
                        unique=True,
                    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    # 1. Remove coluna e índice de transactions
    if "transactions" in tables:
        tx_cols = [c["name"] for c in insp.get_columns("transactions")]
        if "source_message_id" in tx_cols:
            dialect = bind.dialect.name
            if dialect == "postgresql":
                op.drop_index("uq_transactions_source_message_id", table_name="transactions")
                op.drop_column("transactions", "source_message_id")
            else:
                with op.batch_alter_table("transactions") as batch_op:
                    batch_op.drop_index("uq_transactions_source_message_id")
                    batch_op.drop_column("source_message_id")

    # 2. Remove tabela processed_messages
    if "processed_messages" in tables:
        op.drop_table("processed_messages")
