/**
 * frontend/src/js/state.js
 *
 * Store reativo simples com subscribe para gerenciamento do estado da aplicação.
 */

import { formatarMesAno } from './format.js';

const hoje = new Date();
const anoInicial = hoje.getFullYear();
const mesInicial = hoje.getMonth() + 1;

export const state = {
  anoAtual: anoInicial,
  mesAtual: mesInicial,
  mesSelecionado: formatarMesAno(anoInicial, mesInicial),
  modoGeral: false,
  anoDropdownAtual: anoInicial,
  filtroTipoAtual: '',
  transacoesAtuais: [],
  metricasAtuais: null,
  filtrosColuna: {
    data: new Set(),
    tipo: new Set(),
    categoria: new Set(),
    descricao: new Set(),
    vencimento: new Set(),
    author: new Set(),
    channel: new Set(),
    valor: new Set(),
  },
  colunaPopoverAtual: null,
  idEdicaoPendente: null,
  idExclusaoPendente: null,
};

const listeners = new Set();

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notify(changedKey = null) {
  for (const listener of listeners) {
    listener(state, changedKey);
  }
}

export function setState(updater) {
  if (typeof updater === 'function') {
    updater(state);
  } else {
    Object.assign(state, updater);
  }
  notify();
}
