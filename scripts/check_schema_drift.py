#!/usr/bin/env python3
"""
scripts/check_schema_drift.py

Conecta no banco via DATABASE_URL (mesma lógica de backend/database.py) e
compara o schema atual do banco com os models SQLAlchemy (backend.models).
SOMENTE LEITURA: não altera o banco de dados.

Sai com código 0 se não houver diferenças (schema idêntico).
Sai com código 1 se houver drift (tabelas, colunas, tipos, nullable ou índices divergentes).
"""

import os
import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path mesmo ao executar diretamente
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic.migration import MigrationContext
from alembic.autogenerate import compare_metadata

from backend.database import create_db_engine, Base
import backend.models  # Garante que todos os models estão registrados


def main() -> int:
    print("=" * 60)
    print("Verificando Schema Drift entre Modelos SQLAlchemy e Banco Real")
    print("=" * 60)

    engine = create_db_engine()
    # Log sanitized URL
    raw_url = str(engine.url)
    sanitized_url = raw_url.split("@")[-1] if "@" in raw_url else raw_url
    print(f"Destino: ...@{sanitized_url}" if "@" in raw_url else f"Destino: {sanitized_url}")

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True}
        )
        diff = compare_metadata(context, Base.metadata)

    if not diff:
        print("\n[OK] Sucesso: O schema do banco de dados esta 100% sincronizado com os modelos!")
        return 0

    print("\n[ALERTA] Foram encontradas divergencias (Schema Drift) entre o banco e os modelos:\n")
    for change in diff:
        print(f"  - {change}")

    print("\nAcao recomendada:")
    print("  1. Verifique se as migrations necessarias foram executadas (`alembic upgrade head`).")
    print("  2. Se os modelos foram alterados no codigo, gere uma nova revision:")
    print("     alembic revision --autogenerate -m \"descreva as mudancas\"")
    return 1


if __name__ == "__main__":
    sys.exit(main())
