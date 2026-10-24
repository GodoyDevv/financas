import zoneinfo
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from typing import Union, Tuple
import re

TIMEZONE_SP = zoneinfo.ZoneInfo("America/Sao_Paulo")
CENTS = Decimal("0.01")


def now_br() -> datetime:
    """Retorna o datetime atual no fuso horário oficial de Brasília/São Paulo."""
    return datetime.now(TIMEZONE_SP)


def today_br() -> date:
    """Retorna a data atual no fuso horário oficial de Brasília/São Paulo."""
    return now_br().date()


def to_decimal(val: Union[str, int, float, Decimal, None]) -> Decimal:
    """
    Converte qualquer valor numérico com segurança para Decimal(12, 2)
    usando arredondamento bancário ROUND_HALF_UP.
    NUNCA faz Decimal(float_direto), converte float via str(x).
    """
    if val is None:
        return Decimal("0.00")
    if isinstance(val, Decimal):
        return val.quantize(CENTS, rounding=ROUND_HALF_UP)
    if isinstance(val, float):
        d = Decimal(str(val))
    else:
        d = Decimal(str(val).strip())
    return d.quantize(CENTS, rounding=ROUND_HALF_UP)


def month_range(mes: str) -> Tuple[date, date]:
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
        raise ValueError(f"Mês inválido: '{mes_num}'. Deve estar entre 01 e 12.")
    
    inicio = date(ano, mes_num, 1)
    if mes_num == 12:
        fim_exclusivo = date(ano + 1, 1, 1)
    else:
        fim_exclusivo = date(ano, mes_num + 1, 1)
        
    return inicio, fim_exclusivo
