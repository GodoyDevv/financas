/**
 * frontend/src/js/components/table.ts
 *
 * Renderização da tabela de transações, lista de cards responsiva para mobile,
 * e gerenciamento dos badges de filtros ativos.
 */

import { state } from "../state";
import {
  formatBRL,
  formatDateBR,
  formatChannelLabel,
  badgeTipo,
  classValor,
  sinalValor,
} from "../format";
import { escapeHtml } from "../dom";
import { obterValorColuna, NOMES_COLUNAS } from "./filters";

export function renderTableAndCards(): void {
  const trans = state.transacoesAtuais || [];
  const tbody = document.getElementById("tabela-corpo");
  const mobileList = document.getElementById("mobile-tx-list");
  const emptyState = document.getElementById("tabela-empty");

  // Atualiza estado visual dos botões de cabeçalho
  let totalFiltrosAtivos = 0;
  for (const [col, setValores] of Object.entries(state.filtrosColuna)) {
    const btn = document.getElementById(`th-btn-${col}`);
    const badge = document.getElementById(`th-badge-${col}`);
    if (btn && badge) {
      if (setValores.size > 0) {
        totalFiltrosAtivos += setValores.size;
        btn.classList.add("active");
        badge.style.display = "inline-flex";
        badge.innerText = String(setValores.size);
      } else {
        btn.classList.remove("active");
        badge.style.display = "none";
      }
    }
  }

  // Filtra as transações
  const filtradas = trans.filter((t) => {
    for (const [col, setValores] of Object.entries(state.filtrosColuna)) {
      if (setValores.size === 0) continue;
      const valTrans = obterValorColuna(t, col);
      if (!setValores.has(valTrans)) return false;
    }
    return true;
  });

  // Atualiza contador de registros
  const countBadge = document.getElementById("total-records-count");
  if (countBadge) {
    if (totalFiltrosAtivos > 0) {
      countBadge.innerText = `${filtradas.length} de ${trans.length} registros`;
      countBadge.classList.add("filtered");
    } else {
      countBadge.innerText = `${trans.length} registros`;
      countBadge.classList.remove("filtered");
    }
  }

  // Renderiza a barra de chips de filtros ativos
  renderActiveFilterChips(totalFiltrosAtivos);

  // Se vazio
  if (filtradas.length === 0) {
    if (tbody) tbody.innerHTML = "";
    if (mobileList) mobileList.innerHTML = "";
    if (emptyState) emptyState.style.display = "flex";
    return;
  }

  if (emptyState) emptyState.style.display = "none";

  // 1. RENDERIZA A TABELA DESKTOP
  if (tbody) {
    tbody.innerHTML = filtradas
      .map((t) => {
        const badge = badgeTipo(t.tipo);
        const valorClass = classValor(t.tipo);
        const sinal = sinalValor(t.tipo);
        const canalFormatado = formatChannelLabel(
          t.channel || (t.source === "Manual" ? "dashboard" : "whatsapp_text")
        );

        let autorTag = "Geral";
        let autorClass = "author-badge-geral";
        const autorNome = t.author || t.source || "Geral";
        if (/bruno/i.test(autorNome)) {
          autorTag = "Bruno";
          autorClass = "author-badge-bruno";
        } else if (/let[ií]cia/i.test(autorNome)) {
          autorTag = "Letícia";
          autorClass = "author-badge-leticia";
        } else if (autorNome !== "Manual" && autorNome !== "WhatsApp") {
          autorTag = autorNome;
        }

        const isParcelado = !!(
          t.parcela_grupo_id ||
          (t.parcela_num && t.parcela_total)
        );
        const pNum = t.parcela_num || 1;
        const pTot = t.parcela_total || 1;
        const parcelasTag = isParcelado
          ? `<span class="badge-parcela">${pNum}/${pTot}</span>`
          : "";

        return `
        <tr data-id="${t.id}">
          <td style="color: var(--text-dim); font-size: 13px; font-weight: 500;">${escapeHtml(formatDateBR(t.data))}</td>
          <td><span class="badge ${badge.class}">${escapeHtml(badge.text)}</span></td>
          <td style="font-weight: 500;">${escapeHtml(t.categoria)}</td>
          <td>
            <div style="font-weight: 500; display: inline-flex; align-items: center; gap: 6px;">
              <span>${escapeHtml(t.descricao || "-")}</span>
              ${parcelasTag}
            </div>
          </td>
          <td style="color: var(--text-dim);">${t.vencimento ? `Dia ${escapeHtml(t.vencimento)}` : "-"}</td>
          <td>
            <span class="author-badge ${autorClass}">
              <span class="author-dot"></span>
              ${escapeHtml(autorTag)}
            </span>
          </td>
          <td><span class="channel-badge">${escapeHtml(canalFormatado)}</span></td>
          <td class="${valorClass}" style="text-align: right; font-weight: 600;">
            ${sinal} ${escapeHtml(formatBRL(t.valor))}
          </td>
          <td style="text-align: right;">
            <div style="display: inline-flex; gap: 6px;">
              <button class="btn-action" data-action="edit-tx" data-id="${t.id}" title="Editar lançamento">
                <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
              </button>
              <button class="btn-action delete" data-action="delete-tx" data-id="${t.id}" title="Excluir lançamento">
                <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
              </button>
            </div>
          </td>
        </tr>
      `;
      })
      .join("");
  }

  // 2. RENDERIZA OS CARDS MOBILE (VIEWPORT ESTREITO)
  if (mobileList) {
    mobileList.innerHTML = filtradas
      .map((t) => {
        const badge = badgeTipo(t.tipo);
        const valorClass = classValor(t.tipo);
        const sinal = sinalValor(t.tipo);
        const canalFormatado = formatChannelLabel(
          t.channel || (t.source === "Manual" ? "dashboard" : "whatsapp_text")
        );

        let autorTag = "Geral";
        let autorClass = "author-badge-geral";
        const autorNome = t.author || t.source || "Geral";
        if (/bruno/i.test(autorNome)) {
          autorTag = "Bruno";
          autorClass = "author-badge-bruno";
        } else if (/let[ií]cia/i.test(autorNome)) {
          autorTag = "Letícia";
          autorClass = "author-badge-leticia";
        } else if (autorNome !== "Manual" && autorNome !== "WhatsApp") {
          autorTag = autorNome;
        }

        const isParcelado = !!(
          t.parcela_grupo_id ||
          (t.parcela_num && t.parcela_total)
        );
        const pNum = t.parcela_num || 1;
        const pTot = t.parcela_total || 1;
        const parcelasTag = isParcelado
          ? `<span class="badge-parcela">${pNum}/${pTot}</span>`
          : "";

        return `
        <div class="mobile-tx-card" data-id="${t.id}">
          <div class="mobile-tx-header">
            <div class="mobile-tx-desc-group">
              <span class="mobile-tx-desc">${escapeHtml(t.descricao || t.categoria)}</span>
              ${parcelasTag}
            </div>
            <span class="mobile-tx-valor ${valorClass}">${sinal} ${escapeHtml(formatBRL(t.valor))}</span>
          </div>

          <div class="mobile-tx-meta">
            <span class="badge ${badge.class}">${escapeHtml(badge.text)}</span>
            <span class="mobile-tx-bullet">•</span>
            <span>${escapeHtml(t.categoria)}</span>
            <span class="mobile-tx-bullet">•</span>
            <span>${escapeHtml(formatDateBR(t.data))}</span>
          </div>

          <div class="mobile-tx-footer">
            <div class="mobile-tx-tags">
              <span class="author-badge ${autorClass}">
                <span class="author-dot"></span>
                ${escapeHtml(autorTag)}
              </span>
              <span class="channel-badge">${escapeHtml(canalFormatado)}</span>
            </div>
            <div class="mobile-tx-actions">
              <button class="btn-action" data-action="edit-tx" data-id="${t.id}" title="Editar">
                <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
              </button>
              <button class="btn-action delete" data-action="delete-tx" data-id="${t.id}" title="Excluir">
                <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
              </button>
            </div>
          </div>
        </div>
      `;
      })
      .join("");
  }
}

function renderActiveFilterChips(totalFiltrosAtivos: number): void {
  const container = document.getElementById("active-filter-chips");
  if (!container) return;

  if (totalFiltrosAtivos === 0) {
    container.style.display = "none";
    container.innerHTML = "";
    return;
  }

  container.style.display = "flex";
  let chipsHtml = "";

  for (const [col, setValores] of Object.entries(state.filtrosColuna)) {
    if (setValores.size === 0) continue;
    const nomeCol = NOMES_COLUNAS[col] || col;

    for (const val of setValores) {
      const safeVal = escapeHtml(val);
      chipsHtml += `
        <div class="filter-chip">
          <span><strong>${escapeHtml(nomeCol)}:</strong> ${safeVal}</span>
          <button type="button" class="btn-chip-remove" data-action="remove-filter-item" data-col="${col}" data-val="${safeVal}" title="Remover este filtro">
            <svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
              <path d="M18 6L6 18M6 6l12 12"></path>
            </svg>
          </button>
        </div>
      `;
    }
  }

  chipsHtml += `
    <button type="button" class="btn-clear-all-chips" data-action="clear-all-filters">
      Limpar todos os filtros (${totalFiltrosAtivos})
    </button>
  `;

  container.innerHTML = chipsHtml;
}
