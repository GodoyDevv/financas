import os
import sqlite3
import tempfile
from unittest import mock

import pytest

os.environ["APP_PASSWORD"] = "StrongMasterPassword123!"
os.environ["SESSION_SECRET"] = "super_secret_session_key_with_at_least_32_chars_12345"
os.environ["ADMIN_TOKEN"] = "adm_secret_token_secure_98765"
os.environ["DEV_INSECURE_COOKIES"] = "0"
os.environ["WHATSAPP_GROUP_JID"] = "120363000000000000@g.us"
os.environ["WEBHOOK_SECRET"] = "webhook_secret_key_with_at_least_32_characters_12345"
os.environ["WHATSAPP_USER_BRUNO"] = "5511999998888"
os.environ["WHATSAPP_USER_LETICIA"] = "5511977776666"

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from backend.auth import COOKIE_NAME, create_session_token
from backend.categories import (
    normalize_category_name,
    resolve_canonical_name,
)
from backend.database import SessionLocal
from backend.main import app
from backend.models import Category, Transaction


@pytest.fixture
def auth_client():
    client = TestClient(app, base_url="https://testserver")
    token = create_session_token()
    client.cookies.set(COOKIE_NAME, token)
    return client


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_normalization_and_aliases():
    """Valida a remoção de acentos, minúsculas, trim e resolução de aliases."""
    # Variações de acento e caixa
    assert normalize_category_name("  Alimentação  ") == "alimentacao"
    assert normalize_category_name("SAÚDE") == "saude"
    assert normalize_category_name("Água") == "agua"
    assert normalize_category_name("Moradia (Aluguel/Condomínio)") == "moradia (aluguel/condominio)"

    # Resolução de aliases para os nomes canônicos oficiais
    assert resolve_canonical_name("mercado") == "Alimentação"
    assert resolve_canonical_name("supermercado") == "Alimentação"
    assert resolve_canonical_name("padaria") == "Alimentação"
    assert resolve_canonical_name("combustível") == "Transporte"
    assert resolve_canonical_name("gasolina") == "Transporte"
    assert resolve_canonical_name("uber") == "Transporte"
    assert resolve_canonical_name("aluguel") == "Moradia"
    assert resolve_canonical_name("Moradia (Aluguel/Condomínio)") == "Moradia"
    assert resolve_canonical_name("Contas de Consumo (Luz/Água)") == "Contas de Consumo"
    assert resolve_canonical_name("enel") == "Contas de Consumo"
    assert resolve_canonical_name("salario") == "Salário/Renda"
    assert resolve_canonical_name("farmácia") == "Saúde"
    assert resolve_canonical_name("faculdade") == "Educação"
    assert resolve_canonical_name("categoria_totalmente_inexistente_xyz") is None


def test_dashboard_rejects_unknown_category_with_422(auth_client: TestClient):
    """Garante que a escrita pelo dashboard/API rejeita categorias desconhecidas com HTTP 422 e lista válida."""
    payload = {
        "tipo": "despesa_variavel",
        "valor": 50.00,
        "categoria": "CategoriaInvalidaXYZ",
        "data": "2026-10-24",
        "descricao": "Teste de Categoria Inválida",
    }
    response = auth_client.post("/api/transactions", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
    assert "valid_categories" in data["detail"]
    assert "Alimentação" in data["detail"]["valid_categories"]
    assert "Moradia" in data["detail"]["valid_categories"]


def test_dashboard_creates_transaction_with_canonical_category_and_id(
    auth_client: TestClient, db_session
):
    """Garante que o dashboard grava category_id e mantém categoria em dual-write."""
    payload = {
        "tipo": "despesa_variavel",
        "valor": 120.50,
        "categoria": "Alimentação",
        "data": "2026-10-24",
        "descricao": "Almoço de Domingo",
    }
    response = auth_client.post("/api/transactions", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["categoria"] == "Alimentação"
    assert res_data["category_id"] is not None

    tx = db_session.query(Transaction).filter(Transaction.id == res_data["id"]).first()
    assert tx is not None
    assert tx.categoria == "Alimentação"
    assert tx.category_id == res_data["category_id"]
    assert tx.category_rel.name == "Alimentação"


def test_dashboard_accepts_alias_and_maps_to_canonical(auth_client: TestClient, db_session):
    """Garante que um alias aceito pelo sistema é mapeado para a categoria canônica oficial."""
    payload = {
        "tipo": "despesa_variavel",
        "valor": 80.00,
        "categoria": "Mercado",  # alias para Alimentação
        "data": "2026-10-24",
        "descricao": "Compras da semana",
    }
    response = auth_client.post("/api/transactions", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["categoria"] == "Alimentação"


def test_webhook_and_parser_fallback_to_outros_for_unknown_category(
    auth_client: TestClient, db_session
):
    """Valida que entradas vindas de webhook/parser com categoria desconhecida caem seguramente em 'Outros'."""
    webhook_secret = "webhook_secret_key_with_at_least_32_characters_12345"
    headers = {"X-Webhook-Secret": webhook_secret, "Content-Type": "application/json"}

    # Mock de mensagem com categoria desconhecida
    with mock.patch(
        "backend.webhook.parse_text_message",
        return_value={
            "tipo": "despesa_variavel",
            "valor": 45.0,
            "categoria": "Categoria Desconhecida",
            "descricao": "Compra aleatória de teste",
            "data": "2026-10-24",
            "parcelas": 1,
        },
    ):
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "120363000000000000@g.us",
                    "participant": "5511999998888@s.whatsapp.net",
                    "fromMe": False,
                    "id": "msg-unknown-cat-1",
                },
                "pushName": "Bruno",
                "message": {"conversation": "Comprei algo 45,00"},
            },
        }
        res = auth_client.post("/webhook/whatsapp", json=payload, headers=headers)
        assert res.status_code == 200

        # Verifica que a transação foi salva como 'Outros'
        tx = (
            db_session.query(Transaction)
            .filter(Transaction.descricao == "Compra aleatória de teste")
            .first()
        )
        assert tx is not None
        assert tx.categoria == "Outros"
        assert tx.category_rel.name == "Outros"


def test_categories_endpoint_with_budget_and_spend(auth_client: TestClient, db_session):
    """Testa GET /api/categories com cálculo de gasto_mes e percentual do orçamento."""
    # 1. Configura um budget em Alimentação via PUT /api/categories/{id}
    cat_alim = db_session.query(Category).filter(Category.name == "Alimentação").first()
    assert cat_alim is not None

    put_res = auth_client.put(f"/api/categories/{cat_alim.id}", json={"budget": 1000.00})
    assert put_res.status_code == 200
    assert float(put_res.json()["budget"]) == 1000.00

    # 2. Cria despesas no mês 2026-10
    auth_client.post(
        "/api/transactions",
        json={
            "tipo": "despesa_variavel",
            "valor": 350.00,
            "categoria": "Alimentação",
            "data": "2026-10-15",
            "descricao": "Supermercado A",
        },
    )
    auth_client.post(
        "/api/transactions",
        json={
            "tipo": "despesa_variavel",
            "valor": 150.00,
            "categoria": "Alimentação",
            "data": "2026-10-20",
            "descricao": "Supermercado B",
        },
    )

    # 3. Consulta GET /api/categories?mes=2026-10
    get_res = auth_client.get("/api/categories?mes=2026-10")
    assert get_res.status_code == 200
    cats = get_res.json()
    alim_data = next((c for c in cats if c["id"] == cat_alim.id), None)
    assert alim_data is not None
    assert float(alim_data["gasto_mes"]) >= 500.00
    assert float(alim_data["budget"]) == 1000.00
    assert alim_data["percentual_budget"] is not None


def test_metrics_endpoint_includes_budget_and_percentages(auth_client: TestClient):
    """Valida que o resumo de métricas (/api/metrics) expõe dados de orçamento por categoria."""
    res = auth_client.get("/api/metrics?mes=2026-10")
    assert res.status_code == 200
    data = res.json()
    assert "categorias" in data
    alim_metric = next((c for c in data["categorias"] if c["categoria"] == "Alimentação"), None)
    if alim_metric:
        assert "category_id" in alim_metric
        assert "budget" in alim_metric
        assert "percentual_budget" in alim_metric


def test_migration_reversibility_and_unknown_category_creation():
    """Valida que a migration 33154b762c63 cria categoria desconhecida e é perfeitamente reversível."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    old_env = os.environ.get("DATABASE_URL")
    try:
        db_url = f"sqlite:///{db_path.replace(os.sep, '/')}"
        os.environ["DATABASE_URL"] = db_url
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        # 1. Executa até a migration anterior 9240c01a1280
        command.upgrade(alembic_cfg, "9240c01a1280")

        # Insere transação com categoria legada/desconhecida
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO transactions (id, tipo, valor, categoria, data, source, author, channel) "
            "VALUES (1, 'despesa_variavel', 99.00, 'Categoria Exotica Inedita', '2026-10-24', 'Bruno', 'Bruno', 'dashboard')"
        )
        conn.commit()
        conn.close()

        # 2. Roda upgrade para 33154b762c63
        command.upgrade(alembic_cfg, "33154b762c63")

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        # Verifica que a categoria inédita foi criada na tabela categories
        cur.execute(
            "SELECT id, name, normalized_name FROM categories WHERE normalized_name = 'categoria exotica inedita'"
        )
        cat_row = cur.fetchone()
        assert cat_row is not None
        assert cat_row[1] == "Categoria Exotica Inedita"

        # Verifica que a transação teve category_id preenchido
        cur.execute("SELECT category_id, categoria FROM transactions WHERE id = 1")
        tx_row = cur.fetchone()
        assert tx_row[0] == cat_row[0]
        assert tx_row[1] == "Categoria Exotica Inedita"
        conn.close()

        # 3. Roda downgrade de volta para 9240c01a1280
        command.downgrade(alembic_cfg, "9240c01a1280")

        # Verifica que as colunas novas foram removidas no downgrade
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(categories)")
        cat_cols = [c[1] for c in cur.fetchall()]
        assert "normalized_name" not in cat_cols
        assert "ativo" not in cat_cols
        conn.close()

    finally:
        if old_env is not None:
            os.environ["DATABASE_URL"] = old_env
        else:
            os.environ.pop("DATABASE_URL", None)
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
