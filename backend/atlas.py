"""
backend/atlas.py

Módulo de compatibilidade retroativa.
Re-exporta funções segregadas em backend.integrations (gemini, evolution, templates).
"""

from backend.integrations.evolution import (
    download_media_from_url,
    fetch_decrypted_audio_from_evolution,
    send_whatsapp_message,
)
from backend.integrations.gemini import transcribe_audio_bytes
from backend.integrations.templates import format_atlas_confirmation

__all__ = [
    "download_media_from_url",
    "fetch_decrypted_audio_from_evolution",
    "format_atlas_confirmation",
    "send_whatsapp_message",
    "transcribe_audio_bytes",
]
