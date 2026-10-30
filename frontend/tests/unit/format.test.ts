import { describe, it, expect } from "vitest";
import {
  formatBRL,
  formatDateBR,
  formatarMesAno,
  formatChannelLabel,
  badgeTipo,
  classValor,
  sinalValor,
  normalizarNomePessoa,
} from "../../src/js/format";

describe("format module", () => {
  describe("formatBRL", () => {
    it("formats standard numbers to BRL currency", () => {
      const formatted = formatBRL(1234.56).replace(/\s/g, " ");
      expect(formatted).toMatch(/R\$\s?1\.234,56/);
    });

    it("handles null, undefined and invalid numbers safely", () => {
      expect(formatBRL(null)).toMatch(/R\$\s?0,00/);
      expect(formatBRL(undefined)).toMatch(/R\$\s?0,00/);
      expect(formatBRL("abc")).toMatch(/R\$\s?0,00/);
    });
  });

  describe("formatDateBR", () => {
    it("converts YYYY-MM-DD to DD/MM/YYYY", () => {
      expect(formatDateBR("2026-10-30")).toBe("30/10/2026");
      expect(formatDateBR("2026-05-01T14:30:00Z")).toBe("01/05/2026");
    });

    it("returns '-' for empty date inputs", () => {
      expect(formatDateBR(null)).toBe("-");
      expect(formatDateBR("")).toBe("-");
    });
  });

  describe("formatarMesAno", () => {
    it("formats month and year with zero-padding", () => {
      expect(formatarMesAno(2026, 5)).toBe("2026-05");
      expect(formatarMesAno(2026, 12)).toBe("2026-12");
    });
  });

  describe("formatChannelLabel", () => {
    it("maps known channels to human readable strings", () => {
      expect(formatChannelLabel("whatsapp_text")).toBe("WhatsApp Texto");
      expect(formatChannelLabel("whatsapp_audio")).toBe("WhatsApp Áudio");
      expect(formatChannelLabel("dashboard")).toBe("Dashboard Web");
      expect(formatChannelLabel(null)).toBe("Dashboard");
    });
  });

  describe("badgeTipo, classValor, sinalValor", () => {
    it("returns correct badges and signs for receita", () => {
      expect(badgeTipo("receita")).toEqual({ text: "Receita", class: "badge-receita" });
      expect(classValor("receita")).toBe("valor-receita");
      expect(sinalValor("receita")).toBe("+");
    });

    it("returns correct badges and signs for despesas", () => {
      expect(badgeTipo("despesa_fixa")).toEqual({ text: "Despesa Fixa", class: "badge-fixa" });
      expect(badgeTipo("despesa_variavel")).toEqual({
        text: "Gasto Variável",
        class: "badge-variavel",
      });
      expect(classValor("despesa_fixa")).toBe("valor-despesa");
      expect(sinalValor("despesa_fixa")).toBe("-");
    });
  });

  describe("normalizarNomePessoa", () => {
    it("normalizes known couple names", () => {
      expect(normalizarNomePessoa("Bruno Godoy")).toBe("Bruno");
      expect(normalizarNomePessoa("leticia")).toBe("Letícia");
      expect(normalizarNomePessoa("Leticia Silva")).toBe("Letícia");
      expect(normalizarNomePessoa(null)).toBe("Outro");
    });
  });
});
