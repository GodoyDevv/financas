"""Configurações centralizadas e tipadas da aplicação com pydantic-settings.

Garante validação fail-closed no startup e 12-factor compliance.
"""

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Decisão de produto para cálculo de parcelamentos:
PARCELA_MODO: Literal["valor_da_parcela", "valor_total"] = "valor_da_parcela"

# Lista de valores de placeholder/exemplo que devem ser rejeitados em produção
PLACEHOLDER_SUBSTRINGS = (
    "sua_senha",
    "sua_chave",
    "seu_token",
    "sua_instancia",
    "changeme",
    "example",
    "gere_uma_chave",
    "gere_um_segredo",
    "gere_um_token",
    "usuario:senha@host",
)


class Settings(BaseSettings):
    # Lê arquivo .env apenas se não estiver em produção (ou se explicitamente informado)
    model_config = SettingsConfigDict(
        env_file=".env" if os.getenv("ENV", "development").lower() != "production" else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Ambiente de execução
    ENV: Literal["development", "production", "test"] = "development"

    # Autenticação e Segurança Básica
    APP_PASSWORD: SecretStr = Field(default=SecretStr(""))
    SESSION_SECRET: SecretStr = Field(default=SecretStr(""))
    ADMIN_TOKEN: SecretStr = Field(default=SecretStr(""))
    SESSION_TTL_HOURS: int = Field(default=12, ge=1)
    DEV_INSECURE_COOKIES: bool = Field(default=False)

    # Banco de Dados
    DATABASE_URL: str = Field(default="sqlite:///./fintrack.db")

    # Webhook WhatsApp
    WEBHOOK_SECRET: SecretStr = Field(default=SecretStr(""))
    WEBHOOK_SECRET_HEADER: str = Field(default="X-Webhook-Secret")
    WEBHOOK_ALLOW_PATH_TOKEN: bool = Field(default=False)

    # Identificação de Usuários / WhatsApp
    WHATSAPP_GROUP_JID: str = Field(default="")
    WHATSAPP_USER_BRUNO: str = Field(default="")
    WHATSAPP_USER_LETICIA: str = Field(default="")

    # Inteligência Artificial / LLM
    GEMINI_API_KEY: SecretStr = Field(default=SecretStr(""))
    OPENAI_API_KEY: SecretStr = Field(default=SecretStr(""))
    NLP_MODE: Literal["hybrid", "regex", "llm"] = "hybrid"
    GEMINI_MODEL: str = Field(default="gemini-2.5-flash")
    GEMINI_TIMEOUT_SECONDS: float = Field(default=8.0, gt=0)

    # Evolution API Gateway
    EVOLUTION_API_URL: str = Field(default="")
    EVOLUTION_API_KEY: SecretStr = Field(default=SecretStr(""))
    EVOLUTION_INSTANCE: str = Field(default="fintrack-casal")

    # CORS
    ALLOWED_ORIGINS: str = Field(default="")

    @field_validator("DEV_INSECURE_COOKIES", "WEBHOOK_ALLOW_PATH_TOKEN", mode="before")
    @classmethod
    def parse_bool_from_str(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(v, (int, float)):
            return bool(v)
        return False

    @field_validator("DATABASE_URL")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        url = v.strip() if v else ""
        if not url:
            return "sqlite:///./fintrack.db"
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql://") and not url.startswith("postgresql+"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql+psycopg2://"):
            return url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
        return url

    @field_validator("EVOLUTION_API_URL")
    @classmethod
    def clean_evolution_url(cls, v: str) -> str:
        return v.strip().rstrip("/") if v else ""

    @field_validator("WHATSAPP_GROUP_JID", "ALLOWED_ORIGINS")
    @classmethod
    def clean_whitespace(cls, v: str) -> str:
        return v.strip() if v else ""

    @model_validator(mode="after")
    def validate_cross_field_rules(self) -> "Settings":
        errors: list[str] = []

        is_prod = self.ENV == "production"

        app_pwd = self.APP_PASSWORD.get_secret_value().strip()
        sess_sec = self.SESSION_SECRET.get_secret_value().strip()
        adm_tok = self.ADMIN_TOKEN.get_secret_value().strip()
        wh_sec = self.WEBHOOK_SECRET.get_secret_value().strip()
        group_jid = self.WHATSAPP_GROUP_JID.strip()
        phone_bruno = self.WHATSAPP_USER_BRUNO.strip()
        phone_leticia = self.WHATSAPP_USER_LETICIA.strip()

        # 1. Regras obrigatórias de segurança sempre (qualquer ambiente)
        if not app_pwd:
            errors.append("APP_PASSWORD é obrigatória e não pode estar vazia.")
        if not sess_sec:
            errors.append("SESSION_SECRET é obrigatória e não pode estar vazia.")
        elif len(sess_sec) < 32:
            errors.append("SESSION_SECRET deve conter no mínimo 32 caracteres.")

        if not adm_tok:
            errors.append("ADMIN_TOKEN é obrigatória e não pode estar vazia.")

        if wh_sec and len(wh_sec) < 32:
            errors.append("WEBHOOK_SECRET deve conter no mínimo 32 caracteres quando definida.")

        # 2. Regras estritas para ambiente de produção
        if is_prod:
            if not wh_sec:
                errors.append("WEBHOOK_SECRET é obrigatória em ambiente de produção.")
            if not group_jid:
                errors.append("WHATSAPP_GROUP_JID é obrigatório em ambiente de produção.")
            if not phone_bruno:
                errors.append("WHATSAPP_USER_BRUNO é obrigatório em ambiente de produção.")
            if not phone_leticia:
                errors.append("WHATSAPP_USER_LETICIA é obrigatório em ambiente de produção.")

            # Rejeição de placeholders / valores de exemplo em produção
            secrets_to_check = [
                ("APP_PASSWORD", app_pwd),
                ("SESSION_SECRET", sess_sec),
                ("ADMIN_TOKEN", adm_tok),
                ("WEBHOOK_SECRET", wh_sec),
                ("WHATSAPP_GROUP_JID", group_jid),
                ("DATABASE_URL", self.DATABASE_URL),
            ]
            for name, val in secrets_to_check:
                val_lower = val.lower()
                for ph in PLACEHOLDER_SUBSTRINGS:
                    if ph in val_lower:
                        errors.append(
                            f"{name} contém valor de exemplo/placeholder não permitido em produção: '{ph}'"
                        )
                        break

        if errors:
            formatted_errors = "\n  - " + "\n  - ".join(errors)
            raise ValueError(f"Falha na validação de configurações:{formatted_errors}")

        return self

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna a instância única em cache das configurações."""
    return Settings()
