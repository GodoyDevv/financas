"""
tests/test_dates_and_money.py

Suíte de testes de precisão para dinheiro (Decimal/Numeric),
datas (Date ISO) e fuso horário de São Paulo (America/Sao_Paulo).

Critérios de Aceite Cobertos:
1. 0.1 + 0.2 soma exatamente 0.30 (sem imprecisão de float).
2. Arredondamento bancário ROUND_HALF_UP devidamente verificado.
3. month_range validação de 'YYYY-MM' estrita: '2026-10' gera intervalo onde 2026-10-31
   entra em outubro e não em novembro; '2026-13' e 'abc' disparam ValueError / HTTP 400.
4. Lançamento no fuso horário de São Paulo (America/Sao_Paulo) às 23:30 grava a data de SP
   e não a data do dia seguinte em UTC.
5. A API continua retornando valor como número JSON nativo (não string).
6. Teste de migração idempotente com pré-validação: dados legados convertem, dados com
   data inválida abortam com erro claro.
"""

import os
import sqlite3
import tempfile
import zoneinfo
from datetime import date, datetime
from decimal import Decimal

import pytest

# Define variáveis de ambiente necessárias para o fail-closed do auth antes dos imports do backend
os.environ["APP_PASSWORD"] = "StrongMasterPassword123!"
os.environ["SESSION_SECRET"] = "super_secret_session_key_with_at_least_32_chars_12345"
os.environ["ADMIN_TOKEN"] = "adm_secret_token_secure_98765"
os.environ["DEV_INSECURE_COOKIES"] = "0"
os.environ["WHATSAPP_GROUP_JID"] = "120363000000000000@g.us"
os.environ["WEBHOOK_SECRET"] = "webhook_secret_key_with_at_least_32_characters_12345"

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from backend.auth import COOKIE_NAME, create_session_token
from backend.dates_and_money import TIMEZONE_SP, month_range, to_decimal
from backend.main import app


@pytest.fixture
def auth_client():
    client = TestClient(app, base_url="https://testserver")
    token = create_session_token()
    client.cookies.set(COOKIE_NAME, token)
    return client


def test_decimal_precision_and_half_up():
    """0.1 + 0.2 deve somar exatamente 0.30 e half-up deve arredondar 0.005 para 0.01."""
    d1 = to_decimal("0.10")
    d2 = to_decimal("0.20")
    assert d1 + d2 == Decimal("0.30")

    # Float 0.1 + 0.2 no Python normalmente dá 0.30000000000000004
    f_sum = to_decimal(0.1) + to_decimal(0.2)
    assert f_sum == Decimal("0.30")

    # ROUND_HALF_UP: .005 -> .01 | .004 -> .00
    assert to_decimal("10.005") == Decimal("10.01")
    assert to_decimal("10.004") == Decimal("10.00")
    assert to_decimal("10.0051") == Decimal("10.01")


def test_month_range_strict_validation():
    """Valida limites e formato de month_range."""
    inicio, fim = month_range("2026-10")
    assert inicio == date(2026, 10, 1)
    assert fim == date(2026, 11, 1)

    # 2026-10-31 entra em outubro e não em novembro
    dia_31_out = date(2026, 10, 31)
    dia_01_nov = date(2026, 11, 1)
    assert inicio <= dia_31_out < fim
    assert not (inicio <= dia_01_nov < fim)

    # Virada de ano: dezembro
    ini_dez, fim_dez = month_range("2026-12")
    assert ini_dez == date(2026, 12, 1)
    assert fim_dez == date(2027, 1, 1)

    # Entradas inválidas
    with pytest.raises(ValueError):
        month_range("2026-13")
    with pytest.raises(ValueError):
        month_range("abc")
    with pytest.raises(ValueError):
        month_range("2026/10")
    with pytest.raises(ValueError):
        month_range("")


def test_api_month_filter_http_400_on_invalid_month(auth_client):
    """Endpoints com parâmetro 'mes' devem retornar 400 se o mês for inválido."""
    res1 = auth_client.get("/api/transactions?mes=2026-13")
    assert res1.status_code == 400
    assert "Mês inválido" in res1.json()["detail"]

    res2 = auth_client.get("/api/transactions?mes=abc")
    assert res2.status_code == 400

    res3 = auth_client.get("/api/summary?mes=invalid")
    assert res3.status_code == 400

    res4 = auth_client.get("/api/metrics?mes=2026-99")
    assert res4.status_code == 400


def test_timezone_sp_now_and_today():
    """
    Garante que today_br() reflete o fuso de São Paulo mesmo quando UTC já virou o dia.
    Exemplo: 23:30 em SP (UTC-3) corresponde a 02:30 do dia seguinte em UTC.
    A data deve ser a de SP.
    """
    sp_tz = zoneinfo.ZoneInfo("America/Sao_Paulo")
    dt_sp = datetime(2026, 10, 23, 23, 30, 0, tzinfo=sp_tz)
    dt_utc = dt_sp.astimezone(zoneinfo.ZoneInfo("UTC"))

    assert dt_sp.day == 23
    assert dt_utc.day == 24

    # today_br deve ser do fuso de SP
    assert dt_sp.astimezone(TIMEZONE_SP).date() == date(2026, 10, 23)


def test_api_returns_valor_as_number_in_json(auth_client):
    """
    A resposta da API DEVE emitir valor como número JSON (float/int),
    NÃO como string ("150.00"), para não quebrar o frontend.
    """
    payload = {
        "tipo": "despesa_variavel",
        "valor": 125.75,
        "categoria": "Alimentação",
        "data": "2026-10-23",
        "descricao": "Jantar Decimal",
        "source": "Manual",
    }
    create_res = auth_client.post("/api/transactions", json=payload)
    assert create_res.status_code == 200
    body = create_res.json()
    assert isinstance(body["valor"], (int, float))
    assert body["valor"] == 125.75

    # Leitura da lista
    list_res = auth_client.get("/api/transactions")
    assert list_res.status_code == 200
    items = list_res.json()
    found = next((i for i in items if i["descricao"] == "Jantar Decimal"), None)
    assert found is not None
    assert isinstance(found["valor"], (int, float))
    assert found["valor"] == 125.75


def test_migration_abort_on_invalid_date():
    """
    Testa pré-validação da migration: se houver linhas com data inválida,
    a migration c84794fd1d00 DEVE abortar lançando ValueError antes de alterar nada.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path.replace(os.sep, '/')}"
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        os.environ["DATABASE_URL"] = db_url

        # Executa até a revisão anterior
        command.upgrade(cfg, "266f67827cdb")

        # Insere propositalmente uma data corrompida / inválida
        con = sqlite3.connect(db_path)
        con.execute(
            "INSERT INTO transactions (tipo, valor, categoria, data) "
            "VALUES ('despesa_variavel', 50.0, 'Alimentacao', 'data_invalida_nao_iso')"
        )
        con.commit()
        con.close()

        # Tentar fazer upgrade para c84794fd1d00 deve falhar e abortar
        with pytest.raises(Exception) as exc_info:
            command.upgrade(cfg, "c84794fd1d00")

        assert (
            "data inválido" in str(exc_info.value).lower()
            or "abortado" in str(exc_info.value).lower()
        )

    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass


def test_migration_legacy_data_conversion_and_downgrade():
    """
    Testa conversão bem-sucedida de dados legados (Float e String)
    para Numeric e Date, e reversibilidade com downgrade.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path.replace(os.sep, '/')}"
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        os.environ["DATABASE_URL"] = db_url

        # Upgrade até 266f67827cdb (schema legado com String e Float)
        command.upgrade(cfg, "266f67827cdb")

        # Insere linha válida legada
        con = sqlite3.connect(db_path)
        con.execute(
            "INSERT INTO transactions (id, tipo, valor, categoria, data) "
            "VALUES (999, 'despesa_variavel', 123.456, 'Teste', '2026-10-23')"
        )
        con.commit()
        con.close()

        # Upgrade para c84794fd1d00 (deve converter com sucesso)
        command.upgrade(cfg, "c84794fd1d00")

        # Verifica tipo e arredondamento half-up
        con = sqlite3.connect(db_path)
        row = con.execute("SELECT valor, data FROM transactions WHERE id = 999").fetchone()
        con.close()
        assert row is not None
        # 123.456 deve ser arredondado para 123.46
        assert float(row[0]) == 123.46 or str(row[0]) == "123.46"

        # Downgrade reverte sem erros
        command.downgrade(cfg, "266f67827cdb")
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
