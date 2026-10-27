"""Utilitários de tempo e data padronizados.

Garante precisão e conformidade com UTC e timezone de Brasília sem depender de datetime.utcnow() deprecado.
"""

from datetime import UTC, datetime


def utc_now_naive() -> datetime:
    """Retorna timestamp UTC sem tzinfo (naive).

    Preserva compatibilidade com colunas DateTime existentes no banco sem alterar schema.
    Substituto seguro para o deprecado datetime.utcnow().
    """
    return datetime.now(UTC).replace(tzinfo=None)
