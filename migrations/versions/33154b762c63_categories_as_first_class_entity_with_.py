"""categories as first class entity with budgets

Revision ID: 33154b762c63
Revises: 9240c01a1280
Create Date: 2026-10-24 20:41:46.812293

"""
from typing import Sequence, Union
import logging
import unicodedata
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column

# revision identifiers, used by Alembic.
revision: str = '33154b762c63'
down_revision: Union[str, None] = '9240c01a1280'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.migration.categories")

# Função de normalização idêntica à do domínio, autossuficiente dentro da migration
def _normalize_name(name: str) -> str:
    if not name:
        return ""
    s = " ".join(str(name).strip().split())
    s_decomposed = unicodedata.normalize("NFKD", s)
    s_no_accents = "".join(c for c in s_decomposed if not unicodedata.combining(c))
    return s_no_accents.lower()

# Categorias canônicas iniciais
SEED_CANONICAL = [
    {"name": "Salário/Renda", "tipo": "receita"},
    {"name": "Moradia", "tipo": "despesa"},
    {"name": "Contas de Consumo", "tipo": "despesa"},
    {"name": "Alimentação", "tipo": "despesa"},
    {"name": "Transporte", "tipo": "despesa"},
    {"name": "Saúde", "tipo": "despesa"},
    {"name": "Educação", "tipo": "despesa"},
    {"name": "Lazer", "tipo": "despesa"},
    {"name": "Serviços", "tipo": "despesa"},
    {"name": "Outros", "tipo": "despesa"},
]

# Aliases legados para resolução de categorias antigas
ALIASES_MAP = {
    "moradia (aluguel/condominio)": "Moradia",
    "aluguel": "Moradia",
    "condominio": "Moradia",
    "contas de consumo (luz/agua)": "Contas de Consumo",
    "contas de consumo": "Contas de Consumo",
    "luz": "Contas de Consumo",
    "agua": "Contas de Consumo",
    "energia": "Contas de Consumo",
    "enel": "Contas de Consumo",
    "sabesp": "Contas de Consumo",
    "internet": "Contas de Consumo",
    "gas": "Contas de Consumo",
    "salario": "Salário/Renda",
    "salario/renda": "Salário/Renda",
    "renda": "Salário/Renda",
    "freela": "Salário/Renda",
    "alimentacao": "Alimentação",
    "mercado": "Alimentação",
    "supermercado": "Alimentação",
    "padaria": "Alimentação",
    "restaurante": "Alimentação",
    "transporte": "Transporte",
    "combustivel": "Transporte",
    "gasolina": "Transporte",
    "uber": "Transporte",
    "saude": "Saúde",
    "farmacia": "Saúde",
    "medico": "Saúde",
    "educacao": "Educação",
    "faculdade": "Educação",
    "escola": "Educação",
    "curso": "Educação",
    "lazer": "Lazer",
    "viagem": "Lazer",
    "cinema": "Lazer",
    "servicos": "Serviços",
    "outros": "Outros",
    "outro": "Outros",
}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect_name = bind.dialect.name
    is_sqlite = (dialect_name == "sqlite")

    cat_cols = [c["name"] for c in insp.get_columns("categories")]

    # 1. Ajustar colunas na tabela 'categories'
    if is_sqlite:
        with op.batch_alter_table("categories") as batch_op:
            if "normalized_name" not in cat_cols:
                batch_op.add_column(sa.Column("normalized_name", sa.String(60), nullable=True))
            if "tipo" not in cat_cols:
                batch_op.add_column(sa.Column("tipo", sa.String(20), server_default="despesa", nullable=False))
            if "ativo" not in cat_cols:
                batch_op.add_column(sa.Column("ativo", sa.Boolean(), server_default=sa.true(), nullable=False))
            batch_op.alter_column("budget", type_=sa.Numeric(12, 2), nullable=True)
    else:
        if "normalized_name" not in cat_cols:
            op.add_column("categories", sa.Column("normalized_name", sa.String(60), nullable=True))
        if "tipo" not in cat_cols:
            op.add_column("categories", sa.Column("tipo", sa.String(20), server_default="despesa", nullable=False))
        if "ativo" not in cat_cols:
            op.add_column("categories", sa.Column("ativo", sa.Boolean(), server_default=sa.true(), nullable=False))
        op.alter_column(
            "categories",
            "budget",
            type_=sa.Numeric(12, 2),
            nullable=True,
            postgresql_using="budget::numeric(12,2)"
        )

    # 2. Popular / Sincronizar categorias canônicas
    categories_tbl = table(
        "categories",
        column("id", sa.Integer),
        column("name", sa.String),
        column("normalized_name", sa.String),
        column("tipo", sa.String),
        column("budget", sa.Numeric),
        column("ativo", sa.Boolean)
    )

    # Inspeciona linhas existentes em categories
    existing_rows = bind.execute(sa.text("SELECT id, name, normalized_name FROM categories")).fetchall()
    cat_by_norm = {}
    for r in existing_rows:
        cid, cname, cnorm = r[0], r[1], r[2]
        if not cnorm and cname:
            cnorm = _normalize_name(cname)
            bind.execute(
                sa.text("UPDATE categories SET normalized_name = :norm WHERE id = :id"),
                {"norm": cnorm, "id": cid}
            )
        if cnorm:
            cat_by_norm[cnorm] = cid

    for item in SEED_CANONICAL:
        norm = _normalize_name(item["name"])
        if norm not in cat_by_norm:
            bind.execute(
                categories_tbl.insert().values(
                    name=item["name"],
                    normalized_name=norm,
                    tipo=item["tipo"],
                    ativo=True
                )
            )
            # Recupera o id inserido
            new_row = bind.execute(
                sa.text("SELECT id FROM categories WHERE normalized_name = :norm"),
                {"norm": norm}
            ).fetchone()
            cat_by_norm[norm] = new_row[0]

    # Torna categories.normalized_name NOT NULL e cria índice único se não existir
    if is_sqlite:
        with op.batch_alter_table("categories") as batch_op:
            batch_op.alter_column("normalized_name", nullable=False)
            batch_op.create_index("ix_categories_normalized_name", ["normalized_name"], unique=True)
    else:
        op.alter_column("categories", "normalized_name", nullable=False)
        cat_indexes = [ix["name"] for ix in insp.get_indexes("categories")]
        if "ix_categories_normalized_name" not in cat_indexes:
            op.create_index("ix_categories_normalized_name", "categories", ["normalized_name"], unique=True)

    # 3. Backfill em 'transactions'
    # Consulta todas as categorias distintas atualmente em transactions
    tx_cat_rows = bind.execute(
        sa.text("SELECT DISTINCT categoria FROM transactions WHERE categoria IS NOT NULL")
    ).fetchall()

    created_unknown_categories = []

    for row in tx_cat_rows:
        raw_cat = row[0]
        norm = _normalize_name(raw_cat)
        target_name = None

        if norm in cat_by_norm:
            target_name = None
            target_id = cat_by_norm[norm]
        elif norm in ALIASES_MAP:
            canonical_name = ALIASES_MAP[norm]
            canonical_norm = _normalize_name(canonical_name)
            target_id = cat_by_norm[canonical_norm]
            target_name = canonical_name
        else:
            # Categoria desconhecida: cria nova categoria na tabela categories com o nome original (não perde dados!)
            bind.execute(
                categories_tbl.insert().values(
                    name=raw_cat.strip(),
                    normalized_name=norm,
                    tipo="despesa",
                    ativo=True
                )
            )
            new_cat_row = bind.execute(
                sa.text("SELECT id FROM categories WHERE normalized_name = :norm"),
                {"norm": norm}
            ).fetchone()
            target_id = new_cat_row[0]
            cat_by_norm[norm] = target_id
            target_name = raw_cat.strip()
            created_unknown_categories.append(raw_cat)

        # Atualiza category_id para todas as transações com esta categoria
        # Se target_name for canônico diferente do antigo, também sincroniza categoria
        if target_name:
            bind.execute(
                sa.text("UPDATE transactions SET category_id = :cid, categoria = :cname WHERE categoria = :raw"),
                {"cid": target_id, "cname": target_name, "raw": raw_cat}
            )
        else:
            bind.execute(
                sa.text("UPDATE transactions SET category_id = :cid WHERE categoria = :raw"),
                {"cid": target_id, "raw": raw_cat}
            )

    if created_unknown_categories:
        logger.warning(
            f"Categorias desconhecidas encontradas e criadas em 'categories': {created_unknown_categories}"
        )

    # Fallback de segurança para transações com category_id NULL (se houver alguma sem categoria)
    outros_id = cat_by_norm.get("outros")
    if outros_id:
        bind.execute(
            sa.text("UPDATE transactions SET category_id = :oid WHERE category_id IS NULL"),
            {"oid": outros_id}
        )

    # 4. Ajustar 'transactions': criar índice e definir category_id NOT NULL
    tx_indexes = [ix["name"] for ix in insp.get_indexes("transactions")]

    if is_sqlite:
        with op.batch_alter_table("transactions") as batch_op:
            batch_op.alter_column("category_id", nullable=False)
            if "ix_transactions_category_id" not in tx_indexes:
                batch_op.create_index("ix_transactions_category_id", ["category_id"])
    else:
        op.alter_column("transactions", "category_id", nullable=False)
        if "ix_transactions_category_id" not in tx_indexes:
            op.create_index("ix_transactions_category_id", "transactions", ["category_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    dialect_name = bind.dialect.name
    is_sqlite = (dialect_name == "sqlite")

    tx_indexes = [ix["name"] for ix in insp.get_indexes("transactions")]
    cat_indexes = [ix["name"] for ix in insp.get_indexes("categories")]
    cat_cols = [c["name"] for c in insp.get_columns("categories")]

    if is_sqlite:
        with op.batch_alter_table("transactions") as batch_op:
            if "ix_transactions_category_id" in tx_indexes:
                batch_op.drop_index("ix_transactions_category_id")
            batch_op.alter_column("category_id", nullable=True)

        with op.batch_alter_table("categories") as batch_op:
            if "ix_categories_normalized_name" in cat_indexes:
                batch_op.drop_index("ix_categories_normalized_name")
            if "normalized_name" in cat_cols:
                batch_op.drop_column("normalized_name")
            if "tipo" in cat_cols:
                batch_op.drop_column("tipo")
            if "ativo" in cat_cols:
                batch_op.drop_column("ativo")
            batch_op.alter_column("budget", type_=sa.Float(), nullable=True)
    else:
        if "ix_transactions_category_id" in tx_indexes:
            op.drop_index("ix_transactions_category_id", table_name="transactions")
        op.alter_column("transactions", "category_id", nullable=True)

        if "ix_categories_normalized_name" in cat_indexes:
            op.drop_index("ix_categories_normalized_name", table_name="categories")
        if "normalized_name" in cat_cols:
            op.drop_column("categories", "normalized_name")
        if "tipo" in cat_cols:
            op.drop_column("categories", "tipo")
        if "ativo" in cat_cols:
            op.drop_column("categories", "ativo")
        op.alter_column(
            "categories",
            "budget",
            type_=sa.Float(),
            nullable=True,
            postgresql_using="budget::float"
        )
