from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Literal
from datetime import date
import re

def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Remove caracteres de controle ASCII perigosos preservando quebras e espaços normais."""
    if value is None:
        return None
    # Remove caracteres de controle C0/C1 exceto tabs, newlines e espaços
    cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', str(value))
    return cleaned.strip()

TipoTransacao = Literal["receita", "despesa_fixa", "despesa_variavel"]

class TransactionBase(BaseModel):
    tipo: TipoTransacao = Field(..., description="Tipo do lançamento: receita, despesa_fixa ou despesa_variavel")
    valor: float = Field(..., gt=0, le=1_000_000, description="Valor do lançamento entre R$ 0,01 e R$ 1.000.000,00")
    categoria: str = Field(..., min_length=1, max_length=60, description="Categoria do lançamento (máx 60 caracteres)")
    data: date
    descricao: Optional[str] = Field(None, max_length=200, description="Descrição do lançamento (máx 200 caracteres)")
    source: Optional[str] = Field("Manual", max_length=40, description="Origem da transação (máx 40 caracteres)")
    vencimento: Optional[str] = Field(None, max_length=20, description="Dia de vencimento (máx 20 caracteres)")

    @field_validator("descricao", "categoria", "source", "vencimento", mode="before")
    @classmethod
    def clean_control_chars(cls, v):
        return sanitize_text(v)

class TransactionCreate(TransactionBase):
    pass

class TransactionUpdate(BaseModel):
    tipo: Optional[TipoTransacao] = Field(None, description="Tipo do lançamento: receita, despesa_fixa ou despesa_variavel")
    valor: Optional[float] = Field(None, gt=0, le=1_000_000, description="Valor do lançamento entre R$ 0,01 e R$ 1.000.000,00")
    categoria: Optional[str] = Field(None, min_length=1, max_length=60)
    data: Optional[date] = None
    descricao: Optional[str] = Field(None, max_length=200)
    source: Optional[str] = Field(None, max_length=40)
    vencimento: Optional[str] = Field(None, max_length=20)

    @field_validator("descricao", "categoria", "source", "vencimento", mode="before")
    @classmethod
    def clean_control_chars(cls, v):
        return sanitize_text(v)

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
