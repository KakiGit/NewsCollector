"""Tests for CLI commands."""

from __future__ import annotations

from click.testing import CliRunner
from unittest.mock import patch, MagicMock
import pytest

from newscollector.cli import cli


class TestCLI:
    """Test CLI commands."""

    @pytest.fixture()
    def runner(self):
        return CliRunner()

    def test_cli_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "NewsCollector" in result.output
        assert "--help" in result.output

    def test_collect_help(self, runner):
        result = runner.invoke(cli, ["collect", "--help"])
        assert result.exit_code == 0
        assert "--platform" in result.output

    def test_list_platforms(self, runner):
        result = runner.invoke(cli, ["list-platforms"])
        assert result.exit_code == 0
        assert "news_rss" in result.output or "Available platforms" in result.output

    def test_list_regions(self, runner):
        result = runner.invoke(cli, ["list-regions"])
        assert result.exit_code == 0
        assert "us_300" in result.output or "Available regions" in result.output

    def test_collect_reports_help(self, runner):
        result = runner.invoke(cli, ["collect-reports", "--help"])
        assert result.exit_code == 0
        assert "--region" in result.output

    def test_collect_history_help(self, runner):
        result = runner.invoke(cli, ["collect-history", "--help"])
        assert result.exit_code == 0
        assert "--latest" in result.output

    def test_evaluate_reports_help(self, runner):
        result = runner.invoke(cli, ["evaluate-reports", "--help"])
        assert result.exit_code == 0

    def test_clean_reports_help(self, runner):
        result = runner.invoke(cli, ["clean-reports", "--help"])
        assert result.exit_code == 0
        assert "--refetch" in result.output

    def test_update_companies_help(self, runner):
        result = runner.invoke(cli, ["update-companies", "--help"])
        assert result.exit_code == 0


class TestCollectCommand:
    """Test collect command variations."""

    @pytest.fixture()
    def runner(self):
        return CliRunner()

    def test_collect_platforms_list(self, runner):
        result = runner.invoke(cli, ["collect", "--platform", "news_rss", "--help"])
        assert result.exit_code == 0

    def test_collect_with_region(self, runner):
        result = runner.invoke(cli, ["collect", "--platform", "news_rss", "--region", "usa", "--help"])
        assert result.exit_code == 0


class TestVerdictCommand:
    """Test verdict command."""

    @pytest.fixture()
    def runner(self):
        return CliRunner()

    def test_verdict_help(self, runner):
        result = runner.invoke(cli, ["verdict", "--help"])
        assert result.exit_code == 0

    def test_verdict_requires_date(self, runner):
        result = runner.invoke(cli, ["verdict"])
        # Should fail due to missing required argument
        assert result.exit_code != 0


class TestServeCommand:
    """Test serve command."""

    @pytest.fixture()
    def runner(self):
        return CliRunner()

    def test_serve_help(self, runner):
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
        assert "--host" in result.output

    def test_serve_default_port(self, runner):
        result = runner.invoke(cli, ["serve", "--help"])
        assert "8000" in result.output or "default" in result.output.lower()
