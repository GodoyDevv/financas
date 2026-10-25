# Plano de Execução: Recorrências Explícitas e Totais Escopados por Mês

## Fase 0: Mapeamento de Pontos com "OR por tipo" ou Cálculos de Mês
1. `backend/routes.py` (linha 57): `get_transactions` filtra `or_(Transaction.tipo.in_(["receita", "despesa_fixa"]), (Transaction.data >= inicio) & (Transaction.data < fim))`.
2. `backend/routes.py` (linha 280): `get_summary` calcula totais com `or_(Transaction.tipo.in_(["receita", "despesa_fixa"]), (Transaction.data >= inicio) & (Transaction.data < fim))`.
3. `backend/routes.py` (linha 335): `get_metrics` calcula totais gerais com `or_(Transaction.tipo.in_(["receita", "despesa_fixa"]), (Transaction.data >= inicio) & (Transaction.data < fim))`.
4. `backend/routes.py` (linha 377): `get_metrics` distribuição de categorias com `or_(Transaction.tipo == "despesa_fixa", (Transaction.data >= inicio) & (Transaction.data < fim))`.
5. `backend/routes.py` (linha 447): `get_categories` gasto por categoria com `or_(Transaction.tipo == "despesa_fixa", (Transaction.data >= inicio) & (Transaction.data < fim))`.
6. `backend/webhook.py` (linha 351): invoca `get_metrics(mes=mes_iso, db=db)` para o Atlas informar saldo livre (será mantido unificado e fiel ao mês).
7. `backend/scheduler.py`: já filtra por datas estritas `data == data_alvo` e `primeiro_dia_mes <= data <= data_alvo`.
8. `index.html`: consome os endpoints `/api/metrics` e `/api/transactions?mes=YYYY-MM` via API.

## Etapas de Implementação
1. **Modelos (`backend/models.py`)**:
   - Criar `Recurrence`: `id`, `tipo` ("receita"|"despesa_fixa"), `descricao`, `valor` (Numeric 12,2), `category_id` (FK categories.id), `author` (String 40), `dia_do_mes` (int 1-31), `inicio` (Date), `fim` (Date NULL), `ativo` (Boolean, default True), `created_at` (DateTime).
   - Atualizar `Transaction`: `recurrence_id` (FK recurrences.id NULL), `competencia` (Date NULL, 1º dia do mês), `editado_manual` (Boolean, default False). Índice único `("recurrence_id", "competencia")`.
2. **Serviço de Materialização Preguiçosa (`backend/services/recurrences.py`)**:
   - `ensure_recurrences(db: Session, mes: str)`: extrai 1º dia do mês e calcula limite (máx mês atual + 12 meses). Busca `Recurrence` ativas onde `inicio <= primeiro_dia_mes` e `(fim IS NULL OR fim >= primeiro_dia_mes)`.
   - Para cada recorrência, gera data com clamp `dia_do_mes` no mês e tenta inserir `Transaction(recurrence_id=r.id, competencia=primeiro_dia_mes, editado_manual=False)`. Trata `IntegrityError` como "já existe" de forma segura (corrida).
3. **Migration Alembic (`migrations/versions/XXXX_explicit_recurrences.py`)**:
   - Cria tabela `recurrences` e adiciona colunas `recurrence_id`, `competencia`, `editado_manual` e índice único em `transactions`. Totalmente idempotente e reversível.
4. **Atualizar Rotas (`backend/routes.py`)**:
   - Remover **TODOS** os `or_` identificados na Fase 0. Toda agregação e listagem com `?mes=YYYY-MM` invoca `ensure_recurrences(db, mes)` e filtra estritamente por `(Transaction.data >= inicio) & (Transaction.data < fim)`.
   - CRUD `/api/recurrences`: GET, POST, PATCH (vale do mês atual em diante: atualiza regra e instâncias futuras não editadas manualmente), DELETE (encerra regra em `fim = mês anterior` e remove instâncias futuras não editadas).
   - `PUT /api/transactions/{id}`: marca `editado_manual = True` se for instância de recorrência.
5. **Integração WhatsApp/Webhook (`backend/webhook.py`, `backend/parser.py`)**:
   - Se mensagem for `despesa_fixa`: cria `Recurrence` com `inicio = mês atual` e gera a instância do mês.
   - Se mensagem for `receita` e contiver "todo mês", "mensal" ou "fixo"/"fixa": cria `Recurrence` e instância.
   - Retorno do Atlas destaca `"recorrente"`.
6. **Script CLI de Migração de Legados (`scripts/migrate_legacy_fixed.py`)**:
   - `--dry-run` por padrão; lista 20 registros legados propondo recorrente ou avulsa.
   - `--apply --decisions decisions.json`: exige decisões para todos os IDs; se faltar algum, aborta.
   - Gerar `decisions.json` de exemplo.
7. **Testes Automatizados (`tests/test_recurrences.py`)**:
   - Renda de novembro não aparece em outubro.
   - Recorrência de outubro aparece em out/nov/dez e não em set; clamp de dia 31 em fev/abr.
   - Chamadas concorrentes de `ensure_recurrences` não duplicam.
   - PATCH altera futuras não editadas e preserva passadas/editadas.
   - Dry-run e validação do script CLI.
