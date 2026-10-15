from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import date

class TransactionBase(BaseModel):
    tipo: str = Field(..., description="Tipo do lançamento: receita, despesa_fixa ou despesa_variavel")
    valor: float
    categoria: str
    data: date
    descricao: Optional[str] = None
    source: Optional[str] = "Manual"
    vencimento: Optional[str] = None

class TransactionCreate(TransactionBase):
    pass

class TransactionUpdate(BaseModel):
    tipo: Optional[str] = Field(None, description="Tipo do lançamento: receita, despesa_fixa ou despesa_variavel")
    valor: Optional[float] = None
    categoria: Optional[str] = None
    data: Optional[date] = None
    descricao: Optional[str] = None
    source: Optional[str] = None
    vencimento: Optional[str] = None

class TransactionResponse(TransactionBase):
    id: int

    class Config:
        from_attributes = True

class FinancialSummary(BaseModel):
    total_receitas: float
    total_despesas_fixas: float
    total_despesas_variaveis: float
    total_despesas: float
    saldo_livre: float

class CategoryMetric(BaseModel):
    categoria: str
    total: float
    percentual: float

class MetricsResponse(BaseModel):
    receitas_totais: float
    contas_fixas: float
    gastos_whatsapp: float
    total_despesas: float
    saldo_livre: float
    total_transacoes: int
    categorias: List[CategoryMetric]

class MessageParseRequest(BaseModel):
    message: str

class MessageParseResponse(BaseModel):
    tipo: str
    valor: float
    categoria: str
    descricao: str
    data: str
    source: str