from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
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
    valor = Column(Float, nullable=False)
    categoria = Column(String, nullable=False)
    data = Column(String, nullable=False) # YYYY-MM-DD
    descricao = Column(String, nullable=True)
    source = Column(String, default="Manual") # "Manual", "WhatsApp", "Webhook"
    vencimento = Column(String, nullable=True) # Para despesas fixas (ex: dia 10 ou data YYYY-MM-DD)
    created_at = Column(DateTime, default=datetime.utcnow)

    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    category_rel = relationship("Category", back_populates="transactions")
