import re
import calendar
from datetime import date

def add_months(sourcedate: date, months: int) -> date:
    """Adiciona 'months' meses a uma data mantendo o dia válido para o mês de destino."""
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def parse_financial_payload(payload: dict) -> dict:
    """Extrai e normaliza dados de webhook recebidos (ex: WhatsApp/Gateway)."""
    try:
        raw_tipo = str(payload.get("tipo", "despesa_variavel")).lower()
        if raw_tipo in ["receita", "despesa_fixa", "despesa_variavel"]:
            tipo = raw_tipo
        elif raw_tipo == "despesa":
            tipo = "despesa_variavel"
        else:
            tipo = "despesa_variavel"

        valor = float(payload.get("valor", 0.0))
        categoria = str(payload.get("categoria", "Outros")).strip()
        data_str = str(payload.get("data", date.today().isoformat()))
        descricao = str(payload.get("descricao", "Lançamento WhatsApp")).strip()
        source = str(payload.get("source", "WhatsApp"))
        vencimento = payload.get("vencimento")
        parcelas = max(1, int(payload.get("parcelas", 1)))
        
        return {
            "tipo": tipo,
            "valor": abs(valor),
            "categoria": categoria or "Outros",
            "data": data_str,
            "descricao": descricao,
            "source": source,
            "vencimento": str(vencimento) if vencimento else None,
            "parcelas": parcelas
        }
    except Exception:
        return None

def parse_text_message(message: str) -> dict:
    """
    Interpreta mensagens de texto em linguagem natural vindas do WhatsApp ou chat.
    Suporta compras à vista e compras parceladas:
    Exemplos:
    - 'Cabelo 200 3 vezes' -> R$ 200,00 em 3 parcelas
    - 'Tênis 150 em 5x'    -> R$ 150,00 em 5 parcelas
    - 'Uber 30,50'         -> R$ 30,50 em 1 parcela
    """
    clean_msg = message.strip()
    msg_lower = clean_msg.lower()

    # 1. Determina tipo (receita vs despesa_fixa vs despesa_variavel)
    income_keywords = [
        "receita", "salario", "salário", "deposito", "depósito", "rendimento", 
        "pix recebido", "venda", "lucro", "entrada", "freela", "pro-labore", "pró-labore"
    ]
    
    fixed_expense_keywords = [
        "aluguel", "condomínio", "condominio", "energia", "enel", "luz", "agua", "água", 
        "sabesp", "internet", "iptu", "ipva", "mensalidade", "seguro", "plano de saude", 
        "plano de saúde", "fixa", "fatura fixa", "assinatura", "escola", "faculdade"
    ]

    if any(k in msg_lower for k in income_keywords):
        tipo = "receita"
    elif any(k in msg_lower for k in fixed_expense_keywords):
        tipo = "despesa_fixa"
    else:
        tipo = "despesa_variavel"

    # 2. Detecção de Parcelamento ('3 vezes', '3x', 'em 3x', '3 parcelas')
    parcelas = 1
    # Captura padrão como '3 vezes', '3x', 'em 5x', '10 parcelas'
    p_match = re.search(r'(?:em\s+)?(\d{1,2})\s*(?:x|vezes|parcelas)\b', clean_msg, re.IGNORECASE)
    msg_cleaned = clean_msg
    if p_match:
        try:
            qtd = int(p_match.group(1))
            if 1 <= qtd <= 60:
                parcelas = qtd
                # Remove o trecho de parcelas para isolar valor e descrição
                msg_cleaned = clean_msg[:p_match.start()] + clean_msg[p_match.end():]
        except ValueError:
            parcelas = 1

    # 3. Extrai valor numérico (suporta formato R$ 1.250,50 ou 128,50 ou 34.90)
    valor = 0.0
    valor_match = re.search(r'(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+(?:[\.,]\d{1,2})?)', msg_cleaned)
    if valor_match:
        val_str = valor_match.group(1).replace(".", "").replace(",", ".")
        try:
            valor = float(val_str)
        except ValueError:
            valor = 0.0
        # Remove o valor da string para sobrar apenas a descrição
        desc_part = msg_cleaned[:valor_match.start()] + msg_cleaned[valor_match.end():]
    else:
        desc_part = msg_cleaned

    # 4. Categorização inteligente
    categoria = "Outros"
    
    categories_map = {
        "Alimentação": ["almoço", "almoco", "jantar", "café", "cafe", "restaurante", "ifood", "lanche", "mercado", "supermercado", "padaria", "pizza", "hamburguer", "feira"],
        "Transporte": ["uber", "99", "gasolina", "combustivel", "combustível", "estacionamento", "onibus", "ônibus", "metro", "metrô", "pedágio", "pedagio"],
        "Moradia": ["aluguel", "condomínio", "condominio", "energia", "enel", "luz", "agua", "água", "internet", "iptu", "gas", "gás"],
        "Lazer": ["cinema", "streaming", "netflix", "spotify", "show", "viagem", "bar", "cerveja", "jogos", "game"],
        "Saúde": ["farmácia", "farmacia", "remedio", "remédio", "consulta", "médico", "medico", "exame", "hospital", "dentista", "plano"],
        "Salário/Renda": ["salário", "salario", "freela", "rendimento", "dividendo", "pro-labore", "pró-labore", "bonificação", "comissão"]
    }

    if tipo == "receita":
        categoria = "Salário/Renda"
        for cat, keywords in categories_map.items():
            if any(k in msg_lower for k in keywords):
                categoria = cat
                break
    else:
        for cat, keywords in categories_map.items():
            if any(k in msg_lower for k in keywords):
                categoria = cat
                break
        if categoria == "Outros" and tipo == "despesa_fixa":
            categoria = "Moradia"

    # 5. Descrição limpa
    descricao = re.sub(r'(?:R\$\s*)?\d+(?:[\.,]\d+)?', '', desc_part)
    descricao = re.sub(r'\s+', ' ', descricao).strip(" ,.-")
    if not descricao:
        descricao = clean_msg[:60]
    else:
        descricao = descricao[:60].capitalize()

    return {
        "tipo": tipo,
        "valor": round(valor, 2),
        "categoria": categoria,
        "descricao": descricao,
        "data": date.today().isoformat(),
        "source": "WhatsApp",
        "parcelas": parcelas
    }