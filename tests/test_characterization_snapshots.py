"""
tests/test_characterization_snapshots.py

Testes de Caracterização e Regressão de Snapshots.
Garante que todas as saídas de endpoints públicos (/api/summary, /api/metrics,
/api/transactions, /api/categories, /api/recurrences, /api/parse-message),
relatórios do scheduler e mensagens formatadas do Atlas permaneçam 100% IDÊNTICAS
durante toda a refatoração arquitetural em camadas.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.database as db_module
from backend.atlas import format_atlas_confirmation
from backend.main import app
from backend.models import Category, Recurrence, Transaction
from backend.scheduler import gerar_texto_relatorio_diario, gerar_texto_relatorio_semanal_macro

SNAPSHOTS_DIR = Path(__file__).resolve().parent / "snapshots"


@pytest.fixture
def characterization_db():
    """Popula banco com dataset sintético fixo para snapshot determinístico."""
    db = db_module.SessionLocal()
    try:
        db.query(Transaction).delete()
        db.query(Recurrence).delete()
        db.query(Category).delete()
        db.commit()

        # 1. Categorias fixas
        cat_moradia = Category(
            id=1,
            name="Moradia",
            normalized_name="moradia",
            tipo="despesa",
            budget=Decimal("2500.00"),
            ativo=True,
        )
        cat_alimentacao = Category(
            id=2,
            name="Alimentação",
            normalized_name="alimentacao",
            tipo="despesa",
            budget=Decimal("1500.00"),
            ativo=True,
        )
        cat_transporte = Category(
            id=3,
            name="Transporte",
            normalized_name="transporte",
            tipo="despesa",
            budget=Decimal("600.00"),
            ativo=True,
        )
        cat_lazer = Category(
            id=4,
            name="Lazer",
            normalized_name="lazer",
            tipo="despesa",
            budget=Decimal("500.00"),
            ativo=True,
        )
        cat_salario = Category(
            id=5, name="Salário", normalized_name="salario", tipo="receita", budget=None, ativo=True
        )
        cat_outros = Category(
            id=6, name="Outros", normalized_name="outros", tipo="despesa", budget=None, ativo=True
        )
        db.add_all(
            [cat_moradia, cat_alimentacao, cat_transporte, cat_lazer, cat_salario, cat_outros]
        )
        db.commit()

        # 2. Recorrências fixas
        rec_aluguel = Recurrence(
            id=1,
            tipo="despesa_fixa",
            descricao="Aluguel do Apartamento",
            valor=Decimal("2200.00"),
            category_id=1,
            author="Bruno",
            dia_do_mes=10,
            inicio=date(2026, 1, 1),
            fim=None,
            ativo=True,
        )
        rec_salario = Recurrence(
            id=2,
            tipo="receita",
            descricao="Salário Mensal Bruno",
            valor=Decimal("9500.00"),
            category_id=5,
            author="Bruno",
            dia_do_mes=5,
            inicio=date(2026, 1, 1),
            fim=None,
            ativo=True,
        )
        db.add_all([rec_aluguel, rec_salario])
        db.commit()

        # 3. Transações fixas no mês 2026-10
        t1 = Transaction(
            id=101,
            tipo="receita",
            valor=Decimal("9500.00"),
            categoria="Salário",
            category_id=5,
            data=date(2026, 10, 5),
            descricao="Salário Mensal Bruno",
            author="Bruno",
            channel="system",
            recurrence_id=2,
            competencia=date(2026, 10, 1),
            editado_manual=False,
        )
        t2 = Transaction(
            id=102,
            tipo="despesa_fixa",
            valor=Decimal("2200.00"),
            categoria="Moradia",
            category_id=1,
            data=date(2026, 10, 10),
            descricao="Aluguel do Apartamento",
            author="Bruno",
            channel="system",
            recurrence_id=1,
            competencia=date(2026, 10, 1),
            editado_manual=False,
        )
        t3 = Transaction(
            id=103,
            tipo="despesa_variavel",
            valor=Decimal("150.50"),
            categoria="Alimentação",
            category_id=2,
            data=date(2026, 10, 20),
            descricao="Supermercado Semanal",
            author="Letícia",
            channel="whatsapp_text",
        )
        t4 = Transaction(
            id=104,
            tipo="despesa_variavel",
            valor=Decimal("89.90"),
            categoria="Transporte",
            category_id=3,
            data=date(2026, 10, 20),
            descricao="Uber Trabalho",
            author="Bruno",
            channel="whatsapp_audio",
        )
        # Parcelas 1/3, 2/3, 3/3
        t5_p1 = Transaction(
            id=105,
            tipo="despesa_variavel",
            valor=Decimal("200.00"),
            categoria="Lazer",
            category_id=4,
            data=date(2026, 10, 20),
            descricao="Tênis Corrida (1/3)",
            author="Bruno",
            channel="dashboard",
            parcela_grupo_id="snap-parcela-uuid",
            parcela_num=1,
            parcela_total=3,
        )
        t5_p2 = Transaction(
            id=106,
            tipo="despesa_variavel",
            valor=Decimal("200.00"),
            categoria="Lazer",
            category_id=4,
            data=date(2026, 11, 20),
            descricao="Tênis Corrida (2/3)",
            author="Bruno",
            channel="dashboard",
            parcela_grupo_id="snap-parcela-uuid",
            parcela_num=2,
            parcela_total=3,
        )
        t5_p3 = Transaction(
            id=107,
            tipo="despesa_variavel",
            valor=Decimal("200.00"),
            categoria="Lazer",
            category_id=4,
            data=date(2026, 12, 20),
            descricao="Tênis Corrida (3/3)",
            author="Bruno",
            channel="dashboard",
            parcela_grupo_id="snap-parcela-uuid",
            parcela_num=3,
            parcela_total=3,
        )
        db.add_all([t1, t2, t3, t4, t5_p1, t5_p2, t5_p3])
        db.commit()

        yield db

        # Limpa dados após a execução do teste para não contaminar outras suites
        db.query(Transaction).delete()
        db.query(Recurrence).delete()
        db.query(Category).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def authed_client():
    from backend.auth import COOKIE_NAME, get_serializer

    client = TestClient(app)
    token = get_serializer().dumps("authenticated_user")
    client.cookies.set(COOKIE_NAME, token)
    return client


def _assert_or_save_snapshot(snapshot_name: str, current_data: dict | list | str):
    """Compara o dado atual com o arquivo de snapshot no disco. Salva se não existir."""
    file_path = SNAPSHOTS_DIR / f"{snapshot_name}.json"
    if isinstance(current_data, str):
        content_to_save = current_data
        if not file_path.exists():
            file_path.write_text(content_to_save, encoding="utf-8")
        saved_content = file_path.read_text(encoding="utf-8")
        assert current_data == saved_content, f"Snapshot divergence for {snapshot_name}"
    else:
        json_str = json.dumps(current_data, indent=2, ensure_ascii=False, sort_keys=True)
        if not file_path.exists():
            file_path.write_text(json_str, encoding="utf-8")
        saved_str = file_path.read_text(encoding="utf-8")
        assert json.loads(json_str) == json.loads(
            saved_str
        ), f"Snapshot divergence for {snapshot_name}"


def test_snapshot_summary_endpoint(characterization_db, authed_client):
    """Snapshot do endpoint /api/summary para mês específico."""
    res = authed_client.get("/api/summary?month=2026-10")
    assert res.status_code == 200
    data = res.json()
    _assert_or_save_snapshot("api_summary_2026_10", data)


def test_snapshot_metrics_endpoint(characterization_db, authed_client):
    """Snapshot do endpoint /api/metrics para mês específico."""
    res = authed_client.get("/api/metrics?month=2026-10")
    assert res.status_code == 200
    data = res.json()
    _assert_or_save_snapshot("api_metrics_2026_10", data)


def test_snapshot_transactions_endpoint(characterization_db, authed_client):
    """Snapshot do endpoint /api/transactions com filtros de mês."""
    res = authed_client.get("/api/transactions?month=2026-10")
    assert res.status_code == 200
    data = res.json()
    # Remove timestamps dinâmicos de created_at para snapshot determinístico
    for item in data:
        item.pop("created_at", None)
    _assert_or_save_snapshot("api_transactions_2026_10", data)


def test_snapshot_categories_endpoint(characterization_db, authed_client):
    """Snapshot do endpoint /api/categories."""
    res = authed_client.get("/api/categories")
    assert res.status_code == 200
    data = res.json()
    for item in data:
        item.pop("created_at", None)
    _assert_or_save_snapshot("api_categories", data)


def test_snapshot_recurrences_endpoint(characterization_db, authed_client):
    """Snapshot do endpoint /api/recurrences."""
    res = authed_client.get("/api/recurrences")
    assert res.status_code == 200
    data = res.json()
    for item in data:
        item.pop("created_at", None)
    _assert_or_save_snapshot("api_recurrences", data)


def test_snapshot_parse_message_endpoint(authed_client):
    """Snapshot do endpoint /api/parse-message com mensagem típica."""
    payload = {"message": "Almoço de domingo 85,50"}
    res = authed_client.post("/api/parse-message", json=payload)
    assert res.status_code == 200
    data = res.json()
    _assert_or_save_snapshot("api_parse_message", data)


def test_snapshot_relatorio_diario(characterization_db):
    """Snapshot do texto do relatório diário gerado pelo scheduler."""
    target_date = date(2026, 10, 20)
    texto = gerar_texto_relatorio_diario(target_date, characterization_db)
    _assert_or_save_snapshot("scheduler_relatorio_diario_2026_10_20", {"texto": texto})


def test_snapshot_relatorio_semanal_macro(characterization_db):
    """Snapshot do texto do relatório semanal macro gerado pelo scheduler."""
    end_date = date(2026, 10, 24)
    texto = gerar_texto_relatorio_semanal_macro(end_date, characterization_db)
    _assert_or_save_snapshot("scheduler_relatorio_semanal_2026_10_24", {"texto": texto})


def test_snapshot_format_atlas_confirmation():
    """Snapshot da formatação das confirmações de texto do Atlas."""
    m1 = format_atlas_confirmation("Bruno", "Almoço", Decimal("45.00"), 1, Decimal("1250.00"))
    m2 = format_atlas_confirmation(
        "Letícia", "Tênis", Decimal("150.00"), 3, Decimal("800.00"), Decimal("450.00")
    )
    _assert_or_save_snapshot("atlas_confirmation_messages", {"avulsa": m1, "parcelada": m2})
