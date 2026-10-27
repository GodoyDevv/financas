"""Serviço centralizado para criação e gerenciamento de parcelamentos."""

import calendar
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from backend.config import PARCELA_MODO
from backend.dates_and_money import to_decimal, today_br
from backend.models import Transaction

CENT = Decimal("0.01")


def add_months_clamped(sourcedate: date, months: int) -> date:
    """Adiciona 'months' meses a uma data respeitando rigorosamente o limite de dias do mês de destino.

    Exemplo: 31/01 + 1 mês -> 28/02 (ou 29/02 em ano bissexto), e + 2 meses -> 31/03.
    """
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(sourcedate.day, max_day)
    return date(year, month, day)


def calcular_valores_parcelamento(
    valor_input: Decimal, parcelas: int, modo: str | None = None
) -> tuple[list[Decimal], Decimal]:
    """Calcula o valor de cada parcela e o total geral com base na decisão de produto configurada.

    Retorna (lista_valores_parcelas, valor_total_geral).
    - modo 'valor_da_parcela': cada parcela vale valor_input. Total = valor_input * parcelas.
    - modo 'valor_total': o total geral é valor_input. Cada parcela vale floor(total / N), e os centavos
      restantes são adicionados à PRIMEIRA parcela.
    """
    modo_ativo = modo or PARCELA_MODO
    valor_dec = to_decimal(valor_input)

    if parcelas <= 1:
        return [valor_dec], valor_dec

    if modo_ativo == "valor_da_parcela":
        total_geral = (valor_dec * parcelas).quantize(CENT, rounding=ROUND_HALF_UP)
        return [valor_dec] * parcelas, total_geral
    else:  # modo == "valor_total"
        total_geral = valor_dec
        # Divisão básica
        val_base = (total_geral / Decimal(parcelas)).quantize(CENT, rounding=ROUND_HALF_UP)
        # Calcula centavos de diferença devido ao arredondamento
        soma_parcial = val_base * parcelas
        diferenca = total_geral - soma_parcial
        primeira_parcela = (val_base + diferenca).quantize(CENT, rounding=ROUND_HALF_UP)

        valores = [primeira_parcela] + [val_base] * (parcelas - 1)
        return valores, total_geral


def criar_parcelamento(
    db: Session, base_data: dict[str, Any], parcelas: int = 1, modo: str | None = None
) -> list[Transaction]:
    """Cria uma transação única ou um conjunto de N parcelas vinculadas por UUID.

    Executa tudo na mesma transação de banco (tudo ou nada). Em caso de erro, efetua rollback.
    """
    parcelas_qtd = max(1, int(parcelas))
    raw_data = base_data.get("data")
    if isinstance(raw_data, str):
        data_inicial = date.fromisoformat(raw_data)
    elif isinstance(raw_data, date):
        data_inicial = raw_data
    else:
        data_inicial = today_br()

    # Cálculo dos valores
    raw_valor = base_data.get("valor", Decimal("0.00"))
    valores_parcelas, _ = calcular_valores_parcelamento(raw_valor, parcelas_qtd, modo=modo)

    grupo_id = str(uuid.uuid4()) if parcelas_qtd > 1 else None
    descricao_base = str(base_data.get("descricao") or "").strip()

    novas_transacoes: list[Transaction] = []

    try:
        for i in range(parcelas_qtd):
            data_parcela = add_months_clamped(data_inicial, i)
            val_parcela = valores_parcelas[i]

            if parcelas_qtd > 1:
                p_num = i + 1
                desc_parcela = (
                    f"{descricao_base} ({p_num}/{parcelas_qtd})".strip()
                    if descricao_base
                    else f"Parcela ({p_num}/{parcelas_qtd})"
                )
            else:
                p_num = None
                desc_parcela = descricao_base

            tx = Transaction(
                tipo=base_data["tipo"],
                valor=val_parcela,
                categoria=base_data["categoria"],
                category_id=base_data["category_id"],
                data=data_parcela,
                descricao=desc_parcela,
                author=base_data.get("author"),
                channel=base_data.get("channel", "unknown"),
                source=base_data.get("source"),
                vencimento=base_data.get("vencimento"),
                parcela_grupo_id=grupo_id,
                parcela_num=p_num,
                parcela_total=parcelas_qtd if parcelas_qtd > 1 else None,
            )
            db.add(tx)
            novas_transacoes.append(tx)

        db.commit()
        for tx in novas_transacoes:
            db.refresh(tx)
        return novas_transacoes

    except Exception:
        db.rollback()
        raise
