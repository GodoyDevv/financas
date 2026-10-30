"""Exportador estático da especificação OpenAPI do FastAPI.

Gera frontend/openapi.json a partir do app FastAPI sem iniciar servidor web,
permitindo a geração estática de tipos TypeScript (openapi-typescript)
mesmo com /docs e /redoc desativados em produção.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Adiciona raiz do projeto ao sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Força ambiente de teste para export seguro
os.environ["ENV"] = "test"
os.environ.setdefault("APP_PASSWORD", "test_password_for_openapi_export")
os.environ.setdefault("WHATSAPP_GROUP_JID", "123456@g.us")
os.environ.setdefault("SESSION_SECRET", "supersecretkeywithmorethanthirtytwocharacters!")
os.environ.setdefault("WEBHOOK_SECRET", "superwebhooksecretwiththirtytwocharsmin!")
os.environ.setdefault("ADMIN_TOKEN", "superadmintokenwiththirtytwocharsminlength!")

from backend.main import app  # noqa: E402


def export_openapi(output_path: Path | None = None) -> Path:
    if output_path is None:
        output_path = PROJECT_ROOT / "frontend" / "openapi.json"

    openapi_schema = app.openapi()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"OpenAPI exportado com sucesso para {output_path}")
    return output_path


if __name__ == "__main__":
    export_openapi()
