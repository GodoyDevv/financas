"""
Teste unitário de segurança frontend e validação de escapeHtml contra XSS.
Executa os casos de teste do escapeHtml e do backend schemas.
"""

import re
import pytest
from pydantic import ValidationError
from backend.schemas import TransactionCreate, sanitize_text

def js_escape_html(value):
    """Implementação idêntica à função escapeHtml presente em index.html."""
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
        .replace("`", "&#96;")
    )

class TestEscapeHtml:
    def test_null_and_undefined_and_numbers(self):
        assert js_escape_html(None) == ""
        assert js_escape_html("") == ""
        assert js_escape_html(123) == "123"
        assert js_escape_html(0) == "0"
        assert js_escape_html(45.67) == "45.67"

    def test_xss_payload_img_onerror(self):
        payload = "<img src=x onerror=alert(1)>"
        escaped = js_escape_html(payload)
        assert "<" not in escaped
        assert ">" not in escaped
        assert escaped == "&lt;img src=x onerror=alert(1)&gt;"

    def test_xss_payload_svg_onload(self):
        payload = '"><svg onload=alert(1)>'
        escaped = js_escape_html(payload)
        assert '"' not in escaped
        assert "<" not in escaped
        assert ">" not in escaped
        assert escaped == "&quot;&gt;&lt;svg onload=alert(1)&gt;"

    def test_xss_payload_quote_breakout(self):
        payload = "'); alert(1);//"
        escaped = js_escape_html(payload)
        assert "'" not in escaped
        assert escaped == "&#39;); alert(1);//"

    def test_xss_payload_script_tags(self):
        payload = "</script><script>alert(1)</script>"
        escaped = js_escape_html(payload)
        assert "<" not in escaped
        assert ">" not in escaped
        assert escaped == "&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;"

    def test_xss_backtick_interpolation(self):
        payload = "`${alert(1)}`"
        escaped = js_escape_html(payload)
        assert "`" not in escaped
        assert escaped == "&#96;${alert(1)}&#96;"


class TestBackendSchemasValidation:
    def test_valid_transaction(self):
        tx = TransactionCreate(
            tipo="despesa_variavel",
            valor=50.0,
            categoria="Alimentação",
            data="2026-10-23",
            descricao="Lanche",
            source="Bruno"
        )
        assert tx.tipo == "despesa_variavel"
        assert tx.valor == 50.0

    def test_invalid_tipo_rejected(self):
        with pytest.raises(ValidationError):
            TransactionCreate(
                tipo="tipo_invalido",
                valor=50.0,
                categoria="Teste",
                data="2026-10-23"
            )

    def test_invalid_valor_zero_or_negative(self):
        with pytest.raises(ValidationError):
            TransactionCreate(
                tipo="receita",
                valor=0.0,
                categoria="Salário",
                data="2026-10-23"
            )

    def test_invalid_valor_exceeds_million(self):
        with pytest.raises(ValidationError):
            TransactionCreate(
                tipo="receita",
                valor=1_000_000.01,
                categoria="Salário",
                data="2026-10-23"
            )

    def test_lengths_exceeded(self):
        with pytest.raises(ValidationError):
            TransactionCreate(
                tipo="despesa_variavel",
                valor=10.0,
                categoria="C" * 61,
                data="2026-10-23"
            )

        with pytest.raises(ValidationError):
            TransactionCreate(
                tipo="despesa_variavel",
                valor=10.0,
                categoria="Alimentação",
                descricao="D" * 201,
                data="2026-10-23"
            )

    def test_sanitize_control_chars(self):
        cleaned = sanitize_text("Descricao\x00com\x1Fcontrole")
        assert cleaned == "Descricaocomcontrole"
