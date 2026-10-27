"""split source into author and channel

Revision ID: 9240c01a1280
Revises: c84794fd1d00
Create Date: 2026-10-24 03:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision: str = "9240c01a1280"
down_revision: str | None = "c84794fd1d00"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALID_CHANNELS = ["whatsapp_text", "whatsapp_audio", "dashboard", "api", "system", "unknown"]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if not inspector.has_table("transactions"):
        return

    existing_cols = [c["name"] for c in inspector.get_columns("transactions")]

    # 1. Adiciona colunas se não existirem
    if "author" not in existing_cols:
        if dialect == "postgresql":
            op.add_column("transactions", sa.Column("author", sa.String(40), nullable=True))
        else:
            with op.batch_alter_table("transactions") as batch_op:
                batch_op.add_column(sa.Column("author", sa.String(40), nullable=True))

    if "channel" not in existing_cols:
        if dialect == "postgresql":
            op.add_column(
                "transactions",
                sa.Column(
                    "channel", sa.String(20), nullable=False, server_default=sa.text("'unknown'")
                ),
            )
            op.create_check_constraint(
                "ck_transactions_channel", "transactions", sa.column("channel").in_(VALID_CHANNELS)
            )
        else:
            with op.batch_alter_table("transactions") as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "channel",
                        sa.String(20),
                        nullable=False,
                        server_default=sa.text("'unknown'"),
                    )
                )
                batch_op.create_check_constraint(
                    "ck_transactions_channel", sa.column("channel").in_(VALID_CHANNELS)
                )

    # 2. Backfill de dados a partir de 'source'
    rows = bind.execute(text("SELECT id, source FROM transactions")).fetchall()

    count_bruno = 0
    count_leticia = 0
    count_dashboard = 0
    count_whatsapp_text = 0
    count_unknown = 0

    for r in rows:
        row_id, raw_source = r[0], r[1]
        s = str(raw_source).strip() if raw_source is not None else ""
        s_lower = s.lower()

        target_author = None
        target_channel = "unknown"

        if "let" in s_lower or "tícia" in s_lower or "ticia" in s_lower:
            target_author = "Letícia"
            target_channel = "whatsapp_text"
            count_leticia += 1
        elif "bruno" in s_lower:
            target_author = "Bruno"
            target_channel = "whatsapp_text"
            count_bruno += 1
        elif s_lower in ["manual", "dashboard"]:
            target_author = None
            target_channel = "dashboard"
            count_dashboard += 1
        elif s_lower in ["whatsapp", "zap"]:
            target_author = None
            target_channel = "whatsapp_text"
            count_whatsapp_text += 1
        elif s_lower in ["api"]:
            target_author = None
            target_channel = "api"
        elif s_lower in ["system", "sistema", "scheduler"]:
            target_author = None
            target_channel = "system"
        else:
            target_author = s if s else None
            target_channel = "unknown"
            count_unknown += 1

        bind.execute(
            text("UPDATE transactions SET author = :a, channel = :c WHERE id = :id"),
            {"a": target_author, "c": target_channel, "id": row_id},
        )

    print(
        f"[BACKFILL CONCLUÍDO] Linhas atualizadas: "
        f"Bruno={count_bruno}, Letícia={count_leticia}, Dashboard={count_dashboard}, "
        f"WhatsApp_Text={count_whatsapp_text}, Desconhecido={count_unknown}"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if not inspector.has_table("transactions"):
        return

    existing_cols = [c["name"] for c in inspector.get_columns("transactions")]

    if dialect == "postgresql":
        if "channel" in existing_cols:
            op.drop_constraint("ck_transactions_channel", "transactions", type_="check")
            op.drop_column("transactions", "channel")
        if "author" in existing_cols:
            op.drop_column("transactions", "author")
    else:
        with op.batch_alter_table("transactions") as batch_op:
            if "channel" in existing_cols:
                batch_op.drop_constraint("ck_transactions_channel", type_="check")
                batch_op.drop_column("channel")
            if "author" in existing_cols:
                batch_op.drop_column("author")
