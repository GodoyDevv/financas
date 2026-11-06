/**
 * frontend/src/js/state.ts
 *
 * Store reativo simples com subscribe para gerenciamento do estado da aplicação.
 */

import { formatarMesAno } from "./format";
import type { components } from "../api-types";

export type TransactionResponse = components["schemas"]["TransactionResponse"];
export type MetricsResponse = components["schemas"]["MetricsResponse"];

export interface AppState {
  anoAtual: number;
  mesAtual: number;
  mesSelecionado: string;
  modoGeral: boolean;
  anoDropdownAtual: number;
  filtroTipoAtual: string;
  termoBuscaTexto: string;
  transacoesAtuais: TransactionResponse[];
  metricasAtuais: MetricsResponse | null;
  filtrosColuna: {
    data: Set<string>;
    tipo: Set<string>;
    categoria: Set<string>;
    descricao: Set<string>;
    vencimento: Set<string>;
    author: Set<string>;
    channel: Set<string>;
    valor: Set<string>;
  };
  colunaPopoverAtual: string | null;
  idEdicaoPendente: number | null;
  idExclusaoPendente: number | null;
}

const hoje = new Date();
const anoInicial = hoje.getFullYear();
const mesInicial = hoje.getMonth() + 1;

export const state: AppState = {
  anoAtual: anoInicial,
  mesAtual: mesInicial,
  mesSelecionado: formatarMesAno(anoInicial, mesInicial),
  modoGeral: false,
  anoDropdownAtual: anoInicial,
  filtroTipoAtual: "",
  termoBuscaTexto: "",
  transacoesAtuais: [],
  metricasAtuais: null,
  filtrosColuna: {
    data: new Set<string>(),
    tipo: new Set<string>(),
    categoria: new Set<string>(),
    descricao: new Set<string>(),
    vencimento: new Set<string>(),
    author: new Set<string>(),
    channel: new Set<string>(),
    valor: new Set<string>(),
  },
  colunaPopoverAtual: null,
  idEdicaoPendente: null,
  idExclusaoPendente: null,
};

export type Listener = (state: AppState, changedKey?: string | null) => void;
const listeners = new Set<Listener>();

export function subscribe(listener: Listener): () => boolean {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notify(changedKey: string | null = null): void {
  for (const listener of listeners) {
    listener(state, changedKey);
  }
}

export function setState(updater: Partial<AppState> | ((state: AppState) => void)): void {
  if (typeof updater === "function") {
    updater(state);
  } else {
    Object.assign(state, updater);
  }
  notify();
}
