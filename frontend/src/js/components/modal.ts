/**
 * frontend/src/js/components/modal.ts
 *
 * Gerenciamento do modal de exclusão inteligente de compras parceladas / itens únicos.
 */

import { state, type TransactionResponse } from "../state";
import { apiFetch, API_BASE } from "../api";
import { formatBRL } from "../format";

export function abrirModalExclusao(transacao: TransactionResponse): void {
  state.idExclusaoPendente = transacao.id;
  const overlay = document.getElementById("delete-modal-overlay");
  const title = document.getElementById("delete-modal-title");
  const desc = document.getElementById("delete-modal-desc");
  const btnSingle = document.getElementById("btn-confirm-delete-single");
  const btnFuture = document.getElementById("btn-confirm-delete-future");
  const btnAll = document.getElementById("btn-confirm-delete-all");
  const lblSingle = document.getElementById("label-delete-single");

  const isParcelado = !!(
    transacao.parcela_grupo_id ||
    (transacao.parcela_num && transacao.parcela_total)
  );
  const pNum = transacao.parcela_num || 1;
  const pTot = transacao.parcela_total || 1;

  if (isParcelado) {
    if (title) title.innerText = "Excluir Lançamento Parcelado";
    if (desc) {
      desc.innerHTML = `
        O lançamento <strong>${transacao.descricao || "Sem descrição"}</strong> é a parcela
        <strong>${pNum}/${pTot} de ${formatBRL(transacao.valor)}</strong>.<br>
        Como deseja proceder com a exclusão?
      `;
    }
    if (lblSingle) lblSingle.innerText = `Apenas a parcela ${pNum}/${pTot}`;
    if (btnSingle) btnSingle.style.display = "flex";
    if (btnFuture) btnFuture.style.display = "flex";
    if (btnAll) btnAll.style.display = "flex";
  } else {
    if (title) title.innerText = "Confirmar Exclusão";
    if (desc) {
      desc.innerHTML = `
        Tem certeza de que deseja excluir permanentemente o lançamento
        <strong>${transacao.descricao || transacao.categoria}</strong> no valor de
        <strong>${formatBRL(transacao.valor)}</strong>?
      `;
    }
    if (lblSingle) lblSingle.innerText = "Sim, excluir lançamento";
    if (btnSingle) btnSingle.style.display = "flex";
    if (btnFuture) btnFuture.style.display = "none";
    if (btnAll) btnAll.style.display = "none";
  }

  if (overlay) overlay.classList.add("active");
}

export function fecharModalExclusao(): void {
  state.idExclusaoPendente = null;
  const overlay = document.getElementById("delete-modal-overlay");
  if (overlay) overlay.classList.remove("active");
}

export async function executarExclusao(
  escopo: string = "uma",
  onSucesso: (() => void) | null = null
): Promise<void> {
  if (!state.idExclusaoPendente) return;
  const id = state.idExclusaoPendente;
  fecharModalExclusao();

  try {
    const res = await apiFetch(`${API_BASE}/transactions/${id}?escopo=${escopo}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(`Erro ao excluir: ${err.detail || "Não foi possível excluir o lançamento."}`);
      return;
    }
    if (onSucesso) onSucesso();
  } catch (e) {
    console.error("Falha ao excluir lançamento:", e);
    alert("Erro de conexão ao tentar excluir.");
  }
}
