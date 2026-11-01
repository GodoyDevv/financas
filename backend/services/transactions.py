"""
backend/services/transactions.py

Casos de uso para gerenciamento de transações, parcelamentos, soft delete e auditoria.
Regras de validação, cálculo e coordenação sobre repositórios.
Sem dependências de frameworks HTTP (FastAPI) e sem commits no banco.
"""

from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from backend.categories import (
    get_valid_category_names,
    normalize_category_name,
    resolve_canonical_name,
)
from backend.db.models import Category, Transaction
from backend.domain.dates import month_range
from backend.domain.money import to_decimal
from backend.repositories.category_repo import CategoryRepository
from backend.repositories.transaction_event_repo import TransactionEventRepository
from backend.repositories.transaction_repo import TransactionRepository
from backend.services.installments import criar_parcelamento
from backend.services.recurrences import ensure_recurrences
from backend.timeutils import utc_now_naive


class TransactionService:
    def __init__(self, db: Session):
        self.db = db
        self.tx_repo = TransactionRepository(db)
        self.cat_repo = CategoryRepository(db)
        self.event_repo = TransactionEventRepository(db)

    def list_transactions(
        self,
        mes: str | None = None,
        tipo: str | None = None,
        author: str | None = None,
        channel: str | None = None,
    ) -> Sequence[Transaction]:
        """
        Retorna lista de transações ativas com filtros opcionais.
        Materializa recorrências ativas se 'mes' for fornecido.
        """
        if mes:
            inicio, fim = month_range(mes)
            ensure_recurrences(self.db, mes)
            txs = self.tx_repo.list_by_date_range(inicio, fim, tipo=tipo)
        else:
            txs = self.tx_repo.list_by_date_range(date(1970, 1, 1), date(2099, 12, 31), tipo=tipo)

        if author:
            txs = [t for t in txs if t.author == author]
        if channel:
            txs = [t for t in txs if t.channel == channel]

        # Mantém ordenação id desc padrão
        return sorted(txs, key=lambda t: t.id, reverse=True)

    def create_transaction(
        self,
        tx_data: dict[str, Any],
        actor: str | None = None,
        channel: str | None = None,
    ) -> list[Transaction]:
        """
        Cria nova transação ou conjunto de parcelas.
        Valida tipos, canais e categorias.
        Registra evento de auditoria 'created'.
        """
        valid_types = ["receita", "despesa_fixa", "despesa_variavel"]
        raw_tipo = str(tx_data.get("tipo", "")).lower()
        clean_tipo = "despesa_variavel" if raw_tipo == "despesa" else raw_tipo

        if clean_tipo not in valid_types:
            raise ValueError(f"Tipo inválido. Escolha um dos seguintes: {', '.join(valid_types)}")

        categoria_input = str(tx_data.get("categoria", "")).strip()
        canonical_name = resolve_canonical_name(categoria_input)
        if not canonical_name:
            valid_cats = get_valid_category_names()
            raise ValueError(
                f"Categoria '{categoria_input}' não é válida. Categorias permitidas: {valid_cats}"
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

        author_val = str(tx_data.get("author", "")).strip() if tx_data.get("author") else None
        channel_input = tx_data.get("channel") or channel
        channel_val = channel_input if channel_input and channel_input != "unknown" else "dashboard"
        source_val = (
            str(tx_data.get("source", "")).strip()
            if tx_data.get("source")
            else (author_val or channel_val)
        )

        descricao_val = (
            str(tx_data.get("descricao", "")).strip() if tx_data.get("descricao") else ""
        )
        vencimento_val = (
            str(tx_data.get("vencimento", "")).strip() if tx_data.get("vencimento") else None
        )

        base_tx_dict = {
            "tipo": clean_tipo,
            "valor": to_decimal(tx_data.get("valor")),
            "categoria": cat_db.name,
            "category_id": cat_db.id,
            "data": tx_data.get("data"),
            "descricao": descricao_val,
            "author": author_val,
            "channel": channel_val,
            "source": source_val,
            "vencimento": vencimento_val,
        }

        parcelas_count = int(tx_data.get("parcelas") or 1)
        criadas = criar_parcelamento(self.db, base_tx_dict, parcelas=parcelas_count, commit=False)

        # Trilha de auditoria: grava evento 'created' para cada parcela criada
        effective_actor = actor or author_val
        for tx in criadas:
            diff = {
                "descricao": tx.descricao,
                "valor": str(tx.valor),
                "categoria": tx.categoria,
                "data": tx.data.isoformat() if tx.data else None,
                "parcela_num": tx.parcela_num,
                "parcela_total": tx.parcela_total,
            }
            self.event_repo.record_event(
                transaction_id=tx.id,
                action="created",
                actor=effective_actor,
                channel=channel_val,
                diff=diff,
            )

        return criadas

    def update_transaction(
        self,
        trans_id: int,
        update_data: dict[str, Any],
        actor: str | None = None,
        channel: str = "dashboard",
    ) -> Transaction:
        """Atualiza campos permitidos de uma transação existente e grava evento 'updated'."""
        existing = self.tx_repo.get_by_id(trans_id)
        if not existing:
            raise KeyError("Transação não encontrada")

        diff: dict[str, Any] = {}
        valid_types = ["receita", "despesa_fixa", "despesa_variavel"]
        if "tipo" in update_data and update_data["tipo"] is not None:
            new_tipo = str(update_data["tipo"]).lower()
            if new_tipo == "despesa":
                new_tipo = "despesa_variavel"
            if new_tipo not in valid_types:
                raise ValueError(
                    f"Tipo inválido. Escolha um dos seguintes: {', '.join(valid_types)}"
                )
            if existing.tipo != new_tipo:
                diff["tipo"] = {"old": existing.tipo, "new": new_tipo}
                existing.tipo = new_tipo

        if "valor" in update_data and update_data["valor"] is not None:
            new_val = to_decimal(update_data["valor"])
            if existing.valor != new_val:
                diff["valor"] = {"old": str(existing.valor), "new": str(new_val)}
                existing.valor = new_val

        if "categoria" in update_data and update_data["categoria"] is not None:
            cat_input = str(update_data["categoria"]).strip()
            canonical_name = resolve_canonical_name(cat_input)
            if not canonical_name:
                raise ValueError(f"Categoria '{cat_input}' não é válida.")
            norm_name = normalize_category_name(canonical_name)
            cat_db = self.cat_repo.get_by_normalized_name(norm_name)
            if not cat_db:
                cat_db = Category(
                    name=canonical_name,
                    normalized_name=norm_name,
                    tipo="receita" if existing.tipo == "receita" else "despesa",
                    ativo=True,
                )
                self.cat_repo.add(cat_db)
            if existing.category_id != cat_db.id:
                diff["categoria"] = {"old": existing.categoria, "new": cat_db.name}
                existing.categoria = cat_db.name
                existing.category_id = cat_db.id

        if "data" in update_data and update_data["data"] is not None:
            if existing.data != update_data["data"]:
                diff["data"] = {
                    "old": existing.data.isoformat() if existing.data else None,
                    "new": update_data["data"].isoformat()
                    if hasattr(update_data["data"], "isoformat")
                    else str(update_data["data"]),
                }
                existing.data = update_data["data"]

        if "descricao" in update_data and update_data["descricao"] is not None:
            new_desc = str(update_data["descricao"]).strip()
            if existing.descricao != new_desc:
                diff["descricao"] = {"old": existing.descricao, "new": new_desc}
                existing.descricao = new_desc

        if "author" in update_data and update_data["author"] is not None:
            new_author = str(update_data["author"]).strip() or None
            if existing.author != new_author:
                diff["author"] = {"old": existing.author, "new": new_author}
                existing.author = new_author
                if existing.author:
                    existing.source = existing.author

        if "channel" in update_data and update_data["channel"] is not None:
            existing.channel = update_data["channel"]

        if "source" in update_data and update_data["source"] is not None:
            existing.source = str(update_data["source"]).strip()

        if "vencimento" in update_data and update_data["vencimento"] is not None:
            existing.vencimento = str(update_data["vencimento"]).strip()

        if existing.recurrence_id is not None:
            existing.editado_manual = True

        if diff:
            self.event_repo.record_event(
                transaction_id=existing.id,
                action="updated",
                actor=actor or existing.author,
                channel=channel,
                diff=diff,
            )

        self.db.flush()
        return existing

    def delete_transaction(
        self,
        trans_id: int,
        escopo: str = "uma",
        actor: str | None = None,
        channel: str = "dashboard",
    ) -> int:
        """
        Soft delete de transação segundo o escopo ('uma', 'grupo' ou 'futuras').
        Define deleted_at e grava evento 'deleted'.
        Retorna a quantidade de registros alterados.
        """
        existing = self.tx_repo.get_by_id(trans_id)
        if not existing:
            raise KeyError("Transação não encontrada")

        now = utc_now_naive()
        alvos: list[Transaction] = []

        if existing.parcela_grupo_id and escopo in ["grupo", "futuras"]:
            if escopo == "grupo":
                alvos = list(self.tx_repo.list_by_group_id(existing.parcela_grupo_id))
            else:  # 'futuras'
                all_sibs = self.tx_repo.list_by_group_id(existing.parcela_grupo_id)
                current_num = existing.parcela_num or 1
                alvos = [s for s in all_sibs if (s.parcela_num or 1) >= current_num]
        else:
            alvos = [existing]

        for tx in alvos:
            tx.deleted_at = now
            self.event_repo.record_event(
                transaction_id=tx.id,
                action="deleted",
                actor=actor or tx.author,
                channel=channel,
                diff={
                    "escopo": escopo,
                    "descricao": tx.descricao,
                    "valor": str(tx.valor),
                },
            )

        self.db.flush()
        return len(alvos)

    def restore_transaction(
        self,
        trans_id: int,
        restore_grupo: bool = False,
        actor: str | None = None,
        channel: str = "whatsapp",
    ) -> list[Transaction]:
        """
        Restaura transação (ou grupo de parcelas) que sofreu soft delete.
        Define deleted_at = None e grava evento 'restored'.
        """
        tx = self.tx_repo.get_by_id(trans_id, include_deleted=True)
        if not tx or tx.deleted_at is None:
            raise KeyError("Transação não encontrada ou já ativa")

        alvos: list[Transaction] = []
        if restore_grupo and tx.parcela_grupo_id:
            all_in_group = self.tx_repo.list_by_group_id(tx.parcela_grupo_id, include_deleted=True)
            alvos = [t for t in all_in_group if t.deleted_at is not None]
        else:
            alvos = [tx]

        for item in alvos:
            item.deleted_at = None
            self.event_repo.record_event(
                transaction_id=item.id,
                action="restored",
                actor=actor or item.author,
                channel=channel,
                diff={"descricao": item.descricao, "valor": str(item.valor)},
            )

        self.db.flush()
        return alvos
