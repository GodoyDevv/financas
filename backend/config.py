"""Configurações globais de negócio da aplicação."""

from typing import Literal

# Decisão de produto para cálculo de parcelamentos:
# - "valor_da_parcela": "Tênis 300 em 3x" = 3 parcelas de R$ 300,00 (total R$ 900,00).
# - "valor_total": "Tênis 300 em 3x" = total R$ 300,00, em 3 parcelas de R$ 100,00.
PARCELA_MODO: Literal["valor_da_parcela", "valor_total"] = "valor_da_parcela"
