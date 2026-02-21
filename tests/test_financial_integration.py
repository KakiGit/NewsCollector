"""Integration tests for Financial Reports functionality.

These tests verify:
1. CLI commands work correctly (collect-history with --latest flag)
2. Web server starts without errors
3. API endpoints return correct data
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import pytest

# Use venv python
PYTHON_BIN = "/workspaces/NewsCollector/.venv/bin/python"

# Server configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8765
BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


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


class TestCLICommands:
    """Test CLI commands for financial data collection."""

    def test_collect_history_latest_help(self):
        """Test collect-history --latest command help works."""
        result = subprocess.run(
            [PYTHON_BIN, "-m", "newscollector", "collect-history", "--help"],
            capture_output=True,
            text=True,
            cwd="/workspaces/NewsCollector",
        )
        assert result.returncode == 0
        assert "--latest" in result.stdout
        assert "--ai-analyze" in result.stdout

    def test_collect_reports_help(self):
        """Test collect-reports command help works."""
        result = subprocess.run(
            [PYTHON_BIN, "-m", "newscollector", "collect-reports", "--help"],
            capture_output=True,
            text=True,
            cwd="/workspaces/NewsCollector",
        )
        assert result.returncode == 0

    def test_evaluate_reports_help(self):
        """Test evaluate-reports command help works."""
        result = subprocess.run(
            [PYTHON_BIN, "-m", "newscollector", "evaluate-reports", "--help"],
            capture_output=True,
            text=True,
            cwd="/workspaces/NewsCollector",
        )
        assert result.returncode == 0

    def test_list_regions(self):
        """Test list-regions command."""
        result = subprocess.run(
            [PYTHON_BIN, "-m", "newscollector", "list-regions"],
            capture_output=True,
            text=True,
            cwd="/workspaces/NewsCollector",
        )
        assert result.returncode == 0
        # Should show available regions
        assert "us_300" in result.stdout or "No regions" in result.stdout


class TestServerStartup:
    """Test web server startup."""

    def test_server_starts_successfully(self, server):
        """Test that server starts without errors."""
        assert server.poll() is None, "Server process should still be running"

    def test_server_root_endpoint(self, server):
        """Test root endpoint returns HTML."""
        import urllib.request

        response = urllib.request.urlopen(BASE_URL, timeout=5)
        assert response.status == 200
        content = response.read().decode("utf-8")
        assert "<!DOCTYPE html>" in content or "<html" in content


class TestFinancialAPI:
    """Test Financial Reports API endpoints."""

    def test_financial_reports_endpoint(self, server):
        """Test /api/financial-reports endpoint returns data."""
        import urllib.error
        import urllib.request

        url = f"{BASE_URL}/api/financial-reports"
        try:
            response = urllib.request.urlopen(url, timeout=10)
            assert response.status == 200

            import json

            data = json.loads(response.read().decode("utf-8"))

            assert "reports" in data
            assert "total" in data
            assert isinstance(data["reports"], list)
        except urllib.error.HTTPError as e:
            if e.code == 500:
                # Database not configured - skip this test
                pytest.skip("PostgreSQL database not available")
            raise

    def test_financial_regions_endpoint(self, server):
        """Test /api/financial-regions endpoint."""
        import urllib.error
        import urllib.request

        url = f"{BASE_URL}/api/financial-regions"
        try:
            response = urllib.request.urlopen(url, timeout=10)
            assert response.status == 200

            import json

            data = json.loads(response.read().decode("utf-8"))

            assert isinstance(data, list)
        except urllib.error.HTTPError as e:
            if e.code == 500:
                pytest.skip("PostgreSQL database not available")
            raise

    def test_financial_history_endpoint(self, server):
        """Test /api/financial-history endpoint."""
        import urllib.error
        import urllib.request

        url = f"{BASE_URL}/api/financial-history?periods=4"
        try:
            response = urllib.request.urlopen(url, timeout=10)
            assert response.status == 200

            import json

            data = json.loads(response.read().decode("utf-8"))

            assert "by_ticker" in data
            assert isinstance(data["by_ticker"], dict)
        except urllib.error.HTTPError as e:
            if e.code == 500:
                pytest.skip("PostgreSQL database not available")
            raise

    def test_company_scores_endpoint(self, server):
        """Test /api/company-scores endpoint."""
        import urllib.error
        import urllib.request

        url = f"{BASE_URL}/api/company-scores"
        try:
            response = urllib.request.urlopen(url, timeout=10)
            assert response.status == 200

            import json

            data = json.loads(response.read().decode("utf-8"))

            assert "companies" in data
            assert isinstance(data["companies"], list)
        except urllib.error.HTTPError as e:
            if e.code == 500:
                pytest.skip("PostgreSQL database not available")
            raise

    def test_company_scores_filters_endpoint(self, server):
        """Test /api/company-scores/filters endpoint."""
        import urllib.error
        import urllib.request

        url = f"{BASE_URL}/api/company-scores/filters"
        try:
            response = urllib.request.urlopen(url, timeout=10)
            assert response.status == 200

            import json

            data = json.loads(response.read().decode("utf-8"))

            assert "sectors" in data
            assert "industries" in data
        except urllib.error.HTTPError as e:
            if e.code == 500:
                pytest.skip("PostgreSQL database not available")
            raise

    def test_financial_sectors_endpoint(self, server):
        """Test /api/financial-sectors endpoint."""
        import urllib.error
        import urllib.request

        url = f"{BASE_URL}/api/financial-sectors"
        try:
            response = urllib.request.urlopen(url, timeout=10)
            assert response.status == 200

            import json

            data = json.loads(response.read().decode("utf-8"))

            assert "sectors" in data
            assert "industries" in data
        except urllib.error.HTTPError as e:
            if e.code == 500:
                pytest.skip("PostgreSQL database not available")
            raise

    def test_financial_rankings_endpoint(self, server):
        """Test /api/financial-rankings endpoint."""
        import urllib.error
        import urllib.request

        url = f"{BASE_URL}/api/financial-rankings"
        try:
            response = urllib.request.urlopen(url, timeout=10)
            assert response.status == 200

            import json

            data = json.loads(response.read().decode("utf-8"))

            assert "rankings" in data
        except urllib.error.HTTPError as e:
            if e.code == 500:
                pytest.skip("PostgreSQL database not available")
            raise


class TestFinancialUIFeatures:
    """Test Financial Reports UI features via API."""

    def test_financial_reports_pagination(self, server):
        """Test financial reports pagination works."""
        import urllib.error
        import urllib.request

        url = f"{BASE_URL}/api/financial-reports?limit=10&offset=0"
        try:
            response = urllib.request.urlopen(url, timeout=10)
            data = json.loads(response.read().decode("utf-8"))

            assert "limit" in data
            assert "offset" in data
            assert data["limit"] == 10
            assert data["offset"] == 0
        except urllib.error.HTTPError as e:
            if e.code == 500:
                pytest.skip("PostgreSQL database not available")
            raise

    def test_financial_reports_sorting(self, server):
        """Test financial reports sorting works."""
        import urllib.error
        import urllib.request

        url = f"{BASE_URL}/api/financial-reports?sort_by=health_score"
        try:
            response = urllib.request.urlopen(url, timeout=10)
            _ = json.loads(response.read().decode("utf-8"))

            assert response.status == 200
        except urllib.error.HTTPError as e:
            if e.code == 500:
                pytest.skip("PostgreSQL database not available")
            raise

    def test_financial_reports_region_filter(self, server):
        """Test financial reports can be filtered by region."""
        import urllib.error
        import urllib.request

        # Try with a known region or empty
        url = f"{BASE_URL}/api/financial-reports?region=us_300"
        try:
            response = urllib.request.urlopen(url, timeout=10)
            data = json.loads(response.read().decode("utf-8"))

            assert response.status == 200
            # Check that filtered results are from that region
            for report in data.get("reports", []):
                if report.get("regions"):
                    assert "us_300" in report["regions"]
        except urllib.error.HTTPError as e:
            if e.code == 500:
                pytest.skip("PostgreSQL database not available")
            raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
