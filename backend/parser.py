import re
import calendar
from datetime import date
from decimal import Decimal
from .dates_and_money import today_br, to_decimal
from .categories import CANONICAL_CATEGORIES, resolve_canonical_name
from .services.installments import add_months_clamped as add_months

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
        raw_cat = payload.get("categoria")
        resolved = resolve_canonical_name(str(raw_cat).strip()) if raw_cat else None
        categoria = resolved or "Outros"
        data_str = str(payload.get("data", today_br().isoformat()))
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

    # 2. Detecção de Parcelamento ('3 vezes', '3x', 'em quatro vezes', '10 parcelas')
    # Converte numerais por extenso (comuns em transcrição de voz) antes de checar parcelas
    extenso_map = {
        "uma": "1", "um": "1",
        "duas": "2", "dois": "2",
        "três": "3", "tres": "3",
        "quatro": "4",
        "cinco": "5",
        "seis": "6",
        "sete": "7",
        "oito": "8",
        "nove": "9",
        "dez": "10",
        "onze": "11",
        "doze": "12",
        "quinze": "15",
        "dezoito": "18",
        "vinte e quatro": "24",
        "vinte": "20",
        "trinta e seis": "36",
        "quarenta e oito": "48"
    }

    normalized_msg = clean_msg
    for word, digit in sorted(extenso_map.items(), key=lambda x: -len(x[0])):
        normalized_msg = re.sub(
            rf'\b{word}\b(?=\s*(?:x|vezes|parcelas|parcela)\b)',
            digit,
            normalized_msg,
            flags=re.IGNORECASE
        )

    parcelas = 1
    # Captura padrão como '3 vezes', '3x', 'em 5x', '10 parcelas', 'parcelado em 4 vezes'
    p_match = re.search(
        r'(?:parcelado\s+em\s+|dividido\s+em\s+|em\s+)?(\d{1,2})\s*(?:x|vezes|parcelas|parcela)\b',
        normalized_msg,
        re.IGNORECASE
    )
    msg_cleaned = normalized_msg
    if p_match:
        try:
            qtd = int(p_match.group(1))
            if 1 <= qtd <= 60:
                parcelas = qtd
                # Remove o trecho de parcelas para isolar valor e descrição
                msg_cleaned = normalized_msg[:p_match.start()] + normalized_msg[p_match.end():]
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

    # 4. Categorização inteligente com base nas categorias canônicas oficiais
    categoria = "Outros"
    
    categories_map = {
        "Alimentação": ["almoço", "almoco", "jantar", "café", "cafe", "restaurante", "ifood", "lanche", "mercado", "supermercado", "padaria", "pizza", "hamburguer", "feira", "açougue", "acougue"],
        "Transporte": ["uber", "99", "gasolina", "combustivel", "combustível", "estacionamento", "onibus", "ônibus", "metro", "metrô", "pedágio", "pedagio", "carro", "oficina", "mecânico", "mecanico", "pneu", "óleo", "oleo"],
        "Moradia": ["aluguel", "condomínio", "condominio", "iptu"],
        "Contas de Consumo": ["energia", "enel", "luz", "agua", "água", "sabesp", "internet", "gas", "gás"],
        "Lazer": ["cinema", "streaming", "netflix", "spotify", "show", "viagem", "bar", "cerveja", "jogos", "game", "passeio"],
        "Saúde": ["farmácia", "farmacia", "remedio", "remédio", "consulta", "médico", "medico", "exame", "hospital", "dentista", "plano"],
        "Educação": ["escola", "faculdade", "curso", "livro", "mensalidade"],
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
            categoria = "Contas de Consumo"

    # 5. Descrição limpa (remove saudações ao Atlas, preposições soltas e valores)
    descricao = re.sub(r'(?:R\$\s*)?\d+(?:[\.,]\d+)?', '', desc_part)
    # Remove palavras de moeda em qualquer posição
    descricao = re.sub(r'\b(?:reais|real|conto|contos|pilas)\b', '', descricao, flags=re.IGNORECASE)
    # Remove invocações ao Atlas e verbos de comando repetidos no início
    for _ in range(3):
        descricao = re.sub(
            r'^(?:fala\s+|oi\s+|olá\s+|ola\s+|ei\s+|bom\s+dia\s+|boa\s+tarde\s+|boa\s+noite\s+|cara\s+)?'
            r'(?:atlas[\s,:-]+)?'
            r'(?:anota\s+aí|anota\s+ai|anota|registra|lança\s+aí|lança|lanca|coloca|comprei|paguei|gastei(?:\s+com)?|foi|fiz)?[\s,:-]*',
            '',
            descricao.strip(" ,.-!?"),
            flags=re.IGNORECASE
        )
    # Remove preposições residuais no fim
    for _ in range(2):
        descricao = re.sub(r'\b(?:no\s+valor\s+de|valor\s+de|de|por|em|no|na|para|pra)\s*$', '', descricao.strip(" ,.-!?"), flags=re.IGNORECASE)
    # Remove artigos soltos no início ("um ", "uma ", "o ", "a ")
    descricao = re.sub(r'^(?:um|uma|o|a|os|as|de|do|da|no|na)\s+', '', descricao.strip(" ,.-!?"), flags=re.IGNORECASE)
    descricao = re.sub(r'\s+', ' ', descricao).strip(" ,.-!?")
    if not descricao:
        descricao = clean_msg[:60]
    else:
        descricao = descricao[:60].capitalize()

    return {
        "tipo": tipo,
        "valor": round(valor, 2),
        "categoria": categoria,
        "descricao": descricao,
        "data": today_br().isoformat(),
        "source": "WhatsApp",
        "parcelas": parcelas
    }