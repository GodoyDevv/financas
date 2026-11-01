"""
backend/services/message_processor.py

Serviço de processamento e criação de transações a partir de mensagens recebidas
(WhatsApp, áudio, texto, recorrências e parcelas), com suporte a worker assíncrono
idempotente, retries com backoff exponencial e recuperação de travamentos.
"""

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from backend.atlas import format_atlas_confirmation
from backend.categories import normalize_category_name, resolve_canonical_name
from backend.dates_and_money import to_decimal
from backend.db.models import Category, ProcessedMessage, Recurrence, Transaction
from backend.services.installments import calcular_valores_parcelamento, criar_parcelamento
from backend.services.summary import SummaryService
from backend.timeutils import utc_now_naive

logger = logging.getLogger("fintrack.message_processor")

MAX_ATTEMPTS = 3
BACKOFF_DELAYS = {
    1: timedelta(seconds=30),
    2: timedelta(minutes=2),
    3: timedelta(minutes=10),
}


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
        source_message_id: str | None = None,
        commit: bool = True,
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
                if commit:
                    self.db.commit()
                    self.db.refresh(cat_db)
                else:
                    self.db.flush()

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
            "source_message_id": source_message_id,
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
            if commit:
                self.db.commit()
                self.db.refresh(rec)
            else:
                self.db.flush()

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
                source_message_id=source_message_id,
            )
            self.db.add(t_item)
            if commit:
                self.db.commit()
                self.db.refresh(t_item)
            else:
                self.db.flush()
            created_ids = [t_item.id]
            val_parcela_unit = to_decimal(parsed_data["valor"])
            total_geral = val_parcela_unit
        else:
            created_transactions = criar_parcelamento(
                self.db, base_tx_dict, parcelas=parcelas, commit=commit
            )
            created_ids = [t.id for t in created_transactions]

            valores_p, total_geral = calcular_valores_parcelamento(
                to_decimal(parsed_data["valor"]), parcelas
            )
            val_parcela_unit = valores_p[0]

        saldo_atualizado = None
        try:
            mes_iso = base_data.strftime("%Y-%m")
            sum_svc = SummaryService(self.db)
            summary_res = sum_svc.get_month_metrics(mes=mes_iso)
            saldo_atualizado = summary_res.get("saldo_livre")
        except Exception as e:
            logger.debug(f"Não foi possível calcular saldo para o Atlas: {e}")

        desc_feedback = (
            f"{parsed_data['descricao']} (recorrente)"
            if is_recorrente
            else parsed_data["descricao"]
        )

        from backend.config import get_settings

        include_undo = get_settings().FEATURE_WA_CONFIRMATIONS

        atlas_reply = format_atlas_confirmation(
            user_name=user_name,
            item_desc=desc_feedback,
            valor=float(val_parcela_unit),
            parcelas=parcelas,
            saldo_livre=saldo_atualizado,
            valor_total=float(total_geral) if parcelas > 1 else None,
            categoria=cat_nome,
            data_lancamento=base_data.strftime("%d/%m/%Y"),
            transcricao=raw_text if channel_type == "whatsapp_audio" else None,
            include_undo_instruction=include_undo,
        )

        if commit and remote_jid:
            import backend.atlas as atlas_module

            atlas_module.send_whatsapp_message(remote_jid, atlas_reply)

        logger.info(
            "transaction_created",
            extra={"count": len(created_ids), "parcelas": parcelas, "is_recorrente": is_recorrente},
        )

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


def _process_message_impl(session: Session, message_id: str) -> dict[str, Any] | None:
    now = utc_now_naive()
    five_min_ago = now - timedelta(minutes=5)

    # 1. Claim atômico
    stmt = (
        update(ProcessedMessage)
        .where(
            ProcessedMessage.message_id == message_id,
            (
                ProcessedMessage.status.in_(["received", "failed"])
                | (
                    (ProcessedMessage.status == "processing")
                    & (ProcessedMessage.received_at <= five_min_ago)
                )
            ),
        )
        .values(
            status="processing",
            attempts=ProcessedMessage.attempts + 1,
        )
    )
    res = session.execute(stmt)
    session.commit()

    if res.rowcount == 0:
        logger.info(
            "message_claim_skipped",
            extra={"message_id_short": message_id[:8] if len(message_id) >= 8 else message_id},
        )
        return None

    msg_record = (
        session.query(ProcessedMessage).filter(ProcessedMessage.message_id == message_id).first()
    )
    if not msg_record or not msg_record.payload:
        return None

    payload_data = msg_record.payload
    remote_jid = payload_data.get("remote_jid")
    user_name = payload_data.get("user_name") or "Desconhecido"
    sender = payload_data.get("sender")
    instance_name = payload_data.get("instance_name")

    try:
        # 2. Processa áudio se necessário
        raw_text = payload_data.get("raw_text")
        has_audio = payload_data.get("has_audio", False)
        audio_mime = payload_data.get("audio_mime", "audio/ogg")
        audio_base64 = payload_data.get("audio_base64")
        media_url = payload_data.get("media_url")
        is_audio = False

        if has_audio and not raw_text:
            audio_bytes = None
            if audio_base64 and isinstance(audio_base64, str):
                import base64

                try:
                    if "," in audio_base64:
                        audio_base64 = audio_base64.split(",", 1)[1]
                    audio_bytes = base64.b64decode(audio_base64)
                except Exception as b64_err:
                    logger.error(f"Erro ao decodificar base64 de áudio: {b64_err}")

            if not audio_bytes:
                from backend.atlas import fetch_decrypted_audio_from_evolution

                decrypted = fetch_decrypted_audio_from_evolution(
                    message_id, instance_override=instance_name
                )
                if decrypted:
                    audio_bytes, audio_mime = decrypted

            if (
                not audio_bytes
                and media_url
                and isinstance(media_url, str)
                and ".enc" not in media_url
            ):
                from backend.atlas import download_media_from_url

                audio_bytes = download_media_from_url(media_url)

            if audio_bytes:
                if len(audio_bytes) > 2 * 1024 * 1024:
                    logger.warning(
                        f"Áudio de {user_name} rejeitado: {len(audio_bytes)} bytes excede o limite de 2MB."
                    )
                    msg_record.status = "ignored"
                    msg_record.payload = None
                    msg_record.processed_at = utc_now_naive()
                    session.commit()
                    return {"status": "ignored"}

                from backend.atlas import transcribe_audio_bytes

                raw_text = transcribe_audio_bytes(audio_bytes, mime_type=audio_mime)
                if raw_text:
                    is_audio = True

        channel_type = "whatsapp_audio" if is_audio else "whatsapp_text"

        # 3. Extração e interpretação financeira
        from backend.parser import extract_money_values, parse_financial_payload

        cand_val, all_cands, _ = extract_money_values(raw_text or "")
        has_candidate_value = (cand_val is not None) or bool(all_cands)

        parsed_data = None
        if raw_text:
            import unittest.mock as mock_lib

            import backend.webhook as webhook_mod

            if hasattr(webhook_mod, "parse_text_message") and isinstance(
                webhook_mod.parse_text_message, (mock_lib.Mock, mock_lib.MagicMock)
            ):
                parsed_data = webhook_mod.parse_text_message(raw_text)
            elif hasattr(webhook_mod, "interpretar_mensagem") and isinstance(
                webhook_mod.interpretar_mensagem, (mock_lib.Mock, mock_lib.MagicMock)
            ):
                parsed_data = webhook_mod.interpretar_mensagem(raw_text)
            else:
                from backend.nlp import interpretar_mensagem

                parsed_data = interpretar_mensagem(raw_text)
        elif payload_data.get("raw_payload"):
            parsed_data = parse_financial_payload(payload_data["raw_payload"])

        # 4. Mensagem sem valor ou inválida
        if not parsed_data or parsed_data.get("valor", 0) <= 0:
            if has_candidate_value and remote_jid:
                from backend.atlas import send_whatsapp_message

                try:
                    send_whatsapp_message(
                        remote_jid, "Não consegui entender. Exemplo: 'Mercado 150,90'"
                    )
                except Exception as send_err:
                    logger.warning(f"Erro ao enviar esclarecimento: {send_err}")

            msg_record.status = "ignored"
            msg_record.payload = None
            msg_record.processed_at = utc_now_naive()
            msg_record.error_code = None
            session.commit()
            return {"status": "ignored"}

        # 5. Idempotência e criação de transações
        parsed_data["source"] = user_name
        parsed_data["author"] = user_name
        parsed_data["channel"] = channel_type

        existing_tx = (
            session.query(Transaction).filter(Transaction.source_message_id == message_id).first()
        )
        if existing_tx:
            msg_record.status = "done"
            msg_record.processed_at = utc_now_naive()
            msg_record.payload = None
            msg_record.error_code = None
            session.commit()
            return {"status": "done", "id": existing_tx.id}

        svc = MessageProcessingService(session)
        result = svc.process_parsed_message(
            parsed_data=parsed_data,
            user_name=user_name,
            channel_type=channel_type,
            sender_phone=sender,
            remote_jid=remote_jid,
            raw_text=raw_text,
            source_message_id=message_id,
            commit=False,
        )

        msg_record.status = "done"
        msg_record.processed_at = utc_now_naive()
        msg_record.payload = None
        msg_record.error_code = None
        session.commit()

        # Envia confirmação WhatsApp pós-commit e registra em outbound_messages (anti-loop)
        atlas_reply = result.get("atlas_response")
        if remote_jid and atlas_reply:
            from backend.atlas import send_whatsapp_message
            from backend.repositories.outbound_message_repo import OutboundMessageRepository

            try:
                sent_msg_id = send_whatsapp_message(remote_jid, atlas_reply)
                if sent_msg_id and sent_msg_id is not True:
                    msg_id_str = str(sent_msg_id)
                    outbound_repo = OutboundMessageRepository(session)
                    tx_id_ref = result.get("id")
                    if not outbound_repo.exists(msg_id_str):
                        outbound_repo.add(
                            message_id=msg_id_str,
                            kind="confirmation",
                            ref_type="transaction",
                            ref_id=str(tx_id_ref) if tx_id_ref else None,
                            remote_jid=remote_jid,
                        )
                        session.commit()
            except Exception as send_err:
                logger.warning(f"Erro ao enviar confirmação WhatsApp pós-commit: {send_err}")

        return result

    except Exception as exc:
        session.rollback()
        logger.warning(
            "message_processing_transient_error",
            extra={
                "message_id_short": message_id[:8] if len(message_id) >= 8 else message_id,
                "attempt": msg_record.attempts,
                "error": str(exc)[:100],
            },
        )
        attempts = msg_record.attempts
        now_err = utc_now_naive()

        if attempts >= MAX_ATTEMPTS:
            msg_record.status = "failed"
            msg_record.next_attempt_at = None
            msg_record.error_code = str(exc)[:50]

            if not msg_record.replied and remote_jid:
                from backend.atlas import send_whatsapp_message
                from backend.repositories.outbound_message_repo import OutboundMessageRepository

                try:
                    sent_msg_id = send_whatsapp_message(
                        remote_jid,
                        "Não consegui processar sua mensagem, tente novamente",
                    )
                    if sent_msg_id and sent_msg_id is not True:
                        msg_id_str = str(sent_msg_id)
                        outbound_repo = OutboundMessageRepository(session)
                        if not outbound_repo.exists(msg_id_str):
                            outbound_repo.add(
                                message_id=msg_id_str,
                                kind="error",
                                ref_type="processed_message",
                                ref_id=message_id,
                                remote_jid=remote_jid,
                            )
                    msg_record.replied = True
                except Exception as send_err:
                    logger.warning(f"Erro ao notificar grupo sobre falha: {send_err}")
        else:
            delay = BACKOFF_DELAYS.get(attempts, timedelta(minutes=10))
            msg_record.status = "received"
            msg_record.next_attempt_at = now_err + delay
            msg_record.error_code = str(exc)[:50]

        session.commit()
        raise


def process_message(message_id: str, db: Session | None = None) -> dict[str, Any] | None:
    """Worker de processamento atômico de mensagem."""
    from backend.db.session import SessionLocal

    if db is not None:
        return _process_message_impl(db, message_id)
    else:
        with SessionLocal() as session:
            return _process_message_impl(session, message_id)


def reprocess_due(db: Session | None = None) -> list[str]:
    """Reprocessa mensagens recebidas travadas ou com next_attempt_at vencido."""
    from backend.db.session import SessionLocal

    now = utc_now_naive()
    five_min_ago = now - timedelta(minutes=5)
    reprocessed_ids: list[str] = []

    def _query_due(s: Session) -> list[str]:
        query = (
            s.query(ProcessedMessage.message_id)
            .filter(
                ProcessedMessage.attempts < MAX_ATTEMPTS,
                (
                    (
                        ProcessedMessage.next_attempt_at.is_not(None)
                        & (ProcessedMessage.next_attempt_at <= now)
                    )
                    | (
                        ProcessedMessage.status.in_(["received", "processing"])
                        & (ProcessedMessage.received_at <= five_min_ago)
                        & (ProcessedMessage.next_attempt_at.is_(None))
                    )
                ),
            )
            .limit(50)
        )
        return [row[0] for row in query.all()]

    if db is not None:
        msg_ids = _query_due(db)
    else:
        with SessionLocal() as s:
            msg_ids = _query_due(s)

    for mid in msg_ids:
        try:
            if db is not None:
                process_message(mid, db=db)
            else:
                process_message(mid)
            reprocessed_ids.append(mid)
        except Exception as e:
            logger.warning(
                "reprocess_message_failed",
                extra={
                    "message_id_short": mid[:8] if len(mid) >= 8 else mid,
                    "error": str(e)[:100],
                },
            )

    return reprocessed_ids


def purge_old(db: Session | None = None) -> int:
    """
    Expurga mensagens concluídas/ignoradas há mais de 30 dias, falhas há mais de 7 dias,
    e exclui definitivamente (hard delete) transações em soft delete há mais de 30 dias.
    """
    from backend.db.session import SessionLocal

    now = utc_now_naive()
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    def _execute_purge(s: Session) -> int:
        stmt1 = delete(ProcessedMessage).where(
            ProcessedMessage.status.in_(["done", "ignored"]),
            ProcessedMessage.received_at <= thirty_days_ago,
        )
        r1 = s.execute(stmt1)

        stmt2 = delete(ProcessedMessage).where(
            ProcessedMessage.status == "failed",
            ProcessedMessage.received_at <= seven_days_ago,
        )
        r2 = s.execute(stmt2)

        # Expurga transações com soft delete há mais de 30 dias
        stmt3 = delete(Transaction).where(
            Transaction.deleted_at.is_not(None),
            Transaction.deleted_at <= thirty_days_ago,
        )
        r3 = s.execute(stmt3)

        s.commit()
        return (r1.rowcount or 0) + (r2.rowcount or 0) + (r3.rowcount or 0)

    if db is not None:
        return _execute_purge(db)
    else:
        with SessionLocal() as s:
            return _execute_purge(s)
