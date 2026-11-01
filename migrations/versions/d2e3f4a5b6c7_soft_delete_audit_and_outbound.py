"""add soft delete to transactions, outbound_messages and transaction_events

Revision ID: d2e3f4a5b6c7
Revises: c1e2f3a4b5d6
Create Date: 2026-11-01 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "c1e2f3a4b5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    # 1. Adiciona coluna deleted_at na tabela transactions
    if "transactions" in tables:
        columns = [c["name"] for c in insp.get_columns("transactions")]
        if "deleted_at" not in columns:
            op.add_column("transactions", sa.Column("deleted_at", sa.DateTime(), nullable=True))
            op.create_index("ix_transactions_deleted_at", "transactions", ["deleted_at"])

    # 2. Cria tabela outbound_messages
    if "outbound_messages" not in tables:
        op.create_table(
            "outbound_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("message_id", sa.String(128), unique=True, nullable=False),
            sa.Column("kind", sa.String(30), nullable=False),  # confirmation, alert, help, error, report
            sa.Column("ref_type", sa.String(40), nullable=True),  # transaction, parcelamento, etc.
            sa.Column("ref_id", sa.String(64), nullable=True),
            sa.Column("remote_jid", sa.String(128), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_outbound_messages_id", "outbound_messages", ["id"])
        op.create_index("ix_outbound_messages_message_id", "outbound_messages", ["message_id"], unique=True)
        op.create_index("ix_outbound_messages_kind", "outbound_messages", ["kind"])
        op.create_index("ix_outbound_messages_ref", "outbound_messages", ["ref_type", "ref_id"])

    # 3. Cria tabela transaction_events
    if "transaction_events" not in tables:
        op.create_table(
            "transaction_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("transaction_id", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(20), nullable=False),  # created, updated, deleted, restored
            sa.Column("actor", sa.String(60), nullable=True),
            sa.Column("channel", sa.String(40), nullable=False, server_default="unknown"),
            sa.Column("diff", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_transaction_events_id", "transaction_events", ["id"])
        op.create_index("ix_transaction_events_tx_id", "transaction_events", ["transaction_id"])
        op.create_index("ix_transaction_events_action", "transaction_events", ["action"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "transaction_events" in tables:
        op.drop_table("transaction_events")

    if "outbound_messages" in tables:
        op.drop_table("outbound_messages")

    if "transactions" in tables:
        columns = [c["name"] for c in insp.get_columns("transactions")]
        if "deleted_at" in columns:
            op.drop_index("ix_transactions_deleted_at", table_name="transactions")
            op.drop_column("transactions", "deleted_at")
