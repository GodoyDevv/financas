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

class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=60, description="Nome da categoria")
    tipo: Literal["despesa", "receita"] = Field("despesa", description="Tipo da categoria")
    budget: Optional[MoneyDecimal] = Field(None, ge=0, le=1_000_000, description="Orçamento mensal planejado")
    ativo: bool = Field(True, description="Se a categoria está ativa")

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, v):
        return sanitize_text(v)

    @field_validator("budget", mode="before")
    @classmethod
    def parse_budget(cls, v):
        if v is None:
            return None
        return to_decimal(v)

class CategoryCreate(CategoryBase):
    pass

class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=60)
    budget: Optional[MoneyDecimal] = Field(None, ge=0, le=1_000_000)
    ativo: Optional[bool] = None

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, v):
        return sanitize_text(v)

    @field_validator("budget", mode="before")
    @classmethod
    def parse_budget(cls, v):
        if v is None:
            return None
        return to_decimal(v)

class CategoryResponse(BaseModel):
    id: int
    name: str
    nome: str
    tipo: str
    budget: Optional[MoneyDecimal] = None
    ativo: bool
    gasto_mes: MoneyDecimal = Decimal("0.00")
    percentual_budget: Optional[float] = None

    class Config:
        from_attributes = True

class RecurrenceBase(BaseModel):
    tipo: Literal["receita", "despesa_fixa"] = Field(..., description="Tipo da recorrência: receita ou despesa_fixa")
    descricao: str = Field(..., min_length=1, max_length=200, description="Descrição da regra")
    valor: MoneyDecimal = Field(..., gt=0, le=1_000_000, description="Valor recorrente mensal")
    categoria: str = Field(..., min_length=1, max_length=60, description="Nome da categoria")
    author: Optional[str] = Field(None, max_length=40)
    dia_do_mes: int = Field(..., ge=1, le=31, description="Dia do mês para vencimento/lançamento")
    inicio: date = Field(..., description="Data de início (mês inicial)")
    fim: Optional[date] = Field(None, description="Data limite inclusive (ou null para tempo indeterminado)")
    ativo: bool = Field(True, description="Se a recorrência está ativa")

    @field_validator("valor", mode="before")
    @classmethod
    def parse_money(cls, v):
        if v is None:
            return v
        return to_decimal(v)

    @field_validator("descricao", "categoria", "author", mode="before")
    @classmethod
    def clean_control_chars(cls, v):
        return sanitize_text(v)

class RecurrenceCreate(RecurrenceBase):
    pass

class RecurrenceUpdate(BaseModel):
    descricao: Optional[str] = Field(None, max_length=200)
    valor: Optional[MoneyDecimal] = Field(None, gt=0, le=1_000_000)
    categoria: Optional[str] = Field(None, min_length=1, max_length=60)
    author: Optional[str] = Field(None, max_length=40)
    dia_do_mes: Optional[int] = Field(None, ge=1, le=31)
    ativo: Optional[bool] = None
    fim: Optional[date] = None

    @field_validator("valor", mode="before")
    @classmethod
    def parse_money(cls, v):
        if v is None:
            return v
        return to_decimal(v)

    @field_validator("descricao", "categoria", "author", mode="before")
    @classmethod
    def clean_control_chars(cls, v):
        return sanitize_text(v)

class RecurrenceResponse(BaseModel):
    id: int
    tipo: str
    descricao: str
    valor: MoneyDecimal
    category_id: int
    categoria: str
    author: Optional[str] = None
    dia_do_mes: int
    inicio: date
    fim: Optional[date] = None
    ativo: bool

    class Config:
        from_attributes = True

class TransactionBase(BaseModel):
    tipo: TipoTransacao = Field(..., description="Tipo do lançamento: receita, despesa_fixa ou despesa_variavel")
    valor: MoneyDecimal = Field(..., gt=0, le=1_000_000, description="Valor do lançamento entre R$ 0,01 e R$ 1.000.000,00")
    categoria: str = Field(..., min_length=1, max_length=60, description="Categoria do lançamento (máx 60 caracteres)")
    category_id: Optional[int] = Field(None, description="ID da entidade Category associada")
    parcela_grupo_id: Optional[str] = Field(None, max_length=36, description="UUID do grupo de parcelamento")
    parcela_num: Optional[int] = Field(None, ge=1, description="Número da parcela atual")
    parcela_total: Optional[int] = Field(None, ge=1, description="Total de parcelas do grupo")
    recurrence_id: Optional[int] = Field(None, description="ID da regra de recorrência vinculada")
    competencia: Optional[date] = Field(None, description="Primeiro dia do mês da competência da recorrência")
    editado_manual: Optional[bool] = Field(False, description="Indica se a instância foi editada manualmente")
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
    parcelas: Optional[int] = Field(1, ge=1, le=60, description="Quantidade de parcelas (padrão 1)")

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
    category_id: Optional[int] = None
    total: MoneyDecimal
    budget: Optional[MoneyDecimal] = None
    percentual: float
    percentual_budget: Optional[float] = None

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
    parcelas: int = 1
    confianca: str = "alta"
    motivos: List[str] = Field(default_factory=list)

