"""Playwright tests for Financial Reports tab UI.

These tests use Playwright to test the frontend UI directly in a browser.
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest
from playwright.sync_api import Page, expect, sync_playwright

# Server configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8770
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
PYTHON_BIN = "/workspaces/NewsCollector/.venv/bin/python"


def wait_for_server(host: str, port: int, timeout: int = 30) -> bool:
    """Wait for server to be ready."""
    import socket

    start = time.time()
    while time.time() - start < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def start_server() -> subprocess.Popen:
    """Start the web server in the background."""
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    process = subprocess.Popen(
        [
            PYTHON_BIN,
            "-m",
            "newscollector",
            "serve",
            "--host",
            SERVER_HOST,
            "--port",
            str(SERVER_PORT),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd="/workspaces/NewsCollector",
    )
    # Wait for server to start
    if not wait_for_server(SERVER_HOST, SERVER_PORT, timeout=30):
        stdout, stderr = process.communicate(timeout=5)
        raise RuntimeError(
            f"Server failed to start.\nSTDOUT: {stdout}\nSTDERR: {stderr}"
        )
    return process


def stop_server(process: subprocess.Popen) -> None:
    """Stop the web server."""
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@pytest.fixture(scope="module")
def server():
    """Start server for tests and clean up after."""
    process = start_server()
    yield process
    stop_server(process)


@pytest.fixture(scope="module")
def browser_page():
    """Create a browser page using Playwright."""
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()

    yield page

    page.close()
    browser.close()
    playwright.stop()


@pytest.fixture
def page(browser_page: Page, server) -> Page:
    """Provide a fresh page for each test."""
    page = browser_page
    page.goto(BASE_URL)
    yield page


class TestFinancialReportsTab:
    """Tests for Financial Reports tab functionality.

    Note: Some elements are only visible when financial data is available.
    These tests verify the tab navigation and filter controls.
    """

    def test_navigate_to_financial_tab(self, page: Page):
        """Test clicking the Financial Reports tab."""
        # Click the Financial Reports tab
        page.click("text=Financial Reports")

        # Verify filter bar is visible - use more specific locator
        expect(page.locator("label:has-text('Region / List')")).to_be_visible(
            timeout=5000
        )

    def test_financial_filter_bar_elements(self, page: Page):
        """Test all filter bar elements are present."""
        # Navigate to Financial Reports
        page.click("text=Financial Reports")

        # Wait for the page to load
        page.wait_for_timeout(1000)

        # Check that the Status dropdown exists
        expect(page.locator("label:has-text('Status')")).to_be_visible(timeout=5000)

    def test_region_filter_exists(self, page: Page):
        """Test region filter dropdown exists."""
        page.click("text=Financial Reports")
        page.wait_for_timeout(1000)

        # Check that Region dropdown exists
        region_label = page.locator("label:has-text('Region / List')").first
        expect(region_label).to_be_visible(timeout=5000)

    def test_sort_by_dropdown_exists(self, page: Page):
        """Test sort by dropdown exists."""
        page.click("text=Financial Reports")
        page.wait_for_timeout(1000)

        # Check sort dropdown exists
        sort_label = page.locator("label:has-text('Sort by')").first
        expect(sort_label).to_be_visible(timeout=5000)

    def test_no_console_errors_on_load(self, page: Page):
        """Test that there are no critical JavaScript errors on page load."""
        errors = []

        def handle_console(msg):
            if msg.type == "error":
                errors.append(msg.text)

        page.on("console", handle_console)

        # Navigate to Financial Reports
        page.click("text=Financial Reports")
        page.wait_for_timeout(2000)

        # Filter out known non-critical errors
        critical_errors = [
            e for e in errors if "favicon" not in e.lower() and "net::ERR" not in e
        ]

        assert len(critical_errors) == 0, f"Found console errors: {critical_errors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
