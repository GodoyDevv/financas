from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, 
    Numeric, Date, Boolean, Index, CheckConstraint
)
from sqlalchemy.orm import relationship
from backend.database import Base

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(60), unique=True, index=True, nullable=False)
    normalized_name = Column(String(60), unique=True, index=True, nullable=False)
    tipo = Column(String(20), nullable=False, default="despesa") # "despesa" ou "receita"
    budget = Column(Numeric(12, 2), nullable=True) # Orçamento mensal planejado
    ativo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    transactions = relationship("Transaction", back_populates="category_rel")

    @property
    def nome(self) -> str:
        """Alias para manter conformidade com a convenção em português."""
        return self.name

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String, nullable=False) # "receita", "despesa_fixa", "despesa_variavel"
    valor = Column(Numeric(12, 2), nullable=False)
    categoria = Column(String, nullable=False) # Mantido para backward compatibility / dual-write
    data = Column(Date, nullable=False, index=True) # Date object
    descricao = Column(String, nullable=True)
    source = Column(String, default="Manual") # Mantido temporariamente para backward compatibility
    author = Column(String(40), nullable=True) # "Bruno", "Letícia" ou custom
    channel = Column(String(20), nullable=False, default="unknown") # "whatsapp_text", "whatsapp_audio", "dashboard", "api", "system", "unknown"
    vencimento = Column(String, nullable=True) # Para despesas fixas (ex: dia 10 ou data YYYY-MM-DD)
    created_at = Column(DateTime, default=datetime.utcnow)

    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)
    category_rel = relationship("Category", back_populates="transactions")

    # Campos de parcelamento com identidade relacional
    parcela_grupo_id = Column(String(36), nullable=True, index=True)
    parcela_num = Column(Integer, nullable=True)
    parcela_total = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_transactions_data_tipo", "data", "tipo"),
        Index("uq_transactions_grupo_num", "parcela_grupo_id", "parcela_num", unique=True),
        CheckConstraint(
            "(parcela_grupo_id IS NULL AND parcela_num IS NULL AND parcela_total IS NULL) OR "
            "(parcela_grupo_id IS NOT NULL AND parcela_num IS NOT NULL AND parcela_total IS NOT NULL AND parcela_num >= 1 AND parcela_num <= parcela_total)",
            name="ck_transactions_parcelas_valid"
        ),
    )
