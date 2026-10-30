"""
tests/test_observability.py

Testes de observabilidade:
1. Todo log em produção é JSON válido e contém request_id e message_id contextuais.
2. Scrubber do Sentry remove cookies, body, e headers sensíveis (Authorization, X-Admin-Token, X-Webhook-Secret)
   e mascara telefones em mensagens de erro/exceções.
3. Sem SENTRY_DSN, nenhum código do Sentry é inicializado.
4. /ready retorna 200 quando banco e migrações estão OK; 503 com banco indisponível (simulado)
   e quando a revisão do Alembic difere do head.
5. Exceção forçada devolve JSON genérico com request_id, sem vazar stack trace.
"""

import json
import logging
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from backend.auth import COOKIE_NAME, create_session_token
from backend.main import app


@pytest.fixture
def auth_client():
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    token = create_session_token()
    client.cookies.set(COOKIE_NAME, token)
    return client


from backend.observability import (
    MESSAGE_ID_CTX,
    REQUEST_ID_CTX,
    StructuredJsonFormatter,
    init_sentry,
    sentry_before_send,
)


def test_production_log_is_valid_json_with_correlation():
    """Valida que em produção os logs são JSON estrito contendo timestamp, nível e request_id."""
    formatter = StructuredJsonFormatter()

    token1 = REQUEST_ID_CTX.set("test-req-12345")
    token2 = MESSAGE_ID_CTX.set("msg-***-6789")

    try:
        record = logging.LogRecord(
            name="fintrack.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=42,
            msg="transaction_created",
            args=(),
            exc_info=None,
        )
        record.count = 3  # extra param

        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "fintrack.test"
        assert data["message"] == "transaction_created"
        assert data["request_id"] == "test-req-12345"
        assert data["message_id"] == "msg-***-6789"
        assert data["count"] == 3
        assert "timestamp" in data
    finally:
        REQUEST_ID_CTX.reset(token1)
        MESSAGE_ID_CTX.reset(token2)


def test_sentry_scrubber_removes_sensitive_headers_cookies_body_and_masks_phones():
    """Valida scrubbing agressivo de PII para eventos do Sentry."""
    raw_event = {
        "message": "Erro processando dados de 5511999998888 no sistema",
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "Falha de validação para o usuário com telefone +55 (11) 98888-7777 e conta x",
                }
            ]
        },
        "request": {
            "url": "https://fintrack.example.com/webhook",
            "headers": {
                "Host": "fintrack.example.com",
                "Authorization": "Bearer sensitive-jwt-token-123456",
                "X-Admin-Token": "secret-admin-token-value-32chars",
                "X-Webhook-Secret": "secret-webhook-value-32characters",
                "Cookie": "session=sensitive-session-cookie",
                "Content-Type": "application/json",
            },
            "cookies": {"session": "secret-session-value"},
            "data": {"valor": 150.0, "descricao": "Segredo Financeiro"},
        },
    }

    token = REQUEST_ID_CTX.set("req-sentry-scrub-1")
    try:
        scrubbed = sentry_before_send(raw_event, {})
        assert scrubbed is not None

        req = scrubbed["request"]
        # Body e cookies de request devem sumir
        assert "data" not in req
        assert "cookies" not in req

        headers = req["headers"]
        assert headers["Authorization"] == "[REDACTED]"
        assert headers["X-Admin-Token"] == "[REDACTED]"
        assert headers["X-Webhook-Secret"] == "[REDACTED]"
        assert headers["Cookie"] == "[REDACTED]"
        assert headers["Content-Type"] == "application/json"

        # Telefones em mensagens e exceções devem ser mascarados
        assert "5511999998888" not in scrubbed["message"]
        assert "****" in scrubbed["message"]

        exc_val = scrubbed["exception"]["values"][0]["value"]
        assert "98888-7777" not in exc_val
        assert "****" in exc_val

        # Tags de correlação
        assert scrubbed["tags"]["request_id"] == "req-sentry-scrub-1"
    finally:
        REQUEST_ID_CTX.reset(token)


def test_sentry_not_initialized_without_dsn():
    """Sem SENTRY_DSN definido, init_sentry retorna False e não toca no sentry_sdk."""
    with mock.patch("backend.observability.get_settings") as mock_settings:
        from pydantic import SecretStr

        mock_settings.return_value.SENTRY_DSN = SecretStr("")
        assert init_sentry() is False


def test_sentry_initialized_when_dsn_provided():
    """Com SENTRY_DSN definido, sentry_sdk.init é invocado com configurações seguras."""
    with (
        mock.patch("backend.observability.get_settings") as mock_settings,
        mock.patch("sentry_sdk.init") as mock_sentry_init,
    ):
        from pydantic import SecretStr

        mock_settings.return_value.SENTRY_DSN = SecretStr("https://key@sentry.io/12345")
        mock_settings.return_value.ENV = "production"
        mock_settings.return_value.RENDER_GIT_COMMIT = "commit-abc-123"
        mock_settings.return_value.SENTRY_TRACES_SAMPLE_RATE = 0.1

        assert init_sentry() is True
        mock_sentry_init.assert_called_once()
        kwargs = mock_sentry_init.call_args[1]

        assert kwargs["dsn"] == "https://key@sentry.io/12345"
        assert kwargs["environment"] == "production"
        assert kwargs["release"] == "commit-abc-123"
        assert kwargs["send_default_pii"] is False
        assert kwargs["traces_sample_rate"] == 0.1
        assert kwargs["before_send"] == sentry_before_send


def test_ready_check_endpoint_success(auth_client: TestClient):
    """Valida que /ready retorna 200 com booleanos quando banco e migrações coincidem."""
    res = auth_client.get("/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["ready"] is True
    assert data["database"] is True
    assert data["migrations"] is True


def test_ready_check_endpoint_database_down_returns_503(auth_client: TestClient):
    """Valida que /ready retorna 503 com database=False se a conexão com banco falhar."""
    with mock.patch(
        "backend.db.session.engine.connect", side_effect=Exception("DB Connection Timeout")
    ):
        res = auth_client.get("/ready")
        assert res.status_code == 503
        data = res.json()
        assert data["ready"] is False
        assert data["database"] is False
        assert data["migrations"] is False


def test_ready_check_endpoint_migration_mismatch_returns_503(auth_client: TestClient):
    """Valida que /ready retorna 503 se a revisão do banco diferir do head do Alembic."""
    with mock.patch(
        "alembic.runtime.migration.MigrationContext.get_current_revision",
        return_value="outdated_migration_rev_123",
    ):
        res = auth_client.get("/ready")
        assert res.status_code == 503
        data = res.json()
        assert data["ready"] is False
        assert data["database"] is True
        assert data["migrations"] is False


def test_global_exception_handler_returns_generic_json_and_request_id(auth_client: TestClient):
    """Uma rota com erro 500 devolve mensagem genérica com request_id, sem vazar stack trace."""

    # Registra rota temporária de teste que lança erro
    @app.get("/api/test-failure-endpoint")
    def fail_endpoint():
        raise RuntimeError("Falha interna de banco com detalhes sensíveis de credenciais")

    res = auth_client.get(
        "/api/test-failure-endpoint",
        headers={"X-Request-ID": "test-req-custom-9999"},
    )
    assert res.status_code == 500
    assert res.headers.get("X-Request-ID") == "test-req-custom-9999"
    data = res.json()
    assert data["detail"] == "Internal Server Error"
    assert data["request_id"] == "test-req-custom-9999"
    # Garante que nenhum detalhe sensível da stack vazou
    assert "Falha interna" not in res.text
    assert "credenciais" not in res.text


def test_request_id_middleware_propagates_or_generates_header(auth_client: TestClient):
    """Garante que requisições normais recebem e propagam X-Request-ID."""
    res1 = auth_client.get("/health")
    assert res1.status_code == 200
    assert "X-Request-ID" in res1.headers
    generated_id = res1.headers["X-Request-ID"]
    assert len(generated_id) >= 16

    # Fornecendo um X-Request-ID customizado válido
    res2 = auth_client.get("/health", headers={"X-Request-ID": "my-custom-request-id-42"})
    assert res2.status_code == 200
    assert res2.headers.get("X-Request-ID") == "my-custom-request-id-42"
