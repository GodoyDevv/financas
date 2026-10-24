from typing import Union
from decimal import Decimal
import os
import io
import re
import base64
import logging
from typing import Optional, Tuple
import httpx

logger = logging.getLogger("fintrack.atlas")

# Configura httpx e httpcore para WARNING para não logar URLs com parâmetros
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Chaves de API para transcrição / IA
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Configuração da Evolution API para envio de mensagens ativas do Atlas (opcional)
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")

def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Optional[str]:
    """
    Transcreve áudio utilizando Google Gemini Flash ou OpenAI Whisper.
    Prioriza Gemini (gratuito/baixíssimo custo e veloz).
    """
    if not audio_bytes:
        return None

    # 1. Tentativa com Google Gemini Flash
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        # Lista de modelos: gemini-3.5-flash-lite (sem overhead de thinking) + gemini-3.8-flash (com thinkingBudget=0)
        models_to_try = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        
        clean_mime = mime_type.split(";")[0].strip() or "audio/ogg"
        if "ogg" in clean_mime:
            clean_mime = "audio/ogg"
        elif "mp3" in clean_mime or "mpeg" in clean_mime:
            clean_mime = "audio/mp3"
        elif "m4a" in clean_mime or "mp4" in clean_mime:
            clean_mime = "audio/mp4"

        for model_name in models_to_try:
            try:
                gen_config = {
                    "temperature": 0.0,
                    "maxOutputTokens": 1024
                }
                if "3.8" in model_name:
                    gen_config["thinkingConfig"] = {"thinkingBudget": 0}

                payload = {
                    "contents": [
                        {
                            "parts": [
                                {
                                    "inline_data": {
                                        "mime_type": clean_mime,
                                        "data": b64_audio
                                    }
                                },
                                {
                                    "text": (
                                        "Você é o Atlas, secretário pessoal. Transcreva o áudio acima com fidelidade total em português do Brasil. "
                                        "Sempre escreva valores e números de parcelas em algarismos numéricos (ex: 200, 4 vezes). "
                                        "Retorne EXCLUSIVAMENTE o texto transcrito, sem introduções, aspas ou comentários adicionais."
                                    )
                                }
                            ]
                        }
                    ],
                    "generationConfig": gen_config
                }

                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
                headers = {"x-goog-api-key": gemini_key}
                with httpx.Client(timeout=25.0) as client:
                    res = client.post(url, headers=headers, json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                text = parts[0].get("text", "").strip()
                                logger.info(f"Atlas transcreveu áudio com sucesso via Gemini ({model_name}): '{text}'")
                                return text
                    else:
                        # Log seguro: reporta apenas status e código do erro sem logar corpo de resposta bruto
                        err_code = "desconhecido"
                        try:
                            err_code = res.json().get("error", {}).get("status", res.status_code)
                        except Exception:
                            err_code = res.status_code
                        logger.warning(f"Falha na API Gemini ({model_name}) status={res.status_code} erro={err_code}")
            except Exception as e:
                logger.error(f"Erro ao transcrever com Gemini ({model_name}): {e}")

    # 2. Tentativa de Fallback com OpenAI Whisper
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if openai_key:
        try:
            url = "https://api.openai.com/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {openai_key}"}
            files = {"file": ("audio.ogg", io.BytesIO(audio_bytes), mime_type)}
            data = {"model": "whisper-1", "language": "pt"}

            with httpx.Client(timeout=25.0) as client:
                res = client.post(url, headers=headers, files=files, data=data)
                if res.status_code == 200:
                    text = res.json().get("text", "").strip()
                    logger.info(f"Atlas transcreveu áudio via Whisper: '{text}'")
                    return text
                else:
                    logger.warning(f"Falha Whisper ({res.status_code}): {res.text}")
        except Exception as e:
            logger.error(f"Erro ao transcrever áudio com Whisper: {e}")

    logger.warning("Nenhuma chave de IA (GEMINI_API_KEY ou OPENAI_API_KEY) configurada ou erro em ambos.")
    return None

def fetch_decrypted_audio_from_evolution(message_id: str, instance_override: Optional[str] = None) -> Optional[Tuple[bytes, str]]:
    """
    Usa o endpoint oficial getBase64FromMediaMessage da Evolution API para obter o áudio
    descriptografado (pois as URLs .enc do WhatsApp são criptografadas com mediaKey).
    """
    api_url = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
    api_key = os.getenv("EVOLUTION_API_KEY", "")
    instance = instance_override or os.getenv("EVOLUTION_INSTANCE", "fintrack-casal")

    if not (api_url and api_key and message_id):
        return None

    endpoint = f"{api_url}/chat/getBase64FromMediaMessage/{instance}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "message": {
            "key": {
                "id": message_id
            }
        }
    }

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
                logger.warning(f"Erro ao descriptografar mídia via Evolution ({res.status_code}): {res.text}")
    except Exception as e:
        logger.error(f"Exceção ao buscar base64 de mídia na Evolution API: {e}")

    return None

def download_media_from_url(media_url: str) -> Optional[bytes]:
    """Baixa o arquivo de mídia a partir de uma URL pública ou pré-assinada."""
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.get(media_url)
            if res.status_code == 200:
                return res.content
    except Exception as e:
        logger.error(f"Erro ao baixar mídia da URL {media_url}: {e}")
    return None

def format_atlas_confirmation(user_name: str, item_desc: str, valor: Union[float, Decimal], parcelas: int, saldo_livre: Optional[Union[float, Decimal]] = None) -> str:
    """Gera a mensagem de resposta executiva do Atlas."""
    val_formatado = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    
    if parcelas > 1:
        detalhe = f"em {parcelas} parcelas de {val_formatado}"
    else:
        detalhe = f"no valor de {val_formatado}"

    msg = f"🎙️ *Atlas:* Entendido, {user_name}! Lancei *{item_desc}* {detalhe} no Atlas Finanças."
    if saldo_livre is not None:
        saldo_fmt = f"R$ {saldo_livre:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        msg += f"\n📊 *Saldo Livre do Mês:* {saldo_fmt}"
        
    return msg

def send_whatsapp_message(remote_jid: str, text: str) -> bool:
    """Envia uma mensagem de resposta ativa via Evolution API para o grupo do WhatsApp."""
    if not (EVOLUTION_API_URL and EVOLUTION_API_KEY and EVOLUTION_INSTANCE):
        logger.debug("Evolution API não configurada para envio de mensagens ativas de resposta.")
        return False

    endpoint = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "number": remote_jid,
        "text": text,
        "linkPreview": False
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.post(endpoint, headers=headers, json=payload)
            if res.status_code in [200, 201]:
                logger.info(f"Atlas enviou resposta para {remote_jid} com sucesso.")
                return True
            else:
                logger.warning(f"Erro ao enviar resposta via Evolution ({res.status_code}): {res.text}")
    except Exception as e:
        logger.error(f"Exceção ao disparar resposta do Atlas via WhatsApp: {e}")

    return False
