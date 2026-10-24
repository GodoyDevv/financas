import os
import hmac
import logging
from typing import Optional, Tuple
from fastapi import APIRouter, HTTPException, Depends, Request, Header
from sqlalchemy.orm import Session
from .database import get_db
from .models import Transaction
from datetime import date
from .parser import parse_financial_payload, parse_text_message, add_months
from .dates_and_money import to_decimal, today_br
from .models import Transaction, Category
from .categories import normalize_category_name, resolve_canonical_name

logger = logging.getLogger("fintrack.webhook")

webhook_router = APIRouter(prefix="/webhook", tags=["Webhook"])

# Limites de segurança rigorosos
MAX_BODY_BYTES = 1024 * 1024  # 1 MB
MAX_RAW_TEXT_LEN = 500         # 500 caracteres
MAX_AUDIO_BYTES = 2 * 1024 * 1024  # 2 MB

# Deduplicação em memória pós-autorização (máximo 1000 registros para rotação de memória)
PROCESSED_MESSAGE_IDS = set()

def mask_phone(phone: Optional[str]) -> str:
    """Mascara telefone para logs (ex: 5511****9999). Nunca loga telefone em texto claro."""
    if not phone:
        return "[vazio]"
    clean = "".join(filter(str.isdigit, str(phone)))
    if len(clean) <= 4:
        return "****"
    if len(clean) <= 8:
        return f"{clean[:2]}****{clean[-2:]}"
    return f"{clean[:4]}****{clean[-4:]}"

def get_allowed_phone_mapping():
    """
    Retorna mapeamento de correspondência exata para telefones autorizados.
    Aceita a forma com e sem DDI 55:
    Se configurado 5511999998888 -> aceita '5511999998888' e '11999998888'.
    Se configurado 11999998888 -> aceita '11999998888' e '5511999998888'.
    """
    mapping = {}
    phone_bruno = os.getenv("WHATSAPP_USER_BRUNO", "")
    phone_leticia = os.getenv("WHATSAPP_USER_LETICIA", "")

    for raw_p, name in [(phone_bruno, "Bruno"), (phone_leticia, "Letícia")]:
        clean = "".join(filter(str.isdigit, raw_p))
        if clean:
            mapping[clean] = name
            if clean.startswith("55") and len(clean) > 2:
                mapping[clean[2:]] = name
            elif not clean.startswith("55"):
                mapping["55" + clean] = name
    return mapping

def verify_webhook_secret(
    request: Request,
    token_in_path: Optional[str] = None
):
    """
    Valida a autenticidade de quem chama o webhook via hmac.compare_digest.
    Falha fechada com 401 genérico sem detalhes.
    Ordem de verificação:
    1. Header configurável (WEBHOOK_SECRET_HEADER, padrão X-Webhook-Secret)
    2. Se WEBHOOK_ALLOW_PATH_TOKEN == "1" e fornecido via rota /webhook/whatsapp/{token}
    """
    expected_secret = os.getenv("WEBHOOK_SECRET", "")
    if not expected_secret or len(expected_secret) < 32:
        logger.error("WEBHOOK_SECRET não configurado ou menor que 32 caracteres (fail-closed).")
        raise HTTPException(status_code=401, detail="Unauthorized")

    header_name = os.getenv("WEBHOOK_SECRET_HEADER", "X-Webhook-Secret")
    # Busca cabeçalho ignorando maiúsculas/minúsculas
    provided_secret = None
    for k, v in request.headers.items():
        if k.lower() == header_name.lower():
            provided_secret = v
            break

    allow_path = os.getenv("WEBHOOK_ALLOW_PATH_TOKEN", "0").strip() == "1"
    if not provided_secret and allow_path and token_in_path:
        provided_secret = token_in_path

    if not provided_secret or not hmac.compare_digest(provided_secret.strip(), expected_secret.strip()):
        logger.warning("Falha de autenticação no webhook: segredo ausente ou inválido.")
        raise HTTPException(status_code=401, detail="Unauthorized")


async def extract_and_authorize_evolution_message(
    payload: dict,
    request: Request
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extrai, valida e autoriza a mensagem do webhook com:
    - Limite de corpo HTTP <= 1MB
    - Falha fechada para GROUP_JID (503)
    - Rejeição estrita se remoteJid != GROUP_JID
    - Autorização estrita por igualdade exata do número do remetente (sem pushName fallback, sem endswith parcial)
    - Limites de tamanho em texto (500 chars) e áudio (2MB) antes de invocar transcrição/Gemini
    - Retorna: (sender, user_name, raw_text, remote_jid, msg_id_para_dedupe)
    """
    if not isinstance(payload, dict):
        return None, None, None, None, None

    # Validação do tamanho do payload HTTP em bytes (<= 1MB)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                logger.warning(f"Webhook rejeitado: tamanho do corpo excede o limite de 1MB ({content_length} bytes).")
                raise HTTPException(status_code=413, detail="Payload Too Large")
        except ValueError:
            pass

    # Verifica tipo de evento da Evolution API
    event_type = payload.get("event")
    if event_type and event_type not in ["messages.upsert", "MESSAGES_UPSERT", "send.message"]:
        return None, None, None, None, None

    # Fail-closed estrito para WHATSAPP_GROUP_JID:
    # Sem GROUP_JID configurado, a rota responde 503 Service Unavailable
    expected_group_jid = os.getenv("WHATSAPP_GROUP_JID", "").strip()
    if not expected_group_jid:
        logger.error("Configuração crítica ausente: WHATSAPP_GROUP_JID não foi definido no ambiente. Respondendo 503.")
        raise HTTPException(status_code=503, detail="Service Unavailable: Group JID not configured")

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    key = data.get("key") or payload.get("key")

    remote_jid = ""
    msg_id = None
    if isinstance(key, dict):
        remote_jid = key.get("remoteJid") or ""
        msg_id = key.get("id")
    if not remote_jid:
        remote_jid = data.get("remoteJid") or payload.get("remoteJid") or ""

    # TRAVA ESTRITA: Aceita EXCLUSIVAMENTE mensagens vindas do grupo oficial configurado
    if remote_jid != expected_group_jid:
        logger.info(f"Mensagem fora do grupo oficial ({remote_jid}) ignorada.")
        return None, None, None, None, None, False

    # Verifica se já foi processado anteriormente (apenas leitura do cache; registro ocorre DEPOIS da autorização)
    if msg_id and msg_id in PROCESSED_MESSAGE_IDS:
        logger.info(f"Mensagem {msg_id} já processada anteriormente. Ignorando evento duplicado.")
        return None, None, None, None, None, False

    # Identificação do remetente real
    is_from_me = False
    if isinstance(key, dict) and key.get("fromMe") is True:
        is_from_me = True

    sender_raw = None
    if isinstance(key, dict):
        sender_raw = key.get("participantAlt") or key.get("participant") or key.get("remoteJid")
    if not sender_raw:
        sender_raw = data.get("participantAlt") or data.get("participant") or data.get("sender") or data.get("remoteJid") or payload.get("sender")

    # Tratamento caso fromMe seja True
    if is_from_me:
        sender_raw = os.getenv("WHATSAPP_USER_BRUNO", "") or "Bruno"

    if sender_raw and isinstance(sender_raw, str):
        # Ex: 5511999998888@s.whatsapp.net:0 -> 5511999998888
        sender_num = sender_raw.split("@")[0].split(":")[0]
    else:
        sender_num = ""

    clean_sender = "".join(filter(str.isdigit, sender_num))

    # Autorização estrita por IGUALDADE EXATA na allowlist (sem pushName fallback)
    allowed_mapping = get_allowed_phone_mapping()
    user_name = allowed_mapping.get(clean_sender)

    if not user_name:
        logger.warning(f"Mensagem rejeitada de remetente não autorizado: {mask_phone(clean_sender)}")
        return None, None, None, None, None, False

    # Mover registro de deduplicação para DEPOIS de autenticado e autorizado
    msg_id_to_record = msg_id

    instance_name = payload.get("instance") or data.get("instance")
    logger.info(f"Webhook autorizado | Instância: {instance_name} | Remetente: {user_name} ({mask_phone(clean_sender)})")

    # Extração de texto e mídia
    raw_text = None
    msg_obj = data.get("message")
    audio_bytes = None
    audio_mime = "audio/ogg"

    if isinstance(msg_obj, dict):
        audio_msg = msg_obj.get("audioMessage")
        if isinstance(audio_msg, dict):
            audio_mime = audio_msg.get("mimetype") or "audio/ogg"
            b64_data = audio_msg.get("base64") or data.get("base64")
            media_url = audio_msg.get("url") or audio_msg.get("mediaUrl") or data.get("mediaUrl")

            if b64_data and isinstance(b64_data, str):
                import base64
                try:
                    if "," in b64_data:
                        b64_data = b64_data.split(",", 1)[1]
                    audio_bytes = base64.b64decode(b64_data)
                except Exception as e:
                    logger.error(f"Erro ao decodificar base64 de áudio: {e}")

            if not audio_bytes and msg_id:
                from .atlas import fetch_decrypted_audio_from_evolution
                decrypted = fetch_decrypted_audio_from_evolution(msg_id, instance_override=instance_name)
                if decrypted:
                    audio_bytes, audio_mime = decrypted

            if not audio_bytes and media_url and isinstance(media_url, str) and ".enc" not in media_url:
                from .atlas import download_media_from_url
                audio_bytes = download_media_from_url(media_url)

        raw_text = (
            msg_obj.get("conversation")
            or (msg_obj.get("extendedTextMessage", {}).get("text") if isinstance(msg_obj.get("extendedTextMessage"), dict) else None)
            or (msg_obj.get("imageMessage", {}).get("caption") if isinstance(msg_obj.get("imageMessage"), dict) else None)
            or (msg_obj.get("videoMessage", {}).get("caption") if isinstance(msg_obj.get("videoMessage"), dict) else None)
        )

    # Ignora mensagens automáticas do próprio Atlas
    if raw_text and ("*Atlas:*" in raw_text or "🎙️" in raw_text or "Teste de conexão Atlas" in raw_text):
        logger.info("Ignorando mensagem automática gerada pelo próprio Atlas.")
        return None, None, None, None, msg_id_to_record, False

    is_audio = False
    # Validação e limitação de tamanho do áudio (máximo 2 MB) ANTES de invocar transcrição/Gemini
    if audio_bytes and not raw_text:
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            logger.warning(f"Áudio de {user_name} rejeitado: {len(audio_bytes)} bytes excede o limite de {MAX_AUDIO_BYTES} bytes (2MB).")
            return clean_sender, user_name, None, remote_jid, msg_id_to_record, False

        from .atlas import transcribe_audio_bytes
        logger.info(f"Áudio descriptografado de {user_name} ({len(audio_bytes)} bytes). Enviando para o Atlas transcrever...")
        raw_text = transcribe_audio_bytes(audio_bytes, mime_type=audio_mime)
        if raw_text:
            is_audio = True

    if not raw_text:
        raw_text = data.get("text") or data.get("body") or payload.get("text") or payload.get("message")
        if isinstance(raw_text, dict):
            raw_text = raw_text.get("conversation") or raw_text.get("text")

    if raw_text and isinstance(raw_text, str):
        raw_text = raw_text.strip()
        # Limita raw_text a 500 caracteres
        if len(raw_text) > MAX_RAW_TEXT_LEN:
            raw_text = raw_text[:MAX_RAW_TEXT_LEN]
    else:
        raw_text = None

    return clean_sender, user_name, raw_text, remote_jid, msg_id_to_record, is_audio


async def handle_webhook_event(
    payload: dict,
    request: Request,
    db: Session,
    token_in_path: Optional[str] = None
):
    """Lógica central compartilhada de ingestão do webhook."""
    # 1. Autenticação estrita fail-closed
    verify_webhook_secret(request, token_in_path)

    # 2. Extração, autorização e validação de limites
    sender, user_name, raw_text, remote_jid, msg_id, is_audio = await extract_and_authorize_evolution_message(payload, request)

    # 3. Registra dedupe pós-autenticação e autorização
    if msg_id:
        PROCESSED_MESSAGE_IDS.add(msg_id)
        if len(PROCESSED_MESSAGE_IDS) > 1000:
            PROCESSED_MESSAGE_IDS.clear()

    if not user_name:
        return {
            "status": "ignored",
            "detail": "Evento ignorado ou não autorizado"
        }

    channel_type = "whatsapp_audio" if is_audio else "whatsapp_text"

    parsed_data = None
    if raw_text:
        parsed_data = parse_text_message(raw_text)
        if parsed_data:
            parsed_data["tipo"] = "despesa_variavel"
            parsed_data["source"] = user_name
            parsed_data["author"] = user_name
            parsed_data["channel"] = channel_type
    else:
        parsed_data = parse_financial_payload(payload)
        if parsed_data:
            parsed_data["tipo"] = "despesa_variavel"
            parsed_data["source"] = user_name
            parsed_data["author"] = user_name
            parsed_data["channel"] = channel_type

    if not parsed_data or parsed_data.get("valor", 0) <= 0:
        return {
            "status": "ignored",
            "detail": "Nenhuma despesa identificada na mensagem recebida ou evento irrelevante",
            "sender": mask_phone(sender),
            "user": user_name
        }

    parcelas = max(1, int(parsed_data.get("parcelas", 1)))
    base_data = date.fromisoformat(str(parsed_data["data"]))
    created_ids = []

    # Resolução de Categoria para o Webhook: resolve para canônico ou fallback seguro em 'Outros'
    raw_categoria = parsed_data.get("categoria", "Outros")
    canonical_nome = resolve_canonical_name(raw_categoria) or "Outros"
    norm_cat = normalize_category_name(canonical_nome)

    cat_db = db.query(Category).filter(Category.normalized_name == norm_cat).first()
    if not cat_db:
        # Se por algum motivo 'Outros' ainda não estiver na tabela, busca primeiro ou cria
        cat_db = db.query(Category).filter(Category.normalized_name == "outros").first()
        if not cat_db:
            cat_db = Category(name=canonical_nome, normalized_name=norm_cat, tipo="despesa", ativo=True)
            db.add(cat_db)
            db.commit()
            db.refresh(cat_db)

    cat_id = cat_db.id
    cat_nome = cat_db.name

    for i in range(parcelas):
        parcela_data = add_months(base_data, i).isoformat()
        if parcelas > 1:
            desc_parcelada = f"{parsed_data['descricao']} ({i + 1}/{parcelas})"
        else:
            desc_parcelada = parsed_data["descricao"]

        t_item = Transaction(
            tipo=parsed_data["tipo"],
            valor=to_decimal(parsed_data["valor"]),
            categoria=cat_nome,
            category_id=cat_id,
            data=add_months(base_data, i),
            descricao=desc_parcelada,
            author=user_name,
            channel=channel_type,
            source=parsed_data.get("source", user_name),
            vencimento=parsed_data.get("vencimento")
        )
        db.add(t_item)
        db.flush()
        created_ids.append(t_item.id)

    db.commit()

    from .atlas import format_atlas_confirmation, send_whatsapp_message
    from .routes import get_metrics

    saldo_atualizado = None
    try:
        mes_iso = base_data.strftime("%Y-%m")
        metrics = get_metrics(mes=mes_iso, db=db)
        if isinstance(metrics, dict):
            saldo_atualizado = metrics.get("saldo_livre")
        elif hasattr(metrics, "saldo_livre"):
            saldo_atualizado = metrics.saldo_livre
    except Exception as e:
        logger.debug(f"Não foi possível calcular saldo para o Atlas: {e}")

    atlas_reply = format_atlas_confirmation(
        user_name=user_name,
        item_desc=parsed_data['descricao'],
        valor=float(parsed_data['valor']),
        parcelas=parcelas,
        saldo_livre=saldo_atualizado
    )

    if remote_jid:
        send_whatsapp_message(remote_jid, atlas_reply)

    return {
        "status": "success",
        "id": created_ids[0] if created_ids else None,
        "ids": created_ids,
        "parcelas": parcelas,
        "sender": mask_phone(sender),
        "user": user_name,
        "atlas_response": atlas_reply,
        "transaction": parsed_data
    }


@webhook_router.post("/whatsapp")
@webhook_router.post("")
async def receive_webhook(request: Request, payload: dict, db: Session = Depends(get_db)):
    """Receptor oficial de webhook com autenticação por header."""
    return await handle_webhook_event(payload, request, db)


@webhook_router.post("/whatsapp/{token}")
async def receive_webhook_path_token(token: str, request: Request, payload: dict, db: Session = Depends(get_db)):
    """
    Receptor alternativo com token no path para gateways que não suportam headers customizados.
    Ativado apenas se WEBHOOK_ALLOW_PATH_TOKEN=1.
    """
    return await handle_webhook_event(payload, request, db, token_in_path=token)
