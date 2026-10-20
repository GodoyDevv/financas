import os
import asyncio
import logging
from datetime import datetime, date
from typing import Optional
import zoneinfo

from sqlalchemy.orm import Session
from .database import SessionLocal
from .models import Transaction
from .atlas import send_whatsapp_message
from .webhook import GROUP_JID

logger = logging.getLogger("fintrack.scheduler")

TIMEZONE_SP = zoneinfo.ZoneInfo("America/Sao_Paulo")

# Controle em memória para não disparar relatório duplicado no mesmo dia
ULTIMO_RELATORIO_ENVIADO: Optional[date] = None

def format_brl(valor: float) -> str:
    """Formata valor em padrão brasileiro de moeda R$ 1.234,56"""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def normalizar_nome_source(source: Optional[str]) -> str:
    if not source:
        return "Outros"
    s = str(source).strip()
    s_lower = s.lower()
    if "let" in s_lower or "tícia" in s_lower or "ticia" in s_lower:
        return "Letícia"
    if "bruno" in s_lower:
        return "Bruno"
    return s

def gerar_texto_relatorio_diario(data_alvo: date, db: Session) -> str:
    """
    Constrói a mensagem executiva formatada em WhatsApp Markdown elegante
    apenas com as despesas variáveis registradas naquele dia.
    """
    data_str = data_alvo.strftime("%Y-%m-%d")
    data_formatada_br = data_alvo.strftime("%d/%m/%Y")

    # Busca lançamentos de despesa do dia alvo
    transacoes = db.query(Transaction).filter(
        Transaction.data == data_str,
        Transaction.tipo.in_(["despesa_variavel"])
    ).order_by(Transaction.id.asc()).all()

    # Cálculo acumulado do mês corrente até a data alvo para dar contexto financeiro
    primeiro_dia_mes = data_alvo.replace(day=1).strftime("%Y-%m-%d")
    gastos_mes = db.query(Transaction).filter(
        Transaction.data >= primeiro_dia_mes,
        Transaction.data <= data_str,
        Transaction.tipo == "despesa_variavel"
    ).all()
    total_acumulado_mes = sum(float(t.valor or 0) for t in gastos_mes)

    linhas = []
    linhas.append("🌙 *FinTrack Atlas · Fechamento do Dia*")
    linhas.append(f"📅 *{data_formatada_br}*")
    linhas.append("━━━━━━━━━━━━━━━━━━━━━")

    if not transacoes:
        linhas.append("\n✨ *Dia econômico!* Nenhum gasto variável foi registrado hoje no grupo.")
        linhas.append("Vocês mantiveram o foco total no orçamento! 🎯👏")
    else:
        total_dia = sum(float(t.valor or 0) for t in transacoes)
        qtd = len(transacoes)

        linhas.append(f"\n📊 *Resumo Geral:*")
        linhas.append(f"• *{qtd}* lançamento{'s' if qtd > 1 else ''} registrado{'s' if qtd > 1 else ''}")
        linhas.append(f"• Total do dia: *{format_brl(total_dia)}*")

        # Divisão Bruno vs Letícia no dia
        tot_bruno = 0.0
        tot_leticia = 0.0
        tot_outros = 0.0

        for t in transacoes:
            n = normalizar_nome_source(t.source)
            v = float(t.valor or 0)
            if n == "Bruno":
                tot_bruno += v
            elif n == "Letícia":
                tot_leticia += v
            else:
                tot_outros += v

        linhas.append(f"\n👥 *Quem Lançou Hoje:*")
        if tot_bruno > 0:
            linhas.append(f"• 👤 *Bruno:* {format_brl(tot_bruno)}")
        if tot_leticia > 0:
            linhas.append(f"• 🌸 *Letícia:* {format_brl(tot_leticia)}")
        if tot_outros > 0:
            linhas.append(f"• 📝 *Outros/Manual:* {format_brl(tot_outros)}")

        linhas.append(f"\n🧾 *Detalhamento dos Gastos:*")
        for t in transacoes:
            autor = normalizar_nome_source(t.source)
            desc = t.descricao or t.categoria or "Sem descrição"
            cat = t.categoria or "Outros"
            val = float(t.valor or 0)
            linhas.append(f"• *{desc}* ({cat}) ➔ *{format_brl(val)}* _{autor}_")

    linhas.append("\n━━━━━━━━━━━━━━━━━━━━━")
    linhas.append(f"📈 *Total Variável Acumulado no Mês:* *{format_brl(total_acumulado_mes)}*")
    linhas.append("🌐 Acompanhe ao vivo: fintrack-intelligence.onrender.com")
    linhas.append("Tenham uma ótima noite de descanso! 💤✨")

    return "\n".join(linhas)

def executar_envio_relatorio_diario(data_custom: Optional[date] = None, force: bool = False) -> bool:
    """Dispara o envio do relatório diário para o WhatsApp."""
    global ULTIMO_RELATORIO_ENVIADO

    agora = datetime.now(TIMEZONE_SP)
    data_alvo = data_custom or agora.date()

    if not force and ULTIMO_RELATORIO_ENVIADO == data_alvo:
        logger.info(f"Relatório de {data_alvo} já foi enviado hoje. Pulando envio duplicado.")
        return False

    db = SessionLocal()
    try:
        texto = gerar_texto_relatorio_diario(data_alvo, db)
        sucesso = send_whatsapp_message(GROUP_JID, texto)
        if sucesso:
            ULTIMO_RELATORIO_ENVIADO = data_alvo
            logger.info(f"Relatório diário de {data_alvo} enviado com sucesso para {GROUP_JID}.")
            return True
        else:
            logger.warning("Falha ao enviar relatório diário via WhatsApp (Evolution API).")
            return False
    except Exception as e:
        logger.error(f"Erro ao processar relatório diário: {e}", exc_info=True)
        return False
    finally:
        db.close()

async def loop_agendador_relatorio_noturno():
    """
    Loop assíncrono em background.
    Verifica a cada 30 segundos se o horário atual de Brasília está entre 21h30 e 22h00.
    Assim que entra na janela, dispara o relatório e marca a data para não reenviar.
    """
    logger.info("Iniciando agendador em background para Relatório Noturno (21h30 - 22h00 BRT)...")
    while True:
        try:
            agora = datetime.now(TIMEZONE_SP)
            hora = agora.hour
            minuto = agora.minute
            hoje = agora.date()

            # Janela entre 21h30 e 22h00
            na_janela = (hora == 21 and minuto >= 30) or (hora == 22 and minuto == 0)

            if na_janela and ULTIMO_RELATORIO_ENVIADO != hoje:
                logger.info(f"Horário de fechamento alcançado ({hora:02d}:{minuto:02d} BRT). Disparando relatório...")
                executar_envio_relatorio_diario(data_custom=hoje, force=False)

            # Aguarda 30 segundos antes da próxima checagem
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            logger.info("Loop do agendador noturno cancelado.")
            break
        except Exception as e:
            logger.error(f"Erro no loop do agendador: {e}")
            await asyncio.sleep(30)
