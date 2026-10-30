/**
 * frontend/src/js/components/table.js
 *
 * Renderização da tabela de transações, lista de cards responsiva para mobile,
 * e gerenciamento dos badges de filtros ativos.
 */

import { state } from '../state.js';
import {
  formatBRL,
  formatDateBR,
  formatChannelLabel,
  badgeTipo,
  classValor,
  sinalValor,
} from '../format.js';
import { escapeHtml } from '../dom.js';
import { obterValorColuna, NOMES_COLUNAS } from './filters.js';

export function renderTableAndCards() {
  const trans = state.transacoesAtuais || [];
  const tbody = document.getElementById('tabela-corpo');
  const mobileList = document.getElementById('mobile-tx-list');
  const emptyState = document.getElementById('tabela-empty');

  // Atualiza estado visual dos botões de cabeçalho
  let totalFiltrosAtivos = 0;
  for (const [col, setValores] of Object.entries(state.filtrosColuna)) {
    const btn = document.getElementById(`th-btn-${col}`);
    const badge = document.getElementById(`th-badge-${col}`);
    if (btn && badge) {
      if (setValores.size > 0) {
        totalFiltrosAtivos += setValores.size;
        btn.classList.add('active');
        badge.style.display = 'inline-flex';
        badge.innerText = setValores.size;
      } else {
        btn.classList.remove('active');
        badge.style.display = 'none';
      }
    }
  }

  // Filtra as transações
  const filtradas = trans.filter(t => {
    for (const [col, setValores] of Object.entries(state.filtrosColuna)) {
      if (setValores.size === 0) continue;
      const valTrans = obterValorColuna(t, col);
      if (!setValores.has(valTrans)) return false;
    }
    return true;
  });

  // Atualiza barra de Chips de Filtros Ativos
  const barEl = document.getElementById('active-filters-bar');
  const chipsGroup = document.getElementById('active-chips-group');
  const summaryPills = document.getElementById('filtered-summary-pills');

  if (totalFiltrosAtivos > 0) {
    if (barEl) barEl.classList.add('visible');
    let chipsHtml = `<span class="active-filters-label">Filtros ativos:</span>`;
    for (const [col, setValores] of Object.entries(state.filtrosColuna)) {
      for (const val of setValores) {
        chipsHtml += `
          <span class="filter-chip">
            <span class="chip-col">${escapeHtml(NOMES_COLUNAS[col] || col)}:</span>
            <span class="chip-val">${escapeHtml(val)}</span>
            <button type="button" class="btn-remove-chip" data-action="remove-chip" data-col="${escapeHtml(col)}" data-val="${escapeHtml(val)}" title="Remover este filtro">&times;</button>
          </span>
        `;
      }
    }
    chipsHtml += `<button type="button" class="btn-clear-all-filters" data-action="clear-all-filters">Limpar todos</button>`;
    if (chipsGroup) chipsGroup.innerHTML = chipsHtml;

    const somaFiltrada = filtradas.reduce((acc, t) => acc + (t.tipo !== 'receita' ? Number(t.valor) : 0), 0);
    const qtdFiltrada = filtradas.length;
    if (summaryPills) {
      summaryPills.innerHTML = `
        <span class="summary-pill">${qtdFiltrada} lançamento${qtdFiltrada === 1 ? '' : 's'}</span>
        <span class="summary-pill highlight">Total filtrado: <strong>${escapeHtml(formatBRL(somaFiltrada))}</strong></span>
      `;
    }
  } else {
    if (barEl) barEl.classList.remove('visible');
    if (chipsGroup) chipsGroup.innerHTML = '';
    if (summaryPills) summaryPills.innerHTML = '';
  }

  // Se não há dados, exibe empty state
  if (filtradas.length === 0) {
    if (tbody) tbody.innerHTML = '';
    if (mobileList) mobileList.innerHTML = '';
    if (emptyState) emptyState.style.display = 'block';
    return;
  }

  if (emptyState) emptyState.style.display = 'none';

  // Renderiza tabela desktop
  if (tbody) {
    tbody.innerHTML = filtradas.map(t => {
      const bTipo = badgeTipo(t.tipo);
      const tid = Number(t.id);
      const vStr = t.vencimento ? `Dia ${escapeHtml(t.vencimento)}` : '-';
      return `
        <tr>
          <td>${escapeHtml(formatDateBR(t.data))}</td>
          <td><span class="badge ${bTipo.class}">${bTipo.text}</span></td>
          <td>${escapeHtml(t.categoria)}</td>
          <td>
            ${escapeHtml(t.descricao || '-')}
            ${(t.parcela_num && t.parcela_total) ? `<span class="chart-pill-badge" style="margin-left: 6px; font-size: 10px; background: rgba(59, 130, 246, 0.15); color: #93C5FD; border-color: rgba(59, 130, 246, 0.3); font-weight: 700;">${Number(t.parcela_num)}/${Number(t.parcela_total)}</span>` : ''}
          </td>
          <td>${vStr}</td>
          <td>
            <span class="badge-source" title="Canal: ${escapeHtml(formatChannelLabel(t.channel))}">
              ${escapeHtml(t.author || (t.source && t.source !== 'Manual' && t.source !== 'WhatsApp' ? t.source : 'Geral'))}
            </span>
          </td>
          <td>
            <span style="font-size: 11.5px; color: var(--text-dim);" title="Canal de entrada: ${escapeHtml(t.channel || 'unknown')}">
              ${escapeHtml(formatChannelLabel(t.channel || (t.source === 'Manual' ? 'dashboard' : 'whatsapp_text')))}
            </span>
          </td>
          <td class="${classValor(t.tipo)}">
            ${sinalValor(t.tipo)} ${escapeHtml(formatBRL(t.valor))}
          </td>
          <td style="text-align: right;">
            <div class="actions-cell">
              <button class="btn-edit" data-action="edit" data-id="${tid}" title="Editar este lançamento">
                <svg width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                </svg>
                Editar
              </button>
              <button class="btn-delete" data-action="delete" data-id="${tid}" title="Excluir este lançamento">Excluir</button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  // Renderiza cards mobile
  if (mobileList) {
    mobileList.innerHTML = filtradas.map(t => {
      const tid = Number(t.id);
      const vencMobile = t.vencimento ? `Venc: <strong>Dia ${escapeHtml(t.vencimento)}</strong>` : '';
      return `
        <div class="mobile-tx-card">
          <div class="mobile-tx-header">
            <span class="mobile-tx-desc">${escapeHtml(t.descricao || 'Sem descrição')}</span>
            <span class="badge ${badgeTipo(t.tipo).class}">${badgeTipo(t.tipo).text}</span>
          </div>
          <div class="mobile-tx-meta">
            <span class="mobile-tx-cat">${escapeHtml(t.categoria)}</span>
            <span class="mobile-tx-date">
              ${escapeHtml(formatDateBR(t.data))}
              ${vencMobile ? `&bull; ${vencMobile}` : ''}
              &bull; <span class="badge-source" title="${escapeHtml(formatChannelLabel(t.channel))}">${escapeHtml(t.author || (t.source && t.source !== 'Manual' && t.source !== 'WhatsApp' ? t.source : 'Geral'))}</span>
              &bull; <span style="font-size: 10px; opacity: 0.75;">${escapeHtml(formatChannelLabel(t.channel))}</span>
              ${(t.parcela_num && t.parcela_total) ? `&bull; <strong style="color: #93C5FD;">${Number(t.parcela_num)}/${Number(t.parcela_total)}</strong>` : ''}
            </span>
          </div>
          <div class="mobile-tx-footer">
            <span class="mobile-tx-amount ${classValor(t.tipo)}">
              ${sinalValor(t.tipo)} ${escapeHtml(formatBRL(t.valor))}
            </span>
            <div class="mobile-tx-actions">
              <button class="btn-edit" data-action="edit" data-id="${tid}">Editar</button>
              <button class="btn-delete" data-action="delete" data-id="${tid}">Excluir</button>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }
}
