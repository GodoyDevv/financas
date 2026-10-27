"""
Testes de Segurança e Resiliência do Webhook do WhatsApp (AppSec Webhook Hardening).

Critérios de Aceite Cobertos:
1. Sem header -> 401; header errado -> 401 (genérico, fail-closed).
2. Header certo + JID errado -> ignorado (status: ignored).
3. JID certo + pushName "Bruno" mas telefone fora da allowlist -> rejeitado/ignorado.
4. Remetente "9" (curto) -> rejeitado (elimina risco de match por endswith).
5. Remetente autorizado + segredo certo -> transação criada no banco.
6. Áudio acima do limite (2 MB) -> rejeitado sem chamar o Gemini.
7. Sem WEBHOOK_SECRET ou sem GROUP_JID -> comportamento fail-closed (401/503).
"""

import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

TEST_APP_PASSWORD = "StrongMasterPassword123!"
TEST_SESSION_SECRET = "super_secret_session_key_with_at_least_32_chars_12345"
TEST_ADMIN_TOKEN = "adm_secret_token_secure_98765"
TEST_WEBHOOK_SECRET = "webhook_secret_key_with_at_least_32_characters_12345"
TEST_GROUP_JID = "120363000000000000@g.us"
TEST_PHONE_BRUNO = "5511999998888"
TEST_PHONE_LETICIA = "5511977776666"

os.environ["APP_PASSWORD"] = TEST_APP_PASSWORD
os.environ["SESSION_SECRET"] = TEST_SESSION_SECRET
os.environ["ADMIN_TOKEN"] = TEST_ADMIN_TOKEN
os.environ["DEV_INSECURE_COOKIES"] = "0"
os.environ["WEBHOOK_SECRET"] = TEST_WEBHOOK_SECRET
os.environ["WHATSAPP_GROUP_JID"] = TEST_GROUP_JID
os.environ["WHATSAPP_USER_BRUNO"] = TEST_PHONE_BRUNO
os.environ["WHATSAPP_USER_LETICIA"] = TEST_PHONE_LETICIA
os.environ["WEBHOOK_SECRET_HEADER"] = "X-Webhook-Secret"
os.environ["WEBHOOK_ALLOW_PATH_TOKEN"] = "1"

from backend.main import app
from backend.webhook import PROCESSED_MESSAGE_IDS


@pytest.fixture(autouse=True)
def clean_processed_cache():
    PROCESSED_MESSAGE_IDS.clear()
    yield
    PROCESSED_MESSAGE_IDS.clear()


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver")


def make_payload(
    remote_jid=TEST_GROUP_JID,
    sender="5511999998888@s.whatsapp.net",
    text="Pão 10",
    push_name=None,
    msg_id="msg_001",
):
    return {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": remote_jid, "participant": sender, "id": msg_id, "fromMe": False},
            "pushName": push_name or "Desconhecido",
            "message": {"conversation": text},
        },
    }


# ==============================================================================
# 1. AUTENTICAÇÃO DO WEBHOOK (HEADER AUSENTE OU ERRADO)
# ==============================================================================
def test_webhook_missing_header_returns_401(client):
    """Sem o header de segredo -> deve retornar 401 genérico."""
    payload = make_payload()
    res = client.post("/webhook/whatsapp", json=payload)
    assert res.status_code == 401
    assert res.json() == {"detail": "Unauthorized"}


def test_webhook_wrong_header_returns_401(client):
    """Com header de segredo incorreto -> deve retornar 401 genérico."""
    payload = make_payload()
    res = client.post(
        "/webhook/whatsapp",
        json=payload,
        headers={"X-Webhook-Secret": "segredo_completamente_incorreto_12345"},
    )
    assert res.status_code == 401
    assert res.json() == {"detail": "Unauthorized"}


def test_webhook_path_token_support(client):
    """Com WEBHOOK_ALLOW_PATH_TOKEN=1, aceita token correto via path /webhook/whatsapp/{token}."""
    payload = make_payload(text="Café 5", msg_id="msg_token_path")
    with (
        mock.patch(
            "backend.webhook.parse_text_message",
            return_value={
                "tipo": "despesa_variavel",
                "valor": 5.0,
                "categoria": "Alimentação",
                "descricao": "Café",
                "data": "2026-10-23",
                "parcelas": 1,
            },
        ),
        mock.patch("backend.atlas.send_whatsapp_message", return_value=True),
    ):
        res = client.post(f"/webhook/whatsapp/{TEST_WEBHOOK_SECRET}", json=payload)
        assert res.status_code == 200
        assert res.json()["status"] == "success"


# ==============================================================================
# 2. HEADER CERTO + JID ERRADO -> IGNORADO
# ==============================================================================
def test_webhook_wrong_group_jid_ignored(client):
    """Header correto mas remoteJid de outro grupo ou conversa -> ignorado."""
    payload = make_payload(remote_jid="123456789_outro_grupo@g.us", text="Pão 10")
    res = client.post(
        "/webhook/whatsapp", json=payload, headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"


# ==============================================================================
# 3. PUSHNAME "Bruno" MAS TELEFONE FORA DA ALLOWLIST -> REJEITADO
# ==============================================================================
def test_webhook_spoofed_pushname_rejected(client):
    """Atacante define pushName como 'Bruno' mas número de telefone não está autorizado."""
    payload = make_payload(
        sender="5511888880000@s.whatsapp.net", push_name="Bruno Godoy", text="Gasolina 100"
    )
    res = client.post(
        "/webhook/whatsapp", json=payload, headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"


# ==============================================================================
# 4. REMETENTE "9" (CURTO) -> REJEITADO (SEM MATCH ENDSWITH)
# ==============================================================================
def test_webhook_short_phone_rejected(client):
    """Remetente com dígitos curtos (ex: '9') não pode casar com 5511999998888."""
    payload = make_payload(sender="9@s.whatsapp.net", push_name="Invasor", text="Sushi 200")
    res = client.post(
        "/webhook/whatsapp", json=payload, headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"


# ==============================================================================
# 5. REMETENTE AUTORIZADO + SEGREDO CERTO -> TRANSAÇÃO CRIADA
# ==============================================================================
def test_webhook_authorized_sender_creates_transaction(client):
    """Remetente legítimo (Bruno ou Letícia) com segredo válido cria transação com sucesso."""
    payload = make_payload(
        sender=f"{TEST_PHONE_BRUNO}@s.whatsapp.net", text="Mercado 150", msg_id="msg_valid_001"
    )
    with (
        mock.patch(
            "backend.webhook.parse_text_message",
            return_value={
                "tipo": "despesa_variavel",
                "valor": 150.0,
                "categoria": "Mercado",
                "descricao": "Mercado",
                "data": "2026-10-23",
                "parcelas": 1,
            },
        ),
        mock.patch("backend.atlas.send_whatsapp_message", return_value=True),
    ):
        res = client.post(
            "/webhook/whatsapp", json=payload, headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["user"] == "Bruno"
        assert data["parcelas"] == 1
        # Verifica que o telefone nos logs/resposta é mascarado
        assert "****" in data["sender"]

    # Mensagem duplicada subsequente com mesmo msg_id deve ser ignorada após ter sido autorizada
    dup_res = client.post(
        "/webhook/whatsapp", json=payload, headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET}
    )
    assert dup_res.status_code == 200
    assert dup_res.json()["status"] == "ignored"


# ==============================================================================
# 6. ÁUDIO ACIMA DO LIMITE (2 MB) -> REJEITADO SEM CHAMAR O GEMINI
# ==============================================================================
def test_webhook_oversized_audio_rejected_without_gemini(client):
    """Áudio com mais de 2MB via Evolution API decrypt é rejeitado sem invocar transcribe_audio_bytes."""
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "remoteJid": TEST_GROUP_JID,
                "participant": f"{TEST_PHONE_LETICIA}@s.whatsapp.net",
                "id": "msg_audio_oversized",
                "fromMe": False,
            },
            "message": {
                "audioMessage": {
                    "mimetype": "audio/ogg",
                    "url": "https://mmg.whatsapp.net/v/t62.7114-24/audio.enc",
                }
            },
        },
    }

    big_audio_bytes = b"0" * (2 * 1024 * 1024 + 100)

    with (
        mock.patch(
            "backend.atlas.fetch_decrypted_audio_from_evolution",
            return_value=(big_audio_bytes, "audio/ogg"),
        ),
        mock.patch("backend.atlas.transcribe_audio_bytes") as mock_transcribe,
    ):
        res = client.post(
            "/webhook/whatsapp", json=payload, headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET}
        )
        assert res.status_code == 200
        # O mock da transcrição NUNCA deve ser chamado
        mock_transcribe.assert_not_called()
        assert res.json()["status"] == "ignored"


# ==============================================================================
# 7. COMPORTAMENTO FAIL-CLOSED: SEM WEBHOOK_SECRET OU SEM GROUP_JID
# ==============================================================================
def test_fail_closed_without_webhook_secret(client):
    """Se WEBHOOK_SECRET estiver vazio ou ausente, deve responder 401."""
    with mock.patch.dict(os.environ, {"WEBHOOK_SECRET": ""}):
        payload = make_payload()
        res = client.post(
            "/webhook/whatsapp", json=payload, headers={"X-Webhook-Secret": "qualquer_coisa"}
        )
        assert res.status_code == 401
        assert res.json() == {"detail": "Unauthorized"}


def test_fail_closed_without_group_jid(client):
    """Se WHATSAPP_GROUP_JID não estiver configurado, responde 503 Service Unavailable."""
    with mock.patch.dict(os.environ, {"WHATSAPP_GROUP_JID": ""}):
        payload = make_payload(remote_jid="120363000000000000@g.us")
        res = client.post(
            "/webhook/whatsapp", json=payload, headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET}
        )
        assert res.status_code == 503
        assert "Group JID not configured" in res.json()["detail"]
