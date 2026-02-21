"""Tests for newscollector.utils.http_client."""

from __future__ import annotations

import httpx

from newscollector.utils.http_client import DEFAULT_HEADERS, create_client


class TestCreateClient:
    def test_returns_async_client(self):
        client = create_client()
        assert isinstance(client, httpx.AsyncClient)

    def test_default_headers_applied(self):
        client = create_client()
        for key, value in DEFAULT_HEADERS.items():
            assert client.headers.get(key) == value

    def test_custom_headers_merged(self):
        custom = {"X-Custom": "test-value"}
        client = create_client(headers=custom)
        assert client.headers.get("X-Custom") == "test-value"
        assert client.headers.get("User-Agent") == DEFAULT_HEADERS["User-Agent"]

    def test_follow_redirects(self):
        client = create_client(follow_redirects=True)
        assert client.follow_redirects is True

    def test_no_follow_redirects(self):
        client = create_client(follow_redirects=False)
        assert client.follow_redirects is False
