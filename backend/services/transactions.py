"""
backend/services/transactions.py

Casos de uso para gerenciamento de transações e parcelamentos.
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
from backend.repositories.transaction_repo import TransactionRepository
from backend.services.installments import criar_parcelamento
from backend.services.recurrences import ensure_recurrences


class TransactionService:
    def __init__(self, db: Session):
        self.db = db
        self.tx_repo = TransactionRepository(db)
        self.cat_repo = CategoryRepository(db)

    def list_transactions(
        self,
        mes: str | None = None,
        tipo: str | None = None,
        author: str | None = None,
        channel: str | None = None,
    ) -> Sequence[Transaction]:
        """
        Retorna lista de transações com filtros opcionais.
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

    def create_transaction(self, tx_data: dict[str, Any]) -> list[Transaction]:
        """
        Cria nova transação ou conjunto de parcelas.
        Valida tipos, canais e categorias.
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
        channel_val = str(tx_data.get("channel", "dashboard")) or "dashboard"
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
        return criar_parcelamento(self.db, base_tx_dict, parcelas=parcelas_count)

    def update_transaction(self, trans_id: int, update_data: dict[str, Any]) -> Transaction:
        """Atualiza campos permitidos de uma transação existente."""
        existing = self.tx_repo.get_by_id(trans_id)
        if not existing:
            raise KeyError("Transação não encontrada")

        valid_types = ["receita", "despesa_fixa", "despesa_variavel"]
        if "tipo" in update_data and update_data["tipo"] is not None:
            new_tipo = str(update_data["tipo"]).lower()
            if new_tipo == "despesa":
                new_tipo = "despesa_variavel"
            if new_tipo not in valid_types:
                raise ValueError(
                    f"Tipo inválido. Escolha um dos seguintes: {', '.join(valid_types)}"
                )
            existing.tipo = new_tipo

        if "valor" in update_data and update_data["valor"] is not None:
            existing.valor = to_decimal(update_data["valor"])

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
            existing.categoria = cat_db.name
            existing.category_id = cat_db.id

        if "data" in update_data and update_data["data"] is not None:
            existing.data = update_data["data"]

        if "descricao" in update_data and update_data["descricao"] is not None:
            existing.descricao = str(update_data["descricao"]).strip()

        if "author" in update_data and update_data["author"] is not None:
            existing.author = str(update_data["author"]).strip() or None
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

        self.db.flush()
        return existing

    def delete_transaction(self, trans_id: int, escopo: str = "uma") -> int:
        """
        Remove transação segundo o escopo ('uma', 'grupo' ou 'futuras').
        Retorna a quantidade de registros deletados.
        """
        existing = self.tx_repo.get_by_id(trans_id)
        if not existing:
            raise KeyError("Transação não encontrada")

        if existing.parcela_grupo_id and escopo in ["grupo", "futuras"]:
            if escopo == "grupo":
                siblings = self.tx_repo.list_by_group_id(existing.parcela_grupo_id)
            else:  # 'futuras'
                all_sibs = self.tx_repo.list_by_group_id(existing.parcela_grupo_id)
                current_num = existing.parcela_num or 1
                siblings = [s for s in all_sibs if (s.parcela_num or 1) >= current_num]

            count = len(siblings)
            for s in siblings:
                self.tx_repo.delete(s)
            return count

        self.tx_repo.delete(existing)
        return 1
