"""
Módulo de Autenticação, Sessão e Proteção de Aplicação (AppSec).

Implementa autenticação robusta para uso pessoal de dois usuários:
- Configurações estritas via env com Falha Fechada (fail-closed).
- Sessão em cookie assinado com itsdangerous (HttpOnly, SameSite=Strict, Secure).
- Rate-limiting em memória por IP para prevenção de força bruta no login.
- Proteção anti-CSRF baseada no header Origin para métodos mutantes (POST/PUT/DELETE).
- Autenticação administrativa via token constante (X-Admin-Token com hmac.compare_digest).
- Dependências FastAPI para proteção de rotas HTML e API JSON.
"""

import hmac
import logging
import os
import time
from collections import defaultdict
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

logger = logging.getLogger("atlas.auth")


# ------------------------------------------------------------------------------
# 1. CARREGAMENTO E VALIDAÇÃO DE VARIÁVEIS DE AMBIENTE (FALHA FECHADA)
# ------------------------------------------------------------------------------
def get_security_config() -> tuple[str | None, str | None, str | None, int, bool]:
    """Lê as variáveis de ambiente ativas no momento."""
    app_pwd = os.getenv("APP_PASSWORD")
    sess_sec = os.getenv("SESSION_SECRET")
    adm_tok = os.getenv("ADMIN_TOKEN")
    try:
        ttl = int(os.getenv("SESSION_TTL_HOURS", "12"))
    except ValueError:
        ttl = 12
    dev_insecure = os.getenv("DEV_INSECURE_COOKIES", "0") in ("1", "true", "True")
    return app_pwd, sess_sec, adm_tok, ttl, dev_insecure


def validate_security_configuration() -> None:
    """
    Garante falha fechada se qualquer credencial de segurança essencial faltar.
    Impede que a aplicação inicie desprotegida ou em modo aberto acidentalmente.
    """
    app_pwd, sess_sec, adm_tok, _, _ = get_security_config()
    missing = []
    if not app_pwd or not app_pwd.strip():
        missing.append("APP_PASSWORD")
    if not sess_sec or not sess_sec.strip():
        missing.append("SESSION_SECRET")
    elif len(sess_sec.strip()) < 32:
        raise RuntimeError(
            "Configuração de segurança inválida: SESSION_SECRET deve conter no mínimo 32 caracteres."
        )
    if not adm_tok or not adm_tok.strip():
        missing.append("ADMIN_TOKEN")

    if missing:
        raise RuntimeError(
            f"Configuração de segurança incompleta (FALHA FECHADA): defina as variáveis obrigatórias: {', '.join(missing)}"
        )


# Executa validação de inicialização imediata
validate_security_configuration()

COOKIE_NAME = "atlas_session"


def get_serializer() -> URLSafeTimedSerializer:
    _, sess_sec, _, _, _ = get_security_config()
    return URLSafeTimedSerializer(str(sess_sec or ""), salt="atlas-financas-session-v1")


# ------------------------------------------------------------------------------
# 2. RATE LIMITER DE LOGIN EM MEMÓRIA
# ------------------------------------------------------------------------------
# Limite: máximo 5 tentativas por minuto por IP
# LIMITAÇÃO TÉCNICA DOCUMENTADA:
# Por ser mantido em memória no processo Python, este rate-limiter é local à instância.
# Se o servidor for executado com múltiplos workers (ex: Gunicorn/Uvicorn multi-worker)
# ou múltiplas réplicas, cada worker terá seu próprio contador. Para o cenário atual
# (1 worker em plano do Render para uso pessoal de 2 pessoas), a proteção em memória é
# extremamente leve, segura e suficiente. Para arquitetura multi-worker/cluster, a
# persistência distribuída recomendada seria Redis/Memcached.
login_attempts: dict[str, list[float]] = defaultdict(list)
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 60


def get_client_ip(request: Request) -> str:
    """Extrai o IP do cliente respeitando cabeçalhos de proxy do Render."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def check_login_rate_limit(client_ip: str) -> None:
    now = time.time()
    cutoff = now - LOGIN_WINDOW_SECONDS
    # Remove tentativas antigas fora da janela de 1 minuto
    login_attempts[client_ip] = [t for t in login_attempts[client_ip] if t > cutoff]
    if len(login_attempts[client_ip]) >= LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas de login. Aguarde um minuto antes de tentar novamente.",
        )


def record_login_attempt(client_ip: str) -> None:
    login_attempts[client_ip].append(time.time())


# ------------------------------------------------------------------------------
# 3. GERAÇÃO E VALIDAÇÃO DE SESSÃO
# ------------------------------------------------------------------------------
def create_session_token(user_identifier: str = "authenticated_user") -> str:
    s = get_serializer()
    return s.dumps({"user": user_identifier, "t": time.time()})


def verify_session_token(token: str) -> dict | None:
    s = get_serializer()
    _, _, _, ttl_hours, _ = get_security_config()
    max_age_seconds = ttl_hours * 3600
    try:
        data = s.loads(token, max_age=max_age_seconds)
        return data
    except (BadSignature, SignatureExpired, Exception):
        return None


def get_current_session(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return verify_session_token(token)


# ------------------------------------------------------------------------------
# 4. VALIDAÇÃO DE CSRF BASEADA NO HEADER ORIGIN
# ------------------------------------------------------------------------------
def verify_csrf_origin(request: Request) -> None:
    """
    Protege requisições mutantes (POST, PUT, DELETE) baseadas em cookie contra CSRF.
    Se o header 'Origin' estiver presente, deve corresponder à mesma origem do servidor.
    """
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("host")
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            expected_origin_forwarded = f"{proto}://{host}"
            expected_origin_direct = f"{request.url.scheme}://{host}"
            origin_clean = origin.rstrip("/")
            if origin_clean != expected_origin_forwarded.rstrip(
                "/"
            ) and origin_clean != expected_origin_direct.rstrip("/"):
                logger.warning(
                    f"CSRF bloqueado: Origin={origin} esperado={expected_origin_forwarded}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Acesso rejeitado por verificação de segurança de origem (CSRF).",
                )


# ------------------------------------------------------------------------------
# 5. DEPENDÊNCIAS DE AUTENTICAÇÃO FASTAPI
# ------------------------------------------------------------------------------
def require_auth_api(request: Request, _csrf: None = Depends(verify_csrf_origin)) -> dict[str, Any]:
    """
    Exigência de autenticação para todas as rotas da API (/api/*).
    Se não autenticado, retorna 401 Unauthorized com payload JSON.
    """
    session = get_current_session(request)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação necessária. Sessão inexistente ou expirada.",
        )
    return session


def require_auth_page(request: Request) -> dict[str, Any] | None:
    """
    Exigência de autenticação para páginas HTML (rota "/").
    Se não autenticado, retorna None indicando necessidade de redirecionamento.
    """
    return get_current_session(request)


def require_admin_token(request: Request) -> bool:
    """
    Exigência de autenticação para endpoints de disparos administrativos (/api/relatorio-*/disparar).
    Exige o header 'X-Admin-Token' validado com hmac.compare_digest.
    """
    _, _, adm_tok, _, _ = get_security_config()
    token = request.headers.get("x-admin-token")
    if not token or not adm_tok or not hmac.compare_digest(token, adm_tok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token administrativo inválido ou ausente.",
        )
    return True


# ------------------------------------------------------------------------------
# 6. PÁGINA DE LOGIN HTML SELF-CONTAINED (DARK GLASS THEME)
# ------------------------------------------------------------------------------
LOGIN_HTML_PAGE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Login &middot; Atlas Finanças</title>
  <style>
    :root {
      --bg-dark: #0B0F19;
      --bg-card: rgba(15, 23, 42, 0.75);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --accent-blue: #3B82F6;
      --accent-cyan: #06B6D4;
      --text-main: #F8FAFC;
      --text-muted: #94A3B8;
      --error-red: #EF4444;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    body {
      background-color: var(--bg-dark);
      background-image: 
        radial-gradient(at 0% 0%, rgba(37, 99, 235, 0.15) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(6, 182, 212, 0.15) 0px, transparent 50%);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }

    .login-card {
      background: var(--bg-card);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--border-subtle);
      border-radius: 20px;
      padding: 36px 32px;
      width: 100%;
      max-width: 400px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4), 0 0 40px rgba(6, 182, 212, 0.1);
      text-align: center;
      animation: fadeIn 0.4s ease-out;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .brand-avatar {
      width: 72px;
      height: 72px;
      border-radius: 20px;
      margin: 0 auto 16px;
      overflow: hidden;
      border: 2px solid rgba(6, 182, 212, 0.4);
      box-shadow: 0 0 25px rgba(6, 182, 212, 0.3);
      background: #0B0F19;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .brand-avatar img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    .title {
      font-size: 22px;
      font-weight: 700;
      color: #fff;
      letter-spacing: -0.4px;
      margin-bottom: 4px;
    }

    .subtitle {
      font-size: 13px;
      color: var(--text-muted);
      margin-bottom: 28px;
    }

    .form-group {
      text-align: left;
      margin-bottom: 20px;
    }

    .form-group label {
      display: block;
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin-bottom: 8px;
    }

    .input-wrapper {
      position: relative;
    }

    input[type="password"] {
      width: 100%;
      background: rgba(11, 15, 25, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 12px;
      padding: 13px 16px;
      color: #fff;
      font-size: 15px;
      outline: none;
      transition: all 0.2s ease;
    }

    input[type="password"]:focus {
      border-color: var(--accent-cyan);
      box-shadow: 0 0 0 3px rgba(6, 182, 212, 0.2);
      background: rgba(11, 15, 25, 0.95);
    }

    .btn-submit {
      width: 100%;
      background: linear-gradient(135deg, #0284C7, #06B6D4);
      border: none;
      border-radius: 12px;
      padding: 14px;
      color: #fff;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 4px 14px rgba(6, 182, 212, 0.3);
      transition: all 0.2s ease;
    }

    .btn-submit:hover {
      filter: brightness(1.1);
      transform: translateY(-1px);
    }

    .btn-submit:active {
      transform: translateY(1px);
    }

    .btn-submit:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .error-msg {
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.3);
      color: #FCA5A5;
      font-size: 13px;
      border-radius: 10px;
      padding: 10px 14px;
      margin-bottom: 18px;
      display: none;
      text-align: left;
    }

    .footer-note {
      margin-top: 24px;
      font-size: 11.5px;
      color: var(--text-muted);
      opacity: 0.7;
    }
  </style>
</head>
<body>
  <div class="login-card">
    <div class="brand-avatar">
      <img src="/atlas_logo.jpg" alt="Atlas AI" onerror="this.style.display='none';">
    </div>
    <h1 class="title">Atlas Finanças</h1>
    <p class="subtitle">Acesso restrito ao ecossistema doméstico</p>

    <div class="error-msg" id="error-box"></div>

    <form id="login-form">
      <div class="form-group">
        <label for="password">Senha de Acesso</label>
        <div class="input-wrapper">
          <input type="password" id="password" name="password" placeholder="Digite a chave mestre" required autofocus autocomplete="current-password">
        </div>
      </div>
      <button type="submit" class="btn-submit" id="btn-login">Entrar no Dashboard</button>
    </form>

    <div class="footer-note">
      Sessão protegida criptograficamente &middot; Atlas AI Agent
    </div>
  </div>

  <script>
    const form = document.getElementById('login-form');
    const btn = document.getElementById('btn-login');
    const errorBox = document.getElementById('error-box');

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      errorBox.style.display = 'none';
      btn.disabled = true;
      btn.innerText = 'Autenticando...';

      const password = document.getElementById('password').value;

      try {
        const res = await fetch('/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ password })
        });

        if (res.ok) {
          window.location.href = '/';
        } else {
          const data = await res.json().catch(() => ({}));
          errorBox.innerText = data.detail || 'Senha incorreta. Tente novamente.';
          errorBox.style.display = 'block';
          btn.disabled = false;
          btn.innerText = 'Entrar no Dashboard';
          document.getElementById('password').focus();
        }
      } catch (err) {
        errorBox.innerText = 'Falha ao conectar ao servidor.';
        errorBox.style.display = 'block';
        btn.disabled = false;
        btn.innerText = 'Entrar no Dashboard';
      }
    });
  </script>
</body>
</html>
"""


# ------------------------------------------------------------------------------
# 7. ROTAS DE AUTENTICAÇÃO (LOGIN / LOGOUT)
# ------------------------------------------------------------------------------
class LoginRequest(BaseModel):
    password: str


async def login_page(request: Request) -> Response:
    """Exibe formulário de login ou redireciona se já autenticado."""
    session = get_current_session(request)
    if session:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return HTMLResponse(content=LOGIN_HTML_PAGE)


async def login_endpoint(
    payload: LoginRequest, request: Request, _csrf: None = Depends(verify_csrf_origin)
) -> JSONResponse:
    """Valida a senha, aplica rate limit por IP e emite cookie assinado."""
    client_ip = get_client_ip(request)
    check_login_rate_limit(client_ip)

    app_pwd, _, _, ttl_hours, dev_insecure = get_security_config()
    max_age_seconds = ttl_hours * 3600

    # Comparação estrita de senha em tempo constante (contra timing attack)
    is_valid = bool(app_pwd) and hmac.compare_digest(payload.password, str(app_pwd))

    if not is_valid:
        record_login_attempt(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Senha de acesso incorreta."
        )

    # Cria sessão válida
    token = create_session_token()
    response = JSONResponse(
        content={"status": "authenticated", "message": "Login realizado com sucesso"}
    )

    # Cookie assinado com flags de segurança estritas
    # Secure só pode ser falso se DEV_INSECURE_COOKIES for explicitamente ligado
    use_secure = not dev_insecure

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age_seconds,
        httponly=True,
        secure=use_secure,
        samesite="strict",
        path="/",
    )
    return response


async def logout_endpoint(_csrf: None = Depends(verify_csrf_origin)) -> JSONResponse:
    """Invalida a sessão removendo o cookie."""
    response = JSONResponse(
        content={"status": "logged_out", "message": "Sessão encerrada com sucesso"}
    )
    response.delete_cookie(key=COOKIE_NAME, httponly=True, samesite="strict", path="/")
    return response
