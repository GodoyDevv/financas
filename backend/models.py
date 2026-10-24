from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Numeric, Date, Index
from sqlalchemy.orm import relationship
from backend.database import Base

class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    budget = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    transactions = relationship("Transaction", back_populates="category_rel")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(String, nullable=False) # "receita", "despesa_fixa", "despesa_variavel"
    valor = Column(Numeric(12, 2), nullable=False)
    categoria = Column(String, nullable=False)
    data = Column(Date, nullable=False, index=True) # Date object
    descricao = Column(String, nullable=True)
    source = Column(String, default="Manual") # Mantido temporariamente para backward compatibility
    author = Column(String(40), nullable=True) # "Bruno", "Letícia" ou custom
    channel = Column(String(20), nullable=False, default="unknown") # "whatsapp_text", "whatsapp_audio", "dashboard", "api", "system", "unknown"
    vencimento = Column(String, nullable=True) # Para despesas fixas (ex: dia 10 ou data YYYY-MM-DD)
    created_at = Column(DateTime, default=datetime.utcnow)

    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    category_rel = relationship("Category", back_populates="transactions")

    __table_args__ = (
        Index("ix_transactions_data_tipo", "data", "tipo"),
    )
