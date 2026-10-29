"""
backend/services/message_processor.py

Serviço de processamento e criação de transações a partir de mensagens recebidas
(WhatsApp, áudio, texto, recorrências e parcelas).
"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from backend.atlas import format_atlas_confirmation
from backend.categories import normalize_category_name, resolve_canonical_name
from backend.dates_and_money import to_decimal
from backend.db.models import Category, Recurrence, Transaction
from backend.repositories.category_repo import CategoryRepository
from backend.repositories.transaction_repo import TransactionRepository
from backend.services.installments import calcular_valores_parcelamento, criar_parcelamento
from backend.services.summary import SummaryService

logger = logging.getLogger("fintrack.message_processor")


class MessageProcessingService:
    def __init__(self, db: Session):
        self.db = db

    def process_parsed_message(
        self,
        parsed_data: dict,
        user_name: str,
        channel_type: str,
        sender_phone: str | None = None,
        remote_jid: str | None = None,
        raw_text: str | None = None,
    ) -> dict:
        """Cria transação única, parcelamento ou recorrência e envia confirmação do Atlas."""
        parcelas = max(1, int(parsed_data.get("parcelas", 1)))
        base_data = date.fromisoformat(str(parsed_data["data"]))
        created_ids = []

        raw_categoria = parsed_data.get("categoria", "Outros")
        canonical_nome = resolve_canonical_name(raw_categoria) or "Outros"
        norm_cat = normalize_category_name(canonical_nome)

        cat_db = self.db.query(Category).filter(Category.normalized_name == norm_cat).first()
        if not cat_db:
            cat_db = self.db.query(Category).filter(Category.normalized_name == "outros").first()
            if not cat_db:
                cat_db = Category(
                    name=canonical_nome, normalized_name=norm_cat, tipo="despesa", ativo=True
                )
                self.db.add(cat_db)
                self.db.commit()
                self.db.refresh(cat_db)

        cat_id = cat_db.id
        cat_nome = cat_db.name

        base_tx_dict = {
            "tipo": parsed_data["tipo"],
            "valor": to_decimal(parsed_data["valor"]),
            "categoria": cat_nome,
            "category_id": cat_id,
            "data": base_data,
            "descricao": parsed_data["descricao"],
            "author": user_name,
            "channel": channel_type,
            "source": parsed_data.get("source", user_name),
            "vencimento": parsed_data.get("vencimento"),
        }

        raw_lower = (raw_text or "").lower()
        is_despesa_fixa = parsed_data["tipo"] == "despesa_fixa"
        is_receita_recorrente = parsed_data["tipo"] == "receita" and any(
            k in raw_lower for k in ["todo mês", "todo mes", "mensal", "fixo", "fixa"]
        )
        is_recorrente = is_despesa_fixa or is_receita_recorrente
        primeiro_dia_mes = base_data.replace(day=1)

        if is_recorrente:
            rec_tipo = "despesa_fixa" if is_despesa_fixa else "receita"
            rec = Recurrence(
                tipo=rec_tipo,
                descricao=parsed_data["descricao"],
                valor=to_decimal(parsed_data["valor"]),
                category_id=cat_id,
                author=user_name,
                dia_do_mes=base_data.day,
                inicio=primeiro_dia_mes,
                fim=None,
                ativo=True,
            )
            self.db.add(rec)
            self.db.commit()
            self.db.refresh(rec)

            t_item = Transaction(
                tipo=rec_tipo,
                valor=to_decimal(parsed_data["valor"]),
                categoria=cat_nome,
                category_id=cat_id,
                data=base_data,
                descricao=parsed_data["descricao"],
                author=user_name,
                channel=channel_type,
                source=parsed_data.get("source", user_name),
                vencimento=f"Dia {base_data.day}" if rec_tipo == "despesa_fixa" else None,
                recurrence_id=rec.id,
                competencia=primeiro_dia_mes,
                editado_manual=False,
            )
            self.db.add(t_item)
            self.db.commit()
            self.db.refresh(t_item)
            created_ids = [t_item.id]
            val_parcela_unit = to_decimal(parsed_data["valor"])
            total_geral = val_parcela_unit
        else:
            created_transactions = criar_parcelamento(self.db, base_tx_dict, parcelas=parcelas)
            created_ids = [t.id for t in created_transactions]

            valores_p, total_geral = calcular_valores_parcelamento(
                to_decimal(parsed_data["valor"]), parcelas
            )
            val_parcela_unit = valores_p[0]

        saldo_atualizado = None
        try:
            mes_iso = base_data.strftime("%Y-%m")
            sum_svc = SummaryService(
                transaction_repo=TransactionRepository(self.db),
                category_repo=CategoryRepository(self.db),
            )
            summary_res = sum_svc.get_metrics(mes=mes_iso)
            saldo_atualizado = summary_res.get("saldo_livre")
        except Exception as e:
            logger.debug(f"Não foi possível calcular saldo para o Atlas: {e}")

        desc_feedback = (
            f"{parsed_data['descricao']} (recorrente)"
            if is_recorrente
            else parsed_data["descricao"]
        )

        atlas_reply = format_atlas_confirmation(
            user_name=user_name,
            item_desc=desc_feedback,
            valor=float(val_parcela_unit),
            parcelas=parcelas,
            saldo_livre=saldo_atualizado,
            valor_total=float(total_geral) if parcelas > 1 else None,
        )

        if remote_jid:
            import backend.atlas as atlas_module

            atlas_module.send_whatsapp_message(remote_jid, atlas_reply)

        return {
            "status": "success",
            "id": created_ids[0] if created_ids else None,
            "ids": created_ids,
            "parcelas": parcelas,
            "sender": sender_phone,
            "user": user_name,
            "atlas_response": atlas_reply,
            "transaction": parsed_data,
        }
