"""align postgres indexes

Revision ID: 266f67827cdb
Revises: 0001_baseline
Create Date: 2026-10-23 20:03:26.708683

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "266f67827cdb"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # No Postgres, remove constraint unique anterior se existir
        inspector = sa.inspect(bind)
        uq_names = [u["name"] for u in inspector.get_unique_constraints("categories")]
        if "categories_name_key" in uq_names:
            op.drop_constraint("categories_name_key", "categories", type_="unique")

        # Cria índices com if not exists logic
        existing_cat_idx = [i["name"] for i in inspector.get_indexes("categories")]
        if "ix_categories_id" not in existing_cat_idx:
            op.create_index(op.f("ix_categories_id"), "categories", ["id"], unique=False)
        if "ix_categories_name" not in existing_cat_idx:
            op.create_index(op.f("ix_categories_name"), "categories", ["name"], unique=True)

        existing_tx_idx = [i["name"] for i in inspector.get_indexes("transactions")]
        if "ix_transactions_id" not in existing_tx_idx:
            op.create_index(op.f("ix_transactions_id"), "transactions", ["id"], unique=False)
    else:
        # SQLite: usa batch_alter_table para garantir compatibilidade
        with op.batch_alter_table("categories") as batch_op:
            batch_op.create_index(
                op.f("ix_categories_id"), ["id"], unique=False, if_not_exists=True
            )
            batch_op.create_index(
                op.f("ix_categories_name"), ["name"], unique=True, if_not_exists=True
            )
        with op.batch_alter_table("transactions") as batch_op:
            batch_op.create_index(
                op.f("ix_transactions_id"), ["id"], unique=False, if_not_exists=True
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.drop_index(op.f("ix_transactions_id"), table_name="transactions", if_exists=True)
        op.drop_index(op.f("ix_categories_name"), table_name="categories", if_exists=True)
        op.drop_index(op.f("ix_categories_id"), table_name="categories", if_exists=True)
        op.create_unique_constraint("categories_name_key", "categories", ["name"])
    else:
        with op.batch_alter_table("transactions") as batch_op:
            batch_op.drop_index(op.f("ix_transactions_id"))
        with op.batch_alter_table("categories") as batch_op:
            batch_op.drop_index(op.f("ix_categories_name"))
            batch_op.drop_index(op.f("ix_categories_id"))
