"""
backend/database.py

Módulo retrocompatível. Re-exporta sessões e Base de backend.db.
"""

from backend.db.session import (
    Base,
    SessionLocal,
    convention,
    create_db_engine,
    engine,
    get_database_url,
    get_db,
    metadata,
)

__all__ = [
    "Base",
    "SessionLocal",
    "convention",
    "create_db_engine",
    "engine",
    "get_database_url",
    "get_db",
    "metadata",
]
