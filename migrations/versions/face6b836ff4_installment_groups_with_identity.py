"""installment groups with identity

Revision ID: face6b836ff4
Revises: 33154b762c63
Create Date: 2026-10-24 21:19:29.000000

"""

import csv
import logging
import os
import re
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "face6b836ff4"
down_revision: str | None = "33154b762c63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.migration.installments")


def _is_consecutive_months(d1: date, d2: date) -> bool:
    """Verifica se d2 ocorre exatamente no mês seguinte ao de d1."""
    expected_year = d1.year + (d1.month // 12)
    expected_month = (d1.month % 12) + 1
    return d2.year == expected_year and d2.month == expected_month


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect_name = bind.dialect.name
    is_sqlite = dialect_name == "sqlite"

    tx_cols = [c["name"] for c in insp.get_columns("transactions")]
    tx_indexes = [ix["name"] for ix in insp.get_indexes("transactions")]

    # 1. Adicionar colunas se não existirem
    if is_sqlite:
        with op.batch_alter_table("transactions") as batch_op:
            if "parcela_grupo_id" not in tx_cols:
                batch_op.add_column(sa.Column("parcela_grupo_id", sa.String(36), nullable=True))
            if "parcela_num" not in tx_cols:
                batch_op.add_column(sa.Column("parcela_num", sa.Integer(), nullable=True))
            if "parcela_total" not in tx_cols:
                batch_op.add_column(sa.Column("parcela_total", sa.Integer(), nullable=True))
    else:
        if "parcela_grupo_id" not in tx_cols:
            op.add_column(
                "transactions", sa.Column("parcela_grupo_id", sa.String(36), nullable=True)
            )
        if "parcela_num" not in tx_cols:
            op.add_column("transactions", sa.Column("parcela_num", sa.Integer(), nullable=True))
        if "parcela_total" not in tx_cols:
            op.add_column("transactions", sa.Column("parcela_total", sa.Integer(), nullable=True))

    # 2. Backfill de parcelamentos legados com auditoria e relatório CSV
    # Seleciona transações que possuem padrão "(i/N)" na descrição
    query = sa.text("""
        SELECT id, descricao, valor, tipo, categoria, data, author, category_id
        FROM transactions
        WHERE descricao IS NOT NULL
        ORDER BY id ASC
    """)
    rows = bind.execute(query).fetchall()

    regex_parcela = re.compile(r"^(.*?)\s*\((\d+)/(\d+)\)\s*$")

    # Agrupa candidatos por chave canônica: (radical, valor, tipo, categoria, author)
    candidates_by_key = defaultdict(list)
    for r in rows:
        tid, desc, val, tipo, cat, dt, author, cat_id = (
            r[0],
            r[1],
            r[2],
            r[3],
            r[4],
            r[5],
            r[6],
            r[7],
        )
        m = regex_parcela.match(desc.strip()) if desc else None
        if m:
            radical = m.group(1).strip()
            num = int(m.group(2))
            total = int(m.group(3))

            # Se dt for string (ex: em SQLite puro), converte
            if isinstance(dt, str):
                dt_obj = date.fromisoformat(dt)
            else:
                dt_obj = dt

            key = (radical, str(val), tipo, cat, str(author or ""))
            candidates_by_key[key].append(
                {
                    "id": tid,
                    "desc": desc,
                    "radical": radical,
                    "num": num,
                    "total": total,
                    "valor": val,
                    "tipo": tipo,
                    "categoria": cat,
                    "author": author,
                    "data": dt_obj,
                }
            )

    grouped_records = []
    ambiguous_records = []

    for key, items in candidates_by_key.items():
        # Ordena itens por número de parcela e data
        items.sort(key=lambda x: (x["num"], x["data"]))

        # Validação de certeza estrita:
        # - Total declarado em todas deve ser idêntico
        # - Números de parcela devem ser exatamente 1..total sem repetição
        # - As datas devem ser em meses consecutivos
        total_declarado = items[0]["total"]
        nums = [it["num"] for it in items]
        expected_nums = list(range(1, total_declarado + 1))

        eh_candidato_valido = (
            len(items) == total_declarado
            and nums == expected_nums
            and all(it["total"] == total_declarado for it in items)
        )

        # Checa meses consecutivos
        if eh_candidato_valido:
            for idx in range(len(items) - 1):
                if not _is_consecutive_months(items[idx]["data"], items[idx + 1]["data"]):
                    eh_candidato_valido = False
                    break

        if eh_candidato_valido:
            # Certeza absoluta: vincula UUID
            new_grupo_id = str(uuid.uuid4())
            for it in items:
                bind.execute(
                    sa.text("""
                        UPDATE transactions
                        SET parcela_grupo_id = :gid, parcela_num = :pnum, parcela_total = :ptot
                        WHERE id = :tid
                    """),
                    {"gid": new_grupo_id, "pnum": it["num"], "ptot": it["total"], "tid": it["id"]},
                )
                grouped_records.append(
                    {
                        "id": it["id"],
                        "grupo_id": new_grupo_id,
                        "descricao": it["desc"],
                        "parcela_num": it["num"],
                        "parcela_total": it["total"],
                        "valor": it["valor"],
                        "data": it["data"],
                        "motivo": "Agrupamento com certeza absoluta",
                    }
                )
        else:
            # Caso ambíguo ou incompleto: não adivinhar
            for it in items:
                ambiguous_records.append(
                    {
                        "id": it["id"],
                        "descricao": it["desc"],
                        "parcela_num": it["num"],
                        "parcela_total": it["total"],
                        "valor": it["valor"],
                        "data": it["data"],
                        "motivo": f"Inconsistência na sequência (encontradas {len(items)}/{total_declarado} parcelas)",
                    }
                )

    # Gera relatórios CSV em scripts/out/
    out_dir = os.path.join(os.getcwd(), "scripts", "out")
    try:
        os.makedirs(out_dir, exist_ok=True)
        # CSV de Agrupados
        with open(
            os.path.join(out_dir, "backfill_installments_grouped.csv"),
            "w",
            newline="",
            encoding="utf-8",
        ) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "id",
                    "grupo_id",
                    "descricao",
                    "parcela_num",
                    "parcela_total",
                    "valor",
                    "data",
                    "motivo",
                ],
            )
            writer.writeheader()
            writer.writerows(grouped_records)

        # CSV de Ambíguos
        with open(
            os.path.join(out_dir, "backfill_installments_ambiguous.csv"),
            "w",
            newline="",
            encoding="utf-8",
        ) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "id",
                    "descricao",
                    "parcela_num",
                    "parcela_total",
                    "valor",
                    "data",
                    "motivo",
                ],
            )
            writer.writeheader()
            writer.writerows(ambiguous_records)
    except Exception as e:
        logger.warning(f"Não foi possível salvar relatório CSV em scripts/out: {e}")

    # 3. Criar índices e constraints
    if is_sqlite:
        with op.batch_alter_table("transactions") as batch_op:
            if "ix_transactions_parcela_grupo_id" not in tx_indexes:
                batch_op.create_index("ix_transactions_parcela_grupo_id", ["parcela_grupo_id"])
            if "uq_transactions_grupo_num" not in tx_indexes:
                batch_op.create_index(
                    "uq_transactions_grupo_num", ["parcela_grupo_id", "parcela_num"], unique=True
                )
    else:
        if "ix_transactions_parcela_grupo_id" not in tx_indexes:
            op.create_index(
                "ix_transactions_parcela_grupo_id", "transactions", ["parcela_grupo_id"]
            )
        if "uq_transactions_grupo_num" not in tx_indexes:
            op.create_index(
                "uq_transactions_grupo_num",
                "transactions",
                ["parcela_grupo_id", "parcela_num"],
                unique=True,
            )
        # Adiciona CheckConstraint
        op.create_check_constraint(
            "ck_transactions_parcelas_valid",
            "transactions",
            "(parcela_grupo_id IS NULL AND parcela_num IS NULL AND parcela_total IS NULL) OR "
            "(parcela_grupo_id IS NOT NULL AND parcela_num IS NOT NULL AND parcela_total IS NOT NULL AND parcela_num >= 1 AND parcela_num <= parcela_total)",
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect_name = bind.dialect.name
    is_sqlite = dialect_name == "sqlite"

    tx_indexes = [ix["name"] for ix in insp.get_indexes("transactions")]
    tx_cols = [c["name"] for c in insp.get_columns("transactions")]

    if is_sqlite:
        with op.batch_alter_table("transactions") as batch_op:
            if "uq_transactions_grupo_num" in tx_indexes:
                batch_op.drop_index("uq_transactions_grupo_num")
            if "ix_transactions_parcela_grupo_id" in tx_indexes:
                batch_op.drop_index("ix_transactions_parcela_grupo_id")
            if "parcela_total" in tx_cols:
                batch_op.drop_column("parcela_total")
            if "parcela_num" in tx_cols:
                batch_op.drop_column("parcela_num")
            if "parcela_grupo_id" in tx_cols:
                batch_op.drop_column("parcela_grupo_id")
    else:
        try:
            op.drop_constraint("ck_transactions_parcelas_valid", "transactions", type_="check")
        except Exception:
            pass
        if "uq_transactions_grupo_num" in tx_indexes:
            op.drop_index("uq_transactions_grupo_num", table_name="transactions")
        if "ix_transactions_parcela_grupo_id" in tx_indexes:
            op.drop_index("ix_transactions_parcela_grupo_id", table_name="transactions")
        if "parcela_total" in tx_cols:
            op.drop_column("transactions", "parcela_total")
        if "parcela_num" in tx_cols:
            op.drop_column("transactions", "parcela_num")
        if "parcela_grupo_id" in tx_cols:
            op.drop_column("transactions", "parcela_grupo_id")
