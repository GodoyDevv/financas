"""Fonte única de verdade para Categorias, normalização e resolução de aliases."""
import re
import unicodedata
from typing import Optional, List, Dict, Any

def normalize_category_name(name: Optional[str]) -> str:
    """Normaliza o nome da categoria para comparação insensível a maiúsculas, espaços e acentos.
    
    Ex: '  Alimentação  ' -> 'alimentacao'
    'Moradia (Aluguel/Condomínio)' -> 'moradia (aluguel/condominio)'
    """
    if not name:
        return ""
    # Remove espaços nas pontas e comprime espaços internos
    s = " ".join(str(name).strip().split())
    # Decomposição NFKD para separar caracteres base dos diacríticos/acentos
    s_decomposed = unicodedata.normalize("NFKD", s)
    s_no_accents = "".join(c for c in s_decomposed if not unicodedata.combining(c))
    return s_no_accents.lower()

# Lista canônica oficial do sistema: (nome, tipo, ordem)
# tipo: 'despesa' ou 'receita'
CANONICAL_CATEGORIES: List[Dict[str, Any]] = [
    {"name": "Salário/Renda", "tipo": "receita", "ordem": 1},
    {"name": "Moradia", "tipo": "despesa", "ordem": 2},
    {"name": "Contas de Consumo", "tipo": "despesa", "ordem": 3},
    {"name": "Alimentação", "tipo": "despesa", "ordem": 4},
    {"name": "Transporte", "tipo": "despesa", "ordem": 5},
    {"name": "Saúde", "tipo": "despesa", "ordem": 6},
    {"name": "Educação", "tipo": "despesa", "ordem": 7},
    {"name": "Lazer", "tipo": "despesa", "ordem": 8},
    {"name": "Serviços", "tipo": "despesa", "ordem": 9},
    {"name": "Outros", "tipo": "despesa", "ordem": 10},
]

# Aliases legados mapeados para categorias canônicas
CATEGORY_ALIASES: Dict[str, str] = {
    # Moradia
    "moradia (aluguel/condominio)": "Moradia",
    "aluguel": "Moradia",
    "condominio": "Moradia",
    
    # Contas de consumo
    "contas de consumo (luz/agua)": "Contas de Consumo",
    "contas de consumo": "Contas de Consumo",
    "luz": "Contas de Consumo",
    "agua": "Contas de Consumo",
    "energia": "Contas de Consumo",
    "enel": "Contas de Consumo",
    "sabesp": "Contas de Consumo",
    "internet": "Contas de Consumo",
    "gas": "Contas de Consumo",
    
    # Salário e Renda
    "salario": "Salário/Renda",
    "salario/renda": "Salário/Renda",
    "renda": "Salário/Renda",
    "freela": "Salário/Renda",
    
    # Alimentação
    "alimentacao": "Alimentação",
    "mercado": "Alimentação",
    "supermercado": "Alimentação",
    "padaria": "Alimentação",
    "restaurante": "Alimentação",
    
    # Transporte
    "transporte": "Transporte",
    "combustivel": "Transporte",
    "gasolina": "Transporte",
    "uber": "Transporte",
    
    # Saúde
    "saude": "Saúde",
    "farmacia": "Saúde",
    "medico": "Saúde",
    
    # Educação
    "educacao": "Educação",
    "faculdade": "Educação",
    "escola": "Educação",
    "curso": "Educação",
    
    # Lazer
    "lazer": "Lazer",
    "viagem": "Lazer",
    "cinema": "Lazer",
    
    # Serviços
    "servicos": "Serviços",
    
    # Outros
    "outros": "Outros",
    "outro": "Outros",
}

# Mapa de busca rápida: normalized_name -> canonical_name
_CANONICAL_BY_NORM = {
    normalize_category_name(c["name"]): c["name"]
    for c in CANONICAL_CATEGORIES
}

def resolve_canonical_name(raw_name: Optional[str]) -> Optional[str]:
    """Resolve qualquer string de categoria (com acentos, maiúsculas ou aliases) para o nome canônico oficial.
    
    Retorna o nome canônico (ex: 'Moradia') ou None se não for conhecido.
    """
    if not raw_name:
        return None
    norm = normalize_category_name(raw_name)
    # 1. Correspondência exata na lista canônica normalizada
    if norm in _CANONICAL_BY_NORM:
        return _CANONICAL_BY_NORM[norm]
    # 2. Correspondência em aliases
    if norm in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[norm]
    return None

def get_valid_category_names() -> List[str]:
    """Retorna a lista de nomes canônicos oficiais."""
    return [c["name"] for c in CANONICAL_CATEGORIES]
