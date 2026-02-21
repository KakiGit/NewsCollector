"""Tests for newscollector.web FastAPI endpoints."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from newscollector.web import _convert_report_to_usd, app, configure

pytestmark = pytest.mark.usefixtures("db_setup")


@pytest.fixture(autouse=True)
def _configure_output(seeded_db, db_url: str):
    configure(db_url=db_url)
    yield
    configure(db_url=None)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestIndexRoute:
    def test_serves_html(self, client: TestClient):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestApiPlatforms:
    def test_returns_platforms_with_data(self, client: TestClient):
        resp = client.get("/api/platforms")
        assert resp.status_code == 200
        platforms = resp.json()
        assert "news_rss" in platforms
        assert "weibo" in platforms

    def test_excludes_special_dirs(self, client: TestClient):
        platforms = client.get("/api/platforms").json()
        assert "daily_analysis" not in platforms
        assert "financial_reports" not in platforms


class TestApiDates:
    def test_returns_dates(self, client: TestClient):
        resp = client.get("/api/dates")
        dates = resp.json()
        assert "2025-01-15" in dates

    def test_filter_by_platform(self, client: TestClient):
        dates = client.get("/api/dates", params={"platform": "news_rss"}).json()
        assert "2025-01-15" in dates


class TestApiItems:
    def test_returns_items(self, client: TestClient):
        resp = client.get("/api/items", params={"date": "2025-01-15"})
        data = resp.json()
        assert data["count"] == 3
        assert data["date"] == "2025-01-15"

    def test_filter_by_platform(self, client: TestClient):
        data = client.get(
            "/api/items", params={"date": "2025-01-15", "platform": "weibo"}
        ).json()
        assert data["count"] == 1

    def test_filter_by_region(self, client: TestClient):
        data = client.get(
            "/api/items", params={"date": "2025-01-15", "region": "usa"}
        ).json()
        assert data["count"] == 1

    def test_search(self, client: TestClient):
        data = client.get(
            "/api/items", params={"date": "2025-01-15", "search": "Finance"}
        ).json()
        assert data["count"] == 1
        assert data["items"][0]["title"] == "Finance news"

    def test_filter_by_labels(self, client: TestClient):
        data = client.get(
            "/api/items", params={"date": "2025-01-15", "labels": "entertainment"}
        ).json()
        assert data["count"] == 1

    def test_defaults_to_latest_date(self, client: TestClient):
        data = client.get("/api/items").json()
        assert data["date"] == "2025-01-15"
        assert data["count"] > 0


class TestApiRegions:
    def test_returns_distinct_regions(self, client: TestClient):
        regions = client.get("/api/regions").json()
        assert isinstance(regions, list)
        assert len(regions) > 0


class TestApiLabels:
    def test_returns_distinct_labels(self, client: TestClient):
        labels = client.get("/api/labels").json()
        assert isinstance(labels, list)
        assert (
            "politics" in labels or "financial" in labels or "entertainment" in labels
        )


class TestApiDailyVerdict:
    def test_returns_verdict(self, client: TestClient):
        resp = client.get("/api/daily-verdict", params={"date": "2025-01-15"})
        data = resp.json()
        assert data["date"] == "2025-01-15"
        assert data["verdict"] is not None
        assert data["verdict"]["global_political_score"] == 65

    def test_with_platform_filter(self, client: TestClient):
        data = client.get(
            "/api/daily-verdict",
            params={
                "date": "2025-01-15",
                "platform": "news_rss",
            },
        ).json()
        assert data["verdict"]["local_scope_key"] == "platform:news_rss"

    def test_missing_date(self, client: TestClient):
        data = client.get("/api/daily-verdict", params={"date": "1999-01-01"}).json()
        assert data["verdict"] is None


class TestApiDailyAnalysis:
    def test_returns_entries(self, client: TestClient):
        data = client.get("/api/daily-analysis", params={"date": "2025-01-15"}).json()
        assert data["date"] == "2025-01-15"
        assert len(data["entries"]) == 2

    def test_missing_date(self, client: TestClient):
        data = client.get("/api/daily-analysis", params={"date": "1999-01-01"}).json()
        assert data["entries"] == []


class TestApiFinancialReports:
    def test_returns_reports(self, client: TestClient):
        data = client.get("/api/financial-reports").json()
        assert data["count"] == 2
        assert len(data["reports"]) == 2

    def test_filter_by_region(self, client: TestClient):
        data = client.get("/api/financial-reports", params={"region": "us_300"}).json()
        assert data["count"] == 1
        assert data["reports"][0]["ticker"] == "ACME"

    def test_search(self, client: TestClient):
        data = client.get("/api/financial-reports", params={"search": "Euro"}).json()
        assert data["count"] == 1

    def test_data_status_complete(self, client: TestClient):
        data = client.get("/api/financial-reports").json()
        acme = next(r for r in data["reports"] if r["ticker"] == "ACME")
        assert acme["data_status"] == "complete"

    def test_data_status_pending_ai(self, client: TestClient):
        data = client.get("/api/financial-reports").json()
        euro = next(r for r in data["reports"] if r["ticker"] == "EURO")
        assert euro["data_status"] == "pending_ai"


class TestApiFinancialRegions:
    def test_returns_regions(self, client: TestClient):
        regions = client.get("/api/financial-regions").json()
        assert "us_300" in regions
        assert "europe_300" in regions


class TestConvertReportToUsd:
    def test_usd_passthrough(self):
        report = {"currency": "USD", "revenue": 1000}
        result = _convert_report_to_usd(report, {"USD": 1.0})
        assert result["revenue"] == 1000

    def test_conversion(self):
        report = {"currency": "EUR", "revenue": 1000, "net_income": 500}
        rates = {"EUR": 1.1, "USD": 1.0}
        result = _convert_report_to_usd(report, rates)
        assert result["revenue"] == pytest.approx(1100.0)
        assert result["net_income"] == pytest.approx(550.0)
        assert result["currency"] == "USD"
        assert result["original_currency"] == "EUR"

    def test_missing_rate_no_conversion(self):
        report = {"currency": "JPY", "revenue": 1000}
        rates = {"USD": 1.0}
        result = _convert_report_to_usd(report, rates)
        assert result["revenue"] == 1000


class TestApiFinancialHistory:
    def test_returns_history(self, client: TestClient):
        # Need to seed historical data - just test endpoint response
        resp = client.get("/api/financial-history")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert "tickers" in data
        assert "by_ticker" in data

    def test_filter_by_ticker(self, client: TestClient):
        resp = client.get("/api/financial-history", params={"ticker": "AAPL"})
        assert resp.status_code == 200
        # Returns empty if no data, but endpoint should work

    def test_limit_periods(self, client: TestClient):
        resp = client.get("/api/financial-history", params={"periods": 4})
        assert resp.status_code == 200


class TestApiFinancialSectors:
    def test_returns_sectors(self, client: TestClient):
        resp = client.get("/api/financial-sectors")
        assert resp.status_code == 200
        data = resp.json()
        assert "sectors" in data
        assert "industries" in data


class TestApiFinancialRankings:
    def test_returns_rankings(self, client: TestClient):
        resp = client.get("/api/financial-rankings")
        assert resp.status_code == 200
        data = resp.json()
        assert "rankings" in data
        assert "sort_by" in data
        assert data["sort_by"] == "health_score"  # default

    def test_sort_by_revenue(self, client: TestClient):
        resp = client.get("/api/financial-rankings", params={"sort_by": "revenue"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["sort_by"] == "revenue"

    def test_limit_results(self, client: TestClient):
        resp = client.get("/api/financial-rankings", params={"limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rankings"]) <= 10

    def test_filter_by_sector(self, client: TestClient):
        resp = client.get("/api/financial-rankings", params={"sector": "Technology"})
        assert resp.status_code == 200


class TestApiCompanyScores:
    def test_returns_scores(self, client: TestClient):
        resp = client.get("/api/company-scores")
        assert resp.status_code == 200
        data = resp.json()
        assert "companies" in data
        assert "count" in data
        assert "avg_health_score" in data
        assert "avg_potential_score" in data

    def test_filter_by_sector(self, client: TestClient):
        resp = client.get("/api/company-scores", params={"sector": "Technology"})
        assert resp.status_code == 200

    def test_filter_by_health_range(self, client: TestClient):
        resp = client.get(
            "/api/company-scores", params={"min_health": 70, "max_health": 100}
        )
        assert resp.status_code == 200
        data = resp.json()
        # All returned companies should have health_score in range
        for c in data.get("companies", []):
            if c.get("health_score") is not None:
                assert 70 <= c["health_score"] <= 100

    def test_filter_by_potential_range(self, client: TestClient):
        resp = client.get(
            "/api/company-scores", params={"min_potential": 50, "max_potential": 90}
        )
        assert resp.status_code == 200

    def test_sort_by_revenue(self, client: TestClient):
        resp = client.get("/api/company-scores", params={"sort_by": "revenue"})
        assert resp.status_code == 200

    def test_limit_results(self, client: TestClient):
        resp = client.get("/api/company-scores", params={"limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["companies"]) <= 5


class TestApiCompanyScoresDistribution:
    def test_returns_distribution(self, client: TestClient):
        resp = client.get("/api/company-scores/distribution")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "health_distribution" in data
        assert "potential_distribution" in data

    def test_filter_by_sector(self, client: TestClient):
        resp = client.get(
            "/api/company-scores/distribution", params={"sector": "Technology"}
        )
        assert resp.status_code == 200


class TestApiCompanyScoresFilters:
    def test_returns_filters(self, client: TestClient):
        resp = client.get("/api/company-scores/filters")
        assert resp.status_code == 200
        data = resp.json()
        assert "sectors" in data
        assert "industries" in data
