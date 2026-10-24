from pydantic import BaseModel, Field, field_validator, PlainSerializer
from typing import Optional, List, Dict, Literal, Annotated
from datetime import date
from decimal import Decimal
import re
from backend.dates_and_money import to_decimal

# Tipo serializado como float nativo em JSON para preservar compatibilidade estrita com o frontend
MoneyDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda x: float(x) if x is not None else 0.0, return_type=float, when_used="json")
]

def sanitize_text(value: Optional[str]) -> Optional[str]:
    """Remove caracteres de controle ASCII perigosos preservando quebras e espaços normais."""
    if value is None:
        return None
    # Remove caracteres de controle C0/C1 exceto tabs, newlines e espaços
    cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', str(value))
    return cleaned.strip()

TipoTransacao = Literal["receita", "despesa_fixa", "despesa_variavel"]
ChannelType = Literal["whatsapp_text", "whatsapp_audio", "dashboard", "api", "system", "unknown"]

class TransactionBase(BaseModel):
    tipo: TipoTransacao = Field(..., description="Tipo do lançamento: receita, despesa_fixa ou despesa_variavel")
    valor: MoneyDecimal = Field(..., gt=0, le=1_000_000, description="Valor do lançamento entre R$ 0,01 e R$ 1.000.000,00")
    categoria: str = Field(..., min_length=1, max_length=60, description="Categoria do lançamento (máx 60 caracteres)")
    data: date
    descricao: Optional[str] = Field(None, max_length=200, description="Descrição do lançamento (máx 200 caracteres)")
    author: Optional[str] = Field(None, max_length=40, description="Autor do lançamento (ex: Bruno, Letícia)")
    channel: Optional[ChannelType] = Field("unknown", description="Canal de entrada do lançamento")
    source: Optional[str] = Field(None, max_length=40, description="[DEPRECATED] Mantido para compatibilidade reversa")
    vencimento: Optional[str] = Field(None, max_length=20, description="Dia de vencimento (máx 20 caracteres)")

    @field_validator("valor", mode="before")
    @classmethod
    def parse_money(cls, v):
        if v is None:
            return v
        return to_decimal(v)

    @field_validator("descricao", "categoria", "source", "author", "vencimento", mode="before")
    @classmethod
    def clean_control_chars(cls, v):
        return sanitize_text(v)

class TransactionCreate(TransactionBase):
    pass

class TransactionUpdate(BaseModel):
    tipo: Optional[TipoTransacao] = Field(None, description="Tipo do lançamento: receita, despesa_fixa ou despesa_variavel")
    valor: Optional[MoneyDecimal] = Field(None, gt=0, le=1_000_000, description="Valor do lançamento entre R$ 0,01 e R$ 1.000.000,00")
    categoria: Optional[str] = Field(None, min_length=1, max_length=60)
    data: Optional[date] = None
    descricao: Optional[str] = Field(None, max_length=200)
    author: Optional[str] = Field(None, max_length=40)
    channel: Optional[ChannelType] = None
    source: Optional[str] = Field(None, max_length=40, description="[DEPRECATED]")
    vencimento: Optional[str] = Field(None, max_length=20)

    @field_validator("valor", mode="before")
    @classmethod
    def parse_money(cls, v):
        if v is None:
            return v
        return to_decimal(v)

    @field_validator("descricao", "categoria", "source", "author", "vencimento", mode="before")
    @classmethod
    def clean_control_chars(cls, v):
        return sanitize_text(v)

class TransactionResponse(TransactionBase):
    id: int

    class Config:
        from_attributes = True

class FinancialSummary(BaseModel):
    total_receitas: MoneyDecimal
    total_despesas_fixas: MoneyDecimal
    total_despesas_variaveis: MoneyDecimal
    total_despesas: MoneyDecimal
    saldo_livre: MoneyDecimal

class CategoryMetric(BaseModel):
    categoria: str
    total: MoneyDecimal
    percentual: float

class MetricsResponse(BaseModel):
    receitas_totais: MoneyDecimal
    contas_fixas: MoneyDecimal
    gastos_whatsapp: MoneyDecimal
    total_despesas: MoneyDecimal
    saldo_livre: MoneyDecimal
    total_transacoes: int
    categorias: List[CategoryMetric]

class MessageParseRequest(BaseModel):
    message: str

class MessageParseResponse(BaseModel):
    tipo: str
    valor: MoneyDecimal
    categoria: str
    descricao: str
