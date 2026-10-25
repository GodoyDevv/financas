"""Testes unitários e de integração para parcelamentos com identidade relacional (UUID) e exclusão por escopo."""
import os
import tempfile
import sqlite3
import pytest
from datetime import date
from decimal import Decimal
from unittest import mock
from fastapi.testclient import TestClient

os.environ["APP_PASSWORD"] = "StrongMasterPassword123!"
os.environ["SESSION_SECRET"] = "super_secret_session_key_with_at_least_32_chars_12345"
os.environ["ADMIN_TOKEN"] = "adm_secret_token_secure_98765"
os.environ["DEV_INSECURE_COOKIES"] = "0"
os.environ["WHATSAPP_GROUP_JID"] = "120363000000000000@g.us"
os.environ["WEBHOOK_SECRET"] = "webhook_secret_key_with_at_least_32_characters_12345"
os.environ["WHATSAPP_USER_BRUNO"] = "5511999998888"
os.environ["WHATSAPP_USER_LETICIA"] = "5511977776666"

from backend.main import app
from backend.auth import COOKIE_NAME, create_session_token
from backend.database import SessionLocal
from backend.models import Transaction, Category
from backend.services.installments import (
    criar_parcelamento,
    calcular_valores_parcelamento,
    add_months_clamped
)
from alembic.config import Config
from alembic import command


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


def test_add_months_clamped_month_ends():
    """Valida clamp de fim de mês: 31/jan em 3x gera 28 (ou 29)/fev e 31/mar."""
    d0 = date(2026, 1, 31)
    d1 = add_months_clamped(d0, 1)
    d2 = add_months_clamped(d0, 2)
    assert d1 == date(2026, 2, 28)
    assert d2 == date(2026, 3, 31)

    # Ano bissexto (2028)
    d_bissexto = date(2028, 1, 31)
    assert add_months_clamped(d_bissexto, 1) == date(2028, 2, 29)


def test_calcular_valores_parcelamento_modes():
    """Valida os dois modos de parcelamento e divisão de centavos na 1ª parcela."""
    # Modo valor_da_parcela (padrão de produto configurado)
    vals_p, total_p = calcular_valores_parcelamento(Decimal("300.00"), 3, modo="valor_da_parcela")
    assert vals_p == [Decimal("300.00"), Decimal("300.00"), Decimal("300.00")]
    assert total_p == Decimal("900.00")

    # Modo valor_total (100 em 3x = 33,34 + 33,33 + 33,33)
    vals_t, total_t = calcular_valores_parcelamento(Decimal("100.00"), 3, modo="valor_total")
    assert vals_t == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
    assert sum(vals_t) == Decimal("100.00")
    assert total_t == Decimal("100.00")


def test_atomic_installment_creation_rollback_on_failure(db_session):
    """Garante que a criação é atômica (tudo ou nada). Se falhar, faz rollback completo."""
    base_data = {
        "tipo": "despesa_variavel",
        "valor": Decimal("50.00"),
        "categoria": "Alimentação",
        "category_id": 1,
        "data": date(2026, 10, 24),
        "descricao": "Item Atômico"
    }

    # Simula falha na segunda chamada de add_months_clamped
    with mock.patch("backend.services.installments.add_months_clamped", side_effect=[date(2026, 10, 24), RuntimeError("Falha simulada")]):
        with pytest.raises(RuntimeError):
            criar_parcelamento(db_session, base_data, parcelas=3)

    # Verifica que nenhuma parcela do item foi gravada no banco
    found = db_session.query(Transaction).filter(Transaction.descricao.like("Item Atômico%")).all()
    assert len(found) == 0


def test_two_identical_purchases_different_groups_independent_deletion(auth_client: TestClient, db_session):
    """Critério central: duas compras com MESMA descrição, valor e tipo não colidem na exclusão.
    
    Excluir o grupo de uma NÃO toca a outra.
    """
    # 1. Cria Compra A em 3 parcelas de R$ 150
    res_a = auth_client.post("/api/transactions", json={
        "tipo": "despesa_variavel",
        "valor": 150.00,
        "categoria": "Transporte",
        "data": "2026-10-24",
        "descricao": "Pneu Novo",
        "parcelas": 3
    })
    assert res_a.status_code == 200
    tx_a = res_a.json()
    grupo_a = tx_a["parcela_grupo_id"]
    assert grupo_a is not None

    # 2. Cria Compra B idêntica em 3 parcelas de R$ 150
    res_b = auth_client.post("/api/transactions", json={
        "tipo": "despesa_variavel",
        "valor": 150.00,
        "categoria": "Transporte",
        "data": "2026-10-24",
        "descricao": "Pneu Novo",
        "parcelas": 3
    })
    assert res_b.status_code == 200
    tx_b = res_b.json()
    grupo_b = tx_b["parcela_grupo_id"]
    assert grupo_b is not None
    assert grupo_a != grupo_b  # Grupos obrigatoriamente distintos

    # 3. Exclui TODO o grupo de A
    del_res = auth_client.delete(f"/api/transactions/{tx_a['id']}?escopo=grupo")
    assert del_res.status_code == 200
    assert del_res.json()["deleted_count"] == 3

    # 4. Verifica que A foi apagado e B permaneceu intacto com todas as 3 parcelas
    rows_a = db_session.query(Transaction).filter(Transaction.parcela_grupo_id == grupo_a).all()
    assert len(rows_a) == 0

    rows_b = db_session.query(Transaction).filter(Transaction.parcela_grupo_id == grupo_b).all()
    assert len(rows_b) == 3


def test_delete_scopes_uma_futuras_grupo(auth_client: TestClient, db_session):
    """Testa os 3 escopos de exclusão: 'uma', 'futuras' e 'grupo'."""
    # Cria parcelamento em 4 vezes
    res = auth_client.post("/api/transactions", json={
        "tipo": "despesa_variavel",
        "valor": 50.00,
        "categoria": "Lazer",
        "data": "2026-10-01",
        "descricao": "Show de Rock",
        "parcelas": 4
    })
    assert res.status_code == 200
    grupo_id = res.json()["parcela_grupo_id"]

    parcelas = db_session.query(Transaction).filter(
        Transaction.parcela_grupo_id == grupo_id
    ).order_by(Transaction.parcela_num).all()
    assert len(parcelas) == 4

    # 1. Exclui com escopo='uma' na parcela 1
    p1 = parcelas[0]
    del_uma = auth_client.delete(f"/api/transactions/{p1.id}?escopo=uma")
    assert del_uma.status_code == 200
    assert del_uma.json()["deleted_count"] == 1

    sobraram = db_session.query(Transaction).filter(Transaction.parcela_grupo_id == grupo_id).all()
    assert len(sobraram) == 3
    assert all(p.id != p1.id for p in sobraram)

    # 2. Exclui com escopo='futuras' a partir da parcela 3
    p3 = next(p for p in sobraram if p.parcela_num == 3)
    del_futuras = auth_client.delete(f"/api/transactions/{p3.id}?escopo=futuras")
    assert del_futuras.status_code == 200
    # Deve apagar a 3 e a 4
    assert del_futuras.json()["deleted_count"] == 2

    sobraram_apos_futuras = db_session.query(Transaction).filter(Transaction.parcela_grupo_id == grupo_id).all()
    assert len(sobraram_apos_futuras) == 1
    assert sobraram_apos_futuras[0].parcela_num == 2


def test_webhook_creates_installments_with_group_and_formatted_reply(auth_client: TestClient, db_session):
    """Valida criação via webhook: gera grupo UUID e mensagem executiva com ambos os valores."""
    webhook_secret = "webhook_secret_key_with_at_least_32_characters_12345"
    headers = {
        "X-Webhook-Secret": webhook_secret,
        "Content-Type": "application/json"
    }

    with mock.patch("backend.webhook.parse_text_message", return_value={
        "tipo": "despesa_variavel",
        "valor": 200.0,
        "categoria": "Alimentação",
        "descricao": "Jantar Especial",
        "data": "2026-10-24",
        "parcelas": 3
    }):
        with mock.patch("backend.atlas.send_whatsapp_message") as mock_send:
            payload = {
                "event": "messages.upsert",
                "data": {
                    "key": {
                        "remoteJid": "120363000000000000@g.us",
                        "participant": "5511999998888@s.whatsapp.net",
                        "fromMe": False,
                        "id": "msg-inst-webhook-1"
                    },
                    "pushName": "Bruno",
                    "message": {"conversation": "Jantar 200 em 3x"}
                }
            }
            res = auth_client.post("/webhook/whatsapp", json=payload, headers=headers)
            assert res.status_code == 200

            # Verifica que foram geradas 3 parcelas vinculadas por UUID
            rows = db_session.query(Transaction).filter(
                Transaction.descricao.like("Jantar Especial%")
            ).order_by(Transaction.parcela_num).all()
            assert len(rows) == 3
            grupo = rows[0].parcela_grupo_id
            assert grupo is not None
            assert all(r.parcela_grupo_id == grupo for r in rows)
            assert [r.parcela_num for r in rows] == [1, 2, 3]
            assert all(r.parcela_total == 3 for r in rows)

            # Verifica mensagem enviada ao WhatsApp
            assert mock_send.called
            sent_msg = mock_send.call_args[0][1]
            assert "3x de R$ 200,00" in sent_msg
            assert "total R$ 600,00" in sent_msg


def test_migration_backfill_and_ambiguity_handling():
    """Valida a migration de backfill: agrupa casos certos e deixa casos ambíguos sem grupo."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    old_env = os.environ.get("DATABASE_URL")
    try:
        db_url = f"sqlite:///{db_path.replace(os.sep, '/')}"
        os.environ["DATABASE_URL"] = db_url
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        # 1. Upgrade até a migration anterior 33154b762c63
        command.upgrade(alembic_cfg, "33154b762c63")

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        # Caso Claro A (3 parcelas em meses consecutivos)
        cur.execute("INSERT INTO transactions (id, tipo, valor, categoria, data, descricao, author, channel, category_id) VALUES (101, 'despesa_variavel', 100.0, 'Outros', '2026-01-10', 'Curso (1/3)', 'Bruno', 'dashboard', 1)")
        cur.execute("INSERT INTO transactions (id, tipo, valor, categoria, data, descricao, author, channel, category_id) VALUES (102, 'despesa_variavel', 100.0, 'Outros', '2026-02-10', 'Curso (2/3)', 'Bruno', 'dashboard', 1)")
        cur.execute("INSERT INTO transactions (id, tipo, valor, categoria, data, descricao, author, channel, category_id) VALUES (103, 'despesa_variavel', 100.0, 'Outros', '2026-03-10', 'Curso (3/3)', 'Bruno', 'dashboard', 1)")

        # Caso Ambíguo B (incompleto: tem apenas parcela 1 e 3 de 3)
        cur.execute("INSERT INTO transactions (id, tipo, valor, categoria, data, descricao, author, channel, category_id) VALUES (201, 'despesa_variavel', 50.0, 'Outros', '2026-01-15', 'Livro (1/3)', 'Bruno', 'dashboard', 1)")
        cur.execute("INSERT INTO transactions (id, tipo, valor, categoria, data, descricao, author, channel, category_id) VALUES (203, 'despesa_variavel', 50.0, 'Outros', '2026-03-15', 'Livro (3/3)', 'Bruno', 'dashboard', 1)")
        conn.commit()
        conn.close()

        # 2. Executa migration face6b836ff4
        command.upgrade(alembic_cfg, "face6b836ff4")

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        # Caso Claro A deve estar agrupado com mesmo grupo_id
        cur.execute("SELECT parcela_grupo_id, parcela_num, parcela_total FROM transactions WHERE id IN (101, 102, 103)")
        rows_a = cur.fetchall()
        assert len(rows_a) == 3
        assert rows_a[0][0] is not None
        assert rows_a[0][0] == rows_a[1][0] == rows_a[2][0]
        assert [r[1] for r in rows_a] == [1, 2, 3]

        # Caso Ambíguo B deve ter ficado sem grupo (NULL)
        cur.execute("SELECT parcela_grupo_id, parcela_num, parcela_total FROM transactions WHERE id IN (201, 203)")
        rows_b = cur.fetchall()
        assert rows_b[0][0] is None
        assert rows_b[1][0] is None
        conn.close()

        # 3. Testa downgrade
        command.downgrade(alembic_cfg, "33154b762c63")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(transactions)")
        cols = [c[1] for c in cur.fetchall()]
        assert "parcela_grupo_id" not in cols
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
