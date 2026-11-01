"""
backend/services/whatsapp_commands.py

Processador determinístico de comandos de WhatsApp (desfazer, todas, refazer, ajuda).
Sem LLM, com normalização de acentos/caixa, validação de janelas de tempo,
soft delete e restauração via TransactionService e registro de eventos.
"""

import re
import unicodedata
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from backend.db.models import OutboundMessage, Transaction, TransactionEvent
from backend.repositories.outbound_message_repo import OutboundMessageRepository
from backend.repositories.transaction_event_repo import TransactionEventRepository
from backend.repositories.transaction_repo import (
    TransactionRepository,
    active_transactions_filter,
)
from backend.services.transactions import TransactionService
from backend.timeutils import utc_now_naive


def normalize_command_text(text: str | None) -> str:
    """Remove acentos, espaços extras, pontuação e converte para minúsculas."""
    if not text:
        return ""
    # Remove markdown simples como *desfazer* -> desfazer
    clean = re.sub(r"[*_~`]", "", str(text)).strip().lower()
    # Remove acentos
    clean = "".join(
        c for c in unicodedata.normalize("NFD", clean) if unicodedata.category(c) != "Mn"
    )
    return clean.strip()


def identify_whatsapp_command(text: str | None) -> str | None:
    """
    Identifica comandos canônicos via gramática estrita por regex:
    - 'desfazer', 'cancelar', 'undo' -> 'desfazer'
    - 'todas', 'todos', 'tudo' -> 'todas'
    - 'refazer', 'restaurar', 'redo' -> 'refazer'
    - 'ajuda', 'help', 'comandos' -> 'ajuda'
    """
    cmd = normalize_command_text(text)
    if not cmd:
        return None

    if re.fullmatch(r"^(desfazer|cancelar|undo)$", cmd):
        return "desfazer"
    if re.fullmatch(r"^(todas|todos|tudo)$", cmd):
        return "todas"
    if re.fullmatch(r"^(refazer|restaurar|redo)$", cmd):
        return "refazer"
    if re.fullmatch(r"^(ajuda|help|comandos|\?)$", cmd):
        return "ajuda"

    return None


class WhatsAppCommandService:
    def __init__(self, db: Session):
        self.db = db
        self.tx_service = TransactionService(db)
        self.tx_repo = TransactionRepository(db)
        self.event_repo = TransactionEventRepository(db)
        self.outbound_repo = OutboundMessageRepository(db)

    def handle_command(
        self,
        command: str,
        user_name: str,
        remote_jid: str,
        quoted_stanza_id: str | None = None,
    ) -> str:
        """Executa comando identificado e retorna a mensagem de resposta executiva."""
        if command == "ajuda":
            return self._handle_ajuda()
        elif command == "desfazer":
            return self._handle_desfazer(user_name, quoted_stanza_id)
        elif command == "todas":
            return self._handle_todas(user_name)
        elif command == "refazer":
            return self._handle_refazer(user_name)
        return "Comando não reconhecido. Envie *ajuda* para ver a lista de comandos disponíveis."

    def _handle_ajuda(self) -> str:
        return (
            "🤖 *Comandos do Atlas Finanças:*\n\n"
            "• *desfazer* (respondendo à confirmação): Cancela exatamente aquele lançamento (em até 24h).\n"
            "• *desfazer* (sem citar mensagem): Cancela seu último lançamento feito nos últimos 10 minutos.\n"
            "• *todas*: Quando perguntado ao cancelar parcelamento, cancela todas as parcelas (em até 5 min).\n"
            "• *refazer*: Restaura o último lançamento que foi cancelado.\n"
            "• *ajuda*: Exibe esta lista de instruções."
        )

    def _handle_desfazer(self, user_name: str, quoted_stanza_id: str | None) -> str:
        now = utc_now_naive()

        # CASO A: Respondendo (quote) à mensagem de confirmação
        if quoted_stanza_id:
            outbound = self.outbound_repo.get_by_message_id(quoted_stanza_id)
            if not outbound:
                # Tenta buscar por ref_type = transaction se quoted_stanza_id for id da transação
                return "Não encontrei o lançamento referente a esta mensagem citada ou o registro expirou."

            # Janela de 24 horas para quote
            if now - outbound.created_at > timedelta(hours=24):
                return "O prazo de 24 horas para cancelar este lançamento citado expirou."

            tx: Transaction | None = None
            if outbound.ref_type == "transaction" and outbound.ref_id:
                try:
                    tx = self.tx_repo.get_by_id(int(outbound.ref_id))
                except (ValueError, TypeError):
                    tx = None

            if not tx:
                return "Este lançamento já foi cancelado anteriormente ou não está mais ativo."

            # Verifica se faz parte de parcelamento
            if tx.parcela_grupo_id and tx.parcela_total and tx.parcela_total > 1:
                # Soft delete da parcela atual
                self.tx_service.delete_transaction(
                    tx.id, escopo="uma", actor=user_name, channel="whatsapp"
                )
                self.db.commit()
                desc = tx.descricao or tx.categoria
                return (
                    f"🗑️ Cancelei a parcela de *{desc}* (R$ {float(tx.valor):,.2f}).\n\n"
                    f"Deseja cancelar *só esta ou todas* as {tx.parcela_total} parcelas? "
                    "Responda com *todas* nos próximos 5 minutos se quiser cancelar a compra inteira."
                )

            # Transação simples
            desc = tx.descricao or tx.categoria
            val_fmt = f"R$ {float(tx.valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            self.tx_service.delete_transaction(
                tx.id, escopo="uma", actor=user_name, channel="whatsapp"
            )
            self.db.commit()
            return f"🗑️ *Lançamento cancelado:* {desc} ({val_fmt})."

        # CASO B: Sem quote -> cancela último lançamento do mesmo autor nos últimos 10 minutos
        ten_min_ago = now - timedelta(minutes=10)
        recent_tx = (
            self.db.query(Transaction)
            .filter(
                Transaction.author == user_name,
                Transaction.created_at >= ten_min_ago,
                active_transactions_filter(),
            )
            .order_by(Transaction.created_at.desc(), Transaction.id.desc())
            .first()
        )

        if not recent_tx:
            return (
                f"Nenhum lançamento recente encontrado para {user_name} nos últimos 10 minutos.\n"
                "Para cancelar lançamentos mais antigos (até 24h), responda à mensagem de confirmação com *desfazer*."
            )

        if recent_tx.parcela_grupo_id and recent_tx.parcela_total and recent_tx.parcela_total > 1:
            self.tx_service.delete_transaction(
                recent_tx.id, escopo="uma", actor=user_name, channel="whatsapp"
            )
            self.db.commit()
            desc = recent_tx.descricao or recent_tx.categoria
            return (
                f"🗑️ Cancelei a parcela de *{desc}* (R$ {float(recent_tx.valor):,.2f}).\n\n"
                f"Deseja cancelar *só esta ou todas* as {recent_tx.parcela_total} parcelas? "
                "Responda com *todas* nos próximos 5 minutos se quiser cancelar a compra inteira."
            )

        desc = recent_tx.descricao or recent_tx.categoria
        val_fmt = f"R$ {float(recent_tx.valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        self.tx_service.delete_transaction(
            recent_tx.id, escopo="uma", actor=user_name, channel="whatsapp"
        )
        self.db.commit()
        return f"🗑️ *Lançamento cancelado:* {desc} ({val_fmt})."

    def _handle_todas(self, user_name: str) -> str:
        """Processa confirmação de exclusão de todas as parcelas nos últimos 5 minutos."""
        now = utc_now_naive()
        five_min_ago = now - timedelta(minutes=5)

        # Busca último evento 'deleted' pelo usuário nos últimos 5 minutos
        last_del_event = (
            self.db.query(TransactionEvent)
            .filter(
                TransactionEvent.action == "deleted",
                TransactionEvent.actor == user_name,
                TransactionEvent.created_at >= five_min_ago,
            )
            .order_by(TransactionEvent.created_at.desc(), TransactionEvent.id.desc())
            .first()
        )

        if not last_del_event:
            return "Não encontrei nenhuma exclusão de parcela recente (últimos 5 min) para estender a todas."

        tx = self.tx_repo.get_by_id(last_del_event.transaction_id, include_deleted=True)
        if not tx or not tx.parcela_grupo_id:
            return "O último lançamento excluído não faz parte de uma compra parcelada."

        # Soft delete de todas as parcelas restantes do grupo
        siblings = self.tx_repo.list_by_group_id(tx.parcela_grupo_id, include_deleted=False)
        total_removidas = len(siblings) + 1  # contando a que já foi excluída

        for s in siblings:
            s.deleted_at = now
            self.event_repo.record_event(
                transaction_id=s.id,
                action="deleted",
                actor=user_name,
                channel="whatsapp",
                diff={"escopo": "todas", "descricao": s.descricao, "valor": str(s.valor)},
            )

        self.db.commit()
        desc = tx.descricao or tx.categoria
        return f"🗑️ *Todas as {total_removidas} parcelas* de *{desc}* foram canceladas com sucesso."

    def _handle_refazer(self, user_name: str) -> str:
        """Restaura o último lançamento excluído do usuário."""
        last_del_event = (
            self.db.query(TransactionEvent)
            .filter(
                TransactionEvent.action == "deleted",
                TransactionEvent.actor == user_name,
            )
            .order_by(TransactionEvent.created_at.desc(), TransactionEvent.id.desc())
            .first()
        )

        if not last_del_event:
            return f"Não encontrei nenhum lançamento cancelado recente para {user_name}."

        tx = self.tx_repo.get_by_id(last_del_event.transaction_id, include_deleted=True)
        if not tx or tx.deleted_at is None:
            return "O último lançamento já se encontra ativo no sistema."

        # Restaura a transação (ou o grupo se o evento foi de exclusão de todas)
        diff = last_del_event.diff or {}
        restore_grupo = diff.get("escopo") in ["grupo", "todas"]

        restauradas = self.tx_service.restore_transaction(
            tx.id,
            restore_grupo=restore_grupo,
            actor=user_name,
            channel="whatsapp",
        )
        self.db.commit()

        desc = tx.descricao or tx.categoria
        val_fmt = f"R$ {float(tx.valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        qtd = len(restauradas)
        if qtd > 1:
            return f"♻️ *Lançamento restaurado:* {desc} ({qtd} parcelas restauradas)."
        return f"♻️ *Lançamento restaurado:* {desc} ({val_fmt})."
