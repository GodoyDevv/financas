/**
 * frontend/src/js/format.js
 *
 * Funções utilitárias de formatação monetária (BRL), datas (pt-BR)
 * e rótulos de domínio.
 */

const brlFormatter = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
});

export function formatBRL(valor) {
  if (valor === null || valor === undefined || isNaN(Number(valor))) return 'R$ 0,00';
  return brlFormatter.format(Number(valor));
}

export function formatDateBR(dateStr) {
  if (!dateStr) return '-';
  const parts = String(dateStr).split('T')[0].split('-');
  if (parts.length === 3) {
    return `${parts[2]}/${parts[1]}/${parts[0]}`;
  }
  return dateStr;
}

export function formatarMesAno(ano, mes) {
  return `${ano}-${String(mes).padStart(2, '0')}`;
}

export function formatChannelLabel(ch) {
  if (!ch) return 'Dashboard';
  const map = {
    'whatsapp_text': 'WhatsApp Texto',
    'whatsapp_audio': 'WhatsApp Áudio',
    'dashboard': 'Dashboard Web',
    'api': 'API Externa',
    'system': 'Automático / Sistema',
    'unknown': 'Não especificado',
  };
  return map[ch] || ch;
}

export function badgeTipo(tipo) {
  const map = {
    'receita': { text: 'Receita', class: 'badge-receita' },
    'despesa_fixa': { text: 'Despesa Fixa', class: 'badge-fixa' },
    'despesa_variavel': { text: 'Gasto Variável', class: 'badge-variavel' },
  };
  return map[tipo] || { text: tipo || 'Outro', class: 'badge-fixa' };
}

export function classValor(tipo) {
  return tipo === 'receita' ? 'valor-receita' : 'valor-despesa';
}

export function sinalValor(tipo) {
  return tipo === 'receita' ? '+' : '-';
}

export function normalizarNomePessoa(source) {
  if (!source) return 'Outro';
  const s = String(source).trim();
  if (/^bruno\b/i.test(s)) return 'Bruno';
  if (/^let[ií]cia\b/i.test(s)) return 'Letícia';
  return s;
}
