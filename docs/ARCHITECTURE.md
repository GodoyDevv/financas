# Arquitetura do Sistema (Backend)

O backend do FinTrack segue o padrão arquitetural em camadas bem delimitadas, garantindo independência de regras de negócio, testabilidade determinística e acoplamento estritamente unidirecional.

```mermaid
flowchart TD
    subgraph UI_Clients[Clientes Externos]
        Browser["Dashboard Web (SPA / index.html)"]
        WhatsApp["WhatsApp / Evolution API (Webhook)"]
    end

    subgraph API_Layer[Camada de Apresentação (backend/api/)]
        MainApp["FastAPI App (main.py)"]
        RoutesAggr["Routes Aggregator (backend/routes.py)"]
        TxRouter["Transactions Router (backend/api/transactions.py)"]
        SumRouter["Summary & Metrics Router (backend/api/summary.py)"]
        CatRouter["Categories Router (backend/api/categories.py)"]
        RecRouter["Recurrences Router (backend/api/recurrences.py)"]
        ParseRouter["Parser Router (backend/api/parser.py)"]
        WebhookRouter["Webhook Router (backend/api/webhook ou backend/webhook.py)"]
    end

    subgraph Services_Layer[Camada de Aplicação / Casos de Uso (backend/services/)]
        TxService["TransactionService"]
        SumService["SummaryService (Cálculo Único de Totais e Saldos)"]
        CatService["CategoryService"]
        RecService["RecurrenceService (Materialização Preguiçosa)"]
        InstService["InstallmentService (Identidade UUID de Parcelas)"]
        MsgProcService["MessageProcessingService"]
        ReportsService["ReportsService (Relatórios Diários e Semanais)"]
    end

    subgraph Repositories_Layer[Camada de Acesso a Dados (backend/repositories/)]
        TxRepo["TransactionRepository"]
        CatRepo["CategoryRepository"]
        RecRepo["RecurrenceRepository"]
    end

    subgraph Domain_Layer[Núcleo de Domínio (backend/domain/)]
        MoneyDomain["money.py (Validação e Conversão de Moeda Decimal)"]
        DatesDomain["dates.py (Validação estrita de Mês YYYY-MM e Fuso SP)"]
    end

    subgraph Integrations_Layer[Integrações Externas (backend/integrations/)]
        GeminiClient["gemini.py (Google Gemini API / Whisper Fallback)"]
        EvolutionClient["evolution.py (Evolution API / WhatsApp HTTP Client)"]
        Templates["templates.py (WhatsApp Markdown Formatter)"]
    end

    subgraph DB_Layer[Banco de Dados e Persistência (backend/db/)]
        DBSession["session.py (Engine e SessionLocal)"]
        DBModels["models.py (SQLAlchemy 2.0 Mapped Models)"]
        PostgreSQL[("PostgreSQL / SQLite")]
    end

    Browser --> MainApp
    WhatsApp --> WebhookRouter

    MainApp --> RoutesAggr
    RoutesAggr --> TxRouter
    RoutesAggr --> SumRouter
    RoutesAggr --> CatRouter
    RoutesAggr --> RecRouter
    RoutesAggr --> ParseRouter

    TxRouter --> TxService
    SumRouter --> SumService
    CatRouter --> CatService
    RecRouter --> RecService
    WebhookRouter --> MsgProcService

    MsgProcService --> InstService
    MsgProcService --> SumService
    ReportsService --> SumService
    MsgProcService --> Templates
    MsgProcService --> EvolutionClient

    TxService --> TxRepo
    TxService --> CatRepo
    SumService --> TxRepo
    SumService --> CatRepo
    CatService --> CatRepo
    CatService --> TxRepo
    RecService --> RecRepo
    RecService --> TxRepo
    RecService --> CatRepo

    TxService --> MoneyDomain
    TxService --> DatesDomain
    SumService --> DatesDomain
    SumService --> MoneyDomain
    CatService --> MoneyDomain
    RecService --> DatesDomain

    TxRepo --> DBModels
    CatRepo --> DBModels
    RecRepo --> DBModels

    DBSession --> PostgreSQL
    DBModels --> DBSession
```

## Regras de Dependência e Camadas

1. **`backend/domain/`**:
   - Contém funções puras, matemáticas e de manipulação temporal (`money.py`, `dates.py`).
   - Não depende de nenhuma biblioteca de framework (FastAPI, SQLAlchemy) nem de outros módulos internos da aplicação.

2. **`backend/db/`**:
   - Contém a declaração dos modelos mapeados via SQLAlchemy 2.0 (`Mapped[...]`, `mapped_column`) e configuração de sessão/engine.

3. **`backend/repositories/`**:
   - Executa consultas atômicas com a sessão SQLAlchemy (`select`, `where`, `flush`).
   - Não contém regras de negócio de alto nível nem comita transações (`db.commit()`).

4. **`backend/services/`**:
   - Implementa os casos de uso do sistema (regras de parcelamento, materialização de recorrências, sincronização de orçamentos, cálculo de saldos).
   - O cálculo de saldo e métricas financeiras é centralizado exclusivamente em `SummaryService`, compartilhado entre o dashboard web, o webhook e os relatórios noturnos/semanais.
   - Não importa o framework FastAPI nem lida com ciclo de vida de requisição HTTP.
   - Não efetua commits de banco de dados; a confirmação transacional (`db.commit()`) cabe ao chamador (camada de API ou serviço background).

5. **`backend/integrations/`**:
   - Encapsula as chamadas de rede a APIs de terceiros (Gemini, OpenAI, Evolution API) e formatação de saída para canais externos.
   - Não depende das camadas de apresentação (`backend/api/`) ou regras de aplicação (`backend/services/`).

6. **`backend/api/`**:
   - Routers FastAPI finos e especializados (`transactions.py`, `summary.py`, `categories.py`, `recurrences.py`, `parser.py`).
   - Realiza validação de parâmetros de entrada, injeção de dependência (`get_db`, autenticação), invocação de serviços e `db.commit()`.
   - O arquivo `backend/routes.py` atua como agregador unificado, montando todos os sub-routers sob o prefixo `/api`.

7. **Testes e Garantias Contínuas**:
   - Verificação automática da hierarquia arquitetural via AST em `tests/test_architecture.py`.
   - Testes de caracterização e regressão de saída em `tests/test_characterization_snapshots.py`.
   - Cobertura de testes mantida acima do limite exigido de 71% (atualmente ~80%).
