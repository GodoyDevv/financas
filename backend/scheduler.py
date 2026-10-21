import os
import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Optional
import zoneinfo

from sqlalchemy.orm import Session
from .database import SessionLocal
from .models import Transaction
from .atlas import send_whatsapp_message
from .webhook import GROUP_JID

logger = logging.getLogger("fintrack.scheduler")

TIMEZONE_SP = zoneinfo.ZoneInfo("America/Sao_Paulo")

# Controle em memória para não disparar relatórios duplicados
ULTIMO_RELATORIO_ENVIADO: Optional[date] = None
ULTIMO_RELATORIO_SEMANAL_ENVIADO: Optional[date] = None

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

def gerar_barra_progresso(percentual: float, total_blocos: int = 10) -> str:
    """Gera uma barra visual de blocos para WhatsApp (ex: [████░░░░░░] 40%)"""
    preenchidos = round((percentual / 100) * total_blocos)
    preenchidos = max(0, min(total_blocos, preenchidos))
    vazios = total_blocos - preenchidos
    return f"{'■' * preenchidos}{'□' * vazios}"

def gerar_texto_relatorio_diario(data_alvo: date, db: Session) -> str:
    """
    Constrói a mensagem executiva formatada em WhatsApp Markdown elegante
    apenas com as despesas variáveis registradas naquele dia.
    """
    data_str = data_alvo.strftime("%Y-%m-%d")
    data_formatada_br = data_alvo.strftime("%d/%m/%Y")

    transacoes = db.query(Transaction).filter(
        Transaction.data == data_str,
        Transaction.tipo.in_(["despesa_variavel"])
    ).order_by(Transaction.id.asc()).all()

    primeiro_dia_mes = data_alvo.replace(day=1).strftime("%Y-%m-%d")
    gastos_mes = db.query(Transaction).filter(
        Transaction.data >= primeiro_dia_mes,
        Transaction.data <= data_str,
        Transaction.tipo == "despesa_variavel"
    ).all()
    total_acumulado_mes = sum(float(t.valor or 0) for t in gastos_mes)

    linhas = []
    linhas.append("🌙 *Atlas Finanças · Fechamento do Dia*")
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

def gerar_texto_relatorio_semanal_macro(data_fim: date, db: Session) -> str:
    """
    Constrói o Relatório Semanal Macro (Sábado às 22h).
    Consolida os últimos 7 dias (domingo a sábado ou últimos 7 dias corridos)
    agrupado por CATEGORIA (Transporte, Alimentação, Saúde, Lazer, etc).
    """
    data_inicio = data_fim - timedelta(days=6)
    str_inicio = data_inicio.strftime("%Y-%m-%d")
    str_fim = data_fim.strftime("%Y-%m-%d")

    data_fmt_inicio = data_inicio.strftime("%d/%m")
    data_fmt_fim = data_fim.strftime("%d/%m/%Y")

    # Busca apenas despesas variáveis (gastos cotidianos do casal)
    transacoes = db.query(Transaction).filter(
        Transaction.data >= str_inicio,
        Transaction.data <= str_fim,
        Transaction.tipo.in_(["despesa_variavel"])
    ).all()

    linhas = []
    linhas.append("🗓️ *Atlas Finanças · Balanço Semanal Macro*")
    linhas.append(f"📅 *Semana de {data_fmt_inicio} a {data_fmt_fim}*")
    linhas.append("━━━━━━━━━━━━━━━━━━━━━")

    if not transacoes:
        linhas.append("\n✨ *Semana impressionante!* Nenhum gasto variável foi registrado nos últimos 7 dias.")
        linhas.append("Parabéns pelo controle orçamentário impecável do casal! 🚀👏")
    else:
        total_semana = sum(float(t.valor or 0) for t in transacoes)
        qtd = len(transacoes)

        # Agrupamento por Categoria
        mapa_cat = {}
        mapa_source = {}

        for t in transacoes:
            cat = (t.categoria or "Outros").strip()
            val = float(t.valor or 0)
            mapa_cat[cat] = mapa_cat.get(cat, 0.0) + val

            nome = normalizar_nome_source(t.source)
            mapa_source[nome] = mapa_source.get(nome, 0.0) + val

        # Ordenação por maior gasto
        ranking_cat = sorted(mapa_cat.items(), key=lambda x: x[1], reverse=True)

        linhas.append(f"\n💰 *Total da Semana:* *{format_brl(total_semana)}* ({qtd} despesas)")
        linhas.append(f"\n📁 *Gastos por Categoria (Visão Macro):*")

        for cat, val in ranking_cat:
            pct = (val / total_semana * 100) if total_semana > 0 else 0
            barra = gerar_barra_progresso(pct, 8)
            linhas.append(f"• *{cat}*: *{format_brl(val)}* ({pct:.0f}%)\n  `{barra}`")

        # Divisão Macro Casal na Semana
        linhas.append(f"\n👥 *Divisão do Casal na Semana:*")
        tot_bruno = mapa_source.get("Bruno", 0.0)
        tot_leticia = mapa_source.get("Letícia", 0.0)
        tot_outros = mapa_source.get("Outros", 0.0)

        if tot_bruno > 0:
            pct_b = (tot_bruno / total_semana * 100) if total_semana > 0 else 0
            linhas.append(f"• 👤 *Bruno:* {format_brl(tot_bruno)} ({pct_b:.0f}%)")
        if tot_leticia > 0:
            pct_l = (tot_leticia / total_semana * 100) if total_semana > 0 else 0
            linhas.append(f"• 🌸 *Letícia:* {format_brl(tot_leticia)} ({pct_l:.0f}%)")
        if tot_outros > 0:
            linhas.append(f"• 📝 *Outros/Manual:* {format_brl(tot_outros)}")

        # Categoria campeã
        top_cat, top_val = ranking_cat[0]
        linhas.append(f"\n💡 *Principal Ofensor:* A categoria *{top_cat}* representou *{(top_val/total_semana*100):.0f}%* do orçamento semanal.")

    linhas.append("\n━━━━━━━━━━━━━━━━━━━━━")
    linhas.append("🌐 Painel Completo: fintrack-intelligence.onrender.com")
    linhas.append("Excelente final de semana para vocês! 🥂✨")

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

def executar_envio_relatorio_semanal(data_custom: Optional[date] = None, force: bool = False) -> bool:
    """Dispara o relatório semanal macro para o WhatsApp (Sábados às 22h)."""
    global ULTIMO_RELATORIO_SEMANAL_ENVIADO

    agora = datetime.now(TIMEZONE_SP)
    data_alvo = data_custom or agora.date()

    if not force and ULTIMO_RELATORIO_SEMANAL_ENVIADO == data_alvo:
        logger.info(f"Relatório semanal de {data_alvo} já foi enviado esta semana. Pulando.")
        return False

    db = SessionLocal()
    try:
        texto = gerar_texto_relatorio_semanal_macro(data_alvo, db)
        sucesso = send_whatsapp_message(GROUP_JID, texto)
        if sucesso:
            ULTIMO_RELATORIO_SEMANAL_ENVIADO = data_alvo
            logger.info(f"Relatório semanal de {data_alvo} enviado com sucesso para {GROUP_JID}.")
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
    logger.info("Iniciando agendador em background para Relatórios (Diário 21h30 e Semanal Sábado 22h00 BRT)...")
    while True:
        try:
            agora = datetime.now(TIMEZONE_SP)
            hora = agora.hour
            minuto = agora.minute
            hoje = agora.date()
            dia_da_semana = agora.weekday() # 5 = Sábado

            # RELATÓRIO SEMANAL MACRO: Sábado entre 22h00 e 22h15
            if dia_da_semana == 5 and hora == 22 and minuto <= 15:
                if ULTIMO_RELATORIO_SEMANAL_ENVIADO != hoje:
                    logger.info("Horário do Relatório Semanal Macro alcançado (Sábado 22h). Disparando...")
                    executar_envio_relatorio_semanal(data_custom=hoje, force=False)

            # RELATÓRIO DIÁRIO: Entre 21h30 e 22h00
            na_janela_diaria = (hora == 21 and minuto >= 30) or (hora == 22 and minuto == 0 and dia_da_semana != 5)

            if na_janela_diaria and ULTIMO_RELATORIO_ENVIADO != hoje:
                logger.info(f"Horário de fechamento diário ({hora:02d}:{minuto:02d} BRT). Disparando...")
                executar_envio_relatorio_diario(data_custom=hoje, force=False)

            # Aguarda 30 segundos antes da próxima checagem
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            logger.info("Loop do agendador cancelado.")
            break
        except Exception as e:
            logger.error(f"Erro no loop do agendador: {e}")
            await asyncio.sleep(30)
