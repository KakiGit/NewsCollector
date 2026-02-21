"""Tests for newscollector.financial helper functions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from newscollector.financial import (
    _has_meaningful_data,
    _quarter_from_date,
    get_available_regions,
    load_companies,
)


class TestQuarterFromDate:
    def test_q1(self):
        assert _quarter_from_date(datetime(2025, 1, 15)) == "2025-Q1"
        assert _quarter_from_date(datetime(2025, 3, 31)) == "2025-Q1"

    def test_q2(self):
        assert _quarter_from_date(datetime(2025, 4, 1)) == "2025-Q2"
        assert _quarter_from_date(datetime(2025, 6, 30)) == "2025-Q2"

    def test_q3(self):
        assert _quarter_from_date(datetime(2025, 7, 1)) == "2025-Q3"
        assert _quarter_from_date(datetime(2025, 9, 30)) == "2025-Q3"

    def test_q4(self):
        assert _quarter_from_date(datetime(2025, 10, 1)) == "2025-Q4"
        assert _quarter_from_date(datetime(2025, 12, 31)) == "2025-Q4"


class TestHasMeaningfulData:
    def test_has_revenue(self):
        assert _has_meaningful_data({"revenue": 100}) is True

    def test_has_market_cap(self):
        assert _has_meaningful_data({"market_cap": 1e9}) is True

    def test_all_none(self):
        assert _has_meaningful_data({}) is False
        assert _has_meaningful_data({"revenue": None, "net_income": None}) is False

    def test_has_one_key_field(self):
        assert _has_meaningful_data({"ebitda": 50}) is True

    def test_non_key_field_does_not_count(self):
        assert _has_meaningful_data({"pe_ratio": 15.0, "profit_margin": 0.2}) is False


class TestLoadCompanies:
    @pytest.fixture()
    def companies_yaml(self, tmp_path) -> Path:
        data = {
            "companies": {
                "us_300": {"AAPL": "Apple Inc.", "MSFT": "Microsoft"},
                "china_300": {"0700.HK": "Tencent", "AAPL": "Apple Inc."},
            }
        }
        yaml_path = tmp_path / "companies.yaml"
        yaml_path.write_text(yaml.dump(data))
        return yaml_path

    def test_load_all(self, companies_yaml):
        with patch("newscollector.financial.COMPANIES_FILE", companies_yaml):
            companies = load_companies()
        assert "AAPL" in companies
        assert "MSFT" in companies
        assert "0700.HK" in companies
        assert set(companies["AAPL"]["regions"]) == {"us_300", "china_300"}

    def test_filter_by_region(self, companies_yaml):
        with patch("newscollector.financial.COMPANIES_FILE", companies_yaml):
            companies = load_companies(regions=["china_300"])
        assert "0700.HK" in companies
        assert "MSFT" not in companies

    def test_missing_file(self, tmp_path):
        missing = tmp_path / "nope.yaml"
        with patch("newscollector.financial.COMPANIES_FILE", missing):
            assert load_companies() == {}


class TestGetAvailableRegions:
    def test_returns_from_yaml(self, tmp_path):
        data = {"companies": {"us_300": {}, "europe_300": {}}}
        yaml_path = tmp_path / "companies.yaml"
        yaml_path.write_text(yaml.dump(data))
        with patch("newscollector.financial.COMPANIES_FILE", yaml_path):
            regions = get_available_regions()
        assert regions == ["europe_300", "us_300"]

    def test_missing_file(self, tmp_path):
        with patch("newscollector.financial.COMPANIES_FILE", tmp_path / "nope.yaml"):
            assert get_available_regions() == []
