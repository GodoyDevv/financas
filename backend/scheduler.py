"""
backend/scheduler.py

Agendador de background assíncrono para relatórios noturnos e semanais.
Delega a montagem dos relatórios para backend.services.reports.ReportsService.
"""

import asyncio
import logging
from datetime import date, datetime

from backend.config import get_settings
from backend.database import SessionLocal
from backend.dates_and_money import TIMEZONE_SP
from backend.integrations.evolution import send_whatsapp_message
from backend.services.reports import (
    ReportsService,
    format_brl,
    gerar_barra_progresso,
    normalizar_nome_source,
    obter_autor_transacao,
)

logger = logging.getLogger("fintrack.scheduler")

# Controle em memória para não disparar relatórios duplicados
ULTIMO_RELATORIO_ENVIADO: date | None = None
ULTIMO_RELATORIO_SEMANAL_ENVIADO: date | None = None


def get_target_group_jid() -> str:
    """Retorna o JID do grupo oficial a partir das configurações centralizadas."""
    return get_settings().WHATSAPP_GROUP_JID


def gerar_texto_relatorio_diario(data_alvo: date, db) -> str:
    """Wrapper de compatibilidade que delega para ReportsService."""
    return ReportsService(db).gerar_texto_relatorio_diario(data_alvo)


def gerar_texto_relatorio_semanal_macro(data_fim: date, db) -> str:
    """Wrapper de compatibilidade que delega para ReportsService."""
    return ReportsService(db).gerar_texto_relatorio_semanal_macro(data_fim)


def executar_envio_relatorio_diario(data_custom: date | None = None, force: bool = False) -> bool:
    """Dispara o envio do relatório diário para o WhatsApp."""
    global ULTIMO_RELATORIO_ENVIADO

    agora = datetime.now(TIMEZONE_SP)
    data_alvo = data_custom or agora.date()

    if not force and data_alvo == ULTIMO_RELATORIO_ENVIADO:
        logger.info(f"Relatório de {data_alvo} já foi enviado hoje. Pulando envio duplicado.")
        return False

    group_jid = get_target_group_jid()
    if not group_jid:
        logger.error("WHATSAPP_GROUP_JID não configurado. Não é possível enviar relatório diário.")
        return False

    db = SessionLocal()
    try:
        texto = ReportsService(db).gerar_texto_relatorio_diario(data_alvo)
        sucesso = send_whatsapp_message(group_jid, texto)
        if sucesso:
            ULTIMO_RELATORIO_ENVIADO = data_alvo
            logger.info(f"Relatório diário de {data_alvo} enviado com sucesso para {group_jid}.")
            return True
        else:
            logger.warning("Falha ao enviar relatório diário via WhatsApp (Evolution API).")
            return False
    except Exception as e:
        logger.error(f"Erro ao processar relatório diário: {e}", exc_info=True)
        return False
    finally:
        db.close()


def executar_envio_relatorio_semanal(data_custom: date | None = None, force: bool = False) -> bool:
    """Dispara o relatório semanal macro para o WhatsApp (Sábados às 22h)."""
    global ULTIMO_RELATORIO_SEMANAL_ENVIADO

    agora = datetime.now(TIMEZONE_SP)
    data_alvo = data_custom or agora.date()

    if not force and data_alvo == ULTIMO_RELATORIO_SEMANAL_ENVIADO:
        logger.info(f"Relatório semanal de {data_alvo} já foi enviado esta semana. Pulando.")
        return False

    group_jid = get_target_group_jid()
    if not group_jid:
        logger.error("WHATSAPP_GROUP_JID não configurado. Não é possível enviar relatório semanal.")
        return False

    db = SessionLocal()
    try:
        texto = ReportsService(db).gerar_texto_relatorio_semanal_macro(data_alvo)
        sucesso = send_whatsapp_message(group_jid, texto)
        if sucesso:
            ULTIMO_RELATORIO_SEMANAL_ENVIADO = data_alvo
            logger.info(f"Relatório semanal de {data_alvo} enviado com sucesso para {group_jid}.")
            return True
        else:
            logger.warning("Falha ao enviar relatório semanal via WhatsApp.")
            return False
    except Exception as e:
        logger.error(f"Erro ao processar relatório semanal: {e}", exc_info=True)
        return False
    finally:
        db.close()


async def loop_agendador_relatorio_noturno():
    """
    Loop assíncrono em background.
    1. Diário: Verifica se o horário atual de Brasília está entre 21h30 e 22h00 (Domingo a Sexta).
    2. Semanal: No Sábado às 22h00 (weekday == 5), dispara o Relatório Semanal Macro por Categoria!
    """
    logger.info(
        "Iniciando agendador em background para Relatórios (Diário 21h30 e Semanal Sábado 22h00 BRT)..."
    )
    while True:
        try:
            agora = datetime.now(TIMEZONE_SP)
            hora = agora.hour
            minuto = agora.minute
            hoje = agora.date()
            dia_da_semana = agora.weekday()  # 5 = Sábado

            # RELATÓRIO SEMANAL MACRO: Sábado entre 22h00 e 22h15
            if (
                dia_da_semana == 5
                and hora == 22
                and minuto <= 15
                and hoje != ULTIMO_RELATORIO_SEMANAL_ENVIADO
            ):
                logger.info(
                    "Horário do Relatório Semanal Macro alcançado (Sábado 22h). Disparando..."
                )
                executar_envio_relatorio_semanal(data_custom=hoje, force=False)

            # RELATÓRIO DIÁRIO: Entre 21h30 e 22h00
            na_janela_diaria = (hora == 21 and minuto >= 30) or (
                hora == 22 and minuto == 0 and dia_da_semana != 5
            )

            if na_janela_diaria and hoje != ULTIMO_RELATORIO_ENVIADO:
                logger.info(
                    f"Horário de fechamento diário ({hora:02d}:{minuto:02d} BRT). Disparando..."
                )
                executar_envio_relatorio_diario(data_custom=hoje, force=False)

            # Aguarda 30 segundos antes da próxima checagem
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            logger.info("Loop do agendador cancelado.")
            break
        except Exception as e:
            logger.error(f"Erro no loop do agendador: {e}")
            await asyncio.sleep(30)


__all__ = [
    "ULTIMO_RELATORIO_ENVIADO",
    "ULTIMO_RELATORIO_SEMANAL_ENVIADO",
    "executar_envio_relatorio_diario",
    "executar_envio_relatorio_semanal",
    "format_brl",
    "gerar_barra_progresso",
    "gerar_texto_relatorio_diario",
    "gerar_texto_relatorio_semanal_macro",
    "get_target_group_jid",
    "loop_agendador_relatorio_noturno",
    "normalizar_nome_source",
    "obter_autor_transacao",
]
