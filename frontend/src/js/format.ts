/**
 * frontend/src/js/format.ts
 *
 * Funções utilitárias de formatação monetária (BRL), datas (pt-BR)
 * e rótulos de domínio.
 */

const brlFormatter = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});

export function formatBRL(valor: unknown): string {
  if (valor === null || valor === undefined || isNaN(Number(valor))) return "R$ 0,00";
  return brlFormatter.format(Number(valor));
}

export function formatDateBR(dateStr: unknown): string {
  if (!dateStr) return "-";
  const parts = String(dateStr).split("T")[0].split("-");
  if (parts.length === 3) {
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
  }
  return String(dateStr);
}

export function formatarMesAno(ano: number, mes: number): string {
  return `${ano}-${String(mes).padStart(2, "0")}`;
}

export function formatChannelLabel(ch: string | null | undefined): string {
  if (!ch) return "Dashboard";
  const map: Record<string, string> = {
    whatsapp_text: "WhatsApp Texto",
    whatsapp_audio: "WhatsApp Áudio",
    dashboard: "Dashboard Web",
    api: "API Externa",
    system: "Automático / Sistema",
    unknown: "Não especificado",
  };
  return map[ch] || ch;
}

export interface BadgeInfo {
  text: string;
  class: string;
}

export function badgeTipo(tipo: string | null | undefined): BadgeInfo {
  const map: Record<string, BadgeInfo> = {
    receita: { text: "Receita", class: "badge-receita" },
    despesa_fixa: { text: "Despesa Fixa", class: "badge-fixa" },
    despesa_variavel: { text: "Gasto Variável", class: "badge-variavel" },
  };
  return (tipo && map[tipo]) || { text: tipo || "Outro", class: "badge-fixa" };
}

export function classValor(tipo: string | null | undefined): string {
  return tipo === "receita" ? "valor-receita" : "valor-despesa";
}

export function sinalValor(tipo: string | null | undefined): string {
  return tipo === "receita" ? "+" : "-";
}

export function normalizarNomePessoa(source: unknown): string {
  if (!source) return "Outro";
  const s = String(source).trim();
  if (/^bruno\b/i.test(s)) return "Bruno";
  if (/^let[ií]cia\b/i.test(s)) return "Letícia";
  return s;
}
