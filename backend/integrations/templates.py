"""
backend/integrations/templates.py

Templates e formatação executiva de mensagens para o WhatsApp.
Sem dependência de serviços ou API.
"""

from decimal import Decimal


def format_atlas_confirmation(
    user_name: str,
    item_desc: str,
    valor: float | Decimal,
    parcelas: int,
    saldo_livre: float | Decimal | None = None,
    valor_total: float | Decimal | None = None,
    categoria: str | None = None,
    data_lancamento: str | None = None,
    transcricao: str | None = None,
    include_undo_instruction: bool = False,
) -> str:
    """Gera a mensagem de resposta executiva do Atlas mostrando detalhes completos e instrução de desfazer."""
    val_formatado = f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    val_formatado = f"R$ {val_formatado}"

    if parcelas > 1:
        if valor_total is not None:
            tot_str = (
                f"{float(valor_total):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            )
            tot_formatado = f"R$ {tot_str}"
        else:
            tot_val = Decimal(str(valor)) * parcelas
            tot_str = f"{float(tot_val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            tot_formatado = f"R$ {tot_str}"
        detalhe = f"{parcelas}x de {val_formatado} (total {tot_formatado})"
    else:
        detalhe = f"{val_formatado}"

    if include_undo_instruction:
        linhas = []
        linhas.append(f"✅ *Atlas:* Entendido, {user_name}! Lançamento registrado.")
        if transcricao:
            linhas.append(f"🎧 _\"{transcricao.strip()}\"_")
        linhas.append(f"• *Descrição:* {item_desc}")
        linhas.append(f"• *Valor:* {detalhe}")
        if categoria:
            linhas.append(f"• *Categoria:* {categoria}")
        if data_lancamento:
            linhas.append(f"• *Data:* {data_lancamento}")
        if saldo_livre is not None:
            saldo_str = (
                f"{float(saldo_livre):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            )
            saldo_fmt = f"R$ {saldo_str}"
            linhas.append(f"📊 *Saldo Livre do Mês:* {saldo_fmt}")
        linhas.append("\nPara cancelar, responda a esta mensagem com *desfazer*.")
        return "\n".join(linhas)

    detalhe_legado = detalhe if parcelas > 1 else f"no valor de {val_formatado}"
    msg = f"🎙️ *Atlas:* Entendido, {user_name}! Lancei *{item_desc}* {detalhe_legado} no Atlas Finanças."
    if saldo_livre is not None:
        saldo_str = (
            f"{float(saldo_livre):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
        saldo_fmt = f"R$ {saldo_str}"
        msg += f"\n📊 *Saldo Livre do Mês:* {saldo_fmt}"

    return msg
