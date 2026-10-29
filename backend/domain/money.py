"""
backend/domain/money.py

Funções puras e imutáveis para manipulação de valores monetários.
Sem dependências de banco de dados ou frameworks externos.
"""

from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")


def to_decimal(val: str | int | float | Decimal | None) -> Decimal:
    """
    Converte qualquer valor numérico com segurança para Decimal(12, 2)
    usando arredondamento bancário ROUND_HALF_UP.
    NUNCA faz Decimal(float_direto), converte float via str(x).
    """
    if val is None:
        return Decimal("0.00")
    if isinstance(val, Decimal):
        return val.quantize(CENTS, rounding=ROUND_HALF_UP)
    d = Decimal(str(val)) if isinstance(val, float) else Decimal(str(val).strip())
    return d.quantize(CENTS, rounding=ROUND_HALF_UP)


def format_brl(valor: float | Decimal) -> str:
    """Formata valor em padrão brasileiro de moeda R$ 1.234,56"""
    d_val = to_decimal(valor)
    return f"R$ {d_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
