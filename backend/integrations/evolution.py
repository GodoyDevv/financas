"""
backend/integrations/evolution.py

Cliente para envio de mensagens e download/descriptografia de mídia via Evolution API.
Sem dependência de serviços ou API.
"""

import base64
import logging

import httpx

from backend.config import get_settings

logger = logging.getLogger("fintrack.integrations.evolution")


def fetch_decrypted_audio_from_evolution(
    message_id: str, instance_override: str | None = None
) -> tuple[bytes, str] | None:
    """
    Usa o endpoint oficial getBase64FromMediaMessage da Evolution API para obter o áudio
    descriptografado (pois as URLs .enc do WhatsApp são criptografadas com mediaKey).
    """
    s = get_settings()
    api_url = s.EVOLUTION_API_URL
    api_key = s.EVOLUTION_API_KEY.get_secret_value()
    instance = instance_override or s.EVOLUTION_INSTANCE

    if not (api_url and api_key and message_id):
        return None

    endpoint = f"{api_url}/chat/getBase64FromMediaMessage/{instance}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload = {"message": {"key": {"id": message_id}}}

    try:
        with httpx.Client(timeout=25.0) as client:
            res = client.post(endpoint, headers=headers, json=payload)
            if res.status_code in [200, 201]:
                data = res.json()
                b64_str = data.get("base64", "")
                mime = data.get("mimetype") or "audio/ogg"
                if b64_str:
                    if "," in b64_str:
                        b64_str = b64_str.split(",", 1)[1]
                    return base64.b64decode(b64_str), mime
            else:
                logger.warning(
                    f"Erro ao descriptografar mídia via Evolution ({res.status_code}): {res.text}"
                )
    except Exception as e:
        logger.error(f"Exceção ao buscar base64 de mídia na Evolution API: {e}")

    return None


def download_media_from_url(media_url: str) -> bytes | None:
    """Baixa o arquivo de mídia a partir de uma URL pública ou pré-assinada."""
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.get(media_url)
            if res.status_code == 200:
                return res.content
    except Exception as e:
        logger.error(f"Erro ao baixar mídia da URL {media_url}: {e}")
    return None


def send_whatsapp_message(
    remote_jid: str,
    text: str,
    quoted_message_id: str | None = None,
) -> str | None:
    """
    Envia uma mensagem de resposta ativa via Evolution API para o grupo do WhatsApp.
    Retorna o ID da mensagem enviada (para anti-loop e rastreamento em outbound_messages)
    ou None em caso de falha.
    """
    s = get_settings()
    api_url = s.EVOLUTION_API_URL
    api_key = s.EVOLUTION_API_KEY.get_secret_value()
    instance = s.EVOLUTION_INSTANCE

    if not (api_url and api_key and instance):
        logger.debug("Evolution API não configurada para envio de mensagens ativas de resposta.")
        return None

    endpoint = f"{api_url}/message/sendText/{instance}"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    payload: dict = {"number": remote_jid, "text": text, "linkPreview": False}
    if quoted_message_id:
        payload["quoted"] = {"key": {"id": quoted_message_id}}

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(endpoint, headers=headers, json=payload)
            if res.status_code in [200, 201]:
                logger.info(f"Atlas enviou resposta para {remote_jid} com sucesso.")
                try:
                    data = res.json()
                    msg_id = data.get("key", {}).get("id") or data.get("id")
                    return str(msg_id) if msg_id else "sent"
                except Exception:
                    return "sent"
            else:
                logger.warning(
                    f"Erro ao enviar resposta via Evolution ({res.status_code}): {res.text}"
                )
    except Exception as e:
        logger.error(f"Exceção ao disparar resposta do Atlas via WhatsApp: {e}")

    return None
