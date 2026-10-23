"""
Testes automatizados de Security Headers e políticas de segurança HTTP.
"""

import os
import pytest
from unittest import mock

# Configura envs de teste antes de importar o app para fail-closed
os.environ["APP_PASSWORD"] = "StrongMasterPassword123!"
os.environ["SESSION_SECRET"] = "super_secret_session_key_with_at_least_32_chars_12345"
os.environ["ADMIN_TOKEN"] = "adm_secret_token_secure_98765"
os.environ["DEV_INSECURE_COOKIES"] = "0"
os.environ["WHATSAPP_GROUP_JID"] = "120363000000000000@g.us"
os.environ["WEBHOOK_SECRET"] = "webhook_secret_key_with_at_least_32_characters_12345"

from fastapi.testclient import TestClient
from backend.main import app
from backend.auth import COOKIE_NAME, create_session_token

@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver")

def test_security_headers_present_on_response(client):
    """Verifica nosniff, DENY, Referrer-Policy, Permissions-Policy e CSP-Report-Only."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
    assert res.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "camera=()" in res.headers.get("permissions-policy", "")
    assert "Content-Security-Policy-Report-Only" in res.headers
    assert "default-src 'self'" in res.headers["Content-Security-Policy-Report-Only"]

def test_hsts_on_https_or_production(client):
    """HSTS deve ser enviado em conexões HTTPS."""
    res = client.get("/health", headers={"x-forwarded-proto": "https"})
    assert "strict-transport-security" in res.headers
    assert "max-age=31536000" in res.headers["strict-transport-security"]

def test_cache_control_no_store_on_sensitive_routes(client):
    """Rotas / e /api devem conter Cache-Control: no-store."""
    # Rota raiz (redireciona para /login sem sessão, mas já inclui headers)
    res_root = client.get("/", follow_redirects=False)
    assert "no-store" in res_root.headers.get("cache-control", "")

    # Rota de API
    token = create_session_token()
    client.cookies.set(COOKIE_NAME, token)
    res_api = client.get("/api/transactions")
    assert "no-store" in res_api.headers.get("cache-control", "")
def test_health_check_does_not_disclose_database_type(client):
    """/health deve retornar apenas status: online sem vazar database."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data == {"status": "online"}
    assert "database" not in data
