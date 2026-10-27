"""
Testes unitários para backend/config.py (pydantic-settings, validações, 12-factor).
"""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from backend.config import Settings


def test_settings_secret_str_repr_never_exposes_values():
    """Garante que a representação em string ou repr de Settings nunca vaza senhas ou tokens."""
    raw_pwd = "super_secret_pwd_999"
    raw_sess = "super_secret_session_key_with_at_least_32_characters_long"
    raw_token = "admin_super_secret_token_123"

    s = Settings(
        APP_PASSWORD=SecretStr(raw_pwd),
        SESSION_SECRET=SecretStr(raw_sess),
        ADMIN_TOKEN=SecretStr(raw_token),
        WEBHOOK_SECRET=SecretStr("webhook_secret_min_32_chars_1234567"),
    )

    repr_str = repr(s)
    str_val = str(s)

    assert raw_pwd not in repr_str
    assert raw_sess not in repr_str
    assert raw_token not in repr_str
    assert "webhook_secret_min_32" not in repr_str

    assert raw_pwd not in str_val
    assert raw_sess not in str_val
    assert raw_token not in str_val


def test_settings_database_url_normalization():
    """Valida que URLs postgres:// e postgresql:// são normalizadas para postgresql+psycopg://."""
    s1 = Settings(
        APP_PASSWORD=SecretStr("pwd"),
        SESSION_SECRET=SecretStr("12345678901234567890123456789012"),
        ADMIN_TOKEN=SecretStr("token"),
        DATABASE_URL="postgres://user:pass@localhost:5432/db",
    )
    assert s1.DATABASE_URL == "postgresql+psycopg://user:pass@localhost:5432/db"

    s2 = Settings(
        APP_PASSWORD=SecretStr("pwd"),
        SESSION_SECRET=SecretStr("12345678901234567890123456789012"),
        ADMIN_TOKEN=SecretStr("token"),
        DATABASE_URL="postgresql://user:pass@localhost:5432/db",
    )
    assert s2.DATABASE_URL == "postgresql+psycopg://user:pass@localhost:5432/db"

    s3 = Settings(
        APP_PASSWORD=SecretStr("pwd"),
        SESSION_SECRET=SecretStr("12345678901234567890123456789012"),
        ADMIN_TOKEN=SecretStr("token"),
        DATABASE_URL="postgresql+psycopg2://user:pass@localhost:5432/db",
    )
    assert s3.DATABASE_URL == "postgresql+psycopg://user:pass@localhost:5432/db"

    s4 = Settings(
        APP_PASSWORD=SecretStr("pwd"),
        SESSION_SECRET=SecretStr("12345678901234567890123456789012"),
        ADMIN_TOKEN=SecretStr("token"),
        DATABASE_URL="",
    )
    assert s4.DATABASE_URL == "sqlite:///./fintrack.db"


def test_settings_fails_with_all_missing_errors_reported_at_once():
    """Reporta todas as variáveis obrigatórias faltantes em um único erro."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_PASSWORD=SecretStr(""),
            SESSION_SECRET=SecretStr(""),
            ADMIN_TOKEN=SecretStr(""),
        )

    msg = str(exc_info.value)
    assert "APP_PASSWORD é obrigatória" in msg
    assert "SESSION_SECRET é obrigatória" in msg
    assert "ADMIN_TOKEN é obrigatória" in msg


def test_settings_short_session_secret_rejected():
    """Rejeita SESSION_SECRET com menos de 32 caracteres."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_PASSWORD=SecretStr("valid_password"),
            SESSION_SECRET=SecretStr("short_secret_20_chars"),
            ADMIN_TOKEN=SecretStr("admin_token_ok"),
        )
    assert "SESSION_SECRET deve conter no mínimo 32 caracteres" in str(exc_info.value)


def test_settings_production_requires_mandatory_fields():
    """Em ambiente production, exige WEBHOOK_SECRET, GROUP_JID e telefones do casal."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENV="production",
            APP_PASSWORD=SecretStr("ValidProdPassword123!"),
            SESSION_SECRET=SecretStr("LongSessionSecretWithAtLeast32Chars12345"),
            ADMIN_TOKEN=SecretStr("ValidAdminToken12345"),
            WEBHOOK_SECRET=SecretStr(""),
            WHATSAPP_GROUP_JID="",
            WHATSAPP_USER_BRUNO="",
            WHATSAPP_USER_LETICIA="",
        )

    msg = str(exc_info.value)
    assert "WEBHOOK_SECRET é obrigatória em ambiente de produção" in msg
    assert "WHATSAPP_GROUP_JID é obrigatório em ambiente de produção" in msg
    assert "WHATSAPP_USER_BRUNO é obrigatório em ambiente de produção" in msg
    assert "WHATSAPP_USER_LETICIA é obrigatório em ambiente de produção" in msg


def test_settings_production_rejects_example_placeholders():
    """Em ambiente production, rejeita valores contendo placeholders do .env.example."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENV="production",
            APP_PASSWORD=SecretStr("sua_senha_forte_aqui"),
            SESSION_SECRET=SecretStr(
                "gere_uma_chave_secreta_aleatoria_com_mais_de_32_caracteres_hex"
            ),
            ADMIN_TOKEN=SecretStr("gere_um_token_administrativo_aleatorio_seguro"),
            WEBHOOK_SECRET=SecretStr("gere_um_segredo_para_o_webhook_com_pelo_menos_32_caracteres"),
            WHATSAPP_GROUP_JID="120363000000000000@g.us",
            WHATSAPP_USER_BRUNO="5511999999999",
            WHATSAPP_USER_LETICIA="5511988888888",
        )

    msg = str(exc_info.value)
    assert "APP_PASSWORD contém valor de exemplo/placeholder" in msg
    assert "SESSION_SECRET contém valor de exemplo/placeholder" in msg
    assert "ADMIN_TOKEN contém valor de exemplo/placeholder" in msg
    assert "WEBHOOK_SECRET contém valor de exemplo/placeholder" in msg


def test_no_os_getenv_or_environ_in_backend_and_scripts():
    """
    Garante que nenhum módulo em backend/ ou scripts/ use os.getenv ou os.environ,
    assegurando que todas as configurações passem centralizadamente por backend.config.Settings.
    """
    root_dir = Path(__file__).resolve().parent.parent
    targets = [root_dir / "backend", root_dir / "scripts"]

    forbidden_usages = []

    for target in targets:
        for py_file in target.rglob("*.py"):
            # backend/config.py pode usar os.getenv para checar o ENV antes do carregamento do .env
            if py_file.name == "config.py":
                continue

            content = py_file.read_text(encoding="utf-8")
            for idx, line in enumerate(content.splitlines(), start=1):
                clean_line = line.strip()
                if clean_line.startswith("#"):
                    continue
                if "os.getenv(" in clean_line or "os.environ" in clean_line:
                    forbidden_usages.append(
                        f"{py_file.relative_to(root_dir)}:{idx} -> {clean_line}"
                    )

    assert not forbidden_usages, (
        "Foram encontradas chamadas diretas a os.getenv/os.environ proibidas:\n"
        + "\n".join(forbidden_usages)
    )


def test_env_example_and_render_yaml_coverage():
    """
    Valida que todos os campos de Settings estão documentados no .env.example
    e que o render.yaml declara as variáveis obrigatórias.
    """
    root_dir = Path(__file__).resolve().parent.parent

    # 1. Campos de Settings
    settings_fields = set(Settings.model_fields.keys())

    # Lê .env.example
    env_example = (root_dir / ".env.example").read_text(encoding="utf-8")
    example_vars = set()
    for line in env_example.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            var_name = line.split("=")[0].strip()
            example_vars.add(var_name)

    # Campos que devem estar no .env.example
    missing_in_example = settings_fields - example_vars
    assert not missing_in_example, f"Os seguintes campos de Settings não estão documentados no .env.example: {missing_in_example}"

    # 2. render.yaml declara variáveis obrigatórias
    render_yaml = (root_dir / "render.yaml").read_text(encoding="utf-8")
    mandatory_render_vars = [
        "APP_PASSWORD",
        "SESSION_SECRET",
        "ADMIN_TOKEN",
        "WEBHOOK_SECRET",
        "WHATSAPP_GROUP_JID",
    ]
    for var in mandatory_render_vars:
        assert (
            f"key: {var}" in render_yaml
        ), f"Variável obrigatória {var} não declarada no render.yaml"
        # Garante que segredos estejam com sync: false
        assert (
            f"key: {var}\n        sync: false" in render_yaml
        ), f"Segredo {var} no render.yaml deve ter 'sync: false'"
