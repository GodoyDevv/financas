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
) -> str:
    """Gera a mensagem de resposta executiva do Atlas mostrando valor da parcela e valor total."""
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
        detalhe = f"no valor de {val_formatado}"

    msg = f"🎙️ *Atlas:* Entendido, {user_name}! Lancei *{item_desc}* {detalhe} no Atlas Finanças."
    if saldo_livre is not None:
        saldo_str = (
            f"{float(saldo_livre):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
        saldo_fmt = f"R$ {saldo_str}"
        msg += f"\n📊 *Saldo Livre do Mês:* {saldo_fmt}"

    return msg
