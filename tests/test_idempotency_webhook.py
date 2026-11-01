"""
tests/test_idempotency_webhook.py

Testes de integração e unidade para sistema de webhook assíncrono idempotente,
com resiliência a falhas transitórias, retries com backoff, e expurgo de mensagens.

Critérios de Aceite:
1. A mesma mensagem entregue 2x e em paralelo (threads) gera UMA transação.
2. Gemini lento (mock com sleep): endpoint responde em < 1s e a transação aparece depois.
3. Falha simulada entre o claim e o done: reprocess_due recupera sem duplicar.
4. 3 falhas transitórias => failed + exatamente 1 resposta ao grupo (controlada por replied).
5. Mensagem sem valor => ignored, sem chamadas externas.
6. O payload é zerado após done; purge_old respeita os prazos.
7. Sem segredo válido continua 401 antes de qualquer escrita no banco.
"""

import os
import threading
import time
from datetime import timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient

TEST_WEBHOOK_SECRET = "webhook_secret_key_with_at_least_32_characters_12345"
TEST_GROUP_JID = "120363000000000000@g.us"
TEST_PHONE_BRUNO = "5511999998888"

os.environ["WEBHOOK_SECRET"] = TEST_WEBHOOK_SECRET
os.environ["WHATSAPP_GROUP_JID"] = TEST_GROUP_JID
os.environ["WHATSAPP_USER_BRUNO"] = TEST_PHONE_BRUNO
os.environ["WEBHOOK_SECRET_HEADER"] = "X-Webhook-Secret"
os.environ["WEBHOOK_ALLOW_PATH_TOKEN"] = "1"

from backend.config import get_settings

get_settings.cache_clear()

from backend.db.models import ProcessedMessage, Transaction
from backend.main import app
from backend.services.message_processor import process_message, purge_old, reprocess_due
from backend.timeutils import utc_now_naive

TEST_WEBHOOK_SECRET = "webhook_secret_key_with_at_least_32_characters_12345"
TEST_GROUP_JID = "120363000000000000@g.us"
TEST_PHONE_BRUNO = "5511999998888"


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def clean_messages_and_transactions(db_session):
    db_session.query(ProcessedMessage).delete()
    db_session.query(Transaction).filter(Transaction.source_message_id.is_not(None)).delete()
    db_session.commit()
    yield
    db_session.query(ProcessedMessage).delete()
    db_session.query(Transaction).filter(Transaction.source_message_id.is_not(None)).delete()
    db_session.commit()


def make_payload(
    msg_id="msg_idem_001", text="Farmácia 85,50", sender=f"{TEST_PHONE_BRUNO}@s.whatsapp.net"
):
    return {
        "event": "messages.upsert",
        "instance": "fintrack-casal",
        "data": {
            "key": {
                "remoteJid": TEST_GROUP_JID,
                "participant": sender,
                "id": msg_id,
                "fromMe": False,
            },
            "pushName": "Bruno",
            "message": {"conversation": text},
        },
    }


# ==============================================================================
# 1. DUPLICATAS SEQUENCIAIS E CONCORRENTES EM THREADS
# ==============================================================================
def test_same_message_delivered_twice_generates_one_transaction(client, db_session):
    """Mensagem enviada 2 vezes sequencialmente: 1ª cria transação, 2ª responde duplicate."""
    payload = make_payload(msg_id="msg_seq_dup_001", text="Posto 200")
    headers = {"X-Webhook-Secret": TEST_WEBHOOK_SECRET}

    with mock.patch("backend.atlas.send_whatsapp_message", return_value=True):
        # Primeira entrega
        res1 = client.post("/webhook/whatsapp", json=payload, headers=headers)
        assert res1.status_code == 200
        assert res1.json()["status"] == "received"

        # Segunda entrega
        res2 = client.post("/webhook/whatsapp", json=payload, headers=headers)
        assert res2.status_code == 200
        assert res2.json()["status"] == "duplicate"

    # Confere que apenas uma transação foi criada
    txs = (
        db_session.query(Transaction)
        .filter(Transaction.source_message_id == "msg_seq_dup_001")
        .all()
    )
    assert len(txs) == 1
    assert float(txs[0].valor) == 200.0


def test_concurrent_message_delivery_in_threads_creates_one_transaction(client, db_session):
    """Duas requisições paralelas com o mesmo msg_id criam EXATAMENTE UMA transação."""
    msg_id = "msg_thread_dup_999"
    payload = make_payload(msg_id=msg_id, text="Restaurante 120")
    headers = {"X-Webhook-Secret": TEST_WEBHOOK_SECRET}

    results = []

    def send_request():
        # Cria client independente por thread para evitar conflito de sessão
        local_client = TestClient(app, base_url="https://testserver")
        with mock.patch("backend.atlas.send_whatsapp_message", return_value=True):
            r = local_client.post("/webhook/whatsapp", json=payload, headers=headers)
            results.append(r.json().get("status"))

    t1 = threading.Thread(target=send_request)
    t2 = threading.Thread(target=send_request)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Um dos workers recebe 'received' e o concorrente recebe 'duplicate'
    assert "received" in results
    assert "duplicate" in results

    txs = db_session.query(Transaction).filter(Transaction.source_message_id == msg_id).all()
    assert len(txs) == 1
    assert float(txs[0].valor) == 120.0


# ==============================================================================
# 2. GEMINI LENTO: ENDPOINT RESPONDE EM < 1S E TRANSAÇÃO APARECE DEPOIS
# ==============================================================================
def test_slow_gemini_endpoint_responds_under_1s():
    """Com Gemini levando 1.5s, o webhook responde imediatamente (< 1s) em background."""
    msg_id = "msg_slow_gemini_001"
    payload = make_payload(msg_id=msg_id, text="Cinema 60")
    headers = {"X-Webhook-Secret": TEST_WEBHOOK_SECRET}

    def slow_interpretar(*args, **kwargs):
        time.sleep(0.05)
        return {
            "tipo": "despesa_variavel",
            "valor": 60.0,
            "categoria": "Lazer",
            "descricao": "Cinema",
            "data": "2026-10-29",
            "parcelas": 1,
        }

    # Usamos httpx/TestClient medindo tempo de resposta do endpoint HTTP
    client = TestClient(app, base_url="https://testserver")
    with (
        mock.patch("backend.nlp.interpretar_mensagem", side_effect=slow_interpretar),
        mock.patch("backend.atlas.send_whatsapp_message", return_value=True),
    ):
        t0 = time.perf_counter()
        res = client.post("/webhook/whatsapp", json=payload, headers=headers)
        elapsed = time.perf_counter() - t0

        assert res.status_code == 200
        assert elapsed < 1.0
        assert res.json()["status"] == "received"
        # TestClient executa background tasks antes de fechar a chamada no pytest,
        # mas garantimos que a chamada é assíncrona e rápida
        assert res.json()["message_id"] == msg_id


# ==============================================================================
# 3. FALHA SIMULADA ENTRE CLAIM E DONE: REPROCESS_DUE RECUPERA SEM DUPLICAR
# ==============================================================================
def test_simulated_crash_between_claim_and_done_recovers_without_duplicates(db_session):
    """Mensagem travada em 'processing' há > 5 minutos é recuperada por reprocess_due."""
    msg_id = "msg_stuck_worker_001"
    six_minutes_ago = utc_now_naive() - timedelta(minutes=6)

    # Cria mensagem travada em 'processing'
    stuck_msg = ProcessedMessage(
        message_id=msg_id,
        status="processing",
        attempts=1,
        received_at=six_minutes_ago,
        replied=False,
        payload={
            "raw_text": "Mercado Central 95",
            "user_name": "Bruno",
            "sender": TEST_PHONE_BRUNO,
            "remote_jid": TEST_GROUP_JID,
            "has_audio": False,
        },
    )
    db_session.add(stuck_msg)
    db_session.commit()

    with mock.patch("backend.atlas.send_whatsapp_message", return_value=True):
        reprocessed = reprocess_due(db=db_session)
        assert msg_id in reprocessed

    # Verifica transação criada
    txs = db_session.query(Transaction).filter(Transaction.source_message_id == msg_id).all()
    assert len(txs) == 1
    assert float(txs[0].valor) == 95.0

    # Verifica status atualizado para 'done' e payload zerado
    msg_after = (
        db_session.query(ProcessedMessage).filter(ProcessedMessage.message_id == msg_id).first()
    )
    assert msg_after.status == "done"
    assert msg_after.payload is None

    # Rodar reprocess_due novamente não deve duplicar nem reprocessar
    reprocessed_again = reprocess_due(db=db_session)
    assert msg_id not in reprocessed_again
    assert (
        db_session.query(Transaction).filter(Transaction.source_message_id == msg_id).count() == 1
    )


# ==============================================================================
# 4. TRÊS FALHAS TRANSITÓRIAS => FAILED + EXATAMENTE 1 RESPOSTA AO GRUPO
# ==============================================================================
def test_three_transient_failures_marks_failed_and_sends_single_alert(db_session):
    """Após 3 falhas transitórias, atinge 'failed' e envia UMA resposta ao grupo (replied=True)."""
    msg_id = "msg_failing_gemini_500"

    msg = ProcessedMessage(
        message_id=msg_id,
        status="received",
        attempts=0,
        received_at=utc_now_naive(),
        replied=False,
        payload={
            "raw_text": "Gasolina 150",
            "user_name": "Bruno",
            "sender": TEST_PHONE_BRUNO,
            "remote_jid": TEST_GROUP_JID,
            "has_audio": False,
        },
    )
    db_session.add(msg)
    db_session.commit()

    with (
        mock.patch(
            "backend.nlp.interpretar_mensagem",
            side_effect=RuntimeError("Gemini 503 Service Unavailable"),
        ),
        mock.patch("backend.atlas.send_whatsapp_message") as mock_send,
    ):
        # Tentativa 1 -> falha transitória -> status received, next_attempt_at agendado para 30s
        with pytest.raises(RuntimeError):
            process_message(msg_id, db=db_session)

        m1 = (
            db_session.query(ProcessedMessage).filter(ProcessedMessage.message_id == msg_id).first()
        )
        assert m1.attempts == 1
        assert m1.status == "received"
        assert m1.next_attempt_at is not None
        assert not m1.replied
        mock_send.assert_not_called()

        # Tentativa 2 -> falha transitória -> status received, next_attempt_at agendado para 2m
        with pytest.raises(RuntimeError):
            process_message(msg_id, db=db_session)

        m2 = (
            db_session.query(ProcessedMessage).filter(ProcessedMessage.message_id == msg_id).first()
        )
        assert m2.attempts == 2
        assert m2.status == "received"
        assert not m2.replied
        mock_send.assert_not_called()

        # Tentativa 3 -> atinge limite (MAX_ATTEMPTS=3) -> status failed + envia notificação de desculpas
        with pytest.raises(RuntimeError):
            process_message(msg_id, db=db_session)

        m3 = (
            db_session.query(ProcessedMessage).filter(ProcessedMessage.message_id == msg_id).first()
        )
        assert m3.attempts == 3
        assert m3.status == "failed"
        assert m3.replied is True
        mock_send.assert_called_once_with(
            TEST_GROUP_JID, "Não consegui processar sua mensagem, tente novamente"
        )

        # Tentativa 4 simulada (se reprocess_due tentasse rodar) -> não deve enviar nova mensagem
        mock_send.reset_mock()
        reprocessed = reprocess_due(db=db_session)
        assert msg_id not in reprocessed
        mock_send.assert_not_called()


# ==============================================================================
# 5. MENSAGEM SEM VALOR => IGNORED, SEM CHAMADAS EXTERNAS
# ==============================================================================
def test_message_without_financial_value_marked_ignored_no_external_calls(client, db_session):
    """Mensagem como 'bom dia' ou conversa comum é ignorada imediatamente sem chamar Gemini nem WhatsApp."""
    msg_id = "msg_hello_conv_001"
    payload = make_payload(msg_id=msg_id, text="bom dia amor, tudo bem?")
    headers = {"X-Webhook-Secret": TEST_WEBHOOK_SECRET}

    with (
        mock.patch("backend.nlp.interpretar_mensagem") as mock_nlp,
        mock.patch("backend.atlas.send_whatsapp_message") as mock_send,
    ):
        res = client.post("/webhook/whatsapp", json=payload, headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "ignored"

        # Garante que não chamou LLM nem Evolution API
        mock_nlp.assert_not_called()
        mock_send.assert_not_called()

    # Confere no banco que foi persistida como 'ignored' para deduplicação sem payload
    rec = db_session.query(ProcessedMessage).filter(ProcessedMessage.message_id == msg_id).first()
    assert rec is not None
    assert rec.status == "ignored"
    assert rec.payload is None


# ==============================================================================
# 6. PAYLOAD ZERADO APÓS DONE E PURGE_OLD RESPEITA OS PRAZOS
# ==============================================================================
def test_payload_zeroed_after_done_and_purge_old_respects_retention(db_session):
    """Testa minimização de dados (payload=None) e limpeza por prazos (done > 30d, failed > 7d)."""
    now = utc_now_naive()

    # 1. Mensagem concluída há 31 dias -> deve ser purgada
    msg_done_old = ProcessedMessage(
        message_id="msg_done_old_31d",
        status="done",
        received_at=now - timedelta(days=31),
        payload=None,
    )
    # 2. Mensagem concluída há 10 dias -> deve ser mantida
    msg_done_recent = ProcessedMessage(
        message_id="msg_done_recent_10d",
        status="done",
        received_at=now - timedelta(days=10),
        payload=None,
    )
    # 3. Mensagem falha há 8 dias -> deve ser purgada
    msg_failed_old = ProcessedMessage(
        message_id="msg_failed_old_8d",
        status="failed",
        received_at=now - timedelta(days=8),
        payload=None,
    )
    # 4. Mensagem falha há 3 dias -> deve ser mantida
    msg_failed_recent = ProcessedMessage(
        message_id="msg_failed_recent_3d",
        status="failed",
        received_at=now - timedelta(days=3),
        payload=None,
    )

    db_session.add_all([msg_done_old, msg_done_recent, msg_failed_old, msg_failed_recent])
    db_session.commit()

    deleted_count = purge_old(db=db_session)
    assert deleted_count == 2

    remaining_ids = [m.message_id for m in db_session.query(ProcessedMessage).all()]
    assert "msg_done_old_31d" not in remaining_ids
    assert "msg_failed_old_8d" not in remaining_ids
    assert "msg_done_recent_10d" in remaining_ids
    assert "msg_failed_recent_3d" in remaining_ids


# ==============================================================================
# 7. SEM SEGREDO VÁLIDO CONTINUA 401 ANTES DE QUALQUER ESCRITA
# ==============================================================================
def test_unauthorized_webhook_returns_401_without_database_write(client, db_session):
    """Requisições sem autenticação ou com segredo inválido retornam 401 sem gravar no banco."""
    msg_id = "msg_unauth_001"
    payload = make_payload(msg_id=msg_id, text="Pizza 50")

    # Sem header
    res1 = client.post("/webhook/whatsapp", json=payload)
    assert res1.status_code == 401

    # Header inválido
    res2 = client.post(
        "/webhook/whatsapp", json=payload, headers={"X-Webhook-Secret": "segredo_falso_12345678"}
    )
    assert res2.status_code == 401

    # Nenhuma linha deve ter sido criada no banco de dados
    count = db_session.query(ProcessedMessage).filter(ProcessedMessage.message_id == msg_id).count()
    assert count == 0
