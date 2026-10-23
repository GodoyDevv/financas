"""
tests/conftest.py

Configuração global do Pytest.
Garante que o banco de teste SQLite temporário seja inicializado
exclusivamente via `alembic upgrade head`, garantindo a validação
completa das migrations durante a execução da suíte de testes.
"""

import os
import tempfile
import pytest
from alembic.config import Config
from alembic import command


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    # Cria arquivo temporário SQLite para os testes
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        test_db_path = tmp.name

    test_db_url = f"sqlite:///{test_db_path.replace(os.sep, '/')}"
    old_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_db_url

    # Configura e executa `alembic upgrade head`
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)
    command.upgrade(alembic_cfg, "head")

    yield

    # Teardown: restaura variável e remove o arquivo temporário
    if old_db_url is not None:
        os.environ["DATABASE_URL"] = old_db_url
    else:
        os.environ.pop("DATABASE_URL", None)

    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except OSError:
            pass
