"""
backend/services/summary.py

Motor ÚNICO de cálculo de saldo, consolidação de totais e métricas.
Reutilizado por Dashboard (/api/summary, /api/metrics), Relatórios (Scheduler)
e Mensagens do WhatsApp (Webhook).
Sem dependências de FastAPI.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from backend.db.models import Category, Transaction
from backend.domain.dates import month_range
from backend.domain.money import to_decimal
from backend.repositories.transaction_repo import active_transactions_filter
from backend.services.recurrences import ensure_recurrences


class SummaryService:
    def __init__(self, db: Session):
        self.db = db

    def get_month_summary(self, mes: str | None = None) -> dict[str, Decimal]:
        """
        Calcula o resumo consolidado de receitas, despesas fixas,
        despesas variáveis, despesa total e saldo livre para um mês específico ou geral.
        Garante respeito estrito ao soft delete (deleted_at IS NULL).
        """
        query = (
            self.db.query(Transaction.tipo, func.sum(Transaction.valor).label("total"))
            .filter(active_transactions_filter())
        )
        if mes:
            inicio, fim = month_range(mes)
            ensure_recurrences(self.db, mes)
            query = query.filter((Transaction.data >= inicio) & (Transaction.data < fim))

        totals = query.group_by(Transaction.tipo).all()

        total_receitas = Decimal("0.00")
        total_despesas_fixas = Decimal("0.00")
        total_despesas_variaveis = Decimal("0.00")

        for row in totals:
            t = str(row[0]).lower() if row[0] else ""
            val = to_decimal(row[1])
            if t == "receita":
                total_receitas += val
            elif t == "despesa_fixa":
                total_despesas_fixas += val
            elif t in ["despesa_variavel", "despesa"]:
                total_despesas_variaveis += val

        total_despesas = total_despesas_fixas + total_despesas_variaveis
        saldo_livre = total_receitas - total_despesas

        return {
            "total_receitas": total_receitas,
            "total_despesas_fixas": total_despesas_fixas,
            "total_despesas_variaveis": total_despesas_variaveis,
            "total_despesas": total_despesas,
            "saldo_livre": saldo_livre,
        }

    def get_month_metrics(self, mes: str | None = None) -> dict[str, Any]:
        """
        Retorna métricas completas de planejamento financeiro doméstico,
        incluindo distribuição por categorias e percentuais de orçamento.
        """
        query_totals = (
            self.db.query(
                Transaction.tipo,
                func.sum(Transaction.valor).label("total"),
                func.count(Transaction.id).label("qtd"),
            )
            .filter(active_transactions_filter())
        )
        if mes:
            inicio, fim = month_range(mes)
            ensure_recurrences(self.db, mes)
            query_totals = query_totals.filter(
                (Transaction.data >= inicio) & (Transaction.data < fim)
            )

        totals = query_totals.group_by(Transaction.tipo).all()

        receitas_totais = Decimal("0.00")
        contas_fixas = Decimal("0.00")
        gastos_whatsapp = Decimal("0.00")
        total_transacoes = 0

        for row in totals:
            t = str(row[0]).lower() if row[0] else ""
            val = to_decimal(row[1])
            qtd = int(row[2] or 0)
            total_transacoes += qtd

            if t == "receita":
                receitas_totais += val
            elif t == "despesa_fixa":
                contas_fixas += val
            elif t in ["despesa_variavel", "despesa"]:
                gastos_whatsapp += val

        total_despesas = contas_fixas + gastos_whatsapp
        saldo_livre = receitas_totais - total_despesas

        # Distribuição de despesas por categoria (respeitando soft delete)
        cat_query = (
            self.db.query(
                Category.id.label("cat_id"),
                Category.name.label("cat_name"),
                Category.budget.label("cat_budget"),
                func.sum(Transaction.valor).label("total"),
            )
            .join(Transaction, Transaction.category_id == Category.id)
            .filter(
                Transaction.tipo.in_(["despesa_fixa", "despesa_variavel", "despesa"]),
                active_transactions_filter(),
            )
        )

        if mes:
            cat_query = cat_query.filter((Transaction.data >= inicio) & (Transaction.data < fim))

        cat_rows = (
            cat_query.group_by(Category.id, Category.name, Category.budget)
            .order_by(desc(func.sum(Transaction.valor)))
            .all()
        )

        categorias = []
        base_calc = float(total_despesas) if total_despesas > Decimal("0.00") else 1.0
        for cat_row in cat_rows:
            cat_total = to_decimal(cat_row.total)
            cat_budget = to_decimal(cat_row.cat_budget) if cat_row.cat_budget is not None else None
            percentual = (
                round((float(cat_total) / base_calc) * 100, 1)
                if total_despesas > Decimal("0.00")
                else 0.0
            )

            percentual_budget = None
            if cat_budget and cat_budget > Decimal("0.00"):
                percentual_budget = round((float(cat_total) / float(cat_budget)) * 100, 1)

            categorias.append(
                {
                    "categoria": cat_row.cat_name,
                    "category_id": cat_row.cat_id,
                    "total": cat_total,
                    "budget": cat_budget,
                    "percentual": percentual,
                    "percentual_budget": percentual_budget,
                }
            )

        return {
            "receitas_totais": receitas_totais,
            "contas_fixas": contas_fixas,
            "gastos_whatsapp": gastos_whatsapp,
            "total_despesas": total_despesas,
            "saldo_livre": saldo_livre,
            "total_transacoes": total_transacoes,
            "categorias": categorias,
        }
