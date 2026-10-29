"""
backend/services/categories.py

Regras de negócio e casos de uso para Categorias e Orçamentos.
Sem dependências de frameworks HTTP (FastAPI) e sem commits (caller decide).
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from backend.categories import normalize_category_name
from backend.db.models import Category
from backend.domain.money import to_decimal
from backend.repositories.category_repo import CategoryRepository
from backend.repositories.transaction_repo import TransactionRepository


class CategoryService:
    def __init__(
        self,
        category_repo: CategoryRepository,
        transaction_repo: TransactionRepository,
    ):
        self.cat_repo = category_repo
        self.tx_repo = transaction_repo

    def list_categories_with_budget(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        ativo: bool | None = None,
    ) -> list[dict]:
        """
        Retorna a lista de categorias cadastradas com informações de orçamento (budget),
        gasto acumulado no período (se fornecido) e percentual do orçamento atingido.
        """
        stmt = self.cat_repo.db.query(Category)
        if ativo is not None:
            stmt = stmt.filter(Category.ativo == ativo)
        categories: Sequence[Category] = stmt.order_by(Category.id).all()

        spend_by_cat: dict[int, Decimal] = {}
        if start_date is not None and end_date is not None:
            spend_by_cat = self.tx_repo.get_expenses_by_category_in_range(start_date, end_date)

        result: list[dict] = []
        for cat in categories:
            gasto = spend_by_cat.get(cat.id, Decimal("0.00"))
            pct_budget = None
            if cat.budget and to_decimal(cat.budget) > Decimal("0.00"):
                pct_budget = round((float(gasto) / float(cat.budget)) * 100, 1)

            result.append(
                {
                    "id": cat.id,
                    "name": cat.name,
                    "nome": cat.name,
                    "tipo": cat.tipo,
                    "budget": to_decimal(cat.budget) if cat.budget is not None else None,
                    "ativo": cat.ativo,
                    "gasto_mes": gasto,
                    "percentual_budget": pct_budget,
                }
            )

        return result

    def update_category(
        self,
        cat_id: int,
        name: str | None = None,
        budget: Decimal | None = None,
        ativo: bool | None = None,
    ) -> Category:
        """
        Atualiza campos de uma categoria: name, budget, ativo.
        Lança ValueError para regras violadas (ex: categoria inexistente ou duplicada).
        Não commita.
        """
        category = self.cat_repo.get_by_id(cat_id)
        if not category:
            raise ValueError("Categoria não encontrada")

        if name is not None:
            new_name = name.strip()
            new_norm = normalize_category_name(new_name)
            conflict = self.cat_repo.get_by_normalized_name(new_norm)
            if conflict and conflict.id != cat_id:
                raise ValueError(
                    f"Já existe uma categoria cadastrada com o nome '{conflict.name}'."
                )
            category.name = new_name
            category.normalized_name = new_norm

            # Sincroniza nome nas transações existentes
            self.tx_repo.update_category_name_for_transactions(cat_id, new_name)

        if budget is not None:
            category.budget = to_decimal(budget)

        if ativo is not None:
            category.ativo = ativo

        self.cat_repo.db.flush()
        return category
