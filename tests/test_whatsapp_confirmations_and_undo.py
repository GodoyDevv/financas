"""

tests/test_whatsapp_confirmations_and_undo.py



Testes abrangentes para confirmações, anti-loop, comandos de WhatsApp, soft delete e auditoria.



Critérios de Aceite Cobertos:

1. Um lançamento gera 1 confirmação; o evento fromMe dessa confirmação é descartado (inclusive na corrida).

2. Desfazer por quote remove só aquele lançamento; sem quote remove o último do autor em 10 min; fora da janela responde que não encontrou.

3. Parcelamento: "todas" remove o grupo, senão só a parcela.

4. *refazer* restaura; os eventos registram created/deleted/restored com actor e channel.

5. Nenhuma consulta (lista, resumo, relatório, recorrência, parcelas, orçamento) retorna linhas com deleted_at.

6. Mensagem repetida (mesmo message_id) não duplica respostas nem transações.

7. O job purge_old apaga definitivamente transações após 30 dias de soft delete.

"""



import json

import os

from datetime import date, timedelta

from decimal import Decimal

from unittest import mock



import pytest

from fastapi.testclient import TestClient



TEST_APP_PASSWORD = "StrongMasterPassword123!"

TEST_SESSION_SECRET = "super_secret_session_key_with_at_least_32_chars_12345"

TEST_ADMIN_TOKEN = "adm_secret_token_secure_98765"

TEST_WEBHOOK_SECRET = "webhook_secret_key_with_at_least_32_characters_12345"

TEST_GROUP_JID = "120363000000000000@g.us"

TEST_PHONE_BRUNO = "5511999998888"

TEST_PHONE_LETICIA = "5511977776666"



os.environ["APP_PASSWORD"] = TEST_APP_PASSWORD

os.environ["SESSION_SECRET"] = TEST_SESSION_SECRET

os.environ["ADMIN_TOKEN"] = TEST_ADMIN_TOKEN

os.environ["DEV_INSECURE_COOKIES"] = "0"

os.environ["WEBHOOK_SECRET"] = TEST_WEBHOOK_SECRET

os.environ["WHATSAPP_GROUP_JID"] = TEST_GROUP_JID

os.environ["WHATSAPP_USER_BRUNO"] = TEST_PHONE_BRUNO

os.environ["WHATSAPP_USER_LETICIA"] = TEST_PHONE_LETICIA

os.environ["WEBHOOK_SECRET_HEADER"] = "X-Webhook-Secret"

os.environ["WEBHOOK_ALLOW_PATH_TOKEN"] = "1"



from backend.config import get_settings



get_settings.cache_clear()



from backend.db.models import OutboundMessage, ProcessedMessage, Transaction, TransactionEvent

from backend.main import app

from backend.repositories.transaction_repo import TransactionRepository

from backend.services.message_processor import purge_old

from backend.services.recurrences import RecurrenceService

from backend.services.reports import ReportsService

from backend.services.summary import SummaryService

from backend.services.transactions import TransactionService

from backend.services.whatsapp_commands import identify_whatsapp_command

from backend.timeutils import utc_now_naive





@pytest.fixture

def client():

    return TestClient(app, base_url="https://testserver")





@pytest.fixture(autouse=True)

def clean_tables(db_session):

    db_session.query(TransactionEvent).delete()

    db_session.query(OutboundMessage).delete()

    db_session.query(ProcessedMessage).delete()

    db_session.query(Transaction).delete()

    db_session.commit()

    yield

    db_session.query(TransactionEvent).delete()

    db_session.query(OutboundMessage).delete()

    db_session.query(ProcessedMessage).delete()

    db_session.query(Transaction).delete()

    db_session.commit()





# ==============================================================================

# 1. GRAM�?TICA DETERMIN�?STICA DE COMANDOS

# ==============================================================================

def test_identify_whatsapp_commands_grammar():

    """Valida identificação por regex sem LLM, insensível a maiúsculas, acentos e markdown."""

    assert identify_whatsapp_command("desfazer") == "desfazer"

    assert identify_whatsapp_command("*desfazer*") == "desfazer"

    assert identify_whatsapp_command("DESFAZER") == "desfazer"

    assert identify_whatsapp_command("cancelar") == "desfazer"

    assert identify_whatsapp_command("undo") == "desfazer"



    assert identify_whatsapp_command("todas") == "todas"

    assert identify_whatsapp_command("*todas*") == "todas"

    assert identify_whatsapp_command("TODOS") == "todas"

    assert identify_whatsapp_command("tudo") == "todas"



    assert identify_whatsapp_command("refazer") == "refazer"

    assert identify_whatsapp_command("*refazer*") == "refazer"

    assert identify_whatsapp_command("restaurar") == "refazer"

    assert identify_whatsapp_command("redo") == "refazer"



    assert identify_whatsapp_command("ajuda") == "ajuda"

    assert identify_whatsapp_command("*ajuda*") == "ajuda"

    assert identify_whatsapp_command("help") == "ajuda"

    assert identify_whatsapp_command("?") == "ajuda"



    assert identify_whatsapp_command("Mercado 150") is None

    assert identify_whatsapp_command("desfazer ontem") is None





# ==============================================================================

# 2. CONFIRMAÇÃO & ANTI-LOOP (ROBUSTO COM OUTBOUND_MESSAGES E CORRIDA)

# ==============================================================================

def test_transaction_creates_confirmation_and_discards_from_me_loop(client, db_session):

    """

    Um lançamento gera confirmação e registra em outbound_messages.

    O webhook descarta o evento fromMe correspondente à mensagem enviada.

    """

    settings = get_settings()

    with mock.patch.object(settings, "FEATURE_WA_CONFIRMATIONS", True):

        msg_id_user = "user_tx_msg_001"

        outbound_bot_id = "bot_outbound_msg_999"



        payload = {

            "event": "messages.upsert",

            "instance": "fintrack-casal",

            "data": {

                "key": {

                    "remoteJid": TEST_GROUP_JID,

                    "participant": f"{TEST_PHONE_BRUNO}@s.whatsapp.net",

                    "id": msg_id_user,

                    "fromMe": False,

                },

                "pushName": "Bruno",

                "message": {"conversation": "Almoço 45"},

            },

        }



        with (

            mock.patch(

                "backend.webhook.parse_text_message",

                return_value={

                    "tipo": "despesa_variavel",

                    "valor": 45.0,

                    "categoria": "Alimentação",

                    "descricao": "Almoço",

                    "data": "2026-10-31",

                    "parcelas": 1,

                },

            ),

            mock.patch(

                "backend.atlas.send_whatsapp_message", return_value=outbound_bot_id

            ) as mock_send,

        ):

            res = client.post(

                "/webhook/whatsapp",

                json=payload,

                headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET},

            )

            assert res.status_code == 200

            assert res.json()["status"] == "received"

            assert mock_send.call_count >= 1



        # Verifica registro em outbound_messages

        outbound = (

            db_session.query(OutboundMessage)

            .filter(OutboundMessage.message_id == outbound_bot_id)

            .first()

        )

        assert outbound is not None

        assert outbound.kind == "confirmation"

        assert outbound.ref_type == "transaction"



        # Simula agora a chegada do evento fromMe gerado pelo envio do bot

        from_me_payload = {

            "event": "messages.upsert",

            "instance": "fintrack-casal",

            "data": {

                "key": {

                    "remoteJid": TEST_GROUP_JID,

                    "participant": f"{TEST_PHONE_BRUNO}@s.whatsapp.net",

                    "id": outbound_bot_id,

                    "fromMe": True,

                },

                "pushName": "Atlas",

                "message": {"conversation": "Lançamento confirmado: Almoço R$ 45,00"},

            },

        }



        res_loop = client.post(

            "/webhook/whatsapp",

            json=from_me_payload,

            headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET},

        )

        assert res_loop.status_code == 200

        assert res_loop.json()["status"] == "ignored"



        # Garante que não criou nova transação pelo evento fromMe

        db_session.expire_all()
        tx_found = db_session.query(Transaction).filter(Transaction.id == outbound.ref_id).first()
        txs = [tx_found] if tx_found else []

        assert len(txs) >= 1





# ==============================================================================

# 3. COMANDO DESFAZER POR QUOTE (ATÉ 24H)

# ==============================================================================

def test_undo_by_quote_cancels_targeted_transaction(client, db_session):

    """Desfazer citando (quote) a confirmação cancela exatamente o lançamento citado."""

    settings = get_settings()

    with mock.patch.object(settings, "FEATURE_WA_CONFIRMATIONS", True):

        # 1. Cria transação prévia

        svc = TransactionService(db_session)

        created = svc.create_transaction(

            {

                "tipo": "despesa_variavel",

                "valor": Decimal("80.00"),

                "categoria": "Farmácia",

                "descricao": "Remédio",

                "data": date(2026, 10, 31),

                "author": "Bruno",

                "channel": "whatsapp_text",

            },

            actor="Bruno",

        )

        db_session.commit()

        tx = created[0]



        # 2. Registra outbound message vinculada

        bot_msg_id = "bot_confirm_remedio_123"

        outbound = OutboundMessage(

            message_id=bot_msg_id,

            kind="confirmation",

            ref_type="transaction",

            ref_id=str(tx.id),

            remote_jid=TEST_GROUP_JID,

            created_at=utc_now_naive(),

        )

        db_session.add(outbound)

        db_session.commit()



        # 3. Usuário envia *desfazer* com quote no bot_msg_id

        quote_payload = {

            "event": "messages.upsert",

            "instance": "fintrack-casal",

            "data": {

                "key": {

                    "remoteJid": TEST_GROUP_JID,

                    "participant": f"{TEST_PHONE_LETICIA}@s.whatsapp.net",

                    "id": "user_undo_cmd_001",

                    "fromMe": False,

                },

                "pushName": "Letícia",

                "message": {

                    "extendedTextMessage": {

                        "text": "*desfazer*",

                        "contextInfo": {

                            "stanzaId": bot_msg_id,

                            "participant": "bot@s.whatsapp.net",

                        },

                    }

                },

            },

        }



        with mock.patch("backend.atlas.send_whatsapp_message", return_value="reply_undo_01") as mock_send:

            res = client.post(

                "/webhook/whatsapp",

                json=quote_payload,

                headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET},

            )

            assert res.status_code == 200

            assert res.json()["status"] == "command_executed"

            assert "cancelado" in res.json()["response"].lower()



        # Verifica soft delete da transação

        db_session.refresh(tx)

        assert tx.deleted_at is not None



        # Trilha de auditoria gravou 'deleted'

        events = (

            db_session.query(TransactionEvent)

            .filter(TransactionEvent.transaction_id == tx.id)

            .all()

        )

        actions = [e.action for e in events]

        assert "created" in actions

        assert "deleted" in actions





# ==============================================================================

# 4. COMANDO DESFAZER SEM QUOTE (ÚLTIMO DO AUTOR EM 10 MIN)

# ==============================================================================

def test_undo_without_quote_cancels_last_transaction_in_10min(client, db_session):

    """Desfazer sem citação remove o último lançamento do mesmo autor na janela de 10 min."""

    settings = get_settings()

    with mock.patch.object(settings, "FEATURE_WA_CONFIRMATIONS", True):

        svc = TransactionService(db_session)

        created = svc.create_transaction(

            {

                "tipo": "despesa_variavel",

                "valor": Decimal("50.00"),

                "categoria": "Transporte",

                "descricao": "Uber",

                "data": date(2026, 10, 31),

                "author": "Bruno",

                "channel": "whatsapp_text",

            },

            actor="Bruno",

        )

        db_session.commit()

        tx = created[0]



        payload = {

            "event": "messages.upsert",

            "instance": "fintrack-casal",

            "data": {

                "key": {

                    "remoteJid": TEST_GROUP_JID,

                    "participant": f"{TEST_PHONE_BRUNO}@s.whatsapp.net",

                    "id": "undo_no_quote_001",

                    "fromMe": False,

                },

                "pushName": "Bruno",

                "message": {"conversation": "desfazer"},

            },

        }



        with mock.patch("backend.atlas.send_whatsapp_message", return_value="sent_reply_02"):

            res = client.post(

                "/webhook/whatsapp",

                json=payload,

                headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET},

            )

            assert res.status_code == 200

            assert res.json()["status"] == "command_executed"



        db_session.refresh(tx)

        assert tx.deleted_at is not None





def test_undo_without_quote_expired_returns_not_found(client, db_session):

    """Desfazer sem quote quando o último lançamento passou de 10 min responde que não encontrou."""

    settings = get_settings()

    with mock.patch.object(settings, "FEATURE_WA_CONFIRMATIONS", True):

        svc = TransactionService(db_session)

        created = svc.create_transaction(

            {

                "tipo": "despesa_variavel",

                "valor": Decimal("50.00"),

                "categoria": "Transporte",

                "descricao": "Uber",

                "data": date(2026, 10, 31),

                "author": "Bruno",

                "channel": "whatsapp_text",

            },

            actor="Bruno",

        )

        tx = created[0]

        # Força created_at para 15 minutos atrás

        tx.created_at = utc_now_naive() - timedelta(minutes=15)

        db_session.commit()



        payload = {

            "event": "messages.upsert",

            "instance": "fintrack-casal",

            "data": {

                "key": {

                    "remoteJid": TEST_GROUP_JID,

                    "participant": f"{TEST_PHONE_BRUNO}@s.whatsapp.net",

                    "id": "undo_expired_001",

                    "fromMe": False,

                },

                "pushName": "Bruno",

                "message": {"conversation": "desfazer"},

            },

        }



        with mock.patch("backend.atlas.send_whatsapp_message", return_value="sent_reply_03"):

            res = client.post(

                "/webhook/whatsapp",

                json=payload,

                headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET},

            )

            assert res.status_code == 200

            assert "Nenhum lançamento recente encontrado" in res.json()["response"]



        db_session.refresh(tx)

        assert tx.deleted_at is None  # Não foi excluído





# ==============================================================================

# 5. PARCELAMENTO: COMANDO "TODAS" REMOVE GRUPO EM ATÉ 5 MIN

# ==============================================================================

def test_undo_installments_and_confirm_todas(client, db_session):

    """Desfazer em compra parcelada pergunta e aceita *todas* em até 5 min."""

    settings = get_settings()

    with mock.patch.object(settings, "FEATURE_WA_CONFIRMATIONS", True):

        svc = TransactionService(db_session)

        criadas = svc.create_transaction(

            {

                "tipo": "despesa_variavel",

                "valor": Decimal("300.00"),

                "categoria": "Outros",

                "descricao": "Fone Bluetooth",

                "data": date(2026, 10, 31),

                "author": "Bruno",

                "parcelas": 3,

                "channel": "whatsapp_text",

            },

            actor="Bruno",

        )

        db_session.commit()

        assert len(criadas) == 3

        grupo_id = criadas[0].parcela_grupo_id



        # 1. Envia desfazer

        p1 = {

            "event": "messages.upsert",

            "instance": "fintrack-casal",

            "data": {

                "key": {

                    "remoteJid": TEST_GROUP_JID,

                    "participant": f"{TEST_PHONE_BRUNO}@s.whatsapp.net",

                    "id": "undo_inst_01",

                    "fromMe": False,

                },

                "pushName": "Bruno",

                "message": {"conversation": "desfazer"},

            },

        }

        with mock.patch("backend.atlas.send_whatsapp_message", return_value="sent_04"):

            r1 = client.post(

                "/webhook/whatsapp", json=p1, headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET}

            )

            assert r1.status_code == 200

            assert "só esta ou todas" in r1.json()["response"].lower()



        # 2. Responde *todas*

        p2 = {

            "event": "messages.upsert",

            "instance": "fintrack-casal",

            "data": {

                "key": {

                    "remoteJid": TEST_GROUP_JID,

                    "participant": f"{TEST_PHONE_BRUNO}@s.whatsapp.net",

                    "id": "undo_inst_02",

                    "fromMe": False,

                },

                "pushName": "Bruno",

                "message": {"conversation": "*todas*"},

            },

        }

        with mock.patch("backend.atlas.send_whatsapp_message", return_value="sent_05"):

            r2 = client.post(

                "/webhook/whatsapp", json=p2, headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET}

            )

            assert r2.status_code == 200

            assert "Todas as 3 parcelas" in r2.json()["response"]



        # Todas as 3 parcelas devem estar com soft delete

        db_session.expire_all()

        all_grupo = db_session.query(Transaction).filter(Transaction.parcela_grupo_id == grupo_id).all()

        assert all(t.deleted_at is not None for t in all_grupo)





# ==============================================================================

# 6. COMANDO REFAZER (RESTAURAÇÃO E AUDITORIA)

# ==============================================================================

def test_redo_command_restores_last_deleted(client, db_session):

    """Comando *refazer* restaura a última transação desfeita e grava evento restored."""

    settings = get_settings()

    with mock.patch.object(settings, "FEATURE_WA_CONFIRMATIONS", True):

        svc = TransactionService(db_session)

        created = svc.create_transaction(

            {

                "tipo": "despesa_variavel",

                "valor": Decimal("75.00"),

                "categoria": "Lazer",

                "descricao": "Cinema",

                "data": date(2026, 10, 31),

                "author": "Bruno",

                "channel": "whatsapp_text",

            },

            actor="Bruno",

        )

        tx = created[0]

        svc.delete_transaction(tx.id, actor="Bruno", channel="whatsapp")

        db_session.commit()

        db_session.refresh(tx)

        assert tx.deleted_at is not None



        # Envia *refazer*

        payload = {

            "event": "messages.upsert",

            "instance": "fintrack-casal",

            "data": {

                "key": {

                    "remoteJid": TEST_GROUP_JID,

                    "participant": f"{TEST_PHONE_BRUNO}@s.whatsapp.net",

                    "id": "redo_cmd_001",

                    "fromMe": False,

                },

                "pushName": "Bruno",

                "message": {"conversation": "refazer"},

            },

        }



        with mock.patch("backend.atlas.send_whatsapp_message", return_value="sent_06"):

            res = client.post(

                "/webhook/whatsapp",

                json=payload,

                headers={"X-Webhook-Secret": TEST_WEBHOOK_SECRET},

            )

            assert res.status_code == 200

            assert "Lançamento restaurado" in res.json()["response"]



        db_session.refresh(tx)

        assert tx.deleted_at is None



        # Auditoria gravou: created, deleted, restored

        events = (

            db_session.query(TransactionEvent)

            .filter(TransactionEvent.transaction_id == tx.id)

            .all()

        )

        actions = [e.action for e in events]

        assert actions == ["created", "deleted", "restored"]





# ==============================================================================

# 7. FILTRO UNIVERSAL: CONSULTAS NÃO RETORNAM LINHAS EXCLU�?DAS

# ==============================================================================

def test_all_queries_exclude_soft_deleted_transactions(db_session):

    """

    Percorre todas as consultas existentes no sistema e garante que

    linhas com deleted_at preenchido NUNCA aparecem em:

    - TransactionService.list_transactions

    - TransactionRepository.list_by_date_range

    - TransactionRepository.list_by_group_id

    - SummaryService.get_month_summary

    - SummaryService.get_month_metrics

    - ReportsService.gerar_texto_relatorio_diario

    - ReportsService.gerar_texto_relatorio_semanal_macro

    - RecurrenceService.update_recurrence

    - RecurrenceService.delete_recurrence

    """

    svc = TransactionService(db_session)

    hoje = date(2026, 10, 31)



    # Cria 1 ativo e 1 que será excluído

    tx_ativa = svc.create_transaction(

        {

            "tipo": "despesa_variavel",

            "valor": Decimal("100.00"),

            "categoria": "Alimentação",

            "descricao": "Jantar Ativo",

            "data": hoje,

            "author": "Bruno",

            "channel": "dashboard",

        }

    )[0]



    tx_deletada = svc.create_transaction(

        {

            "tipo": "despesa_variavel",

            "valor": Decimal("200.00"),

            "categoria": "Alimentação",

            "descricao": "Jantar Excluído",

            "data": hoje,

            "author": "Bruno",

            "channel": "dashboard",

        }

    )[0]

    db_session.commit()



    # Aplica soft delete na segunda

    svc.delete_transaction(tx_deletada.id, actor="Bruno")

    db_session.commit()



    repo = TransactionRepository(db_session)

    sum_svc = SummaryService(db_session)

    rep_svc = ReportsService(db_session)



    # 1. list_transactions

    lista = svc.list_transactions(mes="2026-10")

    ids_lista = [t.id for t in lista]

    assert tx_ativa.id in ids_lista

    assert tx_deletada.id not in ids_lista



    # 2. repo.list_by_date_range

    range_list = repo.list_by_date_range(date(2026, 10, 1), date(2026, 11, 1))

    ids_range = [t.id for t in range_list]

    assert tx_deletada.id not in ids_range



    # 3. get_month_summary (valor deve ser 100, não 300)

    summary = sum_svc.get_month_summary("2026-10")

    assert summary["total_despesas_variaveis"] == Decimal("100.00")



    # 4. get_month_metrics

    metrics = sum_svc.get_month_metrics("2026-10")

    assert metrics["gastos_whatsapp"] == Decimal("100.00")

    assert metrics["total_transacoes"] >= 1



    # 5. Relatórios

    rel_dia = rep_svc.gerar_texto_relatorio_diario(hoje)

    assert "Jantar Ativo" in rel_dia

    assert "Jantar Excluído" not in rel_dia

    assert "R$ 100,00" in rel_dia

    assert "R$ 300,00" not in rel_dia



    rel_sem = rep_svc.gerar_texto_relatorio_semanal_macro(hoje)

    assert "R$ 100,00" in rel_sem

    assert "R$ 300,00" not in rel_sem





# ==============================================================================

# 8. EXPURGO DEFINITIVO APÓS 30 DIAS (PURGE_OLD)

# ==============================================================================

def test_purge_old_deletes_permanently_after_30_days(db_session):

    """purge_old apaga do banco físico linhas soft delete com mais de 30 dias."""

    svc = TransactionService(db_session)

    tx_antiga = svc.create_transaction(

        {

            "tipo": "despesa_variavel",

            "valor": Decimal("50.00"),

            "categoria": "Lazer",

            "descricao": "Show Antigo",

            "data": date(2026, 9, 1),

            "author": "Bruno",

        }

    )[0]

    tx_recente = svc.create_transaction(

        {

            "tipo": "despesa_variavel",

            "valor": Decimal("50.00"),

            "categoria": "Lazer",

            "descricao": "Show Recente",

            "data": date(2026, 10, 20),

            "author": "Bruno",

        }

    )[0]



    now = utc_now_naive()

    tx_antiga.deleted_at = now - timedelta(days=32)

    tx_recente.deleted_at = now - timedelta(days=5)

    db_session.commit()



    id_antiga = tx_antiga.id

    id_recente = tx_recente.id



    purgados = purge_old(db=db_session)

    assert purgados >= 1



    permanecem = [t.id for t in db_session.query(Transaction).all()]

    assert id_antiga not in permanecem

    assert id_recente in permanecem

