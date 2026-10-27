# ==============================================================================
# ESTÁGIO 1: BUILDER (Instalação e compilação hermética de dependências via uv)
# ==============================================================================
FROM python:3.12.10-slim AS builder

# Instala ferramentas essenciais de build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copia binário oficial do uv
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

WORKDIR /app

# Copia especificações de dependências
COPY pyproject.toml uv.lock ./

# Sincroniza ambiente virtual estritamente com dependências de produção
ENV UV_COMPILE_BYTECODE=1
RUN uv sync --frozen --no-dev --no-install-project

# ==============================================================================
# ESTÁGIO 2: RUNTIME FINAL (Imagem enxuta e segura sem privilégios de root)
# ==============================================================================
FROM python:3.12.10-slim AS runtime

# Instala apenas dependências dinâmicas de runtime (libpq para psycopg e curl para healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Variáveis de ambiente padrão do Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8000

# Cria usuário não-root sem privilégios para execução segura
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser

WORKDIR /app

# Copia ambiente virtual construído pelo builder
COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv

# Copia apenas o código e recursos necessários da aplicação
COPY --chown=appuser:appgroup backend /app/backend
COPY --chown=appuser:appgroup migrations /app/migrations
COPY --chown=appuser:appgroup alembic.ini /app/alembic.ini
COPY --chown=appuser:appgroup index.html /app/index.html
COPY --chown=appuser:appgroup entrypoint.sh /app/entrypoint.sh

# Garante permissões de execução no script de inicialização
RUN chmod +x /app/entrypoint.sh

# Alterna para o usuário não-root
USER appuser

# Healthcheck em conformidade com o endpoint /health da aplicação
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT}/health || exit 1

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
