"""
backend/dates_and_money.py

Módulo retrocompatível. Re-exporta funções do domínio puro backend.domain.
"""

from backend.domain.dates import TIMEZONE_SP, month_range, now_br, today_br
from backend.domain.money import CENTS, to_decimal

__all__ = [
    "CENTS",
    "TIMEZONE_SP",
    "month_range",
    "now_br",
    "to_decimal",
    "today_br",
]
