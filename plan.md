# Plano de Execução: Categorias como Entidade de Primeira Classe com Orçamentos

1. Criar `backend/categories.py`:
   - Lista canônica de categorias (`name`, `tipo`, `ordem`).
   - Função `normalize_category_name(name: str) -> str` (NFKD, lower, trim, remoção de diacríticos e múltiplos espaços).
   - Dicionário de aliases legados mapeando para o nome canônico (ex: "moradia (aluguel/condominio)" -> "Moradia", "contas de consumo (luz/agua)" -> "Contas de Consumo").
   - Fallback para "Outros" em despesas e "Salário/Renda" em receitas.
   - Helper `resolve_category(name: str) -> Optional[dict]`.

2. Atualizar Modelos (`backend/models.py`):
   - `Category`: `id`, `name` (String, nullable=False), `normalized_name` (String, unique=True, index=True, nullable=False), `tipo` (String(20), nullable=False, default="despesa"), `budget` (Numeric(12, 2), nullable=True), `ativo` (Boolean, default=True, nullable=False), `created_at` (DateTime, default=datetime.utcnow). Adicionar propriedade `@property def nome(self): return self.name`.
   - `Transaction`: `category_id` (Integer, ForeignKey("categories.id"), nullable=False, index=True), manter `categoria` String nullable=False (dual-write / expand-contract). Adicionar índice `ix_transactions_category_id`.

3. Migration Alembic Reversível e Idempotente (`migrations/versions/XXXX_categories_as_first_class_entity.py`):
   - Adicionar colunas `normalized_name`, `tipo`, `ativo` em `categories` e alterar `budget` para `Numeric(12,2)` (suportando Postgres e batch mode em SQLite).
   - Inserir as categorias canônicas (caso não existam).
   - Backfill em `transactions`: iterar sobre transações ou agrupar por `categoria`, normalizar via aliases/canônicas; se houver categoria desconhecida, criar nova categoria na tabela `categories` com o nome original (sem perda de dados) e logar.
   - Atualizar `transactions.category_id` para todas as linhas.
   - Criar índice em `transactions.category_id` se não existir.
   - Alterar `transactions.category_id` para `nullable=False`.
   - Downgrade: permitir `transactions.category_id` nullable, reverter alterações em `categories`.

4. Schemas Pydantic (`backend/schemas.py`):
   - `CategoryBase`, `CategoryCreate`, `CategoryUpdate`, `CategoryResponse` (com `id`, `nome`, `name`, `tipo`, `budget`, `ativo`, `gasto_mes`, `percentual_budget`).
   - `TransactionBase`: `categoria: str`, `category_id: Optional[int]`.

5. Rotas e Validação (`backend/routes.py`):
   - Validação na criação/edição via dashboard: se `categoria` informada não pertencer à lista canônica/ativa, retornar HTTP 422 com lista válida de categorias.
   - Atribuir `category_id` e manter `categoria` sincronizada com `category.name`.
   - Implementar `GET /api/categories?mes=YYYY-MM`: listar categorias com seus orçamentos, total gasto no mês e percentual atingido.
   - Implementar `PUT /api/categories/{id}`: atualizar `budget`, `ativo` e `name` (com recálculo de `normalized_name`).
   - Atualizar `/api/metrics` e `/api/summary` com informações de orçamento e percentuais.

6. Webhook e Parser (`backend/webhook.py`, `backend/parser.py`):
   - Parser importa categorias canônicas de `backend/categories.py`.
   - No webhook e parser: resolver categoria; valores não identificados caem com segurança em "Outros" (fallback não quebra).
   - Webhook salva `category_id` ao persistir transação.

7. Frontend (`index.html`):
   - Datalist de categorias alinhado às categorias canônicas.
   - Exibição de orçamentos e barras de progresso respeitando o retorno da API.

8. Testes Automatizados (`tests/test_categories.py`):
   - Testar normalização, aliases, 422 no dashboard para categoria inválida, fallback seguro para "Outros" no webhook/parser, endpoints `GET /api/categories` com `mes` e `PUT /api/categories/{id}`, cálculo de orçamento e reversibilidade da migration.
