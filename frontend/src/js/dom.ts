/**
 * frontend/src/js/dom.ts
 *
 * Helpers utilitários de manipulação do DOM e sanitização contra XSS.
 */

export interface SafeHtml {
  __raw: string;
}

export function escapeHtml(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export function safeRaw(str: string): SafeHtml {
  return { __raw: str };
}

export function html(strings: TemplateStringsArray, ...values: unknown[]): string {
  return strings.reduce((acc, str, i) => {
    const val = values[i - 1];
    let sanitized = "";
    if (val && typeof val === "object" && "__raw" in val) {
      sanitized = (val as SafeHtml).__raw;
    } else {
      sanitized = escapeHtml(val);
    }
    return acc + sanitized + str;
  });
}
