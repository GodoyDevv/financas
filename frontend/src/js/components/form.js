/**
 * frontend/src/js/components/form.js
 *
 * Gerenciamento do formulário de criação e edição de lançamentos financeiros.
 */

import { state } from '../state.js';
import { apiFetch, API_BASE } from '../api.js';

export function aoMudarTipo() {
  const tipoSelect = document.getElementById('tipo');
  const vencimentoGroup = document.getElementById('vencimento-group');
  if (tipoSelect && vencimentoGroup) {
    vencimentoGroup.style.display = tipoSelect.value === 'despesa_fixa' ? 'block' : 'none';
  }
}

export function iniciarEdicao(id) {
  const transacao = (state.transacoesAtuais || []).find(t => t.id === id);
  if (!transacao) return;

  state.idEdicaoPendente = id;

  const tipoEl = document.getElementById('tipo');
  const valorEl = document.getElementById('valor');
  const catEl = document.getElementById('categoria');
  const dataEl = document.getElementById('data');
  const vencEl = document.getElementById('vencimento');
  const authorEl = document.getElementById('author');
  const descEl = document.getElementById('descricao');
  const titleText = document.getElementById('form-title-text');
  const btnSubmit = document.getElementById('btn-submit');
  const btnCancel = document.getElementById('btn-cancelar');
  const panel = document.getElementById('panel-form');

  if (tipoEl) tipoEl.value = transacao.tipo;
  if (valorEl) valorEl.value = transacao.valor;
  if (catEl) catEl.value = transacao.categoria;
  if (dataEl) dataEl.value = transacao.data;
  if (vencEl) vencEl.value = transacao.vencimento || '';
  if (authorEl) authorEl.value = transacao.author || 'Bruno';
  if (descEl) descEl.value = transacao.descricao || '';

  aoMudarTipo();

  if (titleText) titleText.innerText = `Editar Lançamento #${transacao.id}`;
  if (btnSubmit) btnSubmit.innerText = 'Atualizar Lançamento';
  if (btnCancel) btnCancel.style.display = 'inline-flex';

  if (panel) {
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    panel.style.borderColor = 'var(--border-focus)';
  }
}

export function cancelarEdicao() {
  state.idEdicaoPendente = null;

  const form = document.getElementById('form-transacao');
  if (form) form.reset();

  const titleText = document.getElementById('form-title-text');
  const btnSubmit = document.getElementById('btn-submit');
  const btnCancel = document.getElementById('btn-cancelar');
  const dataEl = document.getElementById('data');
  const panel = document.getElementById('panel-form');

  if (titleText) titleText.innerText = 'Cadastrar Lançamento Doméstico';
  if (btnSubmit) btnSubmit.innerText = 'Salvar';
  if (btnCancel) btnCancel.style.display = 'none';
  if (dataEl) dataEl.value = new Date().toISOString().split('T')[0];

  aoMudarTipo();
  if (panel) panel.style.borderColor = 'var(--border-subtle)';
}

export async function salvarTransacao(event, onSucesso = null) {
  event.preventDefault();

  const payload = {
    tipo: document.getElementById('tipo').value,
    valor: parseFloat(document.getElementById('valor').value),
    categoria: document.getElementById('categoria').value,
    data: document.getElementById('data').value,
    vencimento: document.getElementById('vencimento').value || null,
    author: document.getElementById('author').value || null,
    descricao: document.getElementById('descricao').value || null,
  };

  try {
    let res;
    if (state.idEdicaoPendente) {
      res = await apiFetch(`${API_BASE}/transactions/${state.idEdicaoPendente}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } else {
      res = await apiFetch(`${API_BASE}/transactions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    }

    if (res.ok) {
      cancelarEdicao();
      if (onSucesso) onSucesso();
    } else {
      const errData = await res.json().catch(() => ({}));
      alert(`Erro ao salvar lançamento: ${errData.detail || 'Verifique os dados informados'}`);
    }
  } catch (err) {
    console.error('Falha ao submeter lançamento:', err);
    alert('Erro de conexão ao salvar lançamento.');
  }
}
