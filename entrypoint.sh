#!/bin/sh
set -e

# Executa migrações do banco relacional de forma síncrona
echo "Aplicando migrações com Alembic..."
alembic upgrade head

# Executa a aplicação FastAPI respeitando $PORT (Render / Container padrão)
PORT="${PORT:-8000}"
echo "Iniciando servidor Uvicorn na porta ${PORT}..."
exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}"
