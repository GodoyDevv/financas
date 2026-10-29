"""
backend/services/reports.py

Geração de relatórios executivos diários e semanais em WhatsApp Markdown.
Sem acoplamento com o loop assíncrono do scheduler.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.domain.money import to_decimal
from backend.models import Transaction


def format_brl(valor: float | Decimal) -> str:
    """Formata valor em padrão brasileiro de moeda R$ 1.234,56"""
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def normalizar_nome_source(source: str | None) -> str:
    if not source:
        return "Outros"
    s = str(source).strip()
    s_lower = s.lower()
    if "let" in s_lower or "tícia" in s_lower or "ticia" in s_lower:
        return "Letícia"
    if "bruno" in s_lower:
        return "Bruno"
    return s


def obter_autor_transacao(t: Transaction) -> str:
    """Retorna o autor normalizado priorizando o campo t.author ou fallback para t.source."""
    if t.author:
        return normalizar_nome_source(t.author)
    if t.source and t.source not in ["Manual", "WhatsApp", "Webhook"]:
        return normalizar_nome_source(t.source)
    return "Outros"


def gerar_barra_progresso(percentual: float, total_blocos: int = 10) -> str:
    """Gera uma barra visual de blocos para WhatsApp (ex: [████░░░░░░] 40%)"""
    preenchidos = round((percentual / 100) * total_blocos)
    preenchidos = max(0, min(total_blocos, preenchidos))
    vazios = total_blocos - preenchidos
    return f"{'■' * preenchidos}{'□' * vazios}"


class ReportsService:
    def __init__(self, db: Session):
        self.db = db

    def gerar_texto_relatorio_diario(self, data_alvo: date) -> str:
        data_formatada_br = data_alvo.strftime("%d/%m/%Y")

        transacoes = (
            self.db.query(Transaction)
            .filter(Transaction.data == data_alvo, Transaction.tipo.in_(["despesa_variavel"]))
            .order_by(Transaction.id.asc())
            .all()
        )

        primeiro_dia_mes = data_alvo.replace(day=1)
        gastos_mes = (
            self.db.query(Transaction)
            .filter(
                Transaction.data >= primeiro_dia_mes,
                Transaction.data <= data_alvo,
                Transaction.tipo == "despesa_variavel",
            )
            .all()
        )
        total_acumulado_mes = sum((to_decimal(t.valor) for t in gastos_mes), Decimal("0.00"))

        linhas = []
        linhas.append("🌙 *Atlas Finanças · Fechamento do Dia*")
        linhas.append(f"📅 *{data_formatada_br}*")
        linhas.append("━━━━━━━━━━━━━━━━━━━━━")

        if not transacoes:
            linhas.append(
                "\n✨ *Dia econômico!* Nenhum gasto variável foi registrado hoje no grupo."
            )
            linhas.append("Vocês mantiveram o foco total no orçamento! 🎯👏")
        else:
            total_dia = sum((to_decimal(t.valor) for t in transacoes), Decimal("0.00"))
            qtd = len(transacoes)

            linhas.append("\n📊 *Resumo Geral:*")
            linhas.append(
                f"• *{qtd}* lançamento{'s' if qtd > 1 else ''} registrado{'s' if qtd > 1 else ''}"
            )
            linhas.append(f"• Total do dia: *{format_brl(total_dia)}*")

            tot_bruno = Decimal("0.00")
            tot_leticia = Decimal("0.00")
            tot_outros = Decimal("0.00")

            for t in transacoes:
                n = obter_autor_transacao(t)
                v = to_decimal(t.valor)
                if n == "Bruno":
                    tot_bruno += v
                elif n == "Letícia":
                    tot_leticia += v
                else:
                    tot_outros += v

            linhas.append("\n👥 *Quem Lançou Hoje:*")
            if tot_bruno > 0:
                linhas.append(f"• 👤 *Bruno:* {format_brl(tot_bruno)}")
            if tot_leticia > 0:
                linhas.append(f"• 🌸 *Letícia:* {format_brl(tot_leticia)}")
            if tot_outros > 0:
                linhas.append(f"• 📝 *Outros/Manual:* {format_brl(tot_outros)}")

            linhas.append("\n🧾 *Detalhamento dos Gastos:*")
            for t in transacoes:
                autor = obter_autor_transacao(t)
                desc = t.descricao or t.categoria or "Sem descrição"
                cat = t.categoria or "Outros"
                val = to_decimal(t.valor)
                linhas.append(f"• *{desc}* ({cat}) ➔ *{format_brl(val)}* _{autor}_")

        linhas.append("\n━━━━━━━━━━━━━━━━━━━━━")
        linhas.append(f"📈 *Total Variável Acumulado no Mês:* *{format_brl(total_acumulado_mes)}*")
        linhas.append("🌐 Acompanhe ao vivo: fintrack-intelligence.onrender.com")
        linhas.append("Tenham uma ótima noite de descanso! 💤✨")

        return "\n".join(linhas)

    def gerar_texto_relatorio_semanal_macro(self, data_fim: date) -> str:
        data_inicio = data_fim - timedelta(days=6)
        data_fmt_inicio = data_inicio.strftime("%d/%m")
        data_fmt_fim = data_fim.strftime("%d/%m/%Y")

        transacoes = (
            self.db.query(Transaction)
            .filter(
                Transaction.data >= data_inicio,
                Transaction.data <= data_fim,
                Transaction.tipo.in_(["despesa_variavel"]),
            )
            .all()
        )

        linhas = []
        linhas.append("🗓️ *Atlas Finanças · Balanço Semanal Macro*")
        linhas.append(f"📅 *Semana de {data_fmt_inicio} a {data_fmt_fim}*")
        linhas.append("━━━━━━━━━━━━━━━━━━━━━")

        if not transacoes:
            linhas.append(
                "\n✨ *Semana impressionante!* Nenhum gasto variável foi registrado nos últimos 7 dias."
            )
            linhas.append("Parabéns pelo controle orçamentário impecável do casal! 🚀👏")
        else:
            total_semana = sum((to_decimal(t.valor) for t in transacoes), Decimal("0.00"))
            qtd = len(transacoes)

            mapa_cat: dict[str, Decimal] = {}
            mapa_source: dict[str, Decimal] = {}

            for t in transacoes:
                cat = (t.categoria or "Outros").strip()
                val = to_decimal(t.valor)
                mapa_cat[cat] = mapa_cat.get(cat, Decimal("0.00")) + val

                nome = obter_autor_transacao(t)
                mapa_source[nome] = mapa_source.get(nome, Decimal("0.00")) + val

            ranking_cat = sorted(mapa_cat.items(), key=lambda x: x[1], reverse=True)

            linhas.append(f"\n💰 *Total da Semana:* *{format_brl(total_semana)}* ({qtd} despesas)")
            linhas.append("\n📁 *Gastos por Categoria (Visão Macro):*")

            for cat, val in ranking_cat:
                pct = float(val / total_semana * 100) if total_semana > 0 else 0.0
                barra = gerar_barra_progresso(pct, 8)
                linhas.append(f"• *{cat}*: *{format_brl(val)}* ({pct:.0f}%)\n  `{barra}`")

            linhas.append("\n👥 *Divisão do Casal na Semana:*")
            tot_bruno = mapa_source.get("Bruno", Decimal("0.00"))
            tot_leticia = mapa_source.get("Letícia", Decimal("0.00"))
            tot_outros = mapa_source.get("Outros", Decimal("0.00"))

            if tot_bruno > 0:
                pct_b = float(tot_bruno / total_semana * 100) if total_semana > 0 else 0.0
                linhas.append(f"• 👤 *Bruno:* {format_brl(tot_bruno)} ({pct_b:.0f}%)")
            if tot_leticia > 0:
                pct_l = float(tot_leticia / total_semana * 100) if total_semana > 0 else 0.0
                linhas.append(f"• 🌸 *Letícia:* {format_brl(tot_leticia)} ({pct_l:.0f}%)")
            if tot_outros > 0:
                linhas.append(f"• 📝 *Outros/Manual:* {format_brl(tot_outros)}")

            top_cat, top_val = ranking_cat[0]
            linhas.append(
                f"\n💡 *Principal Ofensor:* A categoria *{top_cat}* representou *{(top_val / total_semana * 100):.0f}%* do orçamento semanal."
            )

        linhas.append("\n━━━━━━━━━━━━━━━━━━━━━")
        linhas.append("🌐 Painel Completo: fintrack-intelligence.onrender.com")
        linhas.append("Excelente final de semana para vocês! 🥂✨")

        return "\n".join(linhas)
