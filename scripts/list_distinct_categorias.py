"""Script de leitura para inspecionar categorias distintas e contagens em transactions."""

import sys
from pathlib import Path

# Garante raiz do projeto no sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text

from backend.config import get_settings


def main():
    database_url = get_settings().DATABASE_URL

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
