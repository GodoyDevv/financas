/**
 * frontend/src/js/components/filters.js
 *
 * Popover de filtros multifacetados por coluna e chips de filtros ativos.
 */

import { state, setState } from '../state.js';
import { formatBRL, formatDateBR, formatChannelLabel } from '../format.js';
import { escapeHtml } from '../dom.js';
import { renderTableAndCards } from './table.js';

export const NOMES_COLUNAS = {
  data: 'Data',
  tipo: 'Tipo',
  categoria: 'Categoria',
  descricao: 'Descrição',
  vencimento: 'Vencimento',
  author: 'Autor',
  channel: 'Canal',
  valor: 'Valor',
};

export function obterValorColuna(t, col) {
  switch (col) {
    case 'data':
      return formatDateBR(t.data);
    case 'tipo': {
      const mapTipo = {
        receita: 'Receita',
        despesa_fixa: 'Despesa Fixa',
        despesa_variavel: 'Gasto Variável',
      };
      return mapTipo[t.tipo] || t.tipo;
    }
    case 'categoria':
      return t.categoria || 'Sem categoria';
    case 'descricao':
      return t.descricao || '-';
    case 'vencimento':
      return t.vencimento ? `Dia ${t.vencimento}` : '-';
    case 'author':
      return t.author || (t.source && t.source !== 'Manual' && t.source !== 'WhatsApp' ? t.source : 'Geral');
    case 'channel':
      return formatChannelLabel(t.channel || (t.source === 'Manual' ? 'dashboard' : 'whatsapp_text'));
    case 'valor':
      return formatBRL(t.valor);
    default:
      return String(t[col] ?? '-');
  }
}

export function abrirFiltroColuna(col, btnEl, event) {
  if (event) event.stopPropagation();
  const popover = document.getElementById('col-filter-popover');
  if (!popover) return;

  if (state.colunaPopoverAtual === col && popover.classList.contains('open')) {
    fecharPopoverColuna();
    return;
  }

  state.colunaPopoverAtual = col;
  const searchInput = document.getElementById('col-filter-search');
  if (searchInput) {
    searchInput.placeholder = `Buscar em ${NOMES_COLUNAS[col] || col}...`;
    searchInput.value = '';
  }

  renderizarOpcoesPopover(col, '');

  popover.classList.add('open');
  if (btnEl) {
    const rect = btnEl.getBoundingClientRect();
    const popWidth = 265;
    let left = rect.left;
    if (left + popWidth > window.innerWidth - 16) {
      left = Math.max(16, window.innerWidth - popWidth - 16);
    }
    let top = rect.bottom + 8;
    if (top + 320 > window.innerHeight) {
      top = Math.max(16, rect.top - 320);
    }

    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  }

  setTimeout(() => {
    if (searchInput) searchInput.focus();
  }, 50);
}

export function renderizarOpcoesPopover(col, termoBusca = '') {
  const container = document.getElementById('col-filter-options');
  if (!container) return;

  const trans = state.transacoesAtuais || [];
  const freqMap = new Map();

  for (const t of trans) {
    let matchDemaisColunas = true;
    for (const [outraCol, setValores] of Object.entries(state.filtrosColuna)) {
      if (outraCol === col || setValores.size === 0) continue;
      const val = obterValorColuna(t, outraCol);
      if (!setValores.has(val)) {
        matchDemaisColunas = false;
        break;
      }
    }
    if (!matchDemaisColunas) continue;

    const val = obterValorColuna(t, col);
    const numValor = Number(t.valor) || 0;
    if (!freqMap.has(val)) {
      freqMap.set(val, { count: 1, sum: numValor });
    } else {
      const item = freqMap.get(val);
      item.count += 1;
      item.sum += numValor;
    }
  }

  let opcoes = Array.from(freqMap.entries());
  if (termoBusca.trim() !== '') {
    const q = termoBusca.toLowerCase().trim();
    opcoes = opcoes.filter(([val]) => String(val).toLowerCase().includes(q));
  }

  opcoes.sort((a, b) => b[1].count - a[1].count || String(a[0]).localeCompare(String(b[0])));

  const setMarcados = state.filtrosColuna[col] || new Set();

  if (opcoes.length === 0) {
    container.innerHTML = '<div style="padding: 12px; color: var(--text-dim); font-size: 12px; text-align: center;">Nenhuma opção encontrada</div>';
    return;
  }

  container.innerHTML = opcoes.map(([val, info]) => {
    const checked = setMarcados.has(val) ? 'checked' : '';
    return `
      <label class="col-filter-item">
        <input type="checkbox" data-col="${escapeHtml(col)}" data-val="${escapeHtml(val)}" ${checked}>
        <span class="col-filter-name">${escapeHtml(val)}</span>
        <span class="col-filter-count" title="Soma desta opção: ${escapeHtml(formatBRL(info.sum))}">${Number(info.count || 0)}x &middot; ${escapeHtml(formatBRL(info.sum))}</span>
      </label>
    `;
  }).join('');
}

export function filtrarOpcoesColuna(valorBusca) {
  if (state.colunaPopoverAtual) {
    renderizarOpcoesPopover(state.colunaPopoverAtual, valorBusca);
  }
}

export function alternarOpcaoFiltro(col, val) {
  const setValores = state.filtrosColuna[col];
  if (!setValores) return;

  if (setValores.has(val)) {
    setValores.delete(val);
  } else {
    setValores.add(val);
  }

  renderTableAndCards();
}

export function limparFiltroColunaAberta() {
  if (!state.colunaPopoverAtual) return;
  state.filtrosColuna[state.colunaPopoverAtual].clear();
  renderizarOpcoesPopover(state.colunaPopoverAtual, '');
  renderTableAndCards();
}

export function removerFiltroIndividual(col, val) {
  if (state.filtrosColuna[col]) {
    state.filtrosColuna[col].delete(val);
    renderTableAndCards();
    if (state.colunaPopoverAtual === col) {
      renderizarOpcoesPopover(col, '');
    }
  }
}

export function limparTodosFiltrosColuna() {
  for (const setValores of Object.values(state.filtrosColuna)) {
    setValores.clear();
  }
  renderTableAndCards();
  if (state.colunaPopoverAtual) {
    renderizarOpcoesPopover(state.colunaPopoverAtual, '');
  }
}

export function fecharPopoverColuna() {
  const popover = document.getElementById('col-filter-popover');
  if (popover) popover.classList.remove('open');
  state.colunaPopoverAtual = null;
}
