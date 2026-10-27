"""
Testes de Segurança e Autenticação (AppSec Acceptance Criteria).

Critérios de Aceite Cobertos:
1. GET /api/transactions sem sessão -> 401; com sessão -> 200.
2. GET / sem sessão -> redireciona (302) para /login.
3. POST /api/relatorio-diario/disparar sem X-Admin-Token -> 401; com token correto -> 200.
4. Senha errada -> 401; após 5 tentativas -> 429 Too Many Requests.
5. Cookie com HttpOnly e SameSite=Strict (e Secure em produção/DEV_INSECURE_COOKIES=0).
6. POST com Origin externo -> 403 Forbidden (CSRF).
7. Falha fechada: app recusa iniciar se faltarem variáveis obrigatórias.
"""

import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

# Define variáveis de teste antes de importar a aplicação para satisfazer a validação estrita
TEST_APP_PASSWORD = "StrongMasterPassword123!"
TEST_SESSION_SECRET = "super_secret_session_key_with_at_least_32_chars_12345"
TEST_ADMIN_TOKEN = "adm_secret_token_secure_98765"

os.environ["APP_PASSWORD"] = TEST_APP_PASSWORD
os.environ["SESSION_SECRET"] = TEST_SESSION_SECRET
os.environ["ADMIN_TOKEN"] = TEST_ADMIN_TOKEN
os.environ["DEV_INSECURE_COOKIES"] = "0"
os.environ["SESSION_TTL_HOURS"] = "12"

from backend.auth import (
    COOKIE_NAME,
    create_session_token,
    login_attempts,
    validate_security_configuration,
)
from backend.main import app


@pytest.fixture(autouse=True)
def reset_rate_limit():
    """Limpa o dicionário em memória de rate-limit antes de cada teste."""
    login_attempts.clear()
    yield
    login_attempts.clear()


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver")


# ==============================================================================
# TESTE 1: FALHA FECHADA NA INICIALIZAÇÃO
# ==============================================================================
def test_fail_closed_missing_env_vars():
    """Garante que a aplicação se recusa a iniciar se qualquer variável obrigatória faltar."""
    # Sem APP_PASSWORD
    with mock.patch.dict(
        os.environ,
        {
            "APP_PASSWORD": "",
            "SESSION_SECRET": TEST_SESSION_SECRET,
            "ADMIN_TOKEN": TEST_ADMIN_TOKEN,
        },
    ):
        with pytest.raises(RuntimeError) as excinfo:
            validate_security_configuration()
        assert "APP_PASSWORD" in str(excinfo.value)

    # Sem SESSION_SECRET
    with mock.patch.dict(
        os.environ,
        {"APP_PASSWORD": TEST_APP_PASSWORD, "SESSION_SECRET": "", "ADMIN_TOKEN": TEST_ADMIN_TOKEN},
    ):
        with pytest.raises(RuntimeError) as excinfo:
            validate_security_configuration()
        assert "SESSION_SECRET" in str(excinfo.value)

    # SESSION_SECRET curto (< 32 caracteres)
    with mock.patch.dict(
        os.environ,
        {
            "APP_PASSWORD": TEST_APP_PASSWORD,
            "SESSION_SECRET": "curto",
            "ADMIN_TOKEN": TEST_ADMIN_TOKEN,
        },
    ):
        with pytest.raises(RuntimeError) as excinfo:
            validate_security_configuration()
        assert "mínimo 32 caracteres" in str(excinfo.value)

    # Sem ADMIN_TOKEN
    with mock.patch.dict(
        os.environ,
        {
            "APP_PASSWORD": TEST_APP_PASSWORD,
            "SESSION_SECRET": TEST_SESSION_SECRET,
            "ADMIN_TOKEN": "",
        },
    ):
        with pytest.raises(RuntimeError) as excinfo:
            validate_security_configuration()
        assert "ADMIN_TOKEN" in str(excinfo.value)


# ==============================================================================
# TESTE 2: PROTEÇÃO DA ROTA RAIZ (HTML)
# ==============================================================================
def test_get_root_without_session_redirects_to_login(client):
    """GET / sem sessão deve redirecionar (302) para /login."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_get_root_with_valid_session_returns_200(client):
    """GET / com cookie de sessão válido deve retornar 200 (HTML do dashboard)."""
    valid_token = create_session_token()
    client.cookies.set(COOKIE_NAME, valid_token)
    response = client.get("/")
    assert response.status_code == 200
    assert "Atlas Finanças" in response.text


# ==============================================================================
# TESTE 3: PROTEÇÃO DO ROUTER /api (JSON 401)
# ==============================================================================
def test_get_api_without_session_returns_401(client):
    """GET /api/transactions sem sessão deve retornar 401 JSON."""
    response = client.get("/api/transactions")
    assert response.status_code == 401
    assert "Autenticação necessária" in response.json()["detail"]


def test_get_api_with_valid_session_returns_200(client):
    """GET /api/transactions com sessão válida deve retornar 200."""
    valid_token = create_session_token()
    client.cookies.set(COOKIE_NAME, valid_token)
    response = client.get("/api/transactions")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ==============================================================================
# TESTE 4: ROTAS PÚBLICAS DESPROTEGIDAS DE ESCOPO
# ==============================================================================
def test_public_routes_accessible_without_auth(client):
    """/health, /atlas_logo.jpg e /login devem estar acessíveis sem autenticação."""
    assert client.get("/health").status_code == 200
    assert client.get("/login").status_code == 200
    # atlas_logo.jpg existe no projeto
    assert client.get("/atlas_logo.jpg").status_code == 200


# ==============================================================================
# TESTE 5: LOGIN, COOKIE SECURITY FLAGS E LOGOUT
# ==============================================================================
def test_login_success_and_cookie_attributes(client):
    """Login com senha correta emite cookie com HttpOnly, SameSite=Strict e Secure."""
    response = client.post(
        "/auth/login",
        json={"password": TEST_APP_PASSWORD},
        headers={"Origin": "https://testserver"},
    )
    assert response.status_code == 200
    assert COOKIE_NAME in response.cookies

    # Inspeciona cabeçalho Set-Cookie
    set_cookie_header = response.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie_header
    assert "SameSite=strict" in set_cookie_header or "SameSite=Strict" in set_cookie_header
    assert "Secure" in set_cookie_header


def test_logout_clears_cookie(client):
    """Logout remove o cookie de sessão com flags de segurança."""
    valid_token = create_session_token()
    client.cookies.set(COOKIE_NAME, valid_token)
    response = client.post("/auth/logout", headers={"Origin": "https://testserver"})
    assert response.status_code == 200
    set_cookie_header = response.headers.get("set-cookie", "")
    assert f'{COOKIE_NAME}=""' in set_cookie_header or f"{COOKIE_NAME}=;" in set_cookie_header


# ==============================================================================
# TESTE 6: RATE LIMIT NO LOGIN (MAX 5 TENTATIVAS -> 429)
# ==============================================================================
def test_login_rate_limiting(client):
    """Senha errada retorna 401; a partir da 6ª tentativa deve retornar 429."""
    for _i in range(5):
        res = client.post(
            "/auth/login",
            json={"password": "wrong_password"},
            headers={"Origin": "https://testserver"},
        )
        assert res.status_code == 401
        assert "Senha de acesso incorreta" in res.json()["detail"]

    # 6ª tentativa dentro de 1 minuto: Rate limit disparado
    res_blocked = client.post(
        "/auth/login", json={"password": "wrong_password"}, headers={"Origin": "https://testserver"}
    )
    assert res_blocked.status_code == 429
    assert "Muitas tentativas de login" in res_blocked.json()["detail"]


# ==============================================================================
# TESTE 7: CSRF PROTECTION (HEADER ORIGIN)
# ==============================================================================
def test_csrf_origin_validation(client):
    """POST com Origin divergente deve ser sumariamente bloqueado com 403 Forbidden."""
    # Origin externo malicioso
    response = client.post(
        "/auth/login",
        json={"password": TEST_APP_PASSWORD},
        headers={"Origin": "https://attacker-site.com"},
    )
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


# ==============================================================================
# TESTE 8: ENDPOINTS ADMINISTRATIVOS (X-ADMIN-TOKEN)
# ==============================================================================
def test_admin_endpoints_require_admin_token(client):
    """Endpoints de relatórios exigem X-Admin-Token e recusam acesso sem ele (401)."""
    # Sem token -> 401
    res_no_token = client.post("/api/relatorio-diario/disparar")
    assert res_no_token.status_code == 401

    # Com token inválido -> 401
    res_bad_token = client.post(
        "/api/relatorio-diario/disparar", headers={"X-Admin-Token": "token_falso_invalido"}
    )
    assert res_bad_token.status_code == 401

    # Com token válido -> 200 (Mockando a execução para não disparar rede real)
    with mock.patch("backend.main.executar_envio_relatorio_diario", return_value=True):
        res_ok = client.post(
            "/api/relatorio-diario/disparar", headers={"X-Admin-Token": TEST_ADMIN_TOKEN}
        )
        assert res_ok.status_code == 200
        assert res_ok.json() == {"status": "success", "enviado": True}
