"""
tests/test_author_and_channel.py

Testes para a separação de 'source' em 'author' e 'channel':
1. Migration reversível com dados legados mistos e backfill correto.
2. Webhook grava author e channel corretos (texto -> whatsapp_text, áudio -> whatsapp_audio).
3. POST/PUT no dashboard sem author -> author NULL e channel dashboard.
4. POST/PUT no dashboard com author -> grava author e channel dashboard com dual-write em source.
5. Filtros da API por author e channel funcionam perfeitamente.
"""

import os
import sqlite3
import tempfile
from unittest import mock

import pytest

# Configura ambiente de testes antes dos imports da aplicação
os.environ["APP_PASSWORD"] = "StrongMasterPassword123!"
os.environ["SESSION_SECRET"] = "super_secret_session_key_with_at_least_32_chars_12345"
os.environ["ADMIN_TOKEN"] = "adm_secret_token_secure_98765"
os.environ["DEV_INSECURE_COOKIES"] = "0"
os.environ["WHATSAPP_GROUP_JID"] = "120363000000000000@g.us"
os.environ["WEBHOOK_SECRET"] = "webhook_secret_key_with_at_least_32_characters_12345"
os.environ["WHATSAPP_USER_BRUNO"] = "5511999998888"
os.environ["WHATSAPP_USER_LETICIA"] = "5511977776666"

import contextlib

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from backend.auth import COOKIE_NAME, create_session_token
from backend.main import app


@pytest.fixture
def auth_client():
    client = TestClient(app, base_url="https://testserver")
    token = create_session_token()
    client.cookies.set(COOKIE_NAME, token)
    return client


def test_migration_split_source_backfill_and_downgrade():
    """Valida o backfill da migration 9240c01a1280 e reversibilidade."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        db_url = f"sqlite:///{db_path.replace(os.sep, '/')}"
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        os.environ["DATABASE_URL"] = db_url

        # Upgrade até c84794fd1d00 (antes da separação)
        command.upgrade(cfg, "c84794fd1d00")

        # Insere dados legados com valores mistos de source
        con = sqlite3.connect(db_path)
        con.execute(
            "INSERT INTO transactions (id, tipo, valor, categoria, data, source) VALUES "
            "(1, 'despesa_variavel', 50.0, 'Outros', '2026-10-24', 'Manual'), "
            "(2, 'despesa_variavel', 30.0, 'Outros', '2026-10-24', 'Bruno'), "
            "(3, 'despesa_variavel', 20.0, 'Outros', '2026-10-24', 'Letícia'), "
            "(4, 'despesa_variavel', 10.0, 'Outros', '2026-10-24', 'WhatsApp')"
        )
        con.commit()
        con.close()

        # Upgrade para 9240c01a1280 (aplica colunas e backfill)
        command.upgrade(cfg, "9240c01a1280")

        con = sqlite3.connect(db_path)
        rows = {
            r[0]: (r[1], r[2], r[3])
            for r in con.execute("SELECT id, author, channel, source FROM transactions").fetchall()
        }
        con.close()

        # 1: Manual -> author None, channel dashboard, source Mantido
        assert rows[1][0] is None
        assert rows[1][1] == "dashboard"
        assert rows[1][2] == "Manual"

        # 2: Bruno -> author Bruno, channel whatsapp_text
        assert rows[2][0] == "Bruno"
        assert rows[2][1] == "whatsapp_text"

        # 3: Letícia -> author Letícia, channel whatsapp_text
        assert rows[3][0] == "Letícia"
        assert rows[3][1] == "whatsapp_text"

        # 4: WhatsApp -> author None, channel whatsapp_text
        assert rows[4][0] is None
        assert rows[4][1] == "whatsapp_text"

        # Downgrade reverte e remove as colunas sem erro
        command.downgrade(cfg, "c84794fd1d00")
        con = sqlite3.connect(db_path)
        cols = [c[1] for c in con.execute("PRAGMA table_info(transactions)").fetchall()]
        con.close()
        assert "author" not in cols
        assert "channel" not in cols
        assert "source" in cols

    finally:
        if os.path.exists(db_path):
            with contextlib.suppress(OSError):
                os.remove(db_path)


def test_dashboard_create_transaction_without_author(auth_client):
    """POST /api/transactions sem author deve resultar em author=None e channel='dashboard'."""
    payload = {
        "tipo": "despesa_variavel",
        "valor": 75.50,
        "categoria": "Lazer",
        "data": "2026-10-24",
        "descricao": "Cinema Sem Autor",
    }
    res = auth_client.post("/api/transactions", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["author"] is None
    assert data["channel"] == "dashboard"
    assert data["source"] == "dashboard"  # dual-write fallback


def test_dashboard_create_transaction_with_author(auth_client):
    """POST /api/transactions com author='Bruno' deve salvar author e channel='dashboard'."""
    payload = {
        "tipo": "despesa_variavel",
        "valor": 120.00,
        "categoria": "Farmácia",
        "data": "2026-10-24",
        "descricao": "Medicamentos",
        "author": "Bruno",
    }
    res = auth_client.post("/api/transactions", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["author"] == "Bruno"
    assert data["channel"] == "dashboard"
    assert data["source"] == "Bruno"  # dual-write


def test_filter_transactions_by_author_and_channel(auth_client):
    """GET /api/transactions?author=... e ?channel=... filtram corretamente."""
    # Cria uma transação para Letícia no dashboard
    auth_client.post(
        "/api/transactions",
        json={
            "tipo": "despesa_variavel",
            "valor": 45.0,
            "categoria": "Padaria",
            "data": "2026-10-24",
            "descricao": "Café Letícia",
            "author": "Letícia",
        },
    )

    # Filtra por autor Letícia
    res_author = auth_client.get("/api/transactions?author=Letícia")
    assert res_author.status_code == 200
    items = res_author.json()
    assert len(items) >= 1
    assert all(i["author"] == "Letícia" for i in items)

    # Filtra por canal dashboard
    res_channel = auth_client.get("/api/transactions?channel=dashboard")
    assert res_channel.status_code == 200
    items_ch = res_channel.json()
    assert len(items_ch) >= 1
    assert all(i["channel"] == "dashboard" for i in items_ch)


def test_webhook_records_author_and_channel_for_text_and_audio(auth_client):
    """
    Webhook:
    - Mensagem de texto grava author='Bruno' e channel='whatsapp_text'.
    - Mensagem de áudio grava author='Letícia' e channel='whatsapp_audio'.
    """
    secret = os.environ["WEBHOOK_SECRET"]

    # 1. Teste Texto (Bruno)
    payload_text = {
        "event": "messages.upsert",
        "instance": "fintrack-casal",
        "data": {
            "key": {
                "remoteJid": "120363000000000000@g.us",
                "participant": "5511999998888@s.whatsapp.net",
                "id": "msg_txt_test_001",
            },
            "message": {"conversation": "Gasolina 80"},
        },
    }

    with mock.patch("backend.atlas.send_whatsapp_message", return_value=True):
        res_text = auth_client.post(
            "/webhook/whatsapp", json=payload_text, headers={"X-Webhook-Secret": secret}
        )
        assert res_text.status_code == 200

    # Checa transação criada na API
    res_check_text = auth_client.get("/api/transactions")
    tx_text = next(t for t in res_check_text.json() if t["channel"] == "whatsapp_text")
    assert tx_text["author"] == "Bruno"
    assert tx_text["channel"] == "whatsapp_text"
    assert tx_text["source"] == "Bruno"

    # 2. Teste Áudio Transcrito (Letícia)
    payload_audio = {
        "event": "messages.upsert",
        "instance": "fintrack-casal",
        "data": {
            "key": {
                "remoteJid": "120363000000000000@g.us",
                "participant": "5511977776666@s.whatsapp.net",
                "id": "msg_audio_test_002",
            },
            "message": {
                "audioMessage": {
                    "base64": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=",
                    "mimetype": "audio/ogg",
                }
            },
        },
    }

    with (
        mock.patch("backend.atlas.transcribe_audio_bytes", return_value="Almoço 35"),
        mock.patch("backend.atlas.send_whatsapp_message", return_value=True),
    ):
        res_audio = auth_client.post(
            "/webhook/whatsapp", json=payload_audio, headers={"X-Webhook-Secret": secret}
        )
        assert res_audio.status_code == 200

    res_check_audio = auth_client.get("/api/transactions")
    tx_audio = next(t for t in res_check_audio.json() if t["channel"] == "whatsapp_audio")
    assert tx_audio["author"] == "Letícia"
    assert tx_audio["channel"] == "whatsapp_audio"
    assert tx_audio["source"] == "Letícia"
