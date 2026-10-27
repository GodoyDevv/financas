"""
tests/test_parser.py

Suíte completa de testes parametrizados para o parser determinístico de mensagens de texto (backend/parser.py).
Cobre:
- Correção de bugs de substring ("99" em "199,90", "bar" em "barbeiro", "gás" em "gasto", "entrada do carro", etc.)
- Variações de formato monetário (R$ 1.299,90, 1299,90, 1.299, 50, 50,5, 50 reais, R$50)
- Parcelas ("3x", "em 3 vezes", "10 parcelas", "duas vezes")
- Acentos e maiúsculas
- Mensagens sem valor monetário ou conversa comum ("bom dia", "quem vai ao mercado?") retornando None
- Invariância de valor: trocar o valor numérico NÃO altera tipo nem categoria
- Cálculo de confiança ("alta" vs "baixa") e motivos explicativos
"""

from decimal import Decimal

import pytest

from backend.parser import parse_text_message


@pytest.mark.parametrize(
    "msg, expected_tipo, expected_cat, expected_val, expected_desc, expected_parcelas, expected_confianca",
    [
        # 1-4: Bugs clássicos corrigidos
        ("Tênis 199,90", "despesa_variavel", "Outros", Decimal("199.90"), "Tênis", 1, "baixa"),
        (
            "Entrada do carro 500",
            "despesa_variavel",
            "Transporte",
            Decimal("500.00"),
            "Entrada do carro",
            1,
            "alta",
        ),
        ("Barbeiro 40", "despesa_variavel", "Serviços", Decimal("40.00"), "Barbeiro", 1, "alta"),
        (
            "Lanche 50,pp",
            "despesa_variavel",
            "Alimentação",
            Decimal("50.00"),
            "Lanche pp",
            1,
            "alta",
        ),
        # 5-9: Formatações de dinheiro e separadores de milhar
        (
            "Mercado 1.299,90",
            "despesa_variavel",
            "Alimentação",
            Decimal("1299.90"),
            "Mercado",
            1,
            "alta",
        ),
        (
            "Mercado 1299,90",
            "despesa_variavel",
            "Alimentação",
            Decimal("1299.90"),
            "Mercado",
            1,
            "alta",
        ),
        (
            "Notebook R$ 3.500",
            "despesa_variavel",
            "Outros",
            Decimal("3500.00"),
            "Notebook",
            1,
            "baixa",
        ),
        ("Café 5,5", "despesa_variavel", "Alimentação", Decimal("5.50"), "Café", 1, "alta"),
        (
            "Almoço 35 reais",
            "despesa_variavel",
            "Alimentação",
            Decimal("35.00"),
            "Almoço",
            1,
            "alta",
        ),
        (
            "R$50 gasolina",
            "despesa_variavel",
            "Transporte",
            Decimal("50.00"),
            "Gasolina",
            1,
            "alta",
        ),
        # 10-15: Conflitos de palavras ("gás" vs "gasto", "luz" vs "Luiza", "venda" vs "vendas")
        (
            "Gasolina 100",
            "despesa_variavel",
            "Transporte",
            Decimal("100.00"),
            "Gasolina",
            1,
            "alta",
        ),
        ("Gasto 100", "despesa_variavel", "Outros", Decimal("100.00"), "Gasto", 1, "baixa"),
        ("Gás 120", "despesa_variavel", "Contas de Consumo", Decimal("120.00"), "Gás", 1, "alta"),
        ("Luz 250", "despesa_fixa", "Contas de Consumo", Decimal("250.00"), "Luz", 1, "alta"),
        ("Luiza 50", "despesa_variavel", "Outros", Decimal("50.00"), "Luiza", 1, "baixa"),
        (
            "Venda do celular 800",
            "receita",
            "Salário/Renda",
            Decimal("800.00"),
            "Venda do celular",
            1,
            "alta",
        ),
        ("Vendas 800", "despesa_variavel", "Outros", Decimal("800.00"), "Vendas", 1, "baixa"),
        # 16-22: Receitas explícitas
        ("Salário 5000", "receita", "Salário/Renda", Decimal("5000.00"), "Salário", 1, "alta"),
        (
            "Recebi pix de 1500",
            "receita",
            "Salário/Renda",
            Decimal("1500.00"),
            "Recebi pix",
            1,
            "alta",
        ),
        (
            "Freela desenvolvimento 1200",
            "receita",
            "Salário/Renda",
            Decimal("1200.00"),
            "Freela desenvolvimento",
            1,
            "alta",
        ),
        (
            "Reembolso empresa 350",
            "receita",
            "Salário/Renda",
            Decimal("350.00"),
            "Reembolso empresa",
            1,
            "alta",
        ),
        (
            "Depósito recebido 400",
            "receita",
            "Salário/Renda",
            Decimal("400.00"),
            "Depósito recebido",
            1,
            "alta",
        ),
        (
            "Rendimento investimentos 230",
            "receita",
            "Salário/Renda",
            Decimal("230.00"),
            "Rendimento investimentos",
            1,
            "alta",
        ),
        (
            "Vendi o violão por 600",
            "receita",
            "Salário/Renda",
            Decimal("600.00"),
            "Vendi o violão",
            1,
            "alta",
        ),
        # 23-28: Despesas Fixas explícitas
        ("Aluguel 1800", "despesa_fixa", "Moradia", Decimal("1800.00"), "Aluguel", 1, "alta"),
        ("Condomínio 650", "despesa_fixa", "Moradia", Decimal("650.00"), "Condomínio", 1, "alta"),
        (
            "Internet 120",
            "despesa_fixa",
            "Contas de Consumo",
            Decimal("120.00"),
            "Internet",
            1,
            "alta",
        ),
        (
            "Seguro do carro 220",
            "despesa_fixa",
            "Transporte",
            Decimal("220.00"),
            "Seguro do carro",
            1,
            "alta",
        ),
        (
            "Plano de saúde 450",
            "despesa_fixa",
            "Saúde",
            Decimal("450.00"),
            "Plano de saúde",
            1,
            "alta",
        ),
        ("Faculdade 750", "despesa_fixa", "Educação", Decimal("750.00"), "Faculdade", 1, "alta"),
        # 29-35: Parcelamentos
        ("Sofá 1200 em 10x", "despesa_variavel", "Outros", Decimal("1200.00"), "Sofá", 10, "baixa"),
        (
            "Passagem 900 3 vezes",
            "despesa_variavel",
            "Outros",
            Decimal("900.00"),
            "Passagem",
            3,
            "baixa",
        ),
        (
            "Geladeira 2500 parcelado em 5 vezes",
            "despesa_variavel",
            "Outros",
            Decimal("2500.00"),
            "Geladeira",
            5,
            "baixa",
        ),
        (
            "Tênis 300 em 3 parcelas",
            "despesa_variavel",
            "Outros",
            Decimal("300.00"),
            "Tênis",
            3,
            "baixa",
        ),
        (
            "Manutenção 400 em duas vezes",
            "despesa_variavel",
            "Outros",
            Decimal("400.00"),
            "Manutenção",
            2,
            "baixa",
        ),
        (
            "Jantar 180 em 1x",
            "despesa_variavel",
            "Alimentação",
            Decimal("180.00"),
            "Jantar",
            1,
            "alta",
        ),
        # 36-40: Categorias variadas e comandos cotidianos
        ("Farmácia 85,90", "despesa_variavel", "Saúde", Decimal("85.90"), "Farmácia", 1, "alta"),
        (
            "Ifood pizza 95",
            "despesa_variavel",
            "Alimentação",
            Decimal("95.00"),
            "Ifood pizza",
            1,
            "alta",
        ),
        (
            "Cinema ingresso 45",
            "despesa_variavel",
            "Lazer",
            Decimal("45.00"),
            "Cinema ingresso",
            1,
            "alta",
        ),
        (
            "Uber para o trabalho 28",
            "despesa_variavel",
            "Transporte",
            Decimal("28.00"),
            "Uber para o trabalho",
            1,
            "alta",
        ),
        (
            "Curso de inglês 200",
            "despesa_variavel",
            "Educação",
            Decimal("200.00"),
            "Curso de inglês",
            1,
            "alta",
        ),
        (
            "Atlas anota aí padaria 22,50",
            "despesa_variavel",
            "Alimentação",
            Decimal("22.50"),
            "Padaria",
            1,
            "alta",
        ),
        (
            "Fala Atlas, paguei cerveja 60",
            "despesa_variavel",
            "Lazer",
            Decimal("60.00"),
            "Cerveja",
            1,
            "alta",
        ),
    ],
)
def test_parse_text_message_deterministic(
    msg,
    expected_tipo,
    expected_cat,
    expected_val,
    expected_desc,
    expected_parcelas,
    expected_confianca,
):
    res = parse_text_message(msg)
    assert res is not None, f"Esperava resultado para '{msg}'"
    assert res["tipo"] == expected_tipo
    assert res["categoria"] == expected_cat
    assert res["valor"] == expected_val
    assert res["descricao"] == expected_desc
    assert res["parcelas"] == expected_parcelas
    assert res["confianca"] == expected_confianca


@pytest.mark.parametrize(
    "msg_sem_valor",
    [
        "bom dia",
        "boa tarde pessoal",
        "quem vai ao mercado?",
        "tudo bem com vocês?",
        "atlas cadê o relatório?",
        "ok combinado",
        "",
        "   ",
        "r$",
        "reais",
        "apenas um texto aleatório",
        "vamos almoçar onde?",
    ],
)
def test_messages_without_value_return_none(msg_sem_valor):
    """Mensagens de bate-papo sem valor numérico ou valor zero retornam None."""
    assert parse_text_message(msg_sem_valor) is None


@pytest.mark.parametrize(
    "valor_a, valor_b",
    [
        ("99", "50"),
        ("199,90", "45,00"),
        ("1.299", "80"),
        ("300", "1250,50"),
    ],
)
def test_property_numeric_value_does_not_change_classification(valor_a, valor_b):
    """Propriedade central: Trocar o valor numérico NÃO pode mudar o tipo nem a categoria."""
    msg_a = f"Tênis {valor_a}"
    msg_b = f"Tênis {valor_b}"
    res_a = parse_text_message(msg_a)
    res_b = parse_text_message(msg_b)
    assert res_a is not None and res_b is not None
    assert res_a["tipo"] == res_b["tipo"]
    assert res_a["categoria"] == res_b["categoria"]
    assert res_a["descricao"] == res_b["descricao"]

    msg_uber_a = f"Uber {valor_a}"
    msg_uber_b = f"Uber {valor_b}"
    res_ua = parse_text_message(msg_uber_a)
    res_ub = parse_text_message(msg_uber_b)
    assert res_ua["tipo"] == res_ub["tipo"] == "despesa_variavel"
    assert res_ua["categoria"] == res_ub["categoria"] == "Transporte"


def test_multiple_numbers_mark_low_confidence():
    """Se a mensagem contém múltiplos números que poderiam ser valor monetário, marca baixa confiança."""
    res = parse_text_message("Comprei 50 no mercado e 80 na padaria")
    assert res is not None
    assert res["confianca"] == "baixa"
    assert any("Multiplos valores" in m for m in res["motivos"])
