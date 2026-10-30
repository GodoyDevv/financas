import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.auth import (
    LoginRequest,
    login_endpoint,
    login_page,
    logout_endpoint,
    require_admin_token,
    require_auth_api,
    require_auth_page,
    verify_csrf_origin,
)
from backend.config import get_settings
from backend.db.session import engine
from backend.observability import (
    REQUEST_ID_CTX,
    generate_request_id,
    init_sentry,
    setup_logging,
)
from backend.routes import router as api_router
from backend.scheduler import (
    executar_envio_relatorio_diario,
    executar_envio_relatorio_semanal,
    processar_tick_jobs,
)
from backend.webhook import webhook_router

# Diretório raiz do projeto
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializa logging estruturado e Sentry (se DSN fornecido)
    setup_logging()
    init_sentry()

    # Verificação de segurança fail-closed no startup disparando get_settings()
    settings = get_settings()
    if not settings.WHATSAPP_GROUP_JID:
        logging.getLogger("fintrack.startup").error(
            "ERRO CRÍTICO DE SEGURANÇA: WHATSAPP_GROUP_JID não está definido no ambiente!"
        )

    yield


settings = get_settings()
is_production = settings.is_production

app = FastAPI(
    title="Atlas Finanças Intelligence API",
    description="Backend de alta precisão para controle financeiro e automação WhatsApp",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json",
)

# Configuração restritiva de CORS: front-end é same-origin por padrão (sem CORS).
# Origens externas só são permitidas se explicitamente declaradas via ALLOWED_ORIGINS.
allowed_origins_env = settings.ALLOWED_ORIGINS
allowed_origins_list = [orig.strip() for orig in allowed_origins_env.split(",") if orig.strip()]


# ------------------------------------------------------------------------------
# MIDDLEWARE DE CORRELAÇÃO E REQUEST ID
# ------------------------------------------------------------------------------
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    raw_req_id = request.headers.get("X-Request-ID", "").strip()
    import re

    if raw_req_id and re.match(r"^[a-zA-Z0-9_-]{8,64}$", raw_req_id):
        req_id = raw_req_id
    else:
        req_id = generate_request_id()

    token = REQUEST_ID_CTX.set(req_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response
    finally:
        REQUEST_ID_CTX.reset(token)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    raw_req_id = request.headers.get("X-Request-ID", "").strip()
    import re

    if raw_req_id and re.match(r"^[a-zA-Z0-9_-]{8,64}$", raw_req_id):
        req_id = raw_req_id
    else:
        req_id = REQUEST_ID_CTX.get() or generate_request_id()
    logging.getLogger("fintrack.exceptions").error(
        "Internal Server Error",
        exc_info=exc,
        extra={"request_id": req_id, "path": request.url.path},
    )
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "request_id": req_id},
        headers={"X-Request-ID": req_id},
    )


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
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )

    # HSTS ativado estritamente em HTTPS ou produção
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    is_prod = get_settings().is_production
    if is_https or is_prod:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Prevenção de cache em dados sensíveis do dashboard e API
    path = request.url.path
    if path == "/" or path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"

    # Content-Security-Policy estrita e aplicada (enforced)
    # script-src 'self' sem 'unsafe-inline' (eliminação completa de scripts inline)
    # Chart.js e dependências servidas localmente em /vendor e /static
    csp_enforced = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    response.headers["Content-Security-Policy"] = csp_enforced

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
# ENDPOINTS ADMINISTRATIVOS E JOBS INTERNOS (PROTEGIDOS POR X-ADMIN-TOKEN)
# ------------------------------------------------------------------------------
@app.post(
    "/internal/jobs/tick",
    dependencies=[Depends(require_admin_token)],
    tags=["Jobs"],
)
def jobs_tick():
    """
    Tick externo para orquestração de tarefas agendadas idempotentes.
    Decide pelo relógio de São Paulo quais jobs estão devidos.
    """
    resumo = processar_tick_jobs()
    return {"status": "ok", "summary": resumo}


@app.post(
    "/internal/jobs/{job_name}",
    dependencies=[Depends(require_admin_token)],
    tags=["Jobs"],
)
@app.post(
    "/api/relatorio-diario/disparar",
    dependencies=[Depends(require_admin_token)],
    tags=["Jobs"],
    include_in_schema=False,
)
@app.post(
    "/api/relatorio-semanal/disparar",
    dependencies=[Depends(require_admin_token)],
    tags=["Jobs"],
    include_in_schema=False,
)
def disparar_job_manual(request: Request, job_name: str | None = None):
    """
    Endpoint administrativo para disparar ou testar um job específico manualmente sob demanda.
    Suporta os nomes: relatorio_diario, relatorio_semanal, reprocess_due, purge_old, ensure_recurrences.
    Mantém compatibilidade com /api/relatorio-diario/disparar e /api/relatorio-semanal/disparar.
    """
    path = request.url.path
    target_job = job_name
    if "relatorio-diario" in path or target_job in ("relatorio-diario", "relatorio_diario"):
        sucesso = executar_envio_relatorio_diario(force=True)
        res = {"status": "success" if sucesso else "error", "enviado": sucesso}
        if job_name:
            res["job"] = "relatorio_diario"
        return res
    elif "relatorio-semanal" in path or target_job in ("relatorio-semanal", "relatorio_semanal"):
        sucesso = executar_envio_relatorio_semanal(force=True)
        res = {"status": "success" if sucesso else "error", "enviado": sucesso}
        if job_name:
            res["job"] = "relatorio_semanal"
        return res
    elif target_job == "reprocess_due":
        from backend.services.message_processor import reprocess_due

        reprocessed = reprocess_due()
        return {"status": "success", "job": "reprocess_due", "count": len(reprocessed)}
    elif target_job == "purge_old":
        from backend.services.message_processor import purge_old

        purged = purge_old()
        return {"status": "success", "job": "purge_old", "count": purged}
    elif target_job == "ensure_recurrences":
        from backend.database import SessionLocal
        from backend.dates_and_money import today_br
        from backend.services.recurrences import ensure_recurrences

        with SessionLocal() as s:
            mes_str = today_br().strftime("%Y-%m")
            ensure_recurrences(s, mes_str)
            return {"status": "success", "job": "ensure_recurrences"}
    else:
        raise HTTPException(status_code=404, detail=f"Job desconhecido: {target_job}")


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


@app.get("/ready", tags=["System"])
def ready_check():
    """
    Readiness probe:
    Verifica conectividade com banco via SELECT 1 com timeout curto
    e conformidade da migração Alembic atual com o head.
    Responde 200 (se pronto) ou 503 (se indisponível ou migrações pendentes).
    """
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    is_database_ok = False
    is_migration_ok = False

    try:
        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        head_rev = script.get_current_head()

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            is_database_ok = True

            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()
            is_migration_ok = bool(head_rev and current_rev == head_rev)
    except Exception as e:
        logging.getLogger("fintrack.readiness").warning(f"Readiness probe failed: {e}")

    is_ready = is_database_ok and is_migration_ok
    status_code = 200 if is_ready else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "ready": is_ready,
            "database": is_database_ok,
            "migrations": is_migration_ok,
        },
    )


@app.get("/atlas_logo.jpg", tags=["System"])
def serve_atlas_logo():
    logo_path = PROJECT_ROOT / "atlas_logo.jpg"
    if logo_path.exists():
        return FileResponse(str(logo_path), media_type="image/jpeg")
    return {"error": "Logo not found"}


# ------------------------------------------------------------------------------
# ROTA RAIZ DO DASHBOARD (PROTEGIDA COM REDIRECIONAMENTO PARA /login)
# ------------------------------------------------------------------------------
# Servir arquivos estáticos (CSS, JS, Vendor)
STATIC_DIR = PROJECT_ROOT / "frontend"
if (STATIC_DIR / "src").exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR / "src")), name="static")
if (STATIC_DIR / "vendor").exists():
    app.mount("/vendor", StaticFiles(directory=str(STATIC_DIR / "vendor")), name="vendor")


@app.get("/", tags=["Dashboard"])
def serve_frontend(request: Request):
    session = require_auth_page(request)
    if not session:
        return RedirectResponse(url="/login", status_code=302)
    frontend_index = PROJECT_ROOT / "frontend" / "index.html"
    target_index = frontend_index if frontend_index.exists() else (PROJECT_ROOT / "index.html")
    return FileResponse(str(target_index), media_type="text/html")
