"""
backend/integrations/gemini.py

Cliente para transcrição de áudio e interação multimodal com Google Gemini API (e fallback Whisper).
Sem dependência de serviços ou API.
"""

import base64
import io
import logging

import httpx

from backend.config import get_settings

logger = logging.getLogger("fintrack.integrations.gemini")


def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str | None:
    """
    Transcreve áudio utilizando Google Gemini Flash ou OpenAI Whisper.
    Prioriza Gemini (gratuito/baixíssimo custo e veloz).
    """
    if not audio_bytes:
        return None

    # 1. Tentativa com Google Gemini Flash
    s = get_settings()
    gemini_key = s.GEMINI_API_KEY.get_secret_value()
    if gemini_key:
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
                gen_config: dict[str, object] = {"temperature": 0.0, "maxOutputTokens": 1024}
                if "3.8" in model_name:
                    gen_config["thinkingConfig"] = {"thinkingBudget": 0}

                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"inline_data": {"mime_type": clean_mime, "data": b64_audio}},
                                {
                                    "text": (
                                        "Você é o Atlas, secretário pessoal. Transcreva o áudio acima com fidelidade total em português do Brasil. "
                                        "Sempre escreva valores e números de parcelas em algarismos numéricos (ex: 200, 4 vezes). "
                                        "Retorne EXCLUSIVAMENTE o texto transcrito, sem introduções, aspas ou comentários adicionais."
                                    )
                                },
                            ]
                        }
                    ],
                    "generationConfig": gen_config,
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
                                logger.info(
                                    f"Atlas transcreveu áudio com sucesso via Gemini ({model_name}): '{text}'"
                                )
                                return text
                    else:
                        err_code = "desconhecido"
                        try:
                            err_code = str(
                                res.json().get("error", {}).get("status", res.status_code)
                            )
                        except Exception:
                            err_code = str(res.status_code)
                        logger.warning(
                            f"Falha na API Gemini ({model_name}) status={res.status_code} erro={err_code}"
                        )
            except Exception as e:
                logger.error(f"Erro ao transcrever com Gemini ({model_name}): {e}")

    # 2. Tentativa de Fallback com OpenAI Whisper
    openai_key = s.OPENAI_API_KEY.get_secret_value()
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

    logger.warning(
        "Nenhuma chave de IA (GEMINI_API_KEY ou OPENAI_API_KEY) configurada ou erro em ambos."
    )
    return None
