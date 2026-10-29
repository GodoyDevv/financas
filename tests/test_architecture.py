"""
tests/test_architecture.py

Garante conformidade estrita da arquitetura hexagonal/em camadas via AST inspection:
Regras:
1. backend/domain/: funções puras; NUNCA deve importar backend.db, backend.models, backend.database,
   backend.services, backend.repositories, backend.api ou FastAPI.
2. backend/repositories/: thin session queries; importa backend.db/models; NUNCA deve importar
   backend.api, backend.services ou FastAPI.
3. backend/services/: casos de uso e lógica de negócio; NUNCA deve importar backend.api ou FastAPI.
4. backend/integrations/: clientes externos e templates; NUNCA deve importar backend.api ou backend.services.
"""

import ast
from pathlib import Path


def _get_imports(filepath: Path) -> list[str]:
    """Retorna lista de módulos importados em um arquivo Python via AST."""
    with open(filepath, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=str(filepath))

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_domain_layer_has_no_internal_framework_dependencies():
    """backend/domain deve conter apenas funções puras."""
    domain_dir = Path("backend/domain")
    forbidden = [
        "fastapi",
        "sqlalchemy",
        "backend.db",
        "backend.services",
        "backend.api",
        "backend.repositories",
    ]

    for file in domain_dir.glob("*.py"):
        if file.name == "__init__.py":
            continue
        imports = _get_imports(file)
        for imp in imports:
            for bad in forbidden:
                assert not imp.startswith(
                    bad
                ), f"Violação de arquitetura: {file} importa '{imp}' (proibido na camada de domínio)"


def test_repositories_layer_does_not_import_services_or_api():
    """backend/repositories nunca importa services, api ou fastapi."""
    repo_dir = Path("backend/repositories")
    forbidden = ["fastapi", "backend.api", "backend.services"]

    for file in repo_dir.glob("*.py"):
        if file.name == "__init__.py":
            continue
        imports = _get_imports(file)
        for imp in imports:
            for bad in forbidden:
                assert not imp.startswith(
                    bad
                ), f"Violação de arquitetura: {file} importa '{imp}' (proibido na camada de repositórios)"


def test_services_layer_does_not_import_api_or_fastapi():
    """backend/services nunca importa fastapi ou api."""
    services_dir = Path("backend/services")
    forbidden = ["fastapi", "backend.api"]

    for file in services_dir.glob("*.py"):
        if file.name == "__init__.py":
            continue
        imports = _get_imports(file)
        for imp in imports:
            for bad in forbidden:
                assert not imp.startswith(
                    bad
                ), f"Violação de arquitetura: {file} importa '{imp}' (proibido na camada de serviços)"


def test_integrations_layer_does_not_import_services_or_api():
    """backend/integrations nunca importa services, api ou fastapi."""
    integrations_dir = Path("backend/integrations")
    forbidden = ["fastapi", "backend.api", "backend.services"]

    for file in integrations_dir.glob("*.py"):
        if file.name == "__init__.py":
            continue
        imports = _get_imports(file)
        for imp in imports:
            for bad in forbidden:
                assert not imp.startswith(
                    bad
                ), f"Violação de arquitetura: {file} importa '{imp}' (proibido na camada de integrações)"
