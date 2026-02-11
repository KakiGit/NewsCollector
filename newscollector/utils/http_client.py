"""Shared async HTTP client with sensible defaults."""

from __future__ import annotations

import httpx

# Common browser-like headers to reduce chance of being blocked
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def create_client(
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient with retry-friendly defaults.

    The caller is responsible for closing the client (use as async context manager).
    """
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    transport = httpx.AsyncHTTPTransport(retries=2)
    return httpx.AsyncClient(
        headers=merged_headers,
        timeout=httpx.Timeout(timeout),
        follow_redirects=follow_redirects,
        transport=transport,
    )
