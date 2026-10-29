"""
backend/domain/dates.py

Funções puras para manipulação e validação de datas e fusos horários.
Fuso horário canônico: America/Sao_Paulo.
"""

import re
import zoneinfo
from datetime import date, datetime

TIMEZONE_SP = zoneinfo.ZoneInfo("America/Sao_Paulo")


def now_br() -> datetime:
    """Retorna o datetime atual no fuso horário oficial de Brasília/São Paulo."""
    return datetime.now(TIMEZONE_SP)


def today_br() -> date:
    """Retorna a data atual no fuso horário oficial de Brasília/São Paulo."""
    return now_br().date()


def month_range(mes: str) -> tuple[date, date]:
    """
    Valida estritamente a string 'YYYY-MM' e retorna (inicio_inclusivo, fim_exclusivo).
    Exemplo: '2026-10' -> (date(2026, 10, 1), date(2026, 11, 1))
    Lança ValueError caso o formato ou os limites do mês sejam inválidos.
    """
    if not mes or not isinstance(mes, str):
        raise ValueError("Mês não pode ser vazio")

    match = re.match(r"^(\d{4})-(\d{2})$", mes.strip())
    if not match:
        raise ValueError(f"Formato de mês inválido: '{mes}'. Utilize estritamente 'YYYY-MM'.")

    ano = int(match.group(1))
    mes_num = int(match.group(2))

    if mes_num < 1 or mes_num > 12:
        raise ValueError(f"Mês fora do intervalo 01-12: '{mes}'")

    inicio = date(ano, mes_num, 1)
    if mes_num == 12:
        fim = date(ano + 1, 1, 1)
    else:
        fim = date(ano, mes_num + 1, 1)

    return inicio, fim
