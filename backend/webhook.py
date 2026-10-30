import hmac
import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.models import ProcessedMessage
from backend.db.session import get_db
from backend.nlp import interpretar_mensagem  # noqa: F401
from backend.observability import MESSAGE_ID_CTX
from backend.parser import (  # noqa: F401
    extract_money_values,
    parse_financial_payload,
    parse_text_message,
)
from backend.services.message_processor import process_message, reprocess_due
from backend.timeutils import utc_now_naive

logger = logging.getLogger("fintrack.webhook")

webhook_router = APIRouter(prefix="/webhook", tags=["Webhook"])

# Limites de segurança rigorosos
MAX_BODY_BYTES = 1024 * 1024  # 1 MB
MAX_RAW_TEXT_LEN = 500  # 500 caracteres
MAX_AUDIO_BYTES = 2 * 1024 * 1024  # 2 MB


def mask_phone(phone: str | None) -> str:
    """Mascara telefone para logs (ex: 5511****9999). Nunca loga telefone em texto claro."""
    if not phone:
        return "[vazio]"
    clean = "".join(filter(str.isdigit, str(phone)))
    if len(clean) <= 4:
        return "****"
    if len(clean) <= 8:
        return f"{clean[:2]}****{clean[-2:]}"
    return f"{clean[:4]}****{clean[-4:]}"


def get_allowed_phone_mapping() -> dict[str, str]:
    """Retorna mapeamento de correspondência exata para telefones autorizados."""
    mapping = {}
    s = get_settings()
    phone_bruno = s.WHATSAPP_USER_BRUNO
    phone_leticia = s.WHATSAPP_USER_LETICIA

    for raw_p, name in [(phone_bruno, "Bruno"), (phone_leticia, "Letícia")]:
        clean = "".join(filter(str.isdigit, raw_p))
        if clean:
            mapping[clean] = name
            if clean.startswith("55") and len(clean) > 2:
                mapping[clean[2:]] = name
            elif not clean.startswith("55"):
                mapping["55" + clean] = name
    return mapping


def verify_webhook_secret(request: Request, token_in_path: str | None = None) -> None:
    """Valida a autenticidade de quem chama o webhook via hmac.compare_digest."""
    s = get_settings()
    expected_secret = s.WEBHOOK_SECRET.get_secret_value()
    if not expected_secret or len(expected_secret) < 32:
        logger.error("WEBHOOK_SECRET não configurado ou menor que 32 caracteres (fail-closed).")
        raise HTTPException(status_code=401, detail="Unauthorized")

    header_name = s.WEBHOOK_SECRET_HEADER
    provided_secret = None
    for k, v in request.headers.items():
        if k.lower() == header_name.lower():
            provided_secret = v
            break

    allow_path = s.WEBHOOK_ALLOW_PATH_TOKEN
    if not provided_secret and allow_path and token_in_path:
        provided_secret = token_in_path

    if not provided_secret or not hmac.compare_digest(
        provided_secret.strip(), expected_secret.strip()
    ):
        logger.warning("Falha de autenticação no webhook: segredo ausente ou inválido.")
        raise HTTPException(status_code=401, detail="Unauthorized")


async def extract_and_authorize_evolution_message(
    payload: dict, request: Request
) -> tuple[
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    bool,
    str | None,
    str | None,
    str | None,
]:
    """
    Extrai, valida e autoriza a mensagem do webhook com:
    - Limite de corpo HTTP <= 1MB
    - Falha fechada para GROUP_JID (503)
    - Rejeição estrita se remoteJid != GROUP_JID
    - Autorização estrita por igualdade exata do número do remetente
    - Limites de tamanho em texto (500 chars) e áudio (2MB)
    Retorna: (sender, user_name, raw_text, remote_jid, msg_id, is_audio, audio_base64, audio_mime, media_url)
    """
    if not isinstance(payload, dict):
        return None, None, None, None, None, False, None, None, None

    # Validação do tamanho do payload HTTP em bytes (<= 1MB)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                logger.warning(
                    f"Webhook rejeitado: tamanho do corpo excede o limite de 1MB ({content_length} bytes)."
                )
                raise HTTPException(status_code=413, detail="Payload Too Large")
        except ValueError:
            pass

    # Verifica tipo de evento da Evolution API
    event_type = payload.get("event")
    if event_type and event_type not in ["messages.upsert", "MESSAGES_UPSERT", "send.message"]:
        return None, None, None, None, None, False, None, None, None

    # Fail-closed estrito para WHATSAPP_GROUP_JID
    expected_group_jid = get_settings().WHATSAPP_GROUP_JID
    if not expected_group_jid:
        logger.error(
            "Configuração crítica ausente: WHATSAPP_GROUP_JID não foi definido no ambiente. Respondendo 503."
        )
        raise HTTPException(status_code=503, detail="Service Unavailable: Group JID not configured")

    raw_data = payload.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else payload
    if not isinstance(data, dict):
        data = {}

    raw_key = data.get("key") if isinstance(data, dict) else None
    if isinstance(raw_key, dict):
        key: dict[str, Any] = raw_key
    elif isinstance(payload.get("key"), dict):
        key = payload["key"]
    else:
        key = {}

    remote_jid = ""
    msg_id = None
    if key:
        remote_jid = key.get("remoteJid") or ""
        msg_id = key.get("id")
    if not remote_jid:
        remote_jid = data.get("remoteJid") or payload.get("remoteJid") or ""

    # Aceita exclusivamente mensagens vindas do grupo oficial configurado
    if remote_jid != expected_group_jid:
        logger.info(f"Mensagem fora do grupo oficial ({remote_jid}) ignorada.")
        return None, None, None, None, None, False, None, None, None

    # Identificação do remetente real
    is_from_me = False
    if key and key.get("fromMe") is True:
        is_from_me = True

    sender_raw = None
    if key:
        sender_raw = key.get("participantAlt") or key.get("participant") or key.get("remoteJid")
    if not sender_raw:
        sender_raw = (
            data.get("participantAlt")
            or data.get("participant")
            or data.get("sender")
            or data.get("remoteJid")
            or payload.get("sender")
        )

    if is_from_me:
        sender_raw = get_settings().WHATSAPP_USER_BRUNO or "Bruno"

    if sender_raw and isinstance(sender_raw, str):
        sender_num = sender_raw.split("@")[0].split(":")[0]
    else:
        sender_num = ""

    clean_sender = "".join(filter(str.isdigit, sender_num))

    # Autorização estrita por igualdade exata na allowlist
    allowed_mapping = get_allowed_phone_mapping()
    user_name = allowed_mapping.get(clean_sender)

    if not user_name:
        logger.warning(
            f"Mensagem rejeitada de remetente não autorizado: {mask_phone(clean_sender)}"
        )
        return None, None, None, None, None, False, None, None, None

    instance_name = payload.get("instance") or data.get("instance")
    logger.info(
        f"Webhook autorizado | Instância: {instance_name} | Remetente: {user_name} ({mask_phone(clean_sender)})"
    )

    # Extração de texto e mídia
    raw_text = None
    msg_obj = data.get("message")
    audio_base64 = None
    audio_mime = "audio/ogg"
    media_url = None
    is_audio = False

    if isinstance(msg_obj, dict):
        audio_msg = msg_obj.get("audioMessage")
        if isinstance(audio_msg, dict):
            is_audio = True
            audio_mime = audio_msg.get("mimetype") or "audio/ogg"
            audio_base64 = audio_msg.get("base64") or data.get("base64")
            media_url = audio_msg.get("url") or audio_msg.get("mediaUrl") or data.get("mediaUrl")

            # Validação rápida de tamanho se base64 estiver presente
            if audio_base64 and isinstance(audio_base64, str):
                raw_b64 = audio_base64.split(",", 1)[1] if "," in audio_base64 else audio_base64
                # Base64 length * 3/4 approximates byte size
                approx_bytes = (len(raw_b64) * 3) // 4
                if approx_bytes > MAX_AUDIO_BYTES:
                    logger.warning(
                        f"Áudio de {user_name} rejeitado: ~{approx_bytes} bytes excede limite de {MAX_AUDIO_BYTES} bytes."
                    )
                    return (
                        clean_sender,
                        user_name,
                        None,
                        remote_jid,
                        msg_id,
                        False,
                        None,
                        None,
                        None,
                    )

        raw_text = (
            msg_obj.get("conversation")
            or (
                msg_obj.get("extendedTextMessage", {}).get("text")
                if isinstance(msg_obj.get("extendedTextMessage"), dict)
                else None
            )
            or (
                msg_obj.get("imageMessage", {}).get("caption")
                if isinstance(msg_obj.get("imageMessage"), dict)
                else None
            )
            or (
                msg_obj.get("videoMessage", {}).get("caption")
                if isinstance(msg_obj.get("videoMessage"), dict)
                else None
            )
        )

    # Ignora mensagens automáticas do próprio Atlas
    if raw_text and (
        "*Atlas:*" in raw_text or "🎙️" in raw_text or "Teste de conexão Atlas" in raw_text
    ):
        logger.info("Ignorando mensagem automática gerada pelo próprio Atlas.")
        return None, None, None, None, msg_id, False, None, None, None

    if not raw_text and not is_audio:
        raw_text = (
            data.get("text") or data.get("body") or payload.get("text") or payload.get("message")
        )
        if isinstance(raw_text, dict):
            raw_text = raw_text.get("conversation") or raw_text.get("text")

    if raw_text and isinstance(raw_text, str):
        raw_text = raw_text.strip()
        if len(raw_text) > MAX_RAW_TEXT_LEN:
            raw_text = raw_text[:MAX_RAW_TEXT_LEN]
    else:
        raw_text = None

    return (
        clean_sender,
        user_name,
        raw_text,
        remote_jid,
        msg_id,
        is_audio,
        audio_base64,
        audio_mime,
        media_url,
    )


async def handle_webhook_event(
    payload: dict,
    request: Request,
    db: Session,
    token_in_path: str | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """Lógica central de ingestão assíncrona e idempotente do webhook."""
    # 1. Autenticação estrita fail-closed
    verify_webhook_secret(request, token_in_path)

    # 2. Extração, autorização e validação de limites
    (
        sender,
        user_name,
        raw_text,
        remote_jid,
        msg_id,
        is_audio,
        audio_base64,
        audio_mime,
        media_url,
    ) = await extract_and_authorize_evolution_message(payload, request)

    if not user_name:
        return {"status": "ignored", "detail": "Evento ignorado ou não autorizado"}

    if not msg_id:
        msg_id = str(uuid.uuid4())

    # Registra ID mascarado no contexto de logs
    masked_msg_id = msg_id[:4] + "***" + msg_id[-4:] if len(msg_id) > 8 else "***"
    MESSAGE_ID_CTX.set(masked_msg_id)

    logger.info("webhook_received", extra={"has_user": bool(user_name), "is_audio": is_audio})

    # 3. Verificação de conteúdo financeiro
    cand_val, all_cands, _ = extract_money_values(raw_text or "")
    has_candidate_value = (cand_val is not None) or bool(all_cands)

    # Mensagens de texto sem nenhum número financeiro -> status ignored direto
    if not is_audio and not has_candidate_value:
        ignored_record = ProcessedMessage(
            message_id=msg_id,
            status="ignored",
            attempts=0,
            received_at=utc_now_naive(),
            processed_at=utc_now_naive(),
            replied=False,
            payload=None,
        )
        try:
            db.add(ignored_record)
            db.commit()
        except IntegrityError:
            db.rollback()
            return {"status": "duplicate", "message_id": msg_id}

        return {
            "status": "ignored",
            "detail": "Nenhuma despesa identificada na mensagem recebida ou evento irrelevante",
            "sender": mask_phone(sender),
            "user": user_name,
        }

    # 4. Mensagem com potencial financeiro -> persistência recebida e agendamento
    minimal_payload = {
        "raw_text": raw_text,
        "has_audio": is_audio,
        "audio_mime": audio_mime,
        "audio_base64": audio_base64,
        "media_url": media_url,
        "sender": sender,
        "user_name": user_name,
        "remote_jid": remote_jid,
        "instance_name": payload.get("instance"),
        "raw_payload": payload if not raw_text and not is_audio else None,
    }

    new_msg = ProcessedMessage(
        message_id=msg_id,
        status="received",
        attempts=0,
        received_at=utc_now_naive(),
        replied=False,
        payload=minimal_payload,
    )

    try:
        db.add(new_msg)
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info(
            "webhook_duplicate_ignored",
            extra={"message_id_short": msg_id[:8] if len(msg_id) >= 8 else msg_id},
        )
        return {"status": "duplicate", "message_id": msg_id}

    # Agenda worker em background
    if background_tasks is not None:
        background_tasks.add_task(process_message, msg_id)
        background_tasks.add_task(reprocess_due)
    else:
        process_message(msg_id, db=db)

    return {
        "status": "received",
        "message_id": msg_id,
        "user": user_name,
        "sender": mask_phone(sender),
    }


@webhook_router.post("/whatsapp")
@webhook_router.post("")
async def receive_webhook(
    request: Request,
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Receptor oficial de webhook com autenticação por header."""
    return await handle_webhook_event(payload, request, db, background_tasks=background_tasks)


@webhook_router.post("/whatsapp/{token}")
async def receive_webhook_path_token(
    token: str,
    request: Request,
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Receptor alternativo com token no path para gateways que não suportam headers customizados."""
    return await handle_webhook_event(
        payload, request, db, token_in_path=token, background_tasks=background_tasks
    )
