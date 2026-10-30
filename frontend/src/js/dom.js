/**
 * frontend/src/js/dom.js
 *
 * Helpers utilitários de manipulação do DOM e sanitização contra XSS.
 */

export function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export function safeRaw(str) {
  return { __raw: str };
}

export function html(strings, ...values) {
  return strings.reduce((acc, str, i) => {
    const val = values[i - 1];
    let sanitized = '';
    if (val && typeof val === 'object' && val.__raw !== undefined) {
      sanitized = val.__raw;
    } else {
      sanitized = escapeHtml(val);
    }
    return acc + sanitized + str;
  });
}
