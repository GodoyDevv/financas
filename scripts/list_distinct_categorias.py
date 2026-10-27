"""Script de leitura para inspecionar categorias distintas e contagens em transactions."""

import os
import sys

from sqlalchemy import create_engine, text


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERRO: DATABASE_URL não definida.", file=sys.stderr)
        sys.exit(1)

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://") and not database_url.startswith("postgresql+"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql+psycopg2://"):
        database_url = database_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)

    engine = create_engine(database_url)
    with engine.connect() as conn:
        print("\n--- DISTRIBUIÇÃO ATUAL DE Transaction.categoria ---")
        result = conn.execute(
            text(
                "SELECT categoria, COUNT(*) as qtd FROM transactions GROUP BY categoria ORDER BY qtd DESC"
            )
        )
        rows = result.fetchall()
        if not rows:
            print("Nenhuma transação encontrada no banco.")
        else:
            for row in rows:
                print(f"  {row[0]!r}: {row[1]} transações")

        print("\n--- CATEGORIAS CADASTRADAS NA TABELA categories ---")
        try:
            cat_result = conn.execute(text("SELECT id, name, budget FROM categories"))
            cat_rows = cat_result.fetchall()
            if not cat_rows:
                print("  Nenhuma categoria existente na tabela 'categories'.")
            else:
                for crow in cat_rows:
                    print(f"  ID {crow[0]}: {crow[1]!r} (budget: {crow[2]})")
        except Exception as e:
            print(f"  Erro ao consultar categories: {e}")


if __name__ == "__main__":
    main()
