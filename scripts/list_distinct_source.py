#!/usr/bin/env python3
"""
scripts/list_distinct_source.py

SOMENTE LEITURA: Conecta ao banco de dados configurado em DATABASE_URL
e lista todos os valores distintos encontrados na coluna 'source' da
tabela 'transactions', junto com a contagem de ocorrências de cada um.
"""

import sys
from pathlib import Path

# Adiciona raiz do projeto ao path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sqlalchemy as sa

from backend.database import create_db_engine


def main() -> int:
    print("=" * 60)
    print("Listando valores distintos da coluna 'source' em transactions")
    print("=" * 60)

    try:
        engine = create_db_engine()
        raw_url = str(engine.url)
        sanitized_url = raw_url.split("@")[-1] if "@" in raw_url else raw_url
        print(f"Destino: ...@{sanitized_url}" if "@" in raw_url else f"Destino: {sanitized_url}\n")

        with engine.connect() as conn:
            query = sa.text("""
                SELECT source, count(*) as total
                FROM transactions
                GROUP BY source
                ORDER BY total DESC
            """)
            rows = conn.execute(query).fetchall()

            if not rows:
                print("Nenhuma transação encontrada no banco de dados.")
                return 0

            print(f"{'VALOR DE SOURCE':<30} | {'TOTAL DE LINHAS':<15}")
            print("-" * 50)
            for r in rows:
                val = "<NULL>" if r[0] is None else repr(r[0])
                print(f"{val:<30} | {r[1]:<15}")

            total_geral = sum(r[1] for r in rows)
            print("-" * 50)
            print(f"{'TOTAL GERAL':<30} | {total_geral:<15}")
            return 0

    except Exception as e:
        print(f"Erro ao consultar banco de dados: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
