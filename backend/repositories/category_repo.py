"""
backend/repositories/category_repo.py

Consultas e persistência de dados para Category usando SQLAlchemy Session.
Sem regras de negócio nem commits explícitos.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import Category


class CategoryRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, cat_id: int) -> Category | None:
        stmt = select(Category).where(Category.id == cat_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_normalized_name(self, normalized_name: str) -> Category | None:
        stmt = select(Category).where(Category.normalized_name == normalized_name)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_name(self, name: str) -> Category | None:
        stmt = select(Category).where(Category.name == name)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(self, apenas_ativas: bool = False) -> Sequence[Category]:
        stmt = select(Category)
        if apenas_ativas:
            stmt = stmt.where(Category.ativo.is_(True))
        stmt = stmt.order_by(Category.name.asc())
        return self.db.execute(stmt).scalars().all()

    def add(self, category: Category) -> Category:
        self.db.add(category)
        self.db.flush()
        return category
