"""
backend/scheduler.py

Agendador de jobs e relatórios acionado por tick externo idempotente.
Sem estado global ou threads em background: a persistência relacional (tabela job_runs)
garante atomicidade, recuperação de jobs travados e semântica at-least-once.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import SessionLocal
from backend.dates_and_money import TIMEZONE_SP
from backend.db.models import JobRun
from backend.integrations.evolution import send_whatsapp_message
from backend.services.message_processor import purge_old, reprocess_due
from backend.services.recurrences import ensure_recurrences
from backend.services.reports import (
    ReportsService,
    format_brl,
    gerar_barra_progresso,
    normalizar_nome_source,
    obter_autor_transacao,
)
from backend.timeutils import utc_now_naive

logger = logging.getLogger("fintrack.scheduler")

JOB_CLAIM_TIMEOUT_MINUTES = 10
MAX_JOB_ATTEMPTS = 3


def get_target_group_jid() -> str:
    """Retorna o JID do grupo oficial a partir das configurações centralizadas."""
    return get_settings().WHATSAPP_GROUP_JID


def gerar_texto_relatorio_diario(data_alvo: date, db: Session) -> str:
    """Wrapper de compatibilidade que delega para ReportsService."""
    return ReportsService(db).gerar_texto_relatorio_diario(data_alvo)


def gerar_texto_relatorio_semanal_macro(data_fim: date, db: Session) -> str:
    """Wrapper de compatibilidade que delega para ReportsService."""
    return ReportsService(db).gerar_texto_relatorio_semanal_macro(data_fim)


def claim_job(
    db: Session,
    job_name: str,
    run_key: str,
    now_utc: datetime | None = None,
) -> JobRun | None:
    """
    Tenta registrar o claim de execução do job no banco de forma atômica.
    - Se não existir, faz INSERT com status 'running' e attempts=1.
    - Se já existir:
        * Se estiver 'done', retorna None (já executado).
        * Se estiver 'running' há mais de JOB_CLAIM_TIMEOUT_MINUTES e attempts < MAX_JOB_ATTEMPTS:
          retoma a execução incrementando attempts.
        * Caso contrário, retorna None.
    """
    ts_utc = now_utc or utc_now_naive()
    stuck_threshold = ts_utc - timedelta(minutes=JOB_CLAIM_TIMEOUT_MINUTES)

    new_run = JobRun(
        job_name=job_name,
        run_key=run_key,
        status="running",
        attempts=1,
        started_at=ts_utc,
    )
    try:
        db.add(new_run)
        db.commit()
        db.refresh(new_run)
        return new_run
    except IntegrityError:
        db.rollback()

    # Já existe registro com essa chave. Verifica se está travado.
    existing = (
        db.query(JobRun).filter(JobRun.job_name == job_name, JobRun.run_key == run_key).first()
    )
    if not existing:
        return None

    if existing.status == "done":
        return None

    if existing.status == "running" and existing.started_at <= stuck_threshold:
        if existing.attempts < MAX_JOB_ATTEMPTS:
            existing.attempts += 1
            existing.started_at = ts_utc
            existing.error_code = "stuck_worker_resumed"
            db.commit()
            db.refresh(existing)
            logger.warning(
                "job_stuck_worker_resumed",
                extra={"job_name": job_name, "run_key": run_key, "attempt": existing.attempts},
            )
            return existing
        else:
            existing.status = "failed"
            existing.finished_at = ts_utc
            existing.error_code = "max_attempts_exceeded_stuck"
            db.commit()
            logger.error(
                "job_failed_max_attempts",
                extra={"job_name": job_name, "run_key": run_key},
            )
            return None

    return None


def finish_job(
    db: Session,
    job_run: JobRun,
    status: str = "done",
    error_code: str | None = None,
    now_utc: datetime | None = None,
) -> None:
    """Marca a conclusão ou falha de uma execução de job."""
    ts_utc = now_utc or utc_now_naive()
    job_run.status = status
    job_run.finished_at = ts_utc
    job_run.error_code = error_code
    db.commit()


def run_idempotent_job(
    db: Session,
    job_name: str,
    run_key: str,
    fn: Callable[[], Any],
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Executa a função fn protegida pelo claim idempotente em job_runs."""
    job_run = claim_job(db, job_name, run_key, now_utc=now_utc)
    if not job_run:
        return {"status": "skipped", "job": job_name, "run_key": run_key}

    try:
        res = fn()
        finish_job(db, job_run, status="done", now_utc=now_utc)
        return {"status": "executed", "job": job_name, "run_key": run_key, "result": res}
    except Exception as exc:
        finish_job(db, job_run, status="failed", error_code=str(exc)[:100], now_utc=now_utc)
        logger.error(
            f"Erro ao executar job {job_name} ({run_key}): {exc}",
            exc_info=True,
            extra={"job": job_name, "run_key": run_key},
        )
        return {"status": "failed", "job": job_name, "run_key": run_key, "error": str(exc)}


def executar_envio_relatorio_diario(
    data_custom: date | None = None,
    force: bool = False,
    now: datetime | None = None,
    db: Session | None = None,
) -> bool:
    """Dispara o envio do relatório diário para o WhatsApp."""
    sp_now = now if now is not None else datetime.now(TIMEZONE_SP)
    data_alvo = data_custom or sp_now.date()
    run_key = str(data_alvo)

    def _do_send(s: Session) -> bool:
        group_jid = get_target_group_jid()
        if not group_jid:
            logger.error(
                "WHATSAPP_GROUP_JID não configurado. Não é possível enviar relatório diário."
            )
            return False

        texto = ReportsService(s).gerar_texto_relatorio_diario(data_alvo)
        sucesso = send_whatsapp_message(group_jid, texto)
        if sucesso:
            logger.info("report_sent", extra={"tipo": "diario", "data": str(data_alvo)})
            return True
        else:
            logger.warning("Falha ao enviar relatório diário via WhatsApp (Evolution API).")
            return False

    session = db if db is not None else SessionLocal()
    try:
        if force:
            return _do_send(session)
        res = run_idempotent_job(session, "relatorio_diario", run_key, lambda: _do_send(session))
        return bool(res.get("status") == "executed" and res.get("result"))
    finally:
        if db is None:
            session.close()


def executar_envio_relatorio_semanal(
    data_custom: date | None = None,
    force: bool = False,
    now: datetime | None = None,
    db: Session | None = None,
) -> bool:
    """Dispara o relatório semanal macro para o WhatsApp (Sábados às 22h)."""
    sp_now = now if now is not None else datetime.now(TIMEZONE_SP)
    data_alvo = data_custom or sp_now.date()
    iso_cal = data_alvo.isocalendar()
    run_key = f"{iso_cal.year}-W{iso_cal.week:02d}"

    def _do_send(s: Session) -> bool:
        group_jid = get_target_group_jid()
        if not group_jid:
            logger.error(
                "WHATSAPP_GROUP_JID não configurado. Não é possível enviar relatório semanal."
            )
            return False

        texto = ReportsService(s).gerar_texto_relatorio_semanal_macro(data_alvo)
        sucesso = send_whatsapp_message(group_jid, texto)
        if sucesso:
            logger.info("report_sent", extra={"tipo": "semanal", "data": str(data_alvo)})
            return True
        else:
            logger.warning("Falha ao enviar relatório semanal via WhatsApp.")
            return False

    session = db if db is not None else SessionLocal()
    try:
        if force:
            return _do_send(session)
        res = run_idempotent_job(session, "relatorio_semanal", run_key, lambda: _do_send(session))
        return bool(res.get("status") == "executed" and res.get("result"))
    finally:
        if db is None:
            session.close()


def processar_tick_jobs(now: datetime | None = None, db: Session | None = None) -> dict[str, Any]:
    """
    Decide pelo relógio de São Paulo quais jobs estão devidos e executa cada um com idempotência.
    Relógio injetável (now) para testes determinísticos sem monkeypatching.
    """
    if now is not None:
        sp_now = now if now.tzinfo is not None else now.replace(tzinfo=TIMEZONE_SP)
    else:
        sp_now = datetime.now(TIMEZONE_SP)

    data_sp = sp_now.date()
    hora = sp_now.hour
    minuto = sp_now.minute
    weekday = sp_now.weekday()  # 5 = Sábado

    run_key_diario = str(data_sp)
    iso_cal = data_sp.isocalendar()
    run_key_semanal = f"{iso_cal.year}-W{iso_cal.week:02d}"
    run_key_mes = data_sp.strftime("%Y-%m-%d")

    session = db if db is not None else SessionLocal()
    results: dict[str, Any] = {
        "timestamp_sp": sp_now.isoformat(),
        "jobs": {},
    }

    try:
        # 1. Reprocess due (executado a CADA tick)
        reprocessed = reprocess_due(db=session)
        results["jobs"]["reprocess_due"] = {"reprocessed_count": len(reprocessed)}

        # 2. Relatório diário (devido a partir de 21h30 até o fim do dia)
        # Regra original: Domingo a Sexta entre 21h30 e 22h, ou sábado 21h30-22h.
        # Com tick externo: a partir das 21h30 até 23h59 de qualquer dia, se ainda não enviado
        if hora > 21 or (hora == 21 and minuto >= 30):
            res_diario = run_idempotent_job(
                session,
                "relatorio_diario",
                run_key_diario,
                lambda: executar_envio_relatorio_diario(
                    data_custom=data_sp, force=True, db=session
                ),
            )
            results["jobs"]["relatorio_diario"] = res_diario
        else:
            results["jobs"]["relatorio_diario"] = {"status": "not_due"}

        # 3. Relatório semanal macro: Sábado a partir das 22h00
        if weekday == 5 and hora >= 22:
            res_semanal = run_idempotent_job(
                session,
                "relatorio_semanal",
                run_key_semanal,
                lambda: executar_envio_relatorio_semanal(
                    data_custom=data_sp, force=True, db=session
                ),
            )
            results["jobs"]["relatorio_semanal"] = res_semanal
        else:
            results["jobs"]["relatorio_semanal"] = {"status": "not_due"}

        # 4. Purge de mensagens antigas: 1x ao dia, de madrugada (entre 01h00 e 05h00)
        if 1 <= hora <= 5:
            res_purge = run_idempotent_job(
                session,
                "purge_old",
                run_key_diario,
                lambda: purge_old(db=session),
            )
            results["jobs"]["purge_old"] = res_purge
        else:
            results["jobs"]["purge_old"] = {"status": "not_due"}

        # 5. Ensure recurrences: 1x ao dia (pode rodar no primeiro tick do dia a qualquer hora)
        mes_str = data_sp.strftime("%Y-%m")
        res_rec = run_idempotent_job(
            session,
            "ensure_recurrences",
            run_key_mes,
            lambda: ensure_recurrences(session, mes_str),
        )
        results["jobs"]["ensure_recurrences"] = res_rec

    finally:
        if db is None:
            session.close()

    return results


__all__ = [
    "claim_job",
    "executar_envio_relatorio_diario",
    "executar_envio_relatorio_semanal",
    "finish_job",
    "format_brl",
    "gerar_barra_progresso",
    "gerar_texto_relatorio_diario",
    "gerar_texto_relatorio_semanal_macro",
    "get_target_group_jid",
    "normalizar_nome_source",
    "obter_autor_transacao",
    "processar_tick_jobs",
    "run_idempotent_job",
]
