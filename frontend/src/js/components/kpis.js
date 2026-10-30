/**
 * frontend/src/js/components/kpis.js
 *
 * Atualiza os cartões de métricas (KPIs), barra de progresso do mês
 * e orçamentos de categorias.
 */

import { formatBRL } from '../format.js';
import { escapeHtml } from '../dom.js';

export function renderKPIs(metrics) {
  if (!metrics) return;

  const cardReceitas = document.getElementById('card-receitas');
  const cardFixas = document.getElementById('card-fixas');
  const cardWhatsapp = document.getElementById('card-whatsapp');
  const cardSaldoLivre = document.getElementById('card-saldo-livre');

  if (cardReceitas) cardReceitas.innerText = formatBRL(metrics.receitas_totais || 0);
  if (cardFixas) cardFixas.innerText = formatBRL(metrics.contas_fixas || 0);
  if (cardWhatsapp) cardWhatsapp.innerText = formatBRL(metrics.gastos_whatsapp || 0);
  if (cardSaldoLivre) cardSaldoLivre.innerText = formatBRL(metrics.saldo_livre || 0);

  // Orçamentos por Categoria (Progress Bars)
  const catList = document.getElementById('category-progress-list');
  if (catList && metrics.categorias) {
    if (metrics.categorias.length === 0) {
      catList.innerHTML = '<div style="color: var(--text-dim); font-size: 13px; padding: 8px 0;">Nenhum gasto registrado neste mês.</div>';
    } else {
      catList.innerHTML = metrics.categorias.map(c => {
        const pct = Math.min(100, Math.round(c.percentual || 0));
        let barColor = 'var(--accent-blue)';
        if (pct >= 90) barColor = 'var(--accent-red)';
        else if (pct >= 70) barColor = 'var(--accent-amber)';

        return `
          <div class="category-item">
            <div class="category-meta">
              <span class="category-name">${escapeHtml(c.categoria)}</span>
              <div class="category-values">
                <span>${escapeHtml(formatBRL(c.total))}</span>
                ${c.budget ? `<span class="category-budget">/ ${escapeHtml(formatBRL(c.budget))}</span>` : ''}
              </div>
            </div>
            <div class="progress-bar-bg">
              <div class="progress-bar-fill" style="width: ${pct}%; background-color: ${barColor};"></div>
            </div>
          </div>
        `;
      }).join('');
    }
  }
}
