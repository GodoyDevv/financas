"""
tests/test_scheduler_tick.py

Testes automatizados para o sistema de agendamento acionado por tick externo idempotente
e protegido pelo relógio de São Paulo (UTC-3).

Critérios de Aceite cobertos:
1. Tick um minuto antes do horário configurado do relatório não envia; um minuto depois envia; um segundo tick no mesmo dia não reenvia.
2. Dois ticks simultâneos => um único envio.
3. 00:30 UTC pertence ao dia anterior de São Paulo (run_key correto).
4. Tick atrasado (23:50) ainda envia o relatório do dia; no dia seguinte envia o novo.
5. Job 'running' antigo (> 10 min) é retomado; mais de 3 tentativas => failed.
6. Sem X-Admin-Token => 401; nenhum job roda dentro do processo da aplicação.
"""

import threading
from datetime import UTC, datetime
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.dates_and_money import TIMEZONE_SP
from backend.db.models import JobRun
from backend.main import app
from backend.scheduler import (
    claim_job,
    processar_tick_jobs,
)

TEST_ADMIN_TOKEN = get_settings().ADMIN_TOKEN.get_secret_value()


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def clean_job_runs(db_session):
    db_session.query(JobRun).delete()
    db_session.commit()
    yield
    db_session.query(JobRun).delete()
    db_session.commit()


# ==============================================================================
# 1. HORÁRIO E IDEMPOTÊNCIA DO RELATÓRIO DIÁRIO
# ==============================================================================
def test_tick_before_and_after_scheduled_time_and_idempotency(db_session):
    """
    Tick 1 min antes (21:29) não envia relatório diário.
    Tick 1 min depois (21:31) envia.
    Segundo tick no mesmo dia não reenvia.
    """
    # 21:29 em SP -> não devido
    t_before = datetime(2026, 10, 25, 21, 29, 0, tzinfo=TIMEZONE_SP)
    with mock.patch("backend.integrations.evolution.send_whatsapp_message") as mock_send:
        res1 = processar_tick_jobs(now=t_before, db=db_session)
        assert res1["jobs"]["relatorio_diario"]["status"] == "not_due"
        mock_send.assert_not_called()

    # 21:31 em SP -> devido e executa
    t_after = datetime(2026, 10, 25, 21, 31, 0, tzinfo=TIMEZONE_SP)
    with mock.patch("backend.scheduler.send_whatsapp_message", return_value=True) as mock_send:
        res2 = processar_tick_jobs(now=t_after, db=db_session)
        assert res2["jobs"]["relatorio_diario"]["status"] == "executed"
        mock_send.assert_called_once()

    # Segundo tick às 21:45 no mesmo dia -> skipped (já executado com chave 2026-10-25)
    t_later = datetime(2026, 10, 25, 21, 45, 0, tzinfo=TIMEZONE_SP)
    with mock.patch("backend.scheduler.send_whatsapp_message", return_value=True) as mock_send:
        res3 = processar_tick_jobs(now=t_later, db=db_session)
        assert res3["jobs"]["relatorio_diario"]["status"] == "skipped"
        mock_send.assert_not_called()


# ==============================================================================
# 2. DOIS TICKS SIMULTÂNEOS => UM ÚNICO ENVIO
# ==============================================================================
def test_concurrent_ticks_result_in_single_execution(db_session):
    """Dois ticks concorrentes em threads para o mesmo horário disparam o relatório exatamente uma vez."""
    t_now = datetime(2026, 10, 25, 21, 35, 0, tzinfo=TIMEZONE_SP)
    statuses = []

    def run_tick():
        from backend.database import SessionLocal

        with (
            SessionLocal() as s,
            mock.patch("backend.scheduler.send_whatsapp_message", return_value=True),
        ):
            r = processar_tick_jobs(now=t_now, db=s)
            statuses.append(r["jobs"]["relatorio_diario"]["status"])

    th1 = threading.Thread(target=run_tick)
    th2 = threading.Thread(target=run_tick)

    th1.start()
    th2.start()
    th1.join()
    th2.join()

    # Um deve ter status 'executed' e o outro 'skipped'
    assert "executed" in statuses
    assert "skipped" in statuses

    # No banco, deve haver apenas 1 registro para relatorio_diario / 2026-10-25
    runs = (
        db_session.query(JobRun)
        .filter(JobRun.job_name == "relatorio_diario", JobRun.run_key == "2026-10-25")
        .all()
    )
    assert len(runs) == 1
    assert runs[0].status == "done"


# ==============================================================================
# 3. 00:30 UTC PERTENCE AO DIA ANTERIOR DE SÃO PAULO
# ==============================================================================
def test_utc_midnight_boundary_resolves_to_previous_day_in_sao_paulo(db_session):
    """
    00:30 UTC de 2026-10-26 é 21:30 de 2026-10-25 em São Paulo (UTC-3).
    A chave de execução do relatório diário deve ser '2026-10-25'.
    """
    utc_time = datetime(2026, 10, 26, 0, 30, 0, tzinfo=UTC)
    sp_time = utc_time.astimezone(TIMEZONE_SP)

    with mock.patch("backend.integrations.evolution.send_whatsapp_message", return_value=True):
        res = processar_tick_jobs(now=sp_time, db=db_session)
        assert res["jobs"]["relatorio_diario"]["status"] == "executed"
        assert res["jobs"]["relatorio_diario"]["run_key"] == "2026-10-25"

    run = db_session.query(JobRun).filter(JobRun.job_name == "relatorio_diario").first()
    assert run is not None
    assert run.run_key == "2026-10-25"


# ==============================================================================
# 4. TICK ATRASADO (23:50) AINDA ENVIA O DO DIA; NO DIA SEGUINTE ENVIA O NOVO
# ==============================================================================
def test_delayed_tick_still_executes_and_next_day_executes_new(db_session):
    """Se o tick chegar atrasado (23:50), ainda dispara o relatório do dia; no dia seguinte dispara o próximo."""
    t_late = datetime(2026, 10, 25, 23, 50, 0, tzinfo=TIMEZONE_SP)
    with mock.patch("backend.scheduler.send_whatsapp_message", return_value=True) as mock_send:
        res1 = processar_tick_jobs(now=t_late, db=db_session)
        assert res1["jobs"]["relatorio_diario"]["status"] == "executed"
        assert res1["jobs"]["relatorio_diario"]["run_key"] == "2026-10-25"
        mock_send.assert_called_once()

    # Dia seguinte às 21:35
    t_next_day = datetime(2026, 10, 26, 21, 35, 0, tzinfo=TIMEZONE_SP)
    with mock.patch("backend.scheduler.send_whatsapp_message", return_value=True) as mock_send:
        res2 = processar_tick_jobs(now=t_next_day, db=db_session)
        assert res2["jobs"]["relatorio_diario"]["status"] == "executed"
        assert res2["jobs"]["relatorio_diario"]["run_key"] == "2026-10-26"
        mock_send.assert_called_once()

    # Garante que há 2 registros distintos no banco
    assert db_session.query(JobRun).filter(JobRun.job_name == "relatorio_diario").count() == 2


# ==============================================================================
# 5. RETOMADA DE JOB 'RUNNING' ANTIGO E LIMITE DE 3 TENTATIVAS
# ==============================================================================
def test_stuck_job_resumed_and_max_attempts_marks_failed(db_session):
    """
    Job em 'running' há > 10 min pode ser retomado (attempts+1).
    Atingindo > 3 tentativas, passa para status 'failed'.
    """
    now_utc = datetime(2026, 10, 25, 12, 0, 0)
    old_time = datetime(2026, 10, 25, 11, 40, 0)  # 20 min atrás (> 10 min)

    # 1. Cria job travado com attempt 1
    stuck_run = JobRun(
        job_name="teste_stuck",
        run_key="key_001",
        status="running",
        attempts=1,
        started_at=old_time,
    )
    db_session.add(stuck_run)
    db_session.commit()

    # 2. Claim retoma o job travado incrementando attempts para 2
    claim2 = claim_job(db_session, "teste_stuck", "key_001", now_utc=now_utc)
    assert claim2 is not None
    assert claim2.attempts == 2
    assert claim2.status == "running"

    # Simula que travou novamente (atualiza started_at para 20 min antes)
    claim2.started_at = old_time
    db_session.commit()

    # 3. Claim retoma incrementando para 3
    claim3 = claim_job(db_session, "teste_stuck", "key_001", now_utc=now_utc)
    assert claim3 is not None
    assert claim3.attempts == 3
    assert claim3.status == "running"

    claim3.started_at = old_time
    db_session.commit()

    # 4. Quarta tentativa excede o limite (attempts >= 3) -> marcado como failed e claim retorna None
    claim4 = claim_job(db_session, "teste_stuck", "key_001", now_utc=now_utc)
    assert claim4 is None

    final_run = (
        db_session.query(JobRun)
        .filter(JobRun.job_name == "teste_stuck", JobRun.run_key == "key_001")
        .first()
    )
    assert final_run.status == "failed"
    assert "max_attempts" in final_run.error_code


# ==============================================================================
# 6. AUTENTICAÇÃO E ENDPOINTS HTTP (/internal/jobs/tick e /internal/jobs/{job})
# ==============================================================================
def test_jobs_tick_endpoint_requires_admin_token(client):
    """Sem token -> 401; com token correto -> 200."""
    res_no_token = client.post("/internal/jobs/tick")
    assert res_no_token.status_code == 401

    res_wrong_token = client.post(
        "/internal/jobs/tick", headers={"X-Admin-Token": "token_completamente_errado"}
    )
    assert res_wrong_token.status_code == 401

    with mock.patch("backend.integrations.evolution.send_whatsapp_message", return_value=True):
        res_ok = client.post("/internal/jobs/tick", headers={"X-Admin-Token": TEST_ADMIN_TOKEN})
        assert res_ok.status_code == 200
        data = res_ok.json()
        assert data["status"] == "ok"
        assert "summary" in data
        assert "reprocess_due" in data["summary"]["jobs"]


def test_internal_jobs_manual_dispatch(client):
    """Disparo manual de job específico via POST /internal/jobs/{job_name}."""
    with mock.patch("backend.scheduler.send_whatsapp_message", return_value=True):
        res = client.post(
            "/internal/jobs/relatorio_diario",
            headers={"X-Admin-Token": TEST_ADMIN_TOKEN},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "success"
        assert res.json()["job"] == "relatorio_diario"


def test_backward_compatibility_endpoints_still_work(client):
    """Endpoints legados /api/relatorio-diario/disparar continuam respondendo com sucesso."""
    with mock.patch("backend.scheduler.send_whatsapp_message", return_value=True):
        res = client.post(
            "/api/relatorio-diario/disparar",
            headers={"X-Admin-Token": TEST_ADMIN_TOKEN},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "success"
