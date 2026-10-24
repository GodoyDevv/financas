"""convert valor to numeric and data to date

Revision ID: c84794fd1d00
Revises: 266f67827cdb
Create Date: 2026-10-23 21:50:00.000000

"""
from typing import Sequence, Union
import re
from decimal import Decimal, ROUND_HALF_UP

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = 'c84794fd1d00'
down_revision: Union[str, None] = '266f67827cdb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if not inspector.has_table("transactions"):
        return

    # 1. PRÉ-VALIDAÇÃO DE DADOS EXISTENTES (Idempotência e Segurança)
    rows = bind.execute(text("SELECT id, data, valor FROM transactions")).fetchall()
    
    invalid_dates = []
    values_with_extra_decimals = []

    for r in rows:
        row_id, r_data, r_valor = r[0], str(r[1]).strip() if r[1] is not None else "", r[2]
        
        # Validação de data ISO YYYY-MM-DD
        if not ISO_DATE_REGEX.match(r_data):
            invalid_dates.append((row_id, r_data))
        else:
            try:
                parts = [int(p) for p in r_data.split("-")]
                if parts[1] < 1 or parts[1] > 12 or parts[2] < 1 or parts[2] > 31:
                    invalid_dates.append((row_id, r_data))
            except Exception:
                invalid_dates.append((row_id, r_data))

        # Validação de casas decimais em valor
        if r_valor is not None:
            d_val = Decimal(str(r_valor))
            rounded_val = d_val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if d_val != rounded_val:
                values_with_extra_decimals.append((row_id, str(r_valor), str(rounded_val)))

    # SE HOUVER DATAS INVÁLIDAS: ABORTAR SEM ALTERAR O BANCO
    if invalid_dates:
        err_msg = (
            f"[ABORTADO] Impossível migrar: foram encontradas {len(invalid_dates)} transações com "
            f"formato de data inválido (fora do padrão ISO YYYY-MM-DD). IDs e valores encontrados: "
            f"{invalid_dates[:20]}"
        )
        raise ValueError(err_msg)

    if values_with_extra_decimals:
        print(
            f"[AVISO MIGRATION] {len(values_with_extra_decimals)} transações possuem mais de 2 casas decimais "
            f"e serão arredondadas com ROUND_HALF_UP: IDs: {[v[0] for v in values_with_extra_decimals[:10]]}"
        )

    # 2. APLICAÇÃO DA MIGRAÇÃO POR DIALETO
    if dialect == "postgresql":
        op.execute(text("ALTER TABLE transactions ALTER COLUMN valor TYPE NUMERIC(12,2) USING ROUND(valor::numeric, 2)"))
        op.execute(text("ALTER TABLE transactions ALTER COLUMN data TYPE DATE USING data::date"))
        
        existing_indexes = [idx["name"] for idx in inspector.get_indexes("transactions")]
        if "ix_transactions_data" not in existing_indexes:
            op.create_index("ix_transactions_data", "transactions", ["data"], unique=False)
        if "ix_transactions_data_tipo" not in existing_indexes:
            op.create_index("ix_transactions_data_tipo", "transactions", ["data", "tipo"], unique=False)
            
    else:
        # SQLite: aplica arredondamento explícito antes do batch copy
        if values_with_extra_decimals:
            for item in values_with_extra_decimals:
                bind.execute(
                    text("UPDATE transactions SET valor = :v WHERE id = :id"),
                    {"v": float(item[2]), "id": item[0]}
                )

        with op.batch_alter_table("transactions") as batch_op:
            batch_op.alter_column(
                "valor",
                existing_type=sa.Float(),
                type_=sa.Numeric(12, 2),
                nullable=False
            )
            batch_op.alter_column(
                "data",
                existing_type=sa.String(),
                type_=sa.Date(),
                nullable=False
            )
            batch_op.create_index("ix_transactions_data", ["data"], unique=False)
            batch_op.create_index("ix_transactions_data_tipo", ["data", "tipo"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if not inspector.has_table("transactions"):
        return

    if dialect == "postgresql":
        op.drop_index("ix_transactions_data_tipo", table_name="transactions", if_exists=True)
        op.drop_index("ix_transactions_data", table_name="transactions", if_exists=True)
        op.execute(text("ALTER TABLE transactions ALTER COLUMN valor TYPE DOUBLE PRECISION USING valor::double precision"))
        op.execute(text("ALTER TABLE transactions ALTER COLUMN data TYPE VARCHAR USING data::varchar"))
    else:
        with op.batch_alter_table("transactions") as batch_op:
            batch_op.drop_index("ix_transactions_data_tipo")
            batch_op.drop_index("ix_transactions_data")
            batch_op.alter_column(
                "valor",
                existing_type=sa.Numeric(12, 2),
                type_=sa.Float(),
                nullable=False
            )
            batch_op.alter_column(
                "data",
                existing_type=sa.Date(),
                type_=sa.String(),
                nullable=False
            )
