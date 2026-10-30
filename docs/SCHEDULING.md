# Agendador Idempotente por Ticks Externos

Este documento detalha o funcionamento, configuração e boas práticas do agendador do FinTrack.

---

## 1. Contexto e Arquitetura

O FinTrack roda no ambiente serverless / free-tier do **Render**. Nesse plano, o serviço hiberna após períodos de inatividade para economizar recursos.

Por conta disso, agendadores tradicionais que rodam em segundo plano dentro do mesmo processo (como APScheduler, cron interno ou loops com `asyncio.sleep`) são inadequados:
1. **Perda de disparos durante a hibernação:** Se a aplicação estiver dormindo às 21h30 (horário do relatório noturno), o evento simplesmente não dispara.
2. **Duplicações pós-reinício:** Caso o contêiner reinicie ou múltiplos workers subam, estados em memória são reinicializados, disparando relatórios duplicados.

### Solução: Disparo Externo + Idempotência no Banco

O modelo adotado é baseado em **Tick Externo**:
1. Um serviço de cron externo gratuito (ex.: [cron-job.org](https://cron-job.org)) faz chamadas periódicas (a cada 10 a 15 minutos) para:
   ```http
   POST /internal/jobs/tick
   X-Admin-Token: <seu_ADMIN_TOKEN>
   ```
2. A aplicação acorda no fuso horário oficial de **São Paulo (`America/Sao_Paulo`, UTC-3)**.
3. Cada tarefa devida é reivindicada de forma atômica no banco de dados na tabela `job_runs` com restrição de unicidade `(job_name, run_key)`.
4. Mesmo que o tick rode a cada 10 minutos, o relatório noturno só é enviado **exatamente uma vez por dia**, e o semanal **uma vez por semana**.

---

## 2. Tarefas e Regras de Disparo

| Job | Janela de Execução (Horário de SP) | Formato da `run_key` | Descrição |
|---|---|---|---|
| `relatorio_diario` | A partir das 21:30 até 23:59 | `YYYY-MM-DD` | Gera o resumo financeiro diário e envia ao grupo do WhatsApp. |
| `relatorio_semanal` | Sábados, a partir das 22:00 até 23:59 | `YYYY-Www` (Semana ISO) | Consolida os gastos e saldo da semana e envia ao grupo. |
| `reprocess_due` | A cada tick | UUID / execução | Reprocessa mensagens do WhatsApp pendentes com backoff exponencial. |
| `purge_old` | Madrugada (01:00 às 05:00) | `purge-YYYY-MM-DD` | Remove mensagens processadas com mais de 30 dias. |
| `ensure_recurrences` | Primeiro tick do dia | `recurrences-YYYY-MM` | Materializa de forma idempotente despesas recorrentes do mês. |

### Recuperação de Falhas e Travamentos
Se um job for interrompido por um reinício inesperado do contêiner e ficar em status `running` por mais de 10 minutos, o próximo tick detecta o travamento e retoma a execução (até no máximo 3 tentativas). Caso exceda 3 tentativas, o status é marcado como `failed`.

---

## 3. Configuração do Cron Externo (cron-job.org)

O [cron-job.org](https://cron-job.org) é um serviço gratuito e confiável para acordar o backend e processar os ticks.

### Passo a Passo:
1. Crie uma conta gratuita no [cron-job.org](https://cron-job.org).
2. Clique em **Create Cronjob**.
3. Configure os seguintes campos:
   - **Title:** `FinTrack Tick Agendador`
   - **URL:** `https://<seu-app-no-render>.onrender.com/internal/jobs/tick`
   - **Schedule:** A cada 10 ou 15 minutos (ex.: `*/15 * * * *`).
   - **Request Method:** `POST`
   - **Headers:**
     - Adicione a chave: `X-Admin-Token`
     - Valor: O mesmo valor configurado na variável de ambiente `ADMIN_TOKEN` do seu app no Render.
4. Salve o job.

> [!NOTE]
> **Cold Start no Render (Timeout do 1º Tick):**
> Quando o Render está hibernando, a primeira requisição pode levar de 30 a 50 segundos para subir o contêiner. Alguns serviços externos podem reportar um timeout (504/timeout) no primeiro tick. Isso é esperado: o contêiner acorda, processa a fila, e o próximo tick já responderá rapidamente em milissegundos.

---

## 4. Disparo Manual de Jobs

Você pode acionar qualquer job manualmente a qualquer momento, autenticando via header `X-Admin-Token`:

```bash
# Rodar todos os jobs devidos agora:
curl -X POST https://<seu-app>.onrender.com/internal/jobs/tick \
     -H "X-Admin-Token: <seu_ADMIN_TOKEN>"

# Forçar o envio do relatório diário:
curl -X POST https://<seu-app>.onrender.com/internal/jobs/relatorio_diario \
     -H "X-Admin-Token: <seu_ADMIN_TOKEN>"

# Forçar o envio do relatório semanal:
curl -X POST https://<seu-app>.onrender.com/internal/jobs/relatorio_semanal \
     -H "X-Admin-Token: <seu_ADMIN_TOKEN>"
```

*(As rotas legadas `/api/relatorio-diario/disparar` e `/api/relatorio-semanal/disparar` continuam funcionando para retrocompatibilidade).*

---

## 5. Por que NÃO usar GitHub Actions Cron para Ticks Frequentes?

Um workflow agendado (`schedule: - cron: '*/15 * * * *'`) no GitHub Actions **NÃO** é recomendado para esse caso:
- **Consumo de Minutos Gratuitos:** Contas gratuitas do GitHub possuem cota de 2.000 minutos/mês para repositórios privados. Rodar a cada 15 minutos consumiria ~2.880 minutos/mês, esgotando sua cota antes da metade do mês.
- **Jitter e Atrasos:** No GitHub Actions, crons agendados podem atrasar horas durante picos de carga.

Disponibilizamos um workflow com acionamento manual (`workflow_dispatch`) em `.github/workflows/scheduled-tick.yml` apenas para fins de teste ou trigger manual via CI/CD.
