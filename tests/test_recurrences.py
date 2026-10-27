"""Testes automatizados para o sistema de recorrências explícitas e totais escopados por mês."""

import os
import sqlite3
from datetime import date
from unittest import mock

import pytest
from fastapi.testclient import TestClient

os.environ["APP_PASSWORD"] = "StrongMasterPassword123!"
os.environ["SESSION_SECRET"] = "super_secret_session_key_with_at_least_32_chars_12345"
os.environ["ADMIN_TOKEN"] = "adm_secret_token_secure_98765"
os.environ["DEV_INSECURE_COOKIES"] = "0"
os.environ["WHATSAPP_GROUP_JID"] = "120363000000000000@g.us"
os.environ["WEBHOOK_SECRET"] = "webhook_secret_key_with_at_least_32_characters_12345"
os.environ["WHATSAPP_USER_BRUNO"] = "5511999998888"
os.environ["WHATSAPP_USER_LETICIA"] = "5511977776666"

from backend.auth import COOKIE_NAME, create_session_token
from backend.database import SessionLocal
from backend.main import app
from backend.models import Recurrence, Transaction
from backend.services.recurrences import clamp_day_in_month, ensure_recurrences


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


def test_clamp_day_in_month():
    """Valida clamp de dia: dia 31 vira 30 em abril e 28/29 em fevereiro."""
    # Fevereiro normal
    assert clamp_day_in_month(2026, 2, 31) == date(2026, 2, 28)
    # Fevereiro bissexto
    assert clamp_day_in_month(2028, 2, 31) == date(2028, 2, 29)
    # Abril (30 dias)
    assert clamp_day_in_month(2026, 4, 31) == date(2026, 4, 30)
    # Outubro (31 dias)
    assert clamp_day_in_month(2026, 10, 31) == date(2026, 10, 31)


def test_income_in_november_does_not_appear_in_october(auth_client: TestClient, db_session):
    """Critério central: renda lançada em novembro NÃO aparece em outubro."""
    # Cria uma receita em 2026-11-10
    res_nov = auth_client.post(
        "/api/transactions",
        json={
            "tipo": "receita",
            "valor": 5000.00,
            "categoria": "Salário/Renda",
            "data": "2026-11-10",
            "descricao": "Bônus Novembro",
        },
    )
    assert res_nov.status_code == 200

    # 1. Consulta /api/transactions?mes=2026-10
    res_oct_tx = auth_client.get("/api/transactions?mes=2026-10")
    assert res_oct_tx.status_code == 200
    oct_txs = res_oct_tx.json()
    assert not any(t["descricao"] == "Bônus Novembro" for t in oct_txs)

    # 2. Consulta /api/summary?mes=2026-10
    res_oct_summary = auth_client.get("/api/summary?mes=2026-10")
    assert res_oct_summary.status_code == 200
    summary_data = res_oct_summary.json()
    # O total de receitas em outubro não deve conter os 5000 de novembro
    assert float(summary_data["total_receitas"]) < 5000.00


def test_recurrence_lifespan_and_idempotent_materialization(auth_client: TestClient, db_session):
    """Recorrência iniciada em outubro aparece em out/nov/dez e não em setembro."""
    # Cria regra de recorrência iniciando em 2026-10-01
    rec_res = auth_client.post(
        "/api/recurrences",
        json={
            "tipo": "despesa_fixa",
            "descricao": "Internet Fibra",
            "valor": 120.00,
            "categoria": "Contas de Consumo",
            "author": "Bruno",
            "dia_do_mes": 31,
            "inicio": "2026-10-01",
            "fim": None,
            "ativo": True,
        },
    )
    assert rec_res.status_code == 200
    rec_id = rec_res.json()["id"]

    # 1. Consulta Setembro (2026-09): NÃO deve materializar
    res_sep = auth_client.get("/api/transactions?mes=2026-09")
    assert res_sep.status_code == 200
    assert not any(t.get("recurrence_id") == rec_id for t in res_sep.json())

    # 2. Consulta Outubro (2026-10): DEVE materializar no dia 31
    res_oct = auth_client.get("/api/transactions?mes=2026-10")
    assert res_oct.status_code == 200
    oct_match = [t for t in res_oct.json() if t.get("recurrence_id") == rec_id]
    assert len(oct_match) == 1
    assert oct_match[0]["data"] == "2026-10-31"

    # Chamar ensure_recurrences uma segunda vez não duplica
    ensure_recurrences(db_session, "2026-10")
    res_oct_repeat = auth_client.get("/api/transactions?mes=2026-10")
    assert len([t for t in res_oct_repeat.json() if t.get("recurrence_id") == rec_id]) == 1

    # 3. Consulta Novembro (2026-11): clamp para dia 30
    res_nov = auth_client.get("/api/transactions?mes=2026-11")
    assert res_nov.status_code == 200
    nov_match = [t for t in res_nov.json() if t.get("recurrence_id") == rec_id]
    assert len(nov_match) == 1
    assert nov_match[0]["data"] == "2026-11-30"


def test_patch_recurrence_updates_future_unmodified_instances(auth_client: TestClient, db_session):
    """PATCH altera instâncias futuras não editadas e preserva passadas e editadas manualmente."""
    # Cria recorrência iniciando no mês atual
    hoje = date.today()
    mes_atual = hoje.strftime("%Y-%m")

    rec_res = auth_client.post(
        "/api/recurrences",
        json={
            "tipo": "despesa_fixa",
            "descricao": "Academia VIP",
            "valor": 150.00,
            "categoria": "Saúde",
            "author": "Bruno",
            "dia_do_mes": 10,
            "inicio": f"{mes_atual}-01",
            "ativo": True,
        },
    )
    rec_id = rec_res.json()["id"]

    # Materializa mês atual
    auth_client.get(f"/api/transactions?mes={mes_atual}")
    instancia_atual = (
        db_session.query(Transaction).filter(Transaction.recurrence_id == rec_id).first()
    )
    assert instancia_atual is not None
    assert float(instancia_atual.valor) == 150.00

    # Edita manualmente a instância (altera valor para 180)
    put_res = auth_client.put(f"/api/transactions/{instancia_atual.id}", json={"valor": 180.00})
    assert put_res.status_code == 200
    db_session.refresh(instancia_atual)
    assert instancia_atual.editado_manual is True

    # Realiza PATCH na regra alterando valor para 200
    patch_res = auth_client.patch(f"/api/recurrences/{rec_id}", json={"valor": 200.00})
    assert patch_res.status_code == 200

    # Como a instância atual foi editada manualmente, ela NÃO deve ter sido sobrescrita para 200
    db_session.refresh(instancia_atual)
    assert float(instancia_atual.valor) == 180.00


def test_delete_recurrence_ends_rule_and_cleans_future_instances(
    auth_client: TestClient, db_session
):
    """DELETE encerra a regra de recorrência e remove apenas instâncias futuras não editadas."""
    rec_res = auth_client.post(
        "/api/recurrences",
        json={
            "tipo": "despesa_fixa",
            "descricao": "Assinatura Software",
            "valor": 50.00,
            "categoria": "Serviços",
            "author": "Bruno",
            "dia_do_mes": 5,
            "inicio": "2026-10-01",
            "ativo": True,
        },
    )
    rec_id = rec_res.json()["id"]

    # Deleta recorrência
    del_res = auth_client.delete(f"/api/recurrences/{rec_id}")
    assert del_res.status_code == 200

    # Verifica que a regra está desativada no banco
    rec = db_session.query(Recurrence).filter(Recurrence.id == rec_id).first()
    assert rec.ativo is False
    assert rec.fim is not None


def test_webhook_creates_recurrence_for_fixed_expense(auth_client: TestClient, db_session):
    """Garante que despesa_fixa via webhook cria Recurrence com feedback 'recorrente'."""
    webhook_secret = "webhook_secret_key_with_at_least_32_characters_12345"
    headers = {"X-Webhook-Secret": webhook_secret, "Content-Type": "application/json"}

    with mock.patch(
        "backend.webhook.parse_text_message",
        return_value={
            "tipo": "despesa_fixa",
            "valor": 120.0,
            "categoria": "Contas de Consumo",
            "descricao": "Internet Casa",
            "data": "2026-10-24",
            "parcelas": 1,
        },
    ), mock.patch("backend.atlas.send_whatsapp_message") as mock_send:
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {
                    "remoteJid": "120363000000000000@g.us",
                    "participant": "5511999998888@s.whatsapp.net",
                    "fromMe": False,
                    "id": "msg-rec-webhook-1",
                },
                "pushName": "Bruno",
                "message": {"conversation": "Internet 120 fixa"},
            },
        }
        res = auth_client.post("/webhook/whatsapp", json=payload, headers=headers)
        assert res.status_code == 200

        # Verifica que a regra foi criada
        rec = (
            db_session.query(Recurrence).filter(Recurrence.descricao == "Internet Casa").first()
        )
        assert rec is not None
        assert rec.tipo == "despesa_fixa"

        # Confirma que a mensagem retornada contém 'recorrente'
        assert mock_send.called
        sent_msg = mock_send.call_args[0][1]
        assert "recorrente" in sent_msg


def test_cli_migration_script_dry_run_and_validation(tmp_path):
    """Valida o script CLI de migração de legados: dry-run não escreve e aborta se faltar decisão."""
    import subprocess
    import sys

    # Testa com database SQLite temporário
    test_db = str(tmp_path / "cli_test.db")
    db_url = f"sqlite:///{test_db.replace(os.sep, '/')}"
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url

    # Cria tabela via alembic com DATABASE_URL isolada no ambiente
    old_env = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = db_url
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(cfg, "head")
    finally:
        if old_env is not None:
            os.environ["DATABASE_URL"] = old_env
        else:
            os.environ.pop("DATABASE_URL", None)

    # Insere uma transação legada
    con = sqlite3.connect(test_db)
    con.execute(
        "INSERT INTO transactions (id, tipo, valor, categoria, data, descricao, category_id) VALUES (999, 'despesa_fixa', 80.0, 'Outros', '2026-10-15', 'Condomínio Antigo', 1)"
    )
    con.commit()
    con.close()

    # 1. Executa dry-run
    dec_file = str(tmp_path / "test_decisions.json")
    cmd_dry = [
        sys.executable,
        "scripts/migrate_legacy_fixed.py",
        "--dry-run",
        "--decisions",
        dec_file,
    ]
    p_dry = subprocess.run(cmd_dry, env=env, capture_output=True, text=True)
    assert p_dry.returncode == 0
    assert os.path.exists(dec_file)

    # 2. Testa validação: remove o ID 999 do arquivo para simular omissão
    with open(dec_file, "w") as f:
        f.write("{}")

    cmd_apply_fail = [
        sys.executable,
        "scripts/migrate_legacy_fixed.py",
        "--apply",
        "--decisions",
        dec_file,
    ]
    p_fail = subprocess.run(cmd_apply_fail, env=env, capture_output=True, text=True)
    assert p_fail.returncode != 0
    assert "ERRO DE VALIDAÇÃO" in p_fail.stderr
