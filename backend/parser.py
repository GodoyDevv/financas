import re
import unicodedata
from decimal import Decimal

from .categories import resolve_canonical_name
from .dates_and_money import to_decimal, today_br


def normalize_text_for_matching(text: str) -> str:
    """Normaliza texto para casamento de palavras: minúsculas, sem acentos (NFD) e pontuação virando espaço."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    # Converte qualquer caractere não alfanumérico em espaço
    cleaned = re.sub(r"[^a-z0-9]+", " ", no_accents)
    return " ".join(cleaned.split())


def match_keyword_in_text(kw: str, normalized_text: str) -> bool:
    """Verifica se a palavra ou frase inteira casa usando fronteiras de palavra (\b)."""
    norm_kw = normalize_text_for_matching(kw)
    if not norm_kw:
        return False
    # Para palavras ou frases com mais de um termo, exige fronteira no início e fim
    pattern = rf"\b{re.escape(norm_kw)}\b"
    return bool(re.search(pattern, normalized_text))


def extract_installments_and_clean(text: str) -> tuple[int, str]:
    """Detecta menções a parcelamento ('3x', 'em 3 vezes', '10 parcelas') e remove do texto."""
    extenso_map = {
        "uma": "1",
        "um": "1",
        "duas": "2",
        "dois": "2",
        "três": "3",
        "tres": "3",
        "quatro": "4",
        "cinco": "5",
        "seis": "6",
        "sete": "7",
        "oito": "8",
        "nove": "9",
        "dez": "10",
        "doze": "12",
        "quinze": "15",
        "dezoito": "18",
        "vinte e quatro": "24",
        "vinte": "20",
        "trinta e seis": "36",
        "quarenta e oito": "48",
    }

    norm_msg = text
    for word, digit in sorted(extenso_map.items(), key=lambda x: -len(x[0])):
        norm_msg = re.sub(
            rf"\b{word}\b(?=\s*(?:x|vezes|parcelas|parcela)\b)",
            digit,
            norm_msg,
            flags=re.IGNORECASE,
        )

    pattern = re.compile(
        r"\b(?:parcelado\s+em\s+|dividido\s+em\s+|em\s+)?(\d{1,2})\s*(?:x|vezes|parcelas|parcela)\b",
        re.IGNORECASE,
    )

    parcelas = 1
    m = pattern.search(norm_msg)
    cleaned_text = norm_msg
    if m:
        try:
            qtd = int(m.group(1))
            if 1 <= qtd <= 60:
                parcelas = qtd
                cleaned_text = norm_msg[: m.start()] + " " + norm_msg[m.end() :]
        except ValueError:
            parcelas = 1

    return parcelas, cleaned_text


def extract_money_values(text: str) -> tuple[Decimal | None, list[Decimal], str]:
    """Extrai valores monetários suportando formatos brasileiros e internacionais.

    Formatos suportados:
    - 'R$ 1.299,90', '1299,90', '1.299', '50', '50,5', '50 reais', 'R$50'
    Retorna: (valor_principal, todos_os_valores_encontrados, texto_sem_valores)
    """
    # Regex robusta para capturar números que representam dinheiro com ou sem prefixo/sufixo
    # Grupo 1: prefixo R$ opcional
    # Grupo 2: número (1.299,90 ou 1299,90 ou 1.299 ou 50,5 ou 50)
    # Grupo 3: sufixo opcional (reais, real, conto, contos, pilas)
    money_pattern = re.compile(
        r"(?i)(?:\b(?:r\$|rs)\s*)?"
        r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})|\d+(?:\.\d{1,2})|\d{1,3}(?:\.\d{3})+|\b\d+\b)"
        r"(?:\s*(?:reais|real|conto|contos|pilas)\b)?"
    )

    matches = []
    for m in money_pattern.finditer(text):
        val_raw = m.group(1)
        # Ignora números isolados que não façam sentido como valor se colidirem com outras coisas
        if not val_raw:
            continue

        # Normaliza formato brasileiro / decimal
        # Caso A: possui ponto como milhar e vírgula como decimal (ex: 1.299,90)
        if "." in val_raw and "," in val_raw:
            clean_num = val_raw.replace(".", "").replace(",", ".")
        # Caso B: apenas vírgula (ex: 1299,90 ou 50,5)
        elif "," in val_raw:
            clean_num = val_raw.replace(",", ".")
        # Caso C: apenas ponto, verificar se é milhar (ex: 1.299) ou decimal (ex: 50.50)
        elif "." in val_raw:
            parts = val_raw.split(".")
            # Se a última parte tem 3 dígitos e a anterior tem 1-3 dígitos, é milhar brasileiro (1.299)
            if len(parts) >= 2 and len(parts[-1]) == 3:
                clean_num = val_raw.replace(".", "")
            else:
                clean_num = val_raw
        else:
            clean_num = val_raw

        try:
            val_dec = to_decimal(clean_num)
            if val_dec > Decimal("0.00"):
                matches.append((m.start(), m.end(), val_dec, m.group(0)))
        except (ValueError, TypeError, ArithmeticError):
            continue

    if not matches:
        return None, [], text

    # O valor principal adotado é o primeiro número válido encontrado
    first_match = matches[0]
    primary_value = first_match[2]
    all_values = [m[2] for m in matches]

    # Remove todos os trechos de valores do texto original para não poluir descrição nem keywords
    cleaned_text = text
    # Remove de trás para frente para preservar índices
    for start, end, _, _ in sorted(matches, key=lambda x: -x[0]):
        cleaned_text = cleaned_text[:start] + " " + cleaned_text[end:]

    return primary_value, all_values, cleaned_text


def clean_description(text: str, original_fallback: str) -> str:
    """Limpa pontuação órfã nas pontas e entre palavras, saudações ao bot e colapsa espaços."""
    desc = text
    # Remove palavras de moeda remanescentes
    desc = re.sub(r"(?i)\b(?:r\$|rs|reais|real|conto|contos|pilas)\b", " ", desc)

    # Remove invocações ao Atlas e comandos comuns
    for _ in range(3):
        desc = re.sub(
            r"(?i)^(?:fala\s+|oi\s+|olá\s+|ola\s+|ei\s+|bom\s+dia\s+|boa\s+tarde\s+|boa\s+noite\s+|cara\s+)?"
            r"(?:atlas[\s,:-]+)?"
            r"(?:anota\s+aí|anota\s+ai|anota|registra|lança\s+aí|lança|lanca|coloca|comprei|paguei|gastei(?:\s+com)?|foi|fiz)?[\s,:-]*",
            " ",
            desc.strip(" ,.-!?"),
        )

    # Remove preposições soltas nas pontas
    for _ in range(2):
        desc = re.sub(
            r"(?i)\b(?:no\s+valor\s+de|valor\s+de|de|por|em|no|na|para|pra)\s*$",
            " ",
            desc.strip(" ,.-!?"),
        )
    desc = re.sub(r"(?i)^(?:um|uma|o|a|os|as|de|do|da|no|na)\s+", " ", desc.strip(" ,.-!?"))

    # Remove pontuações órfãs mantendo palavras juntas: "Lanche ,pp" -> "Lanche pp"
    desc = re.sub(r"[\s,._\-:;]+", " ", desc).strip(" ,.-!?")

    if not desc:
        desc = original_fallback.strip()[:60]
    else:
        desc = desc[:60]
        # Capitaliza a primeira letra mantendo o restante
        desc = desc[0].upper() + desc[1:] if len(desc) > 1 else desc.upper()

    return desc


# Dicionário canônico de palavras-chave para categorias com casamento estrito
CATEGORIES_KEYWORDS: dict[str, list[str]] = {
    "Alimentação": [
        "almoco",
        "almoco",
        "jantar",
        "cafe",
        "cafezinho",
        "restaurante",
        "ifood",
        "lanche",
        "mercado",
        "supermercado",
        "padaria",
        "pizza",
        "pizzaria",
        "hamburguer",
        "hamburgueria",
        "feira",
        "acougue",
        "hortifruti",
        "comida",
        "churrasco",
        "acai",
    ],
    "Transporte": [
        "uber",
        "99",
        "99pop",
        "gasolina",
        "combustivel",
        "etanol",
        "diesel",
        "estacionamento",
        "onibus",
        "metro",
        "pedagio",
        "carro",
        "moto",
        "oficina",
        "mecanico",
        "pneu",
        "oleo",
        "troca de oleo",
        "ipva",
    ],
    "Moradia": ["aluguel", "condominio", "iptu", "imovel", "reforma", "casa", "apartamento"],
    "Contas de Consumo": [
        "energia",
        "enel",
        "luz",
        "agua",
        "sabesp",
        "internet",
        "gas",
        "botijao de gas",
        "conta de luz",
        "conta de agua",
        "fatura internet",
    ],
    "Lazer": [
        "cinema",
        "streaming",
        "netflix",
        "spotify",
        "show",
        "viagem",
        "bar",
        "boteco",
        "cerveja",
        "chopp",
        "jogos",
        "game",
        "steam",
        "passeio",
        "parque",
        "barbeiro",
        "balada",
        "festa",
    ],
    "Saúde": [
        "farmacia",
        "drogaria",
        "remedio",
        "medicamento",
        "consulta",
        "medico",
        "exame",
        "hospital",
        "dentista",
        "plano de saude",
        "psicologo",
        "terapia",
    ],
    "Educação": [
        "escola",
        "faculdade",
        "curso",
        "livro",
        "mensalidade",
        "material escolar",
        "idiomas",
        "ingles",
    ],
    "Salário/Renda": [
        "salario",
        "freela",
        "freelance",
        "rendimento",
        "dividendo",
        "pro-labore",
        "bonificacao",
        "comissao",
        "decimo terceiro",
    ],
    "Serviços": ["lavanderia", "chaveiro", "faxina", "diarista", "costureira", "manicure", "salao"],
}


INCOME_STRONG_KEYWORDS = [
    "recebi",
    "salario",
    "vendi",
    "venda de",
    "venda do",
    "venda da",
    "freela",
    "freelance",
    "reembolso",
    "rendimento",
    "pix recebido",
    "deposito",
    "pro-labore",
    "comissao recebida",
    "lucro",
    "bonificacao",
]

FIXED_EXPENSE_KEYWORDS = [
    "aluguel",
    "condominio",
    "seguro",
    "plano de saude",
    "internet",
    "iptu",
    "ipva",
    "energia",
    "enel",
    "luz",
    "agua",
    "sabesp",
    "mensalidade",
    "escola",
    "faculdade",
    "plano",
    "assinatura",
]


def parse_financial_payload(payload: dict) -> dict | None:
    """Extrai e normaliza dados de webhook recebidos (ex: WhatsApp/Gateway)."""
    try:
        raw_tipo = str(payload.get("tipo", "despesa_variavel")).lower()
        if raw_tipo in ["receita", "despesa_fixa", "despesa_variavel"]:
            tipo = raw_tipo
        elif raw_tipo == "despesa":
            tipo = "despesa_variavel"
        else:
            tipo = "despesa_variavel"

        raw_val = payload.get("valor", 0.0)
        valor = to_decimal(raw_val)
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
            "parcelas": parcelas,
            "confianca": "alta",
            "motivos": [],
        }
    except Exception:
        return None


def parse_text_message(message: str) -> dict | None:
    """Interpreta mensagens em linguagem natural de forma determinística com fronteiras de palavra (\b).

    Requisitos:
    - Extrai e remove o valor numérico e parcelas ANTES de qualquer classificação de texto.
    - Se não houver valor numérico positivo, retorna None (ignora saudações ou conversas do grupo).
    - Classifica tipo e categoria sem casamento por substring (evita '99' em '199', 'bar' em 'barbeiro', etc.).
    - Retorna `confianca` ('alta' | 'baixa') e lista de `motivos`.
    """
    if not message or not isinstance(message, str):
        return None

    clean_msg = message.strip()
    if not clean_msg:
        return None

    # 1. Extração isolada de parcelamento ('3x', 'em 3 vezes', etc.)
    parcelas, msg_sem_parcelas = extract_installments_and_clean(clean_msg)

    # 2. Extração isolada do valor numérico
    primary_value, all_values, msg_sem_valor = extract_money_values(msg_sem_parcelas)
    if primary_value is None or primary_value <= Decimal("0.00"):
        # Sem valor numérico positivo -> Mensagem ignorada (ex: 'bom dia', 'quem vai ao mercado?')
        return None

    motivos: list[str] = []

    # Se houver mais de um número detectado que poderia ser valor, sinaliza ambiguidade
    if len(all_values) > 1:
        motivos.append("Multiplos valores numericos identificados na mensagem")

    # 3. Normalização do texto residual para classificação
    text_to_classify = normalize_text_for_matching(msg_sem_valor)

    # 4. Determinação do Tipo (receita vs despesa_fixa vs despesa_variavel)
    is_income = any(match_keyword_in_text(k, text_to_classify) for k in INCOME_STRONG_KEYWORDS)
    is_fixed = any(match_keyword_in_text(k, text_to_classify) for k in FIXED_EXPENSE_KEYWORDS)

    if is_income and is_fixed:
        tipo = "despesa_fixa"
        motivos.append("Conflito entre termos de receita e despesa fixa")
    elif is_income:
        tipo = "receita"
    elif is_fixed:
        tipo = "despesa_fixa"
    else:
        tipo = "despesa_variavel"

    # 5. Categorização por contagem de casamentos estritos com word boundary
    categoria_scores: dict[str, int] = {}
    for cat, kws in CATEGORIES_KEYWORDS.items():
        score = sum(1 for kw in kws if match_keyword_in_text(kw, text_to_classify))
        if score > 0:
            categoria_scores[cat] = score

    # Ajustes de prioridade contextual
    # Ex: 'barbeiro' é categorizado em Serviços (ou Lazer se não houver outra), não 'bar'
    if match_keyword_in_text("barbeiro", text_to_classify):
        categoria_scores["Serviços"] = categoria_scores.get("Serviços", 0) + 2
        # Remove score indevido de bar
        if "Lazer" in categoria_scores:
            categoria_scores["Lazer"] -= 1
            if categoria_scores["Lazer"] <= 0:
                del categoria_scores["Lazer"]

    # Se for receita e nenhuma outra categoria pontuou, vai para 'Salário/Renda'
    if tipo == "receita" and not categoria_scores:
        categoria_scores["Salário/Renda"] = 1

    categoria = "Outros"
    if categoria_scores:
        sorted_cats = sorted(categoria_scores.items(), key=lambda x: -x[1])
        top_cat, top_score = sorted_cats[0]
        # Verifica empate
        if len(sorted_cats) > 1 and sorted_cats[1][1] == top_score:
            motivos.append(f"Empate de categorias entre '{top_cat}' e '{sorted_cats[1][0]}'")
        categoria = top_cat
    else:
        motivos.append("Nenhuma keyword de categoria identificada (fallback Outros)")

    # 6. Avaliação de Confiança
    confianca = "baixa" if categoria == "Outros" or len(motivos) > 0 else "alta"

    # 7. Limpeza da descrição
    descricao = clean_description(msg_sem_valor, original_fallback=clean_msg)

    return {
        "tipo": tipo,
        "valor": primary_value,
        "categoria": categoria,
        "descricao": descricao,
        "data": today_br().isoformat(),
        "source": "WhatsApp",
        "parcelas": parcelas,
        "confianca": confianca,
        "motivos": motivos,
    }
