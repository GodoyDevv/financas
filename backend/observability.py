"""
backend/observability.py

Configuração centralizada de logs estruturados (JSON em produção, texto legível em dev),
contextvars para correlação de requisições/mensagens e scrubbing agressivo de PII para Sentry.
"""

import contextvars
import json
import logging
import re
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from backend.config import get_settings

# Context Variables para rastreamento de correlação
REQUEST_ID_CTX: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
MESSAGE_ID_CTX: contextvars.ContextVar[str] = contextvars.ContextVar("message_id", default="")

# Headers sensíveis que devem ser completamente expurgados do Sentry e logs
SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "x-admin-token",
    "x-webhook-secret",
    "apikey",
    "x-goog-api-key",
}

# Regex para identificação e mascaramento de números de telefone padrão internacional/nacional
# Formatos comuns: +5511999998888, 5511999998888, 11999998888, (11) 99999-8888, 5511999998888@s.whatsapp.net
PHONE_REGEX = re.compile(
    r"(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?(?:9\s?\d{4}[-\s]?\d{4}|\d{4}[-\s]?\d{4})(?:@s\.whatsapp\.net|@g\.us)?"
)


def mask_phone_str(phone: str | None) -> str:
    """Mascara telefone mantendo apenas extremidades ou formato seguro (ex: 5511****9999)."""
    if not phone:
        return "[vazio]"
    clean = "".join(filter(str.isdigit, str(phone)))
    if len(clean) <= 4:
        return "****"
    if len(clean) <= 8:
        return f"{clean[:2]}****{clean[-2:]}"
    return f"{clean[:4]}****{clean[-4:]}"


def mask_phone_in_text(text: str) -> str:
    """Substitui ocorrências de telefones em mensagens de texto/exceções por versão mascarada."""
    if not text:
        return text

    def _replace_phone(match: re.Match) -> str:
        raw = match.group(0)
        # Se for menção ou JID, preserva o sufixo
        suffix = ""
        if "@" in raw:
            raw, suffix = raw.split("@", 1)
            suffix = "@" + suffix
        return mask_phone_str(raw) + suffix

    return PHONE_REGEX.sub(_replace_phone, text)


class StructuredJsonFormatter(logging.Formatter):
    """
    Formatter que serializa todos os registros em JSON estrito.
    Inclui timestamp UTC ISO, nível, logger, mensagem, request_id e message_id contextuais.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_record: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Injeta correlação dos contextvars se disponíveis
        req_id = REQUEST_ID_CTX.get()
        if req_id:
            log_record["request_id"] = req_id

        msg_id = MESSAGE_ID_CTX.get()
        if msg_id:
            log_record["message_id"] = msg_id

        # Injeta atributos adicionais passados via logger.info("...", extra={...})
        # ignorando atributos internos padrão do LogRecord
        builtin_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
        }
        for k, v in record.__dict__.items():
            if k not in builtin_attrs and not k.startswith("_"):
                log_record[k] = v

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_record, ensure_ascii=False)


class DevConsoleFormatter(logging.Formatter):
    """Formatter colorido e legível para terminal de desenvolvimento."""

    def format(self, record: logging.LogRecord) -> str:
        req_id = REQUEST_ID_CTX.get()
        msg_id = MESSAGE_ID_CTX.get()

        prefix_parts = []
        if req_id:
            prefix_parts.append(f"req={req_id[:8]}")
        if msg_id:
            prefix_parts.append(f"msg={msg_id}")

        prefix = f" [{ ' '.join(prefix_parts) }]" if prefix_parts else ""

        base_msg = record.getMessage()
        res = f"{datetime.now(UTC).strftime('%H:%M:%S')} | {record.levelname:<7} | {record.name}{prefix} - {base_msg}"
        if record.exc_info:
            res += f"\n{self.formatException(record.exc_info)}"
        return res


def setup_logging() -> None:
    """Configura o sistema de logging da aplicação, uvicorn e bibliotecas de HTTP."""
    settings = get_settings()
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove handlers legados do root logger
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    if settings.is_production:
        stream_handler.setFormatter(StructuredJsonFormatter())
    else:
        stream_handler.setFormatter(DevConsoleFormatter())

    root_logger.addHandler(stream_handler)

    # Configura uvicorn e http libraries
    for uvicorn_log in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        u_logger = logging.getLogger(uvicorn_log)
        u_logger.handlers = [stream_handler]
        u_logger.propagate = False
        u_logger.setLevel(log_level)

    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def sentry_before_send(event: Any, hint: dict[str, Any]) -> Any | None:
    """
    Scrubber agressivo para eventos do Sentry:
    - Remove request body (data)
    - Remove cookies
    - Remove headers sensíveis
    - Mascara telefones em mensagens de log e descrições de exceção
    """
    if not isinstance(event, dict):
        return event
    # 1. Limpeza do objeto request
    req = event.get("request")
    if isinstance(req, dict):
        # Remove dados/corpo de requisição
        req.pop("data", None)
        req.pop("cookies", None)

        headers = req.get("headers")
        if isinstance(headers, dict):
            filtered_headers = {}
            for k, v in headers.items():
                if k.lower() in SENSITIVE_HEADERS:
                    filtered_headers[k] = "[REDACTED]"
                else:
                    filtered_headers[k] = v
            req["headers"] = filtered_headers

    # 2. Mascaramento de telefones em exceções
    exc_values = event.get("exception", {}).get("values", [])
    for exc in exc_values:
        if "value" in exc and isinstance(exc["value"], str):
            exc["value"] = mask_phone_in_text(exc["value"])

    # 3. Mascaramento de telefones na mensagem do evento
    if "message" in event and isinstance(event["message"], str):
        event["message"] = mask_phone_in_text(event["message"])

    # 4. Injeta correlação se disponível
    req_id = REQUEST_ID_CTX.get()
    if req_id:
        tags = event.setdefault("tags", {})
        tags["request_id"] = req_id

    msg_id = MESSAGE_ID_CTX.get()
    if msg_id:
        tags = event.setdefault("tags", {})
        tags["message_id"] = msg_id

    return event


def init_sentry() -> bool:
    """Inicializa o SDK do Sentry com opções seguras e scrubbing estrito de PII."""
    settings = get_settings()
    sentry_dsn = settings.SENTRY_DSN.get_secret_value().strip()

    if not sentry_dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration

    release = settings.RENDER_GIT_COMMIT or "local"

    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=settings.ENV,
        release=release,
        send_default_pii=False,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        before_send=sentry_before_send,
        integrations=[FastApiIntegration(transaction_style="endpoint")],
    )
    return True


def generate_request_id() -> str:
    """Gera um UUID4 formatado para correlação de requisições."""
    return str(uuid.uuid4())
