"""Tests for newscollector.utils.web_content."""

from __future__ import annotations

from newscollector.utils.web_content import html_to_text, is_http_url, truncate_text


class TestIsHttpUrl:
    def test_http(self):
        assert is_http_url("http://example.com") is True

    def test_https(self):
        assert is_http_url("https://example.com") is True

    def test_ftp_returns_false(self):
        assert is_http_url("ftp://example.com") is False

    def test_empty(self):
        assert is_http_url("") is False

    def test_none(self):
        assert is_http_url(None) is False

    def test_whitespace(self):
        assert is_http_url("  https://example.com  ") is True

    def test_case_insensitive(self):
        assert is_http_url("HTTPS://EXAMPLE.COM") is True


class TestHtmlToText:
    def test_strips_tags(self):
        html = "<p>Hello <b>world</b></p>"
        text = html_to_text(html)
        assert "Hello" in text
        assert "world" in text
        assert "<p>" not in text

    def test_strips_scripts(self):
        html = "<p>Visible</p><script>var x = 1;</script><p>Also visible</p>"
        text = html_to_text(html)
        assert "Visible" in text
        assert "Also visible" in text
        assert "var x" not in text

    def test_strips_styles(self):
        html = "<style>body{color:red}</style><p>Content</p>"
        text = html_to_text(html)
        assert "Content" in text
        assert "color:red" not in text

    def test_char_limit(self):
        html = "<p>" + "A" * 200 + "</p>"
        text = html_to_text(html, char_limit=50)
        assert len(text) <= 50

    def test_empty_html(self):
        assert html_to_text("") == ""

    def test_collapses_whitespace(self):
        html = "<p>Hello    world</p>"
        text = html_to_text(html)
        assert "  " not in text


class TestTruncateText:
    def test_under_limit(self):
        assert truncate_text("short", char_limit=100) == "short"

    def test_at_limit(self):
        text = "x" * 10
        assert truncate_text(text, char_limit=10) == text

    def test_over_limit(self):
        text = "x" * 20
        result = truncate_text(text, char_limit=10)
        assert len(result) == 10

    def test_zero_limit_returns_original(self):
        assert truncate_text("hello", char_limit=0) == "hello"
