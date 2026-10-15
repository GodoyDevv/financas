# 💸 FinTrack Intelligence

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/SQLite-07405E?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/SQLAlchemy-D71F00?style=for-the-badge&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy" />
  <img src="https://img.shields.io/badge/Status-Active-success?style=for-the-badge" alt="Status" />
</p>

<p align="center">
  <b>Sistema inteligente de alta precisão para controle financeiro pessoal, dashboards dinâmicos e automação de lançamentos via Webhook/WhatsApp.</b>
</p>

---

## 📌 Visão Geral

O **FinTrack Intelligence** foi desenvolvido para simplificar e automatizar a gestão financeira diária. Com uma arquitetura moderna baseada em **FastAPI** e **SQLAlchemy**, o sistema disponibiliza uma API RESTful completa, integração flexível para webhooks e uma interface web interativa e fluida servida nativamente.

---

## 🚀 Principais Funcionalidades

- **⚡ API RESTful Assíncrona e Rápida**: Construída com FastAPI e tipagem robusta via Pydantic.
- **📲 Automação via Webhooks**: Receptor dedicado e parser inteligente para capturar gastos e receitas (ideal para integrações com WhatsApp / n8n / Evolution API).
- **📊 Dashboard Interativo**: Interface frontend responsiva (`index.html`) servida diretamente na raiz da aplicação.
- **🗄️ Persistência com SQLite**: Banco relacional leve e sem complicações usando SQLAlchemy ORM.
- **🩺 Endpoint de Healthcheck**: Verificação de integridade da API e conectividade com a base de dados (`/health`).
- **🛡️ Documentação Interativa Automática**: OpenAPI/Swagger integrado diretamente pela rota `/docs`.

---

## 🛠️ Stack Tecnológica

| Camada | Tecnologia |
| :--- | :--- |
| **Backend** | Python 3.12+, FastAPI, Uvicorn |
| **ORM / Banco de Dados** | SQLAlchemy 2.x, SQLite |
| **Validação de Dados** | Pydantic v2 |
| **Frontend** | HTML5, CSS Moderno, JavaScript Vanilla |
| **HTTP Client / Utilitários** | HTTPX, Python-Multipart |

---

## 📂 Estrutura do Projeto

```plaintext
Finanças/
├── backend/
│   ├── database.py       # Configuração da engine do SQLAlchemy e sessão
│   ├── main.py           # Ponto de entrada FastAPI, CORS e montagem de rotas
│   ├── models.py         # Modelos de dados relacionais
│   ├── parser.py         # Parser inteligente para mensagens e webhooks
│   ├── routes.py         # Endpoints da API (CRUD e relatórios)
│   ├── schemas.py        # Schemas de validação e serialização Pydantic
│   └── webhook.py       # Rota especializada em ingestão de webhooks
├── .gitignore            # Regras de exclusão para Git (venv, logs, db)
├── builder.py            # Utilitário de automação e build
├── index.html            # Dashboard e interface web moderna
├── README.md             # Documentação oficial do repositório
└── requirements.txt      # Dependências do ecossistema Python
```

---

## ⚙️ Pré-requisitos e Instalação

### 1. Clonar o repositório
```bash
git clone https://github.com/GodoyDevv/financas.git
cd financas
```

### 2. Criar e ativar o ambiente virtual
```bash
# Windows
python -m venv venv
.\venv\Scripts\activate

# Linux / MacOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar as dependências
```bash
pip install -r requirements.txt
```

---

## ▶️ Como Executar

Inicie o servidor de desenvolvimento com o Uvicorn:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Após iniciar:
- **Painel Web**: Acesse [http://localhost:8000](http://localhost:8000)
- **Documentação Swagger (OpenAPI)**: Acesse [http://localhost:8000/docs](http://localhost:8000/docs)
- **Documentação Redoc**: Acesse [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 🤝 Autor

Desenvolvido por **[Godoy](https://github.com/GodoyDevv)**.

> *"Some trust in chariots, and some in horses, But we trust the name of The LORD our God."* — *Psalms 20:7*
