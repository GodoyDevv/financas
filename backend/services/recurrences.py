"""Serviço de gerenciamento e materialização preguiçosa de recorrências financeiras."""

import calendar
import logging
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.dates_and_money import month_range, to_decimal, today_br
from backend.models import Category, Recurrence, Transaction

logger = logging.getLogger("fintrack.recurrences")


def clamp_day_in_month(year: int, month: int, day: int) -> date:
    """Retorna uma data ajustando o dia ao último dia válido do mês se necessário."""
    max_day = calendar.monthrange(year, month)[1]
    safe_day = min(day, max_day)
    return date(year, month, safe_day)


def ensure_recurrences(db: Session, mes_str: str) -> None:
    """Materializa de forma idempotente e preguiçosa transações recorrentes para o mês solicitado (YYYY-MM).

    Regras:
    - O mês solicitado não pode ultrapassar o mês atual + 12 meses.
    - Seleciona Recurrence onde ativo=True, inicio <= primeiro_dia_mes e (fim IS NULL ou fim >= primeiro_dia_mes).
    - Cria Transaction com recurrence_id, competencia=primeiro_dia_mes e data clamped.
    - Trata IntegrityError (violação do índice único recurrence_id + competencia) como corrida benigna / já existente.
    """
    try:
        inicio_mes, _ = month_range(mes_str)
    except ValueError:
        return

    primeiro_dia_mes = inicio_mes

    # Limite de segurança: materializar no máximo até o mês atual + 12 meses
    hoje = today_br()
    # Limite superior: hoje + 365 dias (ou 12 meses)
    limite_max_ano = hoje.year + ((hoje.month + 12) // 12)
    limite_max_mes = (hoje.month + 12) % 12
    if limite_max_mes == 0:
        limite_max_mes = 12
        limite_max_ano -= 1
    limite_max_date = date(limite_max_ano, limite_max_mes, 1)

    if primeiro_dia_mes > limite_max_date:
        logger.debug(f"Mês {mes_str} excede o horizonte de materialização (máximo +12 meses).")
        return

    # Busca regras ativas que cobrem o mês solicitado
    recorrencias = (
        db.query(Recurrence)
        .filter(
            Recurrence.ativo.is_(True),
            Recurrence.inicio <= primeiro_dia_mes,  # type: ignore[arg-type] # SQLAlchemy binary expression
            (Recurrence.fim.is_(None)) | (Recurrence.fim >= primeiro_dia_mes),  # type: ignore[arg-type] # SQLAlchemy binary expression
        )
        .all()
    )

    if not recorrencias:
        return

    for rec in recorrencias:
        # Verifica se já existe instância criada para esta competência
        existente = (
            db.query(Transaction)
            .filter(
                Transaction.recurrence_id == rec.id, Transaction.competencia == primeiro_dia_mes
            )
            .first()
        )

        if existente:
            continue

        data_transacao = clamp_day_in_month(
            primeiro_dia_mes.year, primeiro_dia_mes.month, int(rec.dia_do_mes)
        )

        # Obtém categoria canônica
        cat_nome = "Outros"
        if rec.category_rel:
            cat_nome = rec.category_rel.name
        else:
            cat = db.query(Category).filter(Category.id == rec.category_id).first()
            if cat:
                cat_nome = str(cat.name)

        nova_transacao = Transaction(
            tipo=rec.tipo,
            valor=to_decimal(rec.valor),  # type: ignore[arg-type] # Column[Decimal] no runtime é Decimal
            categoria=cat_nome,
            category_id=rec.category_id,
            data=data_transacao,
            descricao=rec.descricao,
            author=rec.author,
            channel="system",
            source=rec.author or "Sistema",
            vencimento=f"Dia {rec.dia_do_mes}" if rec.tipo == "despesa_fixa" else None,
            recurrence_id=rec.id,
            competencia=primeiro_dia_mes,
            editado_manual=False,
        )

        try:
            db.add(nova_transacao)
            db.commit()
        except IntegrityError:
            # Concorrência/corrida: outra thread/processo já inseriu esta mesma recorrência + competência
            db.rollback()
            logger.debug(
                f"Instância de recorrência {rec.id} para {primeiro_dia_mes} já existia (IntegrityError tratado)."
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Erro ao materializar recorrência {rec.id}: {e}")
