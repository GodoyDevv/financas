"""
backend/db/models.py

Modelos relacionais do banco de dados (SQLAlchemy 2.0 DeclarativeBase).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.session import Base
from backend.timeutils import utc_now_naive


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        String(60), unique=True, index=True, nullable=False
    )
    tipo: Mapped[str] = mapped_column(
        String(20), nullable=False, default="despesa"
    )  # "despesa" ou "receita"
    budget: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )  # Orçamento mensal planejado
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=utc_now_naive
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="category_rel"
    )

    @property
    def nome(self) -> str:
        """Alias para manter conformidade com a convenção em português."""
        return str(self.name)


class Recurrence(Base):
    __tablename__ = "recurrences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # "receita" ou "despesa_fixa"
    descricao: Mapped[str] = mapped_column(String(200), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False, index=True
    )
    author: Mapped[str | None] = mapped_column(String(40), nullable=True)
    dia_do_mes: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 a 31
    inicio: Mapped[date] = mapped_column(
        Date, nullable=False
    )  # Primeiro dia do mês inicial (YYYY-MM-01)
    fim: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )  # Primeiro dia do mês final inclusive (YYYY-MM-01) ou NULL
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=utc_now_naive
    )

    category_rel: Mapped["Category"] = relationship("Category")
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="recurrence_rel"
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tipo: Mapped[str] = mapped_column(
        String, nullable=False
    )  # "receita", "despesa_fixa", "despesa_variavel"
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    categoria: Mapped[str] = mapped_column(
        String, nullable=False
    )  # Mantido para backward compatibility / dual-write
    data: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # Date object
    descricao: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(
        String, nullable=True, default="Manual"
    )  # Mantido temporariamente para backward compatibility
    author: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )  # "Bruno", "Letícia" ou custom
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown"
    )  # "whatsapp_text", "whatsapp_audio", "dashboard", "api", "system", "unknown"
    vencimento: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Para despesas fixas (ex: dia 10 ou data YYYY-MM-DD)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=utc_now_naive
    )

    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False, index=True
    )
    category_rel: Mapped["Category"] = relationship("Category", back_populates="transactions")

    # Campos de parcelamento com identidade relacional
    parcela_grupo_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    parcela_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parcela_total: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Campos de recorrência com materialização idempotente
    recurrence_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("recurrences.id"), nullable=True, index=True
    )
    competencia: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )  # Primeiro dia do mês da competência (YYYY-MM-01)
    editado_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    recurrence_rel: Mapped["Recurrence | None"] = relationship(
        "Recurrence", back_populates="transactions"
    )

    # Chave de idempotência única com o webhook de origem
    source_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Soft Delete: data de remoção lógica (NULL = ativo)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    events: Mapped[list["TransactionEvent"]] = relationship(
        "TransactionEvent", back_populates="transaction_rel", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_transactions_data_tipo", "data", "tipo"),
        Index("uq_transactions_grupo_num", "parcela_grupo_id", "parcela_num", unique=True),
        Index(
            "uq_transactions_recurrence_competencia", "recurrence_id", "competencia", unique=True
        ),
        Index("uq_transactions_source_message_id", "source_message_id", unique=True),
        CheckConstraint(
            "(parcela_grupo_id IS NULL AND parcela_num IS NULL AND parcela_total IS NULL) OR "
            "(parcela_grupo_id IS NOT NULL AND parcela_num IS NOT NULL AND parcela_total IS NOT NULL AND parcela_num >= 1 AND parcela_num <= parcela_total)",
            name="ck_transactions_parcelas_valid",
        ),
    )


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    message_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True
    )  # confirmation, alert, help, error, report
    ref_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_jid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    __table_args__ = (Index("ix_outbound_messages_ref", "ref_type", "ref_id"),)


class TransactionEvent(Base):
    __tablename__ = "transaction_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    transaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transactions.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # created, updated, deleted, restored
    actor: Mapped[str | None] = mapped_column(String(60), nullable=True)
    channel: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    transaction_rel: Mapped["Transaction"] = relationship("Transaction", back_populates="events")


class ProcessedMessage(Base):
    __tablename__ = "processed_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    message_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="received", index=True
    )  # received, processing, done, ignored, failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    replied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    run_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running", index=True
    )  # running, done, failed, skipped
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (Index("uq_job_runs_name_key", "job_name", "run_key", unique=True),)
