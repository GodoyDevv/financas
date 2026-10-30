/**
 * frontend/src/js/main.ts
 *
 * Ponto de entrada modular do frontend FinTrack.
 * Configura delegação de eventos para eliminar handlers inline (data-action),
 * reatividade de estado e carregamento de dados.
 */

import { state } from "./state";
import { apiFetch, API_BASE, fazerLogout } from "./api";
import { formatarMesAno } from "./format";
import { renderKPIs } from "./components/kpis";
import { renderTableAndCards } from "./components/table";
import {
  abrirFiltroColuna,
  fecharFiltroColuna,
  limparFiltroColuna,
  removerFiltroItem,
  limparTodosFiltros,
  filtrarOpcoesColuna,
} from "./components/filters";
import {
  abrirModalExclusao,
  fecharModalExclusao,
  executarExclusao,
} from "./components/modal";
import {
  iniciarEdicao,
  cancelarEdicao,
  salvarLancamento,
  aoMudarTipo,
} from "./components/form";
import { atualizarGraficos } from "./charts";
import type { MetricsResponse, TransactionResponse } from "./state";

const NOMES_MESES = [
  "Janeiro",
  "Fevereiro",
  "Março",
  "Abril",
  "Maio",
  "Junho",
  "Julho",
  "Agosto",
  "Setembro",
  "Outubro",
  "Novembro",
  "Dezembro",
];

const NOMES_MESES_ABREV = [
  "Jan",
  "Fev",
  "Mar",
  "Abr",
  "Mai",
  "Jun",
  "Jul",
  "Ago",
  "Set",
  "Out",
  "Nov",
  "Dez",
];

// -------------------------------------------------------------
// NAVEGAÇÃO E DROPDOWN DE MÊS
// -------------------------------------------------------------
export function toggleMonthDropdown(event?: Event): void {
  if (event) event.stopPropagation();
  const menu = document.getElementById("month-dropdown-menu");
  if (!menu) return;

  const isOpen = menu.classList.contains("open");
  if (isOpen) {
    fecharMonthDropdown();
  } else {
    state.anoDropdownAtual = state.anoAtual;
    renderGridMesesDropdown();
    menu.classList.add("open");
  }
}

export function fecharMonthDropdown(): void {
  const menu = document.getElementById("month-dropdown-menu");
  if (menu) menu.classList.remove("open");
}

export function renderGridMesesDropdown(): void {
  const yearDisplay = document.getElementById("dropdown-year-display");
  const grid = document.getElementById("dropdown-months-grid");
  if (yearDisplay) yearDisplay.innerText = String(state.anoDropdownAtual);
  if (!grid) return;

  const hoje = new Date();
  const anoHoje = hoje.getFullYear();
  const mesHoje = hoje.getMonth() + 1;

  grid.innerHTML = NOMES_MESES_ABREV.map((abrev, idx) => {
    const numMes = idx + 1;
    const isSelected =
      !state.modoGeral &&
      state.anoAtual === state.anoDropdownAtual &&
      state.mesAtual === numMes;
    const isCurrent =
      state.anoDropdownAtual === anoHoje && numMes === mesHoje;

    let classes = "month-btn";
    if (isSelected) classes += " active";
    if (isCurrent) classes += " is-today";

    return `
      <button type="button" class="${classes}" data-action="select-month" data-year="${state.anoDropdownAtual}" data-month="${numMes}">
        ${abrev}
      </button>
    `;
  }).join("");
}

export function mudarAnoDropdown(delta: number): void {
  state.anoDropdownAtual += delta;
  renderGridMesesDropdown();
}

export function selecionarMesDireto(ano: number, mes: number): void {
  state.modoGeral = false;
  state.anoAtual = ano;
  state.mesAtual = mes;
  state.mesSelecionado = formatarMesAno(ano, mes);
  fecharMonthDropdown();
  atualizarDisplayMes();
  carregarDados();
}

export function irParaMesCorrenteDropdown(): void {
  const hoje = new Date();
  selecionarMesDireto(hoje.getFullYear(), hoje.getMonth() + 1);
}

export function atualizarDisplayMes(): void {
  const display = document.getElementById("mes-display");
  const btnAtual = document.getElementById("btn-mes-atual");
  const btnGeral = document.getElementById("btn-todos-meses");
  const subtitle = document.getElementById("dashboard-subtitle");

  if (state.modoGeral) {
    if (display) display.innerText = "Todos os Meses";
    if (btnAtual) btnAtual.classList.remove("active");
    if (btnGeral) btnGeral.classList.add("active");
    if (subtitle)
      subtitle.innerText =
        "Consolidado histórico de todas as movimentações financeiras";
  } else {
    if (display)
      display.innerText = `${NOMES_MESES[state.mesAtual - 1]} ${state.anoAtual}`;
    if (btnGeral) btnGeral.classList.remove("active");

    const hoje = new Date();
    const isMesHoje =
      state.anoAtual === hoje.getFullYear() &&
      state.mesAtual === hoje.getMonth() + 1;
    if (btnAtual) btnAtual.classList.toggle("active", isMesHoje);
    if (subtitle)
      subtitle.innerText = `Planejamento e acompanhamento das despesas de ${NOMES_MESES[
        state.mesAtual - 1
      ].toLowerCase()}`;
  }
}

export function navegarMes(delta: number): void {
  if (state.modoGeral) {
    state.modoGeral = false;
    const hoje = new Date();
    state.anoAtual = hoje.getFullYear();
    state.mesAtual = hoje.getMonth() + 1;
  }

  state.mesAtual += delta;
  if (state.mesAtual > 12) {
    state.mesAtual = 1;
    state.anoAtual += 1;
  } else if (state.mesAtual < 1) {
    state.mesAtual = 12;
    state.anoAtual -= 1;
  }

  state.mesSelecionado = formatarMesAno(state.anoAtual, state.mesAtual);
  atualizarDisplayMes();
  carregarDados();
}

export function voltarMesAtual(): void {
  state.modoGeral = false;
  const hoje = new Date();
  state.anoAtual = hoje.getFullYear();
  state.mesAtual = hoje.getMonth() + 1;
  state.mesSelecionado = formatarMesAno(state.anoAtual, state.mesAtual);
  atualizarDisplayMes();
  carregarDados();
}

export function alternarModoGeral(): void {
  state.modoGeral = true;
  state.mesSelecionado = "";
  atualizarDisplayMes();
  carregarDados();
}

// -------------------------------------------------------------
// CARREGAMENTO DE DADOS
// -------------------------------------------------------------
export async function carregarDados(): Promise<void> {
  const urlParam = state.modoGeral ? "" : `?mes=${state.mesSelecionado}`;

  try {
    const [resMetrics, resTrans] = await Promise.all([
      apiFetch(`${API_BASE}/metrics${urlParam}`),
      apiFetch(
        `${API_BASE}/transactions${urlParam}${
          state.filtroTipoAtual
            ? state.modoGeral
              ? `?tipo=${state.filtroTipoAtual}`
              : `&tipo=${state.filtroTipoAtual}`
            : ""
        }`
      ),
    ]);

    const metrics = (await resMetrics.json()) as MetricsResponse;
    const trans = (await resTrans.json()) as TransactionResponse[];

    state.metricasAtuais = metrics;
    state.transacoesAtuais = trans;

    renderKPIs(metrics);
    renderTableAndCards();
    atualizarGraficos(metrics, trans);
  } catch (error) {
    console.error("Erro ao carregar dados:", error);
  }
}

export function filtrarTabela(tipo: string): void {
  state.filtroTipoAtual = tipo;
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach((btn) => {
    btn.classList.toggle("active", (btn.getAttribute("data-tipo") || "") === tipo);
  });
  carregarDados();
}

// -------------------------------------------------------------
// DELEGAÇÃO CENTRALIZADA DE EVENTOS (SEM INLINE ONCLICK)
// -------------------------------------------------------------
function setupEventDelegation(): void {
  document.addEventListener("click", (event: MouseEvent) => {
    const target = event.target as HTMLElement | null;
    if (!target) return;

    // Fecha dropdowns se clicar fora
    if (
      !target.closest("#month-dropdown-menu") &&
      !target.closest("#month-pill-trigger")
    ) {
      fecharMonthDropdown();
    }
    if (
      !target.closest("#col-filter-popover") &&
      !target.closest(".th-filter-btn")
    ) {
      fecharFiltroColuna();
    }
    if (target.id === "delete-modal-overlay") {
      fecharModalExclusao();
    }

    const actionBtn = target.closest("[data-action]") as HTMLElement | null;
    if (!actionBtn) return;

    const action = actionBtn.getAttribute("data-action");

    switch (action) {
      case "logout":
        fazerLogout();
        break;
      case "prev-month":
        navegarMes(-1);
        break;
      case "next-month":
        navegarMes(1);
        break;
      case "toggle-month-dropdown":
        toggleMonthDropdown(event);
        break;
      case "prev-year-dropdown":
        mudarAnoDropdown(-1);
        break;
      case "next-year-dropdown":
        mudarAnoDropdown(1);
        break;
      case "current-month-dropdown":
        irParaMesCorrenteDropdown();
        break;
      case "close-month-dropdown":
        fecharMonthDropdown();
        break;
      case "select-month": {
        const y = Number(actionBtn.getAttribute("data-year"));
        const m = Number(actionBtn.getAttribute("data-month"));
        selecionarMesDireto(y, m);
        break;
      }
      case "month-current":
        voltarMesAtual();
        break;
      case "month-general":
        alternarModoGeral();
        break;
      case "filter-tab": {
        const tipo = actionBtn.getAttribute("data-tipo") || "";
        filtrarTabela(tipo);
        break;
      }
      case "open-col-filter": {
        const col = actionBtn.getAttribute("data-col");
        if (col) abrirFiltroColuna(col, actionBtn);
        break;
      }
      case "clear-col-filter":
        if (state.colunaPopoverAtual) {
          limparFiltroColuna(state.colunaPopoverAtual);
        }
        break;
      case "close-col-filter":
        fecharFiltroColuna();
        break;
      case "remove-filter-item": {
        const c = actionBtn.getAttribute("data-col");
        const v = actionBtn.getAttribute("data-val");
        if (c && v) removerFiltroItem(c, v);
        break;
      }
      case "clear-all-filters":
        limparTodosFiltros();
        break;
      case "edit-tx": {
        const id = Number(actionBtn.getAttribute("data-id"));
        if (!isNaN(id)) iniciarEdicao(id);
        break;
      }
      case "delete-tx": {
        const id = Number(actionBtn.getAttribute("data-id"));
        const trans = (state.transacoesAtuais || []).find((t) => t.id === id);
        if (!trans) return;

        const isParcelado = !!(
          trans.parcela_grupo_id ||
          (trans.parcela_num && trans.parcela_total)
        );
        if (isParcelado) {
          abrirModalExclusao(trans);
        } else {
          const desc = trans.descricao || trans.categoria;
          if (confirm(`Tem certeza de que deseja excluir o lançamento "${desc}"?`)) {
            state.idExclusaoPendente = id;
            executarExclusao("uma", carregarDados);
          }
        }
        break;
      }
      case "cancel-edit":
        cancelarEdicao();
        break;
      case "modal-delete-single":
        executarExclusao("uma", carregarDados);
        break;
      case "modal-delete-future":
        executarExclusao("futuras", carregarDados);
        break;
      case "modal-delete-all":
        executarExclusao("grupo", carregarDados);
        break;
      case "modal-cancel":
        fecharModalExclusao();
        break;
      default:
        break;
    }
  });

  const tipoSelect = document.getElementById("tipo");
  if (tipoSelect) {
    tipoSelect.addEventListener("change", aoMudarTipo);
  }

  const colSearchInput = document.getElementById("col-filter-search") as HTMLInputElement | null;
  if (colSearchInput) {
    colSearchInput.addEventListener("input", (e) => {
      const target = e.target as HTMLInputElement;
      filtrarOpcoesColuna(target.value);
    });
  }

  const formTransacao = document.getElementById("form-transacao");
  if (formTransacao) {
    formTransacao.addEventListener("submit", (e) => {
      e.preventDefault();
      salvarLancamento(carregarDados);
    });
  }
}

// -------------------------------------------------------------
// INICIALIZAÇÃO
// -------------------------------------------------------------
function initApp(): void {
  setupEventDelegation();

  const dataInput = document.getElementById("data") as HTMLInputElement | null;
  if (dataInput && !dataInput.value) {
    dataInput.value = new Date().toISOString().split("T")[0];
  }

  atualizarDisplayMes();
  carregarDados();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}
