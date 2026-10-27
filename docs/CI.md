# 🛡️ Guia de Configuração Manual do GitHub (Branch Protection)

Este documento detalha as configurações de governança e segurança que devem ser ativadas manualmente nas configurações do repositório no GitHub (`Settings > Branches`), uma vez que agentes de automação e workflows de CI não possuem permissões administrativas para alterar regras de repositório.

---

## 🎯 Objetivo
Garantir que nenhum commit entre diretamente na branch `main` sem passar por validação de pull request e aprovação de todos os portões de qualidade do CI.

---

## 📋 Passo a Passo para Ativação da Branch Protection

1. Acesse o repositório no GitHub:
   - Navegue até **Settings** (Configurações do repositório).
2. No menu lateral esquerdo, clique em **Branches** (na seção *Code and automation*).
3. Em **Branch protection rules**, clique no botão **Add branch ruleset** ou **Add rule**.
4. Configure os seguintes campos:

### 1. Nome do Padrão da Branch
- **Branch name pattern**: `main`

### 2. Exigir Pull Request antes de Merge
- Marque: `Require a pull request before merging`.
- *(Opcional)*: `Require approvals` (se trabalhar em equipe ou desejar revisão explícita).
- Marque: `Dismiss stale pull request approvals when new commits are pushed`.

### 3. Exigir que os Portões de Qualidade (Status Checks) Passem
- Marque: `Require status checks to pass before merging`.
- Marque: `Require branches to be up to date before merging` (garante que o código foi testado com a versão mais recente da `main`).
- Na barra de busca de status checks (**Status checks that are required**), pesquise e selecione exatamente os 4 checks obrigatórios definidos no pipeline do CI:
  - `Lint & Format Check (Ruff)` (Job: `lint`)
  - `Static Type Check (Mypy)` (Job: `typecheck`)
  - `Unit & Integration Tests (SQLite)` (Job: `test`)
  - `PostgreSQL Migration & Integration Tests` (Job: `test-postgres`)
  - *(Opcional recomendado)*: `Dependencies Lock Sync` (Job: `deps-sync`)
  - *(Opcional recomendado)*: `Gitleaks Security Scan` (Workflow: `Secret Scan`)

### 4. Bloquear Forçar Push e Exclusão Acidental
- Marque: `Do not allow bypassing the above settings` (aplica as regras também a administradores).
- Garanta que `Allow force pushes` esteja **desmarcado**.
- Garanta que `Allow deletions` esteja **desmarcado**.

5. Clique em **Create** ou **Save changes** no final da página.

---

## 🔒 Auditoria de Dependências e Segurança
O repositório já conta com monitoramento automatizado contínuo:
- **Secret Scan (`secret-scan.yml`)**: Executa em cada push/PR para detectar vazamento de chaves ou senhas.
- **Security Audit (`security-audit.yml`)**: Roda semanalmente via cron (segundas-feiras 03h BRT) utilizando `pip-audit` contra as dependências do `uv.lock`.
- **Dependabot (`.github/dependabot.yml`)**: Monitora semanalmente atualizações de supply chain tanto para ações do GitHub quanto para pacotes Python.
