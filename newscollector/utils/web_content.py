"""Helpers to fetch and sanitize web content for AI prompts."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

from newscollector.utils.http_client import create_client


class _TextExtractor(HTMLParser):
    """Extract visible text while skipping script/style/noscript blocks."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        return " ".join(self._chunks)


def is_http_url(url: str | None) -> bool:
    """Return True for http(s) URL values."""
    if not url:
        return False
    lower = url.strip().lower()
    return lower.startswith("http://") or lower.startswith("https://")


def html_to_text(html: str, *, char_limit: int = 15000) -> str:
    """Convert HTML to compact plain text suitable for AI input."""
    raw = html or ""
    extractor = _TextExtractor()
    extractor.feed(raw)
    text = extractor.text()
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if char_limit > 0 and len(text) > char_limit:
        return text[:char_limit]
    return text


def truncate_text(text: str, *, char_limit: int) -> str:
    """Trim text to a configured character budget."""
    if char_limit <= 0:
        return text
    if len(text) <= char_limit:
        return text
    return text[:char_limit]


async def fetch_html(
    url: str, *, timeout: float = 25.0, char_limit: int = 200000
) -> str | None:
    """Fetch raw HTML from URL. Returns None on errors."""
    if not is_http_url(url):
        return None
    try:
        async with create_client(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text or ""
    except Exception:
        return None

    if char_limit > 0 and len(html) > char_limit:
        return html[:char_limit]
    return html


async def fetch_page_text(
    url: str,
    *,
    timeout: float = 25.0,
    html_char_limit: int = 200000,
    text_char_limit: int = 12000,
) -> str | None:
    """Fetch URL then convert HTML into plain text."""
    html = await fetch_html(url, timeout=timeout, char_limit=html_char_limit)
    if not html:
        return None
    text = html_to_text(html, char_limit=text_char_limit)
    if not text:
        return None
    return text
