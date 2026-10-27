from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import get_settings

# Convenção de nomenclatura de constraints para integridade no Postgres e batch mode no SQLite
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)


class Base(DeclarativeBase):
    metadata = metadata


def get_database_url() -> str:
    """Retorna e normaliza a DATABASE_URL para conexão com psycopg 3 ou fallback SQLite."""
    return get_settings().DATABASE_URL


def create_db_engine():
    url = get_database_url()
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"prepare_threshold": None},
    )


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
