/**
 * frontend/src/js/components/form.ts
 *
 * Gerenciamento do formulário de criação e edição de lançamentos financeiros.
 */

import { state } from "../state";
import { apiFetch, API_BASE } from "../api";

export function aoMudarTipo(): void {
  const tipoSelect = document.getElementById("tipo") as HTMLSelectElement | null;
  const vencimentoGroup = document.getElementById("vencimento-group");
  if (tipoSelect && vencimentoGroup) {
    vencimentoGroup.style.display = tipoSelect.value === "despesa_fixa" ? "block" : "none";
  }
}

export function iniciarEdicao(id: number): void {
  const transacao = (state.transacoesAtuais || []).find((t) => t.id === id);
  if (!transacao) return;

  state.idEdicaoPendente = id;

  const tipoEl = document.getElementById("tipo") as HTMLSelectElement | null;
  const valorEl = document.getElementById("valor") as HTMLInputElement | null;
  const catEl = document.getElementById("categoria") as HTMLInputElement | null;
  const dataEl = document.getElementById("data") as HTMLInputElement | null;
  const vencEl = document.getElementById("vencimento") as HTMLInputElement | null;
  const authorEl = document.getElementById("author") as HTMLSelectElement | null;
  const descEl = document.getElementById("descricao") as HTMLInputElement | null;
  const titleText = document.getElementById("form-title-text");
  const btnSubmit = document.getElementById("btn-submit");
  const btnCancel = document.getElementById("btn-cancelar");
  const panel = document.getElementById("panel-form");

  if (tipoEl) tipoEl.value = transacao.tipo;
  if (valorEl) valorEl.value = String(transacao.valor);
  if (catEl) catEl.value = transacao.categoria;
  if (dataEl) dataEl.value = transacao.data;
  if (vencEl) vencEl.value = transacao.vencimento ? String(transacao.vencimento) : "";
  if (authorEl) authorEl.value = transacao.author || "Bruno";
  if (descEl) descEl.value = transacao.descricao || "";

  aoMudarTipo();

  if (titleText) titleText.innerText = `Editar Lançamento #${transacao.id}`;
  if (btnSubmit) btnSubmit.innerText = "Atualizar Lançamento";
  if (btnCancel) btnCancel.style.display = "inline-flex";

  if (panel) {
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

export function cancelarEdicao(): void {
  state.idEdicaoPendente = null;

  const form = document.getElementById("form-transacao") as HTMLFormElement | null;
  if (form) form.reset();

  const titleText = document.getElementById("form-title-text");
  const btnSubmit = document.getElementById("btn-submit");
  const btnCancel = document.getElementById("btn-cancelar");

  if (titleText) titleText.innerText = "Novo Lançamento";
  if (btnSubmit) btnSubmit.innerText = "Salvar Lançamento";
  if (btnCancel) btnCancel.style.display = "none";

  const dataEl = document.getElementById("data") as HTMLInputElement | null;
  if (dataEl) {
    const hoje = new Date().toISOString().split("T")[0];
    dataEl.value = hoje;
  }

  aoMudarTipo();
}

export async function salvarLancamento(onSucesso: (() => void) | null = null): Promise<void> {
  const tipoEl = document.getElementById("tipo") as HTMLSelectElement | null;
  const valorEl = document.getElementById("valor") as HTMLInputElement | null;
  const catEl = document.getElementById("categoria") as HTMLInputElement | null;
  const dataEl = document.getElementById("data") as HTMLInputElement | null;
  const vencEl = document.getElementById("vencimento") as HTMLInputElement | null;
  const authorEl = document.getElementById("author") as HTMLSelectElement | null;
  const descEl = document.getElementById("descricao") as HTMLInputElement | null;

  const tipo = tipoEl?.value || "despesa_variavel";
  const valor = parseFloat(valorEl?.value || "0");
  const categoria = catEl?.value.trim() || "";
  const data = dataEl?.value || "";
  const vencimento = vencEl?.value ? parseInt(vencEl.value, 10) : null;
  const author = authorEl?.value || "Bruno";
  const descricao = descEl?.value.trim() || null;

  if (isNaN(valor) || valor <= 0) {
    alert("Informe um valor numérico válido maior que zero.");
    return;
  }
  if (!categoria) {
    alert("Informe a categoria do lançamento.");
    return;
  }
  if (!data) {
    alert("Informe a data do lançamento.");
    return;
  }

  const payload = {
    tipo,
    valor,
    categoria,
    data,
    vencimento: tipo === "despesa_fixa" ? vencimento : null,
    author,
    descricao,
  };

  const id = state.idEdicaoPendente;
  const url = id ? `${API_BASE}/transactions/${id}` : `${API_BASE}/transactions`;
  const method = id ? "PUT" : "POST";

  try {
    const res = await apiFetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(`Erro ao salvar: ${err.detail || "Verifique os dados informados."}`);
      return;
    }

    cancelarEdicao();
    if (onSucesso) onSucesso();
  } catch (err) {
    console.error("Falha ao salvar lançamento:", err);
    alert("Erro de comunicação ao salvar lançamento.");
  }
}
