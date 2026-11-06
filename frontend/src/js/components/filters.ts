/**
 * frontend/src/js/components/filters.ts
 *
 * Popover de filtros multifacetados por coluna e chips de filtros ativos.
 */

import { state } from "../state";
import { formatBRL, formatDateBR, formatChannelLabel } from "../format";
import { escapeHtml } from "../dom";
import { renderTableAndCards } from "./table";
import type { TransactionResponse } from "../state";

export const NOMES_COLUNAS: Record<string, string> = {
  data: "Data",
  tipo: "Tipo",
  categoria: "Categoria",
  descricao: "Descrição",
  vencimento: "Vencimento",
  author: "Autor",
  channel: "Canal",
  valor: "Valor",
};

export function obterValorColuna(t: TransactionResponse, col: string): string {
  switch (col) {
    case "data":
      return formatDateBR(t.data);
    case "tipo": {
      const mapTipo: Record<string, string> = {
        receita: "Receita",
        despesa_fixa: "Despesa Fixa",
        despesa_variavel: "Gasto Variável",
      };
      return mapTipo[t.tipo] || t.tipo;
    }
    case "categoria":
      return t.categoria || "Sem categoria";
    case "descricao":
      return t.descricao || "-";
    case "vencimento":
      return t.vencimento ? `Dia ${t.vencimento}` : "-";
    case "author":
      return (
        t.author ||
        (t.source && t.source !== "Manual" && t.source !== "WhatsApp"
          ? t.source
          : "Geral")
      );
    case "channel":
      return formatChannelLabel(
        t.channel || (t.source === "Manual" ? "dashboard" : "whatsapp_text")
      );
    case "valor":
      return formatBRL(t.valor);
    default:
      return String((t as unknown as Record<string, unknown>)[col] ?? "-");
  }
}

export function abrirFiltroColuna(coluna: string, triggerBtn?: HTMLElement): void {
  const popover = document.getElementById("col-filter-popover");
  if (!popover) return;

  if (state.colunaPopoverAtual === coluna && popover.classList.contains("open")) {
    fecharFiltroColuna();
    return;
  }

  state.colunaPopoverAtual = coluna;

  if (triggerBtn) {
    const rect = triggerBtn.getBoundingClientRect();
    const popWidth = Math.min(280, window.innerWidth - 32);
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
  } else {
    // Abertura sem botão ancorado (ex: centralizado em mobile)
    const popWidth = Math.min(290, window.innerWidth - 32);
    popover.style.left = `${Math.max(16, (window.innerWidth - popWidth) / 2)}px`;
    popover.style.top = "100px";
  }

  const searchInput = document.getElementById("col-filter-search") as HTMLInputElement | null;
  if (searchInput) searchInput.value = "";

  renderOpcoesFiltroColuna(coluna);
  popover.classList.add("open");

  setTimeout(() => {
    if (searchInput) searchInput.focus();
  }, 50);
}

export function fecharFiltroColuna(): void {
  const popover = document.getElementById("col-filter-popover");
  if (popover) popover.classList.remove("open");
  state.colunaPopoverAtual = null;
}

export function renderOpcoesFiltroColuna(coluna: string, termoBusca: string = ""): void {
  const container =
    document.getElementById("col-filter-list") ||
    document.getElementById("col-filter-options");
  if (!container) return;

  const trans = state.transacoesAtuais || [];
  const valoresUnicos = new Set<string>();

  for (const t of trans) {
    const val = obterValorColuna(t, coluna);
    if (val) valoresUnicos.add(val);
  }

  const valoresArray = Array.from(valoresUnicos).sort((a, b) => a.localeCompare(b));
  const filtroAtivoSet = state.filtrosColuna[coluna as keyof typeof state.filtrosColuna] || new Set();

  const filtrados = termoBusca
    ? valoresArray.filter((v) => v.toLowerCase().includes(termoBusca.toLowerCase()))
    : valoresArray;

  if (filtrados.length === 0) {
    container.innerHTML =
      '<div style="color: var(--text-dim); font-size: 12px; padding: 12px 8px; text-align: center;">Nenhuma opção encontrada</div>';
    return;
  }

  container.innerHTML = filtrados
    .map((val) => {
      const isChecked = filtroAtivoSet.has(val);
      const safeVal = escapeHtml(val);
      return `
      <label class="col-filter-item ${isChecked ? "selected" : ""}">
        <div class="col-filter-item-left">
          <input type="checkbox" data-col="${coluna}" data-val="${safeVal}" ${isChecked ? "checked" : ""} style="display:none;">
          <span class="col-filter-check">${isChecked ? "✓" : ""}</span>
          <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${safeVal}</span>
        </div>
      </label>
    `;
    })
    .join("");

  container.querySelectorAll('input[type="checkbox"]').forEach((chk) => {
    chk.addEventListener("change", (e) => {
      const target = e.target as HTMLInputElement;
      const col = target.getAttribute("data-col") as keyof typeof state.filtrosColuna;
      const val = target.getAttribute("data-val");
      if (!col || !val) return;

      if (target.checked) {
        state.filtrosColuna[col].add(val);
      } else {
        state.filtrosColuna[col].delete(val);
      }
      renderOpcoesFiltroColuna(coluna, termoBusca);
      renderTableAndCards();
    });
  });
}

export function limparFiltroColuna(coluna: string): void {
  const colKey = coluna as keyof typeof state.filtrosColuna;
  if (state.filtrosColuna[colKey]) {
    state.filtrosColuna[colKey].clear();
    renderOpcoesFiltroColuna(coluna);
    renderTableAndCards();
  }
}

export function limparTodosFiltros(): void {
  for (const setVal of Object.values(state.filtrosColuna)) {
    setVal.clear();
  }
  state.termoBuscaTexto = "";
  const inputSearch = document.getElementById("tx-search-input") as HTMLInputElement | null;
  if (inputSearch) inputSearch.value = "";
  fecharFiltroColuna();
  renderTableAndCards();
}

export function removerFiltroItem(coluna: string, valor: string): void {
  const colKey = coluna as keyof typeof state.filtrosColuna;
  if (state.filtrosColuna[colKey]) {
    state.filtrosColuna[colKey].delete(valor);
    renderTableAndCards();
  }
}

export function filtrarOpcoesColuna(termo: string): void {
  if (state.colunaPopoverAtual) {
    renderOpcoesFiltroColuna(state.colunaPopoverAtual, termo);
  }
}
