import { describe, it, expect } from "vitest";
import { escapeHtml, safeRaw, html } from "../../src/js/dom";

describe("dom module - XSS sanitization and html template", () => {
  describe("escapeHtml", () => {
    it("escapes all dangerous HTML characters", () => {
      const dangerous = '<script>alert("XSS & \'attack\'")</script>';
      const sanitized = escapeHtml(dangerous);
      expect(sanitized).toBe(
        "&lt;script&gt;alert(&quot;XSS &amp; &#039;attack&#039;&quot;)&lt;/script&gt;"
      );
    });

    it("handles null and undefined safely", () => {
      expect(escapeHtml(null)).toBe("");
      expect(escapeHtml(undefined)).toBe("");
    });

    it("converts non-string primitives safely", () => {
      expect(escapeHtml(12345)).toBe("12345");
      expect(escapeHtml(false)).toBe("false");
    });
  });

  describe("html tagged template", () => {
    it("automatically escapes interpolated string values", () => {
      const userInput = "<img src=x onerror=alert(1)>";
      const result = html`<div class="user">${userInput}</div>`;
      expect(result).toBe('<div class="user">&lt;img src=x onerror=alert(1)&gt;</div>');
    });

    it("respects safeRaw bypass only when explicitly marked", () => {
      const rawTrustedBadge = safeRaw('<span class="badge">OK</span>');
      const untrustedDesc = "<script>evil()</script>";
      const result = html`<div>${rawTrustedBadge} - ${untrustedDesc}</div>`;
      expect(result).toBe(
        '<div><span class="badge">OK</span> - &lt;script&gt;evil()&lt;/script&gt;</div>'
      );
    });
  });
});
