import os
import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from backend.database import engine, Base
from backend.routes import router as api_router
from backend.webhook import webhook_router
from backend.auth import (
    require_auth_api,
    require_auth_page,
    require_admin_token,
    verify_csrf_origin,
    login_page,
    login_endpoint,
    logout_endpoint,
    LoginRequest
)
from backend.scheduler import (
    loop_agendador_relatorio_noturno,
    executar_envio_relatorio_diario,
    executar_envio_relatorio_semanal
)

# Diretório raiz do projeto
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Criação das tabelas no SQLite se não existirem (sem nenhum seed de dados)
Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verificação de segurança fail-closed no startup para o Webhook
    group_jid = os.getenv("WHATSAPP_GROUP_JID", "").strip()
    if not group_jid:
        logging.getLogger("fintrack.startup").error("ERRO CRÍTICO DE SEGURANÇA: WHATSAPP_GROUP_JID não está definido no ambiente!")

    # Inicia o agendador assíncrono para o relatório noturno
    task = asyncio.create_task(loop_agendador_relatorio_noturno())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

is_production = os.getenv("ENV", "development").lower() == "production"

app = FastAPI(
    title="Atlas Finanças Intelligence API",
    description="Backend de alta precisão para controle financeiro e automação WhatsApp",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json"
)

# Configuração restritiva de CORS: front-end é same-origin por padrão (sem CORS).
# Origens externas só são permitidas se explicitamente declaradas via ALLOWED_ORIGINS.
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
allowed_origins_list = [orig.strip() for orig in allowed_origins_env.split(",") if orig.strip()]

# ------------------------------------------------------------------------------
# MIDDLEWARE DE CABEÇALHOS DE SEGURANÇA (AppSec Hardening)
# ------------------------------------------------------------------------------
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)

    # Prevenção de MIME-sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"

    # Prevenção de Clickjacking
    response.headers["X-Frame-Options"] = "DENY"

    # Política de Referrer estrita
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # Permissions-Policy restritiva (desativa recursos desnecessários do navegador)
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"

    # HSTS ativado estritamente em HTTPS ou produção
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    is_prod = os.getenv("ENV", "development").lower() == "production"
    if is_https or is_prod:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Prevenção de cache em dados sensíveis do dashboard e API
    path = request.url.path
    if path == "/" or path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"

    # Content-Security-Policy em modo Report-Only
    # TODO: Migrar 'unsafe-inline' de script-src e style-src para nonce/hash na próxima fase
    csp_report_only = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    response.headers["Content-Security-Policy-Report-Only"] = csp_report_only

    return response

if allowed_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Admin-Token", "X-Webhook-Secret"],
    )

# ------------------------------------------------------------------------------
# ROTAS PÚBLICAS DE AUTENTICAÇÃO
# ------------------------------------------------------------------------------
@app.get("/login", tags=["Auth"])
async def route_login_page(request: Request):
    return await login_page(request)

@app.post("/auth/login", dependencies=[Depends(verify_csrf_origin)], tags=["Auth"])
async def route_login_post(payload: LoginRequest, request: Request):
    return await login_endpoint(payload, request)

@app.post("/auth/logout", dependencies=[Depends(verify_csrf_origin)], tags=["Auth"])
async def route_logout_post():
    return await logout_endpoint()

# ------------------------------------------------------------------------------
# ENDPOINTS ADMINISTRATIVOS (PROTEGIDOS POR X-ADMIN-TOKEN)
# ------------------------------------------------------------------------------
@app.post("/api/relatorio-diario/disparar", dependencies=[Depends(require_admin_token)], tags=["Admin"])
def disparar_relatorio_diario_manual():
    """Endpoint administrativo para disparar ou testar o relatório diário sob demanda."""
    sucesso = executar_envio_relatorio_diario(force=True)
    return {"status": "success" if sucesso else "error", "enviado": sucesso}

@app.post("/api/relatorio-semanal/disparar", dependencies=[Depends(require_admin_token)], tags=["Admin"])
def disparar_relatorio_semanal_manual():
    """Endpoint administrativo para disparar ou testar o relatório semanal sob demanda."""
    sucesso = executar_envio_relatorio_semanal(force=True)
    return {"status": "success" if sucesso else "error", "enviado": sucesso}

# ------------------------------------------------------------------------------
# INCLUSÃO DE ROTEADORES
# ------------------------------------------------------------------------------
# Protege todo o router /api com a dependência require_auth_api
app.include_router(api_router, dependencies=[Depends(require_auth_api)])

# Webhook possui segurança e autenticação próprias (não protegido por sessão)
app.include_router(webhook_router)

# ------------------------------------------------------------------------------
# ROTAS PÚBLICAS DO SISTEMA
# ------------------------------------------------------------------------------
@app.get("/health", tags=["System"])
def health_check():
    """Healthcheck simples e seguro sem divulgar detalhes de infraestrutura interna."""
    return {"status": "online"}

@app.get("/atlas_logo.jpg", tags=["System"])
def serve_atlas_logo():
    logo_path = PROJECT_ROOT / "atlas_logo.jpg"
    if logo_path.exists():
        return FileResponse(str(logo_path), media_type="image/jpeg")
    return {"error": "Logo not found"}

# ------------------------------------------------------------------------------
# ROTA RAIZ DO DASHBOARD (PROTEGIDA COM REDIRECIONAMENTO PARA /login)
# ------------------------------------------------------------------------------
@app.get("/", tags=["Dashboard"])
def serve_frontend(request: Request):
    session = require_auth_page(request)
    if not session:
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse(str(PROJECT_ROOT / "index.html"), media_type="text/html")
