"""
backend/services/recurrences.py

Serviço de gerenciamento e materialização preguiçosa de recorrências financeiras.
Sem dependências de frameworks HTTP (FastAPI).
"""

import calendar
import logging
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.categories import (
    get_valid_category_names,
    normalize_category_name,
    resolve_canonical_name,
)
from backend.dates_and_money import month_range, to_decimal, today_br
from backend.db.models import Category, Recurrence, Transaction
from backend.repositories.category_repo import CategoryRepository
from backend.repositories.recurrence_repo import RecurrenceRepository
from backend.repositories.transaction_repo import (
    TransactionRepository,
    active_transactions_filter,
)

logger = logging.getLogger("fintrack.recurrences")


def clamp_day_in_month(year: int, month: int, day: int) -> date:
    """Retorna uma data ajustando o dia ao último dia válido do mês se necessário."""
    max_day = calendar.monthrange(year, month)[1]
    safe_day = min(day, max_day)
    return date(year, month, safe_day)


def ensure_recurrences(db: Session, mes_str: str) -> None:
    """Materializa de forma idempotente e preguiçosa transações recorrentes para o mês solicitado (YYYY-MM)."""
    try:
        inicio_mes, _ = month_range(mes_str)
    except ValueError:
        return

    primeiro_dia_mes = inicio_mes

    # Limite de segurança: materializar no máximo até o mês atual + 12 meses
    hoje = today_br()
    limite_max_ano = hoje.year + ((hoje.month + 12) // 12)
    limite_max_mes = (hoje.month + 12) % 12
    if limite_max_mes == 0:
        limite_max_mes = 12
        limite_max_ano -= 1
    limite_max_date = date(limite_max_ano, limite_max_mes, 1)

    if primeiro_dia_mes > limite_max_date:
        logger.debug(f"Mês {mes_str} excede o horizonte de materialização (máximo +12 meses).")
        return

    rec_repo = RecurrenceRepository(db)
    recorrencias = rec_repo.list_active_for_month(primeiro_dia_mes)
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

        cat_nome = "Outros"
        if rec.category_rel:
            cat_nome = rec.category_rel.name
        else:
            cat = db.query(Category).filter(Category.id == rec.category_id).first()
            if cat:
                cat_nome = str(cat.name)

        nova_transacao = Transaction(
            tipo=rec.tipo,
            valor=to_decimal(rec.valor),  # type: ignore[arg-type]
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
            db.rollback()
            logger.debug(
                f"Instância de recorrência {rec.id} para {primeiro_dia_mes} já existia (IntegrityError tratado)."
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Erro ao materializar recorrência {rec.id}: {e}")


class RecurrenceService:
    def __init__(
        self,
        recurrence_repo: RecurrenceRepository,
        transaction_repo: TransactionRepository,
        category_repo: CategoryRepository,
    ):
        self.rec_repo = recurrence_repo
        self.tx_repo = transaction_repo
        self.cat_repo = category_repo
        self.db = recurrence_repo.db

    def list_recurrences(self, apenas_ativas: bool = False) -> Sequence[Recurrence]:
        return self.rec_repo.list_all(apenas_ativas=apenas_ativas)

    def create_recurrence(
        self,
        tipo: str,
        descricao: str,
        valor: Decimal,
        categoria: str,
        dia_do_mes: int,
        author: str | None = None,
        inicio: date | None = None,
        fim: date | None = None,
    ) -> Recurrence:
        valid_types = ["receita", "despesa_fixa"]
        clean_tipo = tipo.lower()
        if clean_tipo not in valid_types:
            raise ValueError(f"Tipo inválido. Escolha: {', '.join(valid_types)}")

        canonical_name = resolve_canonical_name(categoria)
        if not canonical_name:
            raise ValueError(
                f"Categoria '{categoria}' não é válida. Válidas: {', '.join(get_valid_category_names())}"
            )

        norm_name = normalize_category_name(canonical_name)
        cat_db = self.cat_repo.get_by_normalized_name(norm_name)
        if not cat_db:
            cat_db = Category(
                name=canonical_name,
                normalized_name=norm_name,
                tipo="receita" if clean_tipo == "receita" else "despesa",
                ativo=True,
            )
            self.cat_repo.add(cat_db)

        inicio_date = inicio.replace(day=1) if inicio else today_br().replace(day=1)
        fim_date = fim.replace(day=1) if fim else None

        rec = Recurrence(
            tipo=clean_tipo,
            descricao=descricao.strip(),
            valor=to_decimal(valor),
            category_id=cat_db.id,
            author=author.strip() if author else None,
            dia_do_mes=dia_do_mes,
            inicio=inicio_date,
            fim=fim_date,
            ativo=True,
        )
        self.rec_repo.add(rec)
        return rec

    def update_recurrence(
        self,
        rec_id: int,
        descricao: str | None = None,
        valor: Decimal | None = None,
        dia_do_mes: int | None = None,
        ativo: bool | None = None,
        fim: date | None = None,
        author: str | None = None,
        categoria: str | None = None,
    ) -> Recurrence:
        rec = self.rec_repo.get_by_id(rec_id)
        if not rec:
            raise ValueError("Recorrência não encontrada")

        primeiro_dia_mes_atual = today_br().replace(day=1)

        if descricao is not None:
            rec.descricao = descricao.strip()
        if valor is not None:
            rec.valor = to_decimal(valor)
        if dia_do_mes is not None:
            rec.dia_do_mes = dia_do_mes
        if ativo is not None:
            rec.ativo = ativo
        if fim is not None:
            rec.fim = fim.replace(day=1)
        if author is not None:
            rec.author = author.strip() if author else None

        if categoria is not None:
            canonical_name = resolve_canonical_name(categoria)
            if not canonical_name:
                raise ValueError(
                    f"Categoria '{categoria}' não é válida. Válidas: {', '.join(get_valid_category_names())}"
                )
            norm_name = normalize_category_name(canonical_name)
            cat_db = self.cat_repo.get_by_normalized_name(norm_name)
            if not cat_db:
                cat_db = Category(
                    name=canonical_name,
                    normalized_name=norm_name,
                    tipo="receita" if rec.tipo == "receita" else "despesa",
                    ativo=True,
                )
                self.cat_repo.add(cat_db)
            rec.category_id = cat_db.id

        # Sincroniza instâncias do mês atual em diante que NÃO foram editadas manualmente e estão ativas
        instancias_futuras = (
            self.db.query(Transaction)
            .filter(
                Transaction.recurrence_id == rec.id,
                Transaction.competencia >= primeiro_dia_mes_atual,
                Transaction.editado_manual.is_(False),
                active_transactions_filter(),
            )
            .all()
        )

        cat_name = rec.category_rel.name if rec.category_rel else "Outros"

        for inst in instancias_futuras:
            if descricao is not None:
                inst.descricao = rec.descricao
            if valor is not None:
                inst.valor = rec.valor
            if author is not None:
                inst.author = rec.author
            if categoria is not None:
                inst.categoria = cat_name
                inst.category_id = rec.category_id
            if dia_do_mes is not None and inst.competencia:
                inst.data = clamp_day_in_month(
                    inst.competencia.year, inst.competencia.month, rec.dia_do_mes
                )
                if inst.tipo == "despesa_fixa":
                    inst.vencimento = f"Dia {rec.dia_do_mes}"

        self.db.flush()
        return rec

    def delete_recurrence(self, rec_id: int) -> tuple[Recurrence, int]:
        """
        Encerra a regra de recorrência:
        - Define fim = mês anterior ao mês atual.
        - Remove apenas instâncias futuras NÃO editadas manualmente.
        Retorna a recorrência alterada e o número de instâncias futuras removidas.
        """
        rec = self.rec_repo.get_by_id(rec_id)
        if not rec:
            raise ValueError("Recorrência não encontrada")

        primeiro_dia_mes_atual = today_br().replace(day=1)
        mes_anterior = (primeiro_dia_mes_atual.replace(day=1) - timedelta(days=1)).replace(day=1)

        rec.fim = mes_anterior
        rec.ativo = False

        futuras = (
            self.db.query(Transaction)
            .filter(
                Transaction.recurrence_id == rec.id,
                Transaction.competencia >= primeiro_dia_mes_atual,
                Transaction.editado_manual.is_(False),
                active_transactions_filter(),
            )
            .all()
        )

        removed_count = len(futuras)
        for f in futuras:
            self.db.delete(f)

        self.db.flush()
        return rec, removed_count
