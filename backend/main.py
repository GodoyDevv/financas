import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.database import engine, Base
from backend.routes import router as api_router
from backend.webhook import webhook_router
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
    # Inicia o agendador assíncrono para o relatório noturno
    task = asyncio.create_task(loop_agendador_relatorio_noturno())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="FinTrack Intelligence API",
    description="Backend de alta precisão para controle financeiro e automação WhatsApp",
    version="1.0.0",
    lifespan=lifespan
)

# Configuração irrestrita de CORS para requisições de qualquer origem e index.html local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusão dos roteadores da aplicação
app.include_router(api_router)
app.include_router(webhook_router)

@app.get("/health")
def health_check():
    from backend.database import DATABASE_URL
    db_type = "postgresql_supabase" if DATABASE_URL else "sqlite_local"
    return {"status": "online", "database": db_type}

@app.post("/api/relatorio-diario/disparar")
def disparar_relatorio_diario_manual():
    """Endpoint administrativo para disparar ou testar o relatório diário sob demanda."""
    sucesso = executar_envio_relatorio_diario(force=True)
    return {"status": "success" if sucesso else "error", "enviado": sucesso}

@app.post("/api/relatorio-semanal/disparar")
def disparar_relatorio_semanal_manual():
    """Endpoint administrativo para disparar ou testar o relatório semanal sob demanda."""
    sucesso = executar_envio_relatorio_semanal(force=True)
    return {"status": "success" if sucesso else "error", "enviado": sucesso}

# Servir a interface web diretamente na raiz do servidor
@app.get("/")
def serve_frontend():
    return FileResponse(str(PROJECT_ROOT / "index.html"), media_type="text/html")
