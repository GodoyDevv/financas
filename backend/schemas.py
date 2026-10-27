import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from backend.dates_and_money import to_decimal

# Tipo serializado como float nativo em JSON para preservar compatibilidade estrita com o frontend
MoneyDecimal = Annotated[
    Decimal,
    PlainSerializer(
        lambda x: float(x) if x is not None else 0.0, return_type=float, when_used="json"
    ),
]


def sanitize_text(value: str | None) -> str | None:
    """Remove caracteres de controle ASCII perigosos preservando quebras e espaços normais."""
    if value is None:
        return None
    # Remove caracteres de controle C0/C1 exceto tabs, newlines e espaços
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", "", str(value))
    return cleaned.strip()


TipoTransacao = Literal["receita", "despesa_fixa", "despesa_variavel"]
ChannelType = Literal["whatsapp_text", "whatsapp_audio", "dashboard", "api", "system", "unknown"]


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=60, description="Nome da categoria")
    tipo: Literal["despesa", "receita"] = Field("despesa", description="Tipo da categoria")
    budget: MoneyDecimal | None = Field(
        None, ge=0, le=1_000_000, description="Orçamento mensal planejado"
    )
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
    name: str | None = Field(None, min_length=1, max_length=60)
    budget: MoneyDecimal | None = Field(None, ge=0, le=1_000_000)
    ativo: bool | None = None

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
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    nome: str
    tipo: str
    budget: MoneyDecimal | None = None
    ativo: bool
    gasto_mes: MoneyDecimal = Decimal("0.00")
    percentual_budget: float | None = None


class RecurrenceBase(BaseModel):
    tipo: Literal["receita", "despesa_fixa"] = Field(
        ..., description="Tipo da recorrência: receita ou despesa_fixa"
    )
    descricao: str = Field(..., min_length=1, max_length=200, description="Descrição da regra")
    valor: MoneyDecimal = Field(..., gt=0, le=1_000_000, description="Valor recorrente mensal")
    categoria: str = Field(..., min_length=1, max_length=60, description="Nome da categoria")
    author: str | None = Field(None, max_length=40)
    dia_do_mes: int = Field(..., ge=1, le=31, description="Dia do mês para vencimento/lançamento")
    inicio: date = Field(..., description="Data de início (mês inicial)")
    fim: date | None = Field(
        None, description="Data limite inclusive (ou null para tempo indeterminado)"
    )
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
    descricao: str | None = Field(None, max_length=200)
    valor: MoneyDecimal | None = Field(None, gt=0, le=1_000_000)
    categoria: str | None = Field(None, min_length=1, max_length=60)
    author: str | None = Field(None, max_length=40)
    dia_do_mes: int | None = Field(None, ge=1, le=31)
    ativo: bool | None = None
    fim: date | None = None

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
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: str
    descricao: str
    valor: MoneyDecimal
    category_id: int
    categoria: str
    author: str | None = None
    dia_do_mes: int
    inicio: date
    fim: date | None = None
    ativo: bool


class TransactionBase(BaseModel):
    tipo: TipoTransacao = Field(
        ..., description="Tipo do lançamento: receita, despesa_fixa ou despesa_variavel"
    )
    valor: MoneyDecimal = Field(
        ..., gt=0, le=1_000_000, description="Valor do lançamento entre R$ 0,01 e R$ 1.000.000,00"
    )
    categoria: str = Field(
        ..., min_length=1, max_length=60, description="Categoria do lançamento (máx 60 caracteres)"
    )
    category_id: int | None = Field(None, description="ID da entidade Category associada")
    parcela_grupo_id: str | None = Field(
        None, max_length=36, description="UUID do grupo de parcelamento"
    )
    parcela_num: int | None = Field(None, ge=1, description="Número da parcela atual")
    parcela_total: int | None = Field(None, ge=1, description="Total de parcelas do grupo")
    recurrence_id: int | None = Field(None, description="ID da regra de recorrência vinculada")
    competencia: date | None = Field(
        None, description="Primeiro dia do mês da competência da recorrência"
    )
    editado_manual: bool | None = Field(
        False, description="Indica se a instância foi editada manualmente"
    )
    data: date
    descricao: str | None = Field(
        None, max_length=200, description="Descrição do lançamento (máx 200 caracteres)"
    )
    author: str | None = Field(
        None, max_length=40, description="Autor do lançamento (ex: Bruno, Letícia)"
    )
    channel: ChannelType | None = Field("unknown", description="Canal de entrada do lançamento")
    source: str | None = Field(
        None, max_length=40, description="[DEPRECATED] Mantido para compatibilidade reversa"
    )
    vencimento: str | None = Field(
        None, max_length=20, description="Dia de vencimento (máx 20 caracteres)"
    )

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
    parcelas: int | None = Field(1, ge=1, le=60, description="Quantidade de parcelas (padrão 1)")


class TransactionUpdate(BaseModel):
    tipo: TipoTransacao | None = Field(
        None, description="Tipo do lançamento: receita, despesa_fixa ou despesa_variavel"
    )
    valor: MoneyDecimal | None = Field(
        None, gt=0, le=1_000_000, description="Valor do lançamento entre R$ 0,01 e R$ 1.000.000,00"
    )
    categoria: str | None = Field(None, min_length=1, max_length=60)
    data: date | None = None
    descricao: str | None = Field(None, max_length=200)
    author: str | None = Field(None, max_length=40)
    channel: ChannelType | None = None
    source: str | None = Field(None, max_length=40, description="[DEPRECATED]")
    vencimento: str | None = Field(None, max_length=20)

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
    model_config = ConfigDict(from_attributes=True)

    id: int


class FinancialSummary(BaseModel):
    total_receitas: MoneyDecimal
    total_despesas_fixas: MoneyDecimal
    total_despesas_variaveis: MoneyDecimal
    total_despesas: MoneyDecimal
    saldo_livre: MoneyDecimal


class CategoryMetric(BaseModel):
    categoria: str
    category_id: int | None = None
    total: MoneyDecimal
    budget: MoneyDecimal | None = None
    percentual: float
    percentual_budget: float | None = None


class MetricsResponse(BaseModel):
    receitas_totais: MoneyDecimal
    contas_fixas: MoneyDecimal
    gastos_whatsapp: MoneyDecimal
    total_despesas: MoneyDecimal
    saldo_livre: MoneyDecimal
    total_transacoes: int
    categorias: list[CategoryMetric]


class MessageParseRequest(BaseModel):
    message: str


class MessageParseResponse(BaseModel):
    tipo: str
    valor: MoneyDecimal
    categoria: str
    descricao: str
    parcelas: int = 1
    confianca: str = "alta"
    motivos: list[str] = Field(default_factory=list)
