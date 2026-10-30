/**
 * frontend/src/js/main.js
 *
 * Ponto de entrada modular do frontend FinTrack.
 * Configura delegação de eventos para eliminar handlers inline (data-action),
 * reatividade de estado e carregamento de dados.
 */

import { state, setState } from './state.js';
import { apiFetch, API_BASE, fazerLogout } from './api.js';
import { formatarMesAno } from './format.js';
import { renderKPIs } from './components/kpis.js';
import { renderTableAndCards } from './components/table.js';
import {
  abrirFiltroColuna,
  fecharPopoverColuna,
  alternarOpcaoFiltro,
  limparFiltroColunaAberta,
  removerFiltroIndividual,
  limparTodosFiltrosColuna,
  filtrarOpcoesColuna,
} from './components/filters.js';
import {
  abrirModalExclusao,
  fecharModalExclusao,
  executarExclusao,
} from './components/modal.js';
import {
  iniciarEdicao,
  cancelarEdicao,
  salvarTransacao,
  aoMudarTipo,
} from './components/form.js';
import { atualizarGraficos } from './charts.js';

const NOMES_MESES = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
];

const NOMES_MESES_ABREV = [
  'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
  'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez',
];

// -------------------------------------------------------------
// NAVEGAÇÃO E DROPDOWN DE MÊS
// -------------------------------------------------------------
export function toggleMonthDropdown(event) {
  if (event) event.stopPropagation();
  const dropdown = document.getElementById('month-dropdown-menu');
  const trigger = document.getElementById('month-pill-trigger');
  if (!dropdown) return;

  const isActive = dropdown.classList.toggle('active');
  if (trigger) trigger.classList.toggle('open', isActive);

  if (isActive) {
    state.anoDropdownAtual = state.anoAtual;
    renderMonthsGrid();
  }
}

export function fecharMonthDropdown() {
  const dropdown = document.getElementById('month-dropdown-menu');
  const trigger = document.getElementById('month-pill-trigger');
  if (dropdown) dropdown.classList.remove('active');
  if (trigger) trigger.classList.remove('open');
}

export function mudarAnoDropdown(delta) {
  state.anoDropdownAtual += delta;
  renderMonthsGrid();
}

export function renderMonthsGrid() {
  const yearEl = document.getElementById('month-dropdown-year');
  const gridEl = document.getElementById('months-grid');
  if (yearEl) yearEl.innerText = state.anoDropdownAtual;
  if (!gridEl) return;

  const hoje = new Date();
  const anoHoje = hoje.getFullYear();
  const mesHoje = hoje.getMonth() + 1;

  gridEl.innerHTML = NOMES_MESES_ABREV.map((abrev, idx) => {
    const mesNum = idx + 1;
    const isSelected = !state.modoGeral && state.anoDropdownAtual === state.anoAtual && mesNum === state.mesAtual;
    const isCurrent = state.anoDropdownAtual === anoHoje && mesNum === mesHoje;

    let classes = ['month-grid-item'];
    if (isSelected) classes.push('selected');
    if (isCurrent) classes.push('current');

    return `
      <button
        type="button"
        class="${classes.join(' ')}"
        data-action="select-month"
        data-year="${state.anoDropdownAtual}"
        data-month="${mesNum}"
      >
        ${abrev}
      </button>
    `;
  }).join('');
}

export function selecionarMesDireto(ano, mes) {
  state.anoAtual = ano;
  state.mesAtual = mes;
  state.mesSelecionado = formatarMesAno(ano, mes);
  state.modoGeral = false;
  fecharMonthDropdown();
  atualizarDisplayMes();
  carregarDados();
}

export function irParaMesCorrenteDropdown() {
  const hoje = new Date();
  selecionarMesDireto(hoje.getFullYear(), hoje.getMonth() + 1);
}

export function atualizarDisplayMes() {
  const display = document.getElementById('mes-display');
  const btnAtual = document.getElementById('btn-mes-atual');
  const btnGeral = document.getElementById('btn-todos-meses');
  const subtitle = document.getElementById('dashboard-subtitle');

  if (state.modoGeral) {
    if (display) display.innerText = 'Todos os Meses';
    if (btnAtual) btnAtual.classList.remove('active');
    if (btnGeral) btnGeral.classList.add('active');
    if (subtitle) subtitle.innerText = 'Consolidado histórico de todas as movimentações financeiras';
  } else {
    if (display) display.innerText = `${NOMES_MESES[state.mesAtual - 1]} ${state.anoAtual}`;
    if (btnGeral) btnGeral.classList.remove('active');

    const hoje = new Date();
    const isMesHoje = (state.anoAtual === hoje.getFullYear() && state.mesAtual === hoje.getMonth() + 1);
    if (btnAtual) btnAtual.classList.toggle('active', isMesHoje);
    if (subtitle) subtitle.innerText = `Planejamento e acompanhamento das despesas de ${NOMES_MESES[state.mesAtual - 1].toLowerCase()}`;
  }
}

export function navegarMes(delta) {
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

export function voltarMesAtual() {
  state.modoGeral = false;
  const hoje = new Date();
  state.anoAtual = hoje.getFullYear();
  state.mesAtual = hoje.getMonth() + 1;
  state.mesSelecionado = formatarMesAno(state.anoAtual, state.mesAtual);
  atualizarDisplayMes();
  carregarDados();
}

export function alternarModoGeral() {
  state.modoGeral = true;
  state.mesSelecionado = null;
  atualizarDisplayMes();
  carregarDados();
}

// -------------------------------------------------------------
// CARREGAMENTO DE DADOS
// -------------------------------------------------------------
export async function carregarDados() {
  const urlParam = state.modoGeral ? '' : `?mes=${state.mesSelecionado}`;

  try {
    const [resMetrics, resTrans] = await Promise.all([
      apiFetch(`${API_BASE}/metrics${urlParam}`),
      apiFetch(`${API_BASE}/transactions${urlParam}${state.filtroTipoAtual ? (state.modoGeral ? `?tipo=${state.filtroTipoAtual}` : `&tipo=${state.filtroTipoAtual}`) : ''}`),
    ]);

    const metrics = await resMetrics.json();
    const trans = await resTrans.json();

    state.metricasAtuais = metrics;
    state.transacoesAtuais = trans;

    renderKPIs(metrics);
    renderTableAndCards();
    atualizarGraficos(metrics, trans);
  } catch (error) {
    console.error('Erro ao carregar dados:', error);
  }
}

export function filtrarTabela(tipo) {
  state.filtroTipoAtual = tipo;
  const tabBtns = document.querySelectorAll('.tab-btn');
  tabBtns.forEach(btn => {
    btn.classList.toggle('active', (btn.getAttribute('data-tipo') || '') === tipo);
  });
  carregarDados();
}

// -------------------------------------------------------------
// DELEGAÇÃO CENTRALIZADA DE EVENTOS (SEM INLINE ONCLICK)
// -------------------------------------------------------------
function setupEventDelegation() {
  // Clique global para data-action e fechamento de popovers
  document.addEventListener('click', (event) => {
    const target = event.target;

    // Fecha dropdowns se clicar fora
    if (!target.closest('#month-dropdown-menu') && !target.closest('#month-pill-trigger')) {
      fecharMonthDropdown();
    }
    if (!target.closest('#col-filter-popover') && !target.closest('.th-filter-btn')) {
      fecharPopoverColuna();
    }
    if (target.id === 'delete-modal-overlay') {
      fecharModalExclusao();
    }

    const actionBtn = target.closest('[data-action]');
    if (!actionBtn) return;

    const action = actionBtn.getAttribute('data-action');

    switch (action) {
      case 'logout':
        fazerLogout();
        break;
      case 'prev-month':
        navegarMes(-1);
        break;
      case 'next-month':
        navegarMes(1);
        break;
      case 'toggle-month-dropdown':
        toggleMonthDropdown(event);
        break;
      case 'prev-year-dropdown':
        mudarAnoDropdown(-1);
        break;
      case 'next-year-dropdown':
        mudarAnoDropdown(1);
        break;
      case 'current-month-dropdown':
        irParaMesCorrenteDropdown();
        break;
      case 'close-month-dropdown':
        fecharMonthDropdown();
        break;
      case 'select-month': {
        const y = Number(actionBtn.getAttribute('data-year'));
        const m = Number(actionBtn.getAttribute('data-month'));
        selecionarMesDireto(y, m);
        break;
      }
      case 'month-current':
        voltarMesAtual();
        break;
      case 'month-general':
        alternarModoGeral();
        break;
      case 'filter-tab': {
        const tipo = actionBtn.getAttribute('data-tipo') || '';
        filtrarTabela(tipo);
        break;
      }
      case 'open-col-filter': {
        const col = actionBtn.getAttribute('data-col');
        abrirFiltroColuna(col, actionBtn, event);
        break;
      }
      case 'clear-col-filter':
        limparFiltroColunaAberta();
        break;
      case 'close-col-filter':
        fecharPopoverColuna();
        break;
      case 'remove-chip': {
        const c = actionBtn.getAttribute('data-col');
        const v = actionBtn.getAttribute('data-val');
        removerFiltroIndividual(c, v);
        break;
      }
      case 'clear-all-filters':
        limparTodosFiltrosColuna();
        break;
      case 'edit': {
        const id = Number(actionBtn.getAttribute('data-id'));
        iniciarEdicao(id);
        break;
      }
      case 'delete': {
        const id = Number(actionBtn.getAttribute('data-id'));
        const trans = (state.transacoesAtuais || []).find(t => t.id === id);
        if (!trans) return;

        const isParcelado = !!(trans.parcela_grupo_id || (trans.parcela_num && trans.parcela_total));
        if (isParcelado) {
          abrirModalExclusao(trans);
        } else {
          const desc = trans.descricao || trans.categoria;
          if (confirm(`Tem certeza de que deseja excluir o lançamento "${desc}"?`)) {
            state.idExclusaoPendente = id;
            executarExclusao('uma', carregarDados);
          }
        }
        break;
      }
      case 'cancel-edit':
        cancelarEdicao();
        break;
      case 'modal-delete-single':
        executarExclusao('uma', carregarDados);
        break;
      case 'modal-delete-future':
        executarExclusao('futuras', carregarDados);
        break;
      case 'modal-delete-all':
        executarExclusao('grupo', carregarDados);
        break;
      case 'modal-cancel':
        fecharModalExclusao();
        break;
      default:
        break;
    }
  });

  // Mudança em checkboxes de filtros do popover
  document.addEventListener('change', (event) => {
    const target = event.target;
    if (target.matches('#tipo')) {
      aoMudarTipo();
    } else if (target.matches('.col-filter-item input[type="checkbox"]')) {
      const col = target.getAttribute('data-col');
      const val = target.getAttribute('data-val');
      alternarOpcaoFiltro(col, val);
    }
  });

  // Input no campo de busca do popover de coluna
  const colSearchInput = document.getElementById('col-filter-search');
  if (colSearchInput) {
    colSearchInput.addEventListener('input', (e) => {
      filtrarOpcoesColuna(e.target.value);
    });
  }

  // Formulário de Cadastro / Edição
  const formTransacao = document.getElementById('form-transacao');
  if (formTransacao) {
    formTransacao.addEventListener('submit', (e) => {
      salvarTransacao(e, carregarDados);
    });
  }
}

// -------------------------------------------------------------
// INICIALIZAÇÃO
// -------------------------------------------------------------
function initApp() {
  setupEventDelegation();

  // Define data de hoje no campo de data do formulário
  const dataInput = document.getElementById('data');
  if (dataInput && !dataInput.value) {
    dataInput.value = new Date().toISOString().split('T')[0];
  }

  atualizarDisplayMes();
  carregarDados();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
