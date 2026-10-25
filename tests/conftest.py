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

# Garante que DATABASE_URL esteja definida ANTES de qualquer import do backend
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db_path = _tmp_db.name
_tmp_db.close()
_test_db_url = f"sqlite:///{_test_db_path.replace(os.sep, '/')}"
os.environ["DATABASE_URL"] = _test_db_url

# Importa database e reconfigura o engine e SessionLocal caso já tenham sido importados
import backend.database as db_module
db_module.engine = db_module.create_db_engine()
db_module.SessionLocal.configure(bind=db_module.engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", _test_db_url)
    command.upgrade(alembic_cfg, "head")

    yield

    if os.path.exists(_test_db_path):
        try:
            os.remove(_test_db_path)
        except OSError:
            pass

