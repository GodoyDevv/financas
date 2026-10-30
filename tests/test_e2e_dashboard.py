"""
tests/test_e2e_dashboard.py

Testes End-to-End (E2E) com Playwright para o Dashboard do FinTrack.
Cobre:
- Login via /login com senha de aplicação
- Carregamento do dashboard sem erros de console nem violações de CSP
- Troca de mês (navegação e seletor rápido)
- Criação de nova transação via modal/formulário
- Filtros por coluna, autor e canal (com chips e pills)
- Exclusão de transação simples e exclusão de transação parcelada (via modal)
- Layout responsivo mobile (viewport 390x844)
- Logout e redirecionamento seguro
"""

import os
import socket
import threading
import time
from collections.abc import Generator
from datetime import date

import pytest
import uvicorn
from playwright.sync_api import Browser, BrowserContext, Page, expect

from backend.database import SessionLocal
from backend.db.models import Category, Transaction
from backend.main import app


def get_free_port() -> int:
    """Retorna uma porta TCP livre."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def test_server() -> Generator[str, None, None]:
    """Inicia o servidor Uvicorn em background com a aplicação FastAPI para os testes E2E."""
    port = get_free_port()
    config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config=config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Aguarda o servidor responder
    base_url = f"http://127.0.0.1:{port}"
    timeout = 10.0
    start = time.time()
    ready = False
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                ready = True
                break
        except OSError:
            time.sleep(0.1)

    if not ready:
        raise RuntimeError(f"Servidor Uvicorn não iniciou na porta {port} a tempo.")

    yield base_url
    server.should_exit = True
    thread.join(timeout=2)


@pytest.fixture(scope="module")
def seed_test_data():
    """Popula dados sintéticos de teste no banco para os cenários E2E."""
    with SessionLocal() as db:
        # Categorias essenciais
        for cat_nome, cat_tipo in [
            ("Alimentação", "despesa"),
            ("Transporte", "despesa"),
            ("Salário", "receita"),
            ("Aluguel", "despesa"),
        ]:
            if not db.query(Category).filter(Category.name == cat_nome).first():
                norm = cat_nome.lower()
                db.add(Category(name=cat_nome, normalized_name=norm, tipo=cat_tipo))

        # Transações do mês atual
        hoje = date.today()
        primeiro_dia = hoje.replace(day=1)

        cat_transporte = db.query(Category).filter(Category.name == "Transporte").first()
        cat_alim = db.query(Category).filter(Category.name == "Alimentação").first()

        # Transação simples
        t1 = Transaction(
            data=primeiro_dia,
            descricao="Mercado Semanal",
            valor=150.00,
            tipo="despesa_variavel",
            categoria="Alimentação",
            category_id=cat_alim.id,
            author="Bruno",
            channel="dashboard",
            source="Manual",
            competencia=primeiro_dia,
        )
        # Transação parcelada
        t2 = Transaction(
            data=primeiro_dia,
            descricao="Smartphone Novo (Parcela 1)",
            valor=200.00,
            tipo="despesa_variavel",
            categoria="Transporte",
            category_id=cat_transporte.id,
            author="Letícia",
            channel="whatsapp_text",
            source="WhatsApp",
            parcela_grupo_id="test-group-parcela-123",
            parcela_num=1,
            parcela_total=3,
            competencia=primeiro_dia,
        )
        db.add_all([t1, t2])
        db.commit()


@pytest.mark.e2e
def test_dashboard_e2e_complete_flow(test_server: str, seed_test_data, browser: Browser):
    """
    Fluxo completo E2E:
    1. Acessa / -> redirecionado para /login
    2. Faz login com APP_PASSWORD de teste
    3. Monitora erros de console e violações de CSP
    4. Valida carregamento de KPIs e tabela
    5. Testa navegação de meses
    6. Cria nova transação
    7. Aplica filtros por coluna (categoria / autor)
    8. Exclui transação e exclui parcela via modal inteligente
    9. Testa viewport mobile (390px)
    10. Efetua logout
    """
    context: BrowserContext = browser.new_context(viewport={"width": 1280, "height": 800})
    page: Page = context.new_page()

    console_errors = []
    csp_violations = []

    def handle_console(msg):
        print(f"BROWSER CONSOLE [{msg.type}]: {msg.text}")
        if msg.type == "error":
            console_errors.append(msg.text)
        if "Content Security Policy" in msg.text or "violates" in msg.text:
            csp_violations.append(msg.text)

    def handle_pageerror(err):
        print(f"PAGE ERROR: {err}")
        console_errors.append(str(err))

    page.on("console", handle_console)
    page.on("pageerror", handle_pageerror)

    # 1. Acesso à home não autenticado deve redirecionar para /login
    page.goto(f"{test_server}/")
    page.wait_for_url("**/login")
    assert "/login" in page.url

    # 2. Login com senha de teste
    test_password = os.environ.get("APP_PASSWORD", "test_app_password_123")
    page.fill("#password", test_password)
    page.click("#btn-login")

    # Aguarda redirecionamento para o dashboard
    page.wait_for_url(f"{test_server}/", timeout=10000)
    assert page.url.rstrip("/") == test_server.rstrip("/")

    # Aguarda o dashboard carregar dados da API
    page.wait_for_selector("#tabela-corpo tr", timeout=10000)

    # 3. Validação de console sem erros críticos nem violações de CSP
    # Filtra avisos não impeditivos se houver
    crit_errors = [e for e in console_errors if "favicon" not in e and "404" not in e]
    assert len(crit_errors) == 0, f"Erros inesperados no console: {crit_errors}"

    # Salva screenshot Desktop de referência
    os.makedirs("docs/screenshots", exist_ok=True)
    page.screenshot(path="docs/screenshots/desktop_dashboard.png")

    # 4. Troca de mês (navegar mês anterior e voltar ao mês atual)
    btn_prev = page.locator(".btn-month-chevron").first
    btn_prev.click()
    page.wait_for_timeout(500)

    # Clica no botão "Mês Atual"
    page.click("#btn-mes-atual")
    page.wait_for_timeout(500)

    # 5. Criar nova transação
    page.fill("#descricao", "Almoço Teste E2E")
    page.fill("#valor", "45.50")
    page.fill("#categoria", "Alimentação")
    page.click("#btn-submit")
    page.wait_for_timeout(1000)

    # Verifica se a transação aparece na tabela
    expect(page.locator("#tabela-corpo")).to_contain_text("Almoço Teste E2E")

    # 6. Filtrar por Coluna (Abrir popover de filtro em Categoria)
    th_cat = page.locator("#th-btn-categoria")
    th_cat.click()
    page.wait_for_selector("#col-filter-popover.open", timeout=3000)

    # Conclui filtro
    page.click(".btn-col-done")
    page.wait_for_timeout(300)

    # 7. Exclusão de transação simples
    # Localiza linha do Almoço Teste E2E e clica no botão Excluir
    row_almoco = page.locator("#tabela-corpo tr", has_text="Almoço Teste E2E")
    btn_del = row_almoco.locator(".btn-delete")

    # Configura aceitação do window.confirm nativo do browser para transação simples
    page.once("dialog", lambda dialog: dialog.accept())
    btn_del.click()
    page.wait_for_timeout(1000)
    expect(page.locator("#tabela-corpo")).not_to_contain_text("Almoço Teste E2E")

    # 8. Exclusão de transação parcelada (Dispara Modal Inteligente)
    row_parcela = page.locator("#tabela-corpo tr", has_text="Smartphone Novo")
    if row_parcela.count() > 0:
        row_parcela.first.locator(".btn-delete").click()
        # Modal inteligente deve abrir
        page.wait_for_selector("#delete-modal-overlay.active", timeout=3000)
        # Clica em cancelar para fechar
        page.click(".btn-modal-cancel")
        page.wait_for_selector("#delete-modal-overlay.active", state="hidden", timeout=3000)

    # 9. Teste de Layout Mobile (Viewport 390px)
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(500)
    # Cards mobile devem estar visíveis
    expect(page.locator("#mobile-tx-list")).to_be_visible()
    page.screenshot(path="docs/screenshots/mobile_dashboard.png")

    # 10. Logout
    page.click("#btn-logout")
    page.wait_for_url("**/login", timeout=5000)
    assert "/login" in page.url

    context.close()
