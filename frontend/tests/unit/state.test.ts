import { describe, it, expect, beforeEach } from "vitest";
import { state, setState, subscribe, notify } from "../../src/js/state";

describe("state module", () => {
  beforeEach(() => {
    state.modoGeral = false;
    state.anoAtual = 2026;
    state.mesAtual = 10;
    state.filtroTipoAtual = "";
    state.transacoesAtuais = [];
    state.metricasAtuais = null;
  });

  it("updates state with object partial", () => {
    setState({ modoGeral: true, filtroTipoAtual: "receita" });
    expect(state.modoGeral).toBe(true);
    expect(state.filtroTipoAtual).toBe("receita");
  });

  it("updates state with functional updater", () => {
    setState((s) => {
      s.anoAtual = 2027;
      s.mesAtual = 1;
    });
    expect(state.anoAtual).toBe(2027);
    expect(state.mesAtual).toBe(1);
  });

  it("notifies subscribers when state changes", () => {
    let callCount = 0;
    let receivedState = null;

    const unsubscribe = subscribe((s) => {
      callCount++;
      receivedState = s;
    });

    setState({ modoGeral: true });
    expect(callCount).toBe(1);
    expect(receivedState).toBe(state);

    notify("customKey");
    expect(callCount).toBe(2);

    unsubscribe();
    setState({ modoGeral: false });
    expect(callCount).toBe(2); // No new invocation after unsubscribe
  });
});
