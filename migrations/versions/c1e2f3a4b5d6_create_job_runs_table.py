"""create job_runs table for external-tick idempotent job scheduler

Revision ID: c1e2f3a4b5d6
Revises: b7a1f8c2e4d9
Create Date: 2026-10-30 08:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1e2f3a4b5d6"
down_revision: str | None = "b7a1f8c2e4d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "job_runs" not in tables:
        op.create_table(
            "job_runs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("job_name", sa.String(60), nullable=False),
            sa.Column("run_key", sa.String(60), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'running'")),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("error_code", sa.String(100), nullable=True),
        )
        op.create_index("ix_job_runs_id", "job_runs", ["id"])
        op.create_index("ix_job_runs_job_name", "job_runs", ["job_name"])
        op.create_index("ix_job_runs_run_key", "job_runs", ["run_key"])
        op.create_index("ix_job_runs_status", "job_runs", ["status"])
        op.create_index(
            "uq_job_runs_name_key",
            "job_runs",
            ["job_name", "run_key"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "job_runs" in tables:
        op.drop_table("job_runs")
