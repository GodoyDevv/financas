# Plano de Execução: Parcelamentos com Identidade (UUID) e Exclusão sem Regex

1. Atualizar `.gitignore`:
   - Adicionar `scripts/out/` para garantir que relatórios CSV de auditoria nunca sejam commitados.

2. Configuração Única de Modo de Parcelamento:
   - Criar `backend/config.py` (ou `backend/installments_config.py`) com:
     `PARCELA_MODO: Literal["valor_da_parcela", "valor_total"] = "valor_da_parcela"`

3. Modelos SQLAlchemy (`backend/models.py`):
   - Adicionar colunas em `Transaction`:
     `parcela_grupo_id = Column(String(36), index=True, nullable=True)`
     `parcela_num = Column(Integer, nullable=True)`
     `parcela_total = Column(Integer, nullable=True)`
   - Adicionar `CheckConstraint` garantindo: ou todos 3 são nulos ou todos 3 são preenchidos com `1 <= parcela_num <= parcela_total`.
   - Adicionar `Index("uq_transactions_grupo_num", "parcela_grupo_id", "parcela_num", unique=True)`.

4. Serviço Único de Parcelamento (`backend/services/installments.py`):
   - Função `criar_parcelamento(db: Session, base_transaction_data: dict, parcelas: int, modo: Optional[str] = None) -> List[Transaction]`
   - Se `parcelas == 1`: cria transação normal com campos de parcela nulos.
   - Se `parcelas > 1`: gera `uuid4()`, calcula valores com `Decimal` (no modo `valor_total`, distribui centavos na 1ª parcela), calcula datas com clamp de fim de mês via `calendar.monthrange`, executa inserção atômica no banco (tudo ou nada).
   - Função helper `calcular_valores_parcelamento(valor: Decimal, parcelas: int, modo: str) -> Tuple[Decimal, Decimal, Decimal]` (valor_parcela, valor_total, valor_primeira_parcela se diferente).
   - Atualizar `format_atlas_confirmation` em `backend/atlas.py` para exibir `"3x de R$ 300,00 (total R$ 900,00)"`.

5. Migration Alembic Reversível (`migrations/versions/XXXX_installment_groups_with_identity.py`):
   - Adicionar colunas `parcela_grupo_id`, `parcela_num`, `parcela_total`, CheckConstraint e UniqueIndex.
   - Script de backfill seguro e geração de relatório CSV em `scripts/out/`:
     - Identificar grupos existentes somente com certeza absoluta (mesmo radical, valor, tipo, categoria, autor e meses consecutivos `1..N`).
     - Casos ambíguos ou incompletos são deixados sem grupo e gravados em `scripts/out/backfill_installments_ambiguous.csv`.
     - Casos associados com sucesso são gravados em `scripts/out/backfill_installments_grouped.csv`.
   - Downgrade: remove colunas e índices.

6. Exclusão e Schemas na API (`backend/routes.py`, `backend/schemas.py`):
   - `TransactionResponse` e `TransactionBase` expõem `parcela_grupo_id`, `parcela_num`, `parcela_total`.
   - `TransactionCreate` aceita `parcelas: Optional[int] = 1`. Se > 1, invoca `criar_parcelamento`.
   - `DELETE /api/transactions/{id}?escopo=uma|grupo|futuras` (padrão `"uma"`).
     - Remove completamente a busca por regex.
     - `"uma"`: apaga somente a transação com ID `{id}`.
     - `"grupo"`: se tiver `parcela_grupo_id`, apaga todas do grupo (`Transaction.parcela_grupo_id == existing.parcela_grupo_id`).
     - `"futuras"`: se tiver `parcela_grupo_id`, apaga da parcela atual em diante (`Transaction.parcela_grupo_id == existing.parcela_grupo_id AND Transaction.parcela_num >= existing.parcela_num`).
   - `backend/webhook.py`: passa a chamar `criar_parcelamento(...)` do serviço único.

7. Frontend (`index.html`):
   - Atualizar tabela e lista mobile para renderizar badge de parcelas (ex: `"2/3"`) com base em `t.parcela_num` e `t.parcela_total` (ou fallback seguro).
   - Modal de exclusão: 3 opções quando for parcelada: `"Só esta parcela"`, `"Esta e as próximas"`, `"Todas as parcelas"`, passando `?escopo=uma|futuras|grupo`.

8. Testes e Validação (`tests/test_installments.py`):
   - Colisão evitada: duas compras com mesma descrição/valor/tipo excluem apenas seu respectivo grupo sem afetar a outra.
   - Datas com clamp de fim de mês: 31/jan em 3x $\to$ 28 (ou 29)/fev e 31/mar.
   - Divisão de centavos em `valor_total`: 100 em 3x $\to$ 33,34 + 33,33 + 33,33.
   - Atomicidade da criação (rollback em caso de falha).
   - Backfill e exclusão por escopos (`uma`, `futuras`, `grupo`).
