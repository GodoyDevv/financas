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
from alembic import command
from alembic.config import Config

# Garante variáveis falsas mínimas para Settings no ambiente de teste
os.environ.setdefault("APP_PASSWORD", "test_app_password_123")
os.environ.setdefault("SESSION_SECRET", "test_session_secret_with_32_characters_12345")
os.environ.setdefault("ADMIN_TOKEN", "test_admin_token_123")
os.environ.setdefault("ENV", "test")

# Garante que DATABASE_URL esteja definida ANTES de qualquer import do backend
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db_path = _tmp_db.name
_tmp_db.close()
_test_db_url = f"sqlite:///{_test_db_path.replace(os.sep, '/')}"
os.environ["DATABASE_URL"] = _test_db_url

from backend.config import get_settings

get_settings.cache_clear()

# Importa database e reconfigura o engine e SessionLocal caso já tenham sido importados
import contextlib

import backend.database as db_module

db_module.engine = db_module.create_db_engine()
db_module.SessionLocal.configure(bind=db_module.engine)


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Garante que o cache de get_settings seja limpo após cada teste."""
    from backend.config import get_settings

    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", _test_db_url)
    command.upgrade(alembic_cfg, "head")

    yield

    if os.path.exists(_test_db_path):
        with contextlib.suppress(OSError):
            os.remove(_test_db_path)
