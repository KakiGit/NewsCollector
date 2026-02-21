"""Tests for newscollector.utils.storage."""

from __future__ import annotations


import pytest

from newscollector.models import (
    CollectionResult,
    DailyVerdict,
    FinancialReport,
    TrendingItem,
)
from newscollector.utils.storage import (
    _is_duplicate,
    _item_identity,
    _normalize_url,
    _sanitize_floats,
    get_collected_tickers,
    load_collected_items,
    load_daily_verdicts,
    load_financial_reports,
    save_daily_verdict,
    save_financial_reports,
    save_financial_reports_raw,
    save_result,
)

pytestmark = pytest.mark.usefixtures("db_setup")


class TestNormalizeUrl:
    def test_strips_fragment(self):
        assert (
            _normalize_url("https://example.com/page#section")
            == "https://example.com/page"
        )

    def test_lowercases_host(self):
        result = _normalize_url("https://EXAMPLE.COM/Path")
        assert "example.com" in result
        assert "/Path" in result

    def test_none_returns_none(self):
        assert _normalize_url(None) is None

    def test_empty_returns_none(self):
        assert _normalize_url("") is None
        assert _normalize_url("   ") is None

    def test_preserves_query(self):
        result = _normalize_url("https://example.com/page?q=1&b=2")
        assert "q=1" in result
        assert "b=2" in result


class TestItemIdentity:
    def test_url_based(self):
        item = {
            "url": "https://example.com/article",
            "title": "T",
            "platform": "p",
            "source": "s",
        }
        ident = _item_identity(item)
        assert ident[0] == "url"

    def test_title_based_when_no_url(self):
        item = {"url": None, "title": "Hello World", "platform": "p", "source": "s"}
        ident = _item_identity(item)
        assert ident[0] == "title"

    def test_title_normalized(self):
        item = {
            "url": None,
            "title": "  Hello   World  ",
            "platform": "p",
            "source": "s",
        }
        ident = _item_identity(item)
        assert ident[-1] == "hello world"


class TestIsDuplicate:
    def test_detects_url_duplicate(self):
        existing = [
            {
                "url": "https://example.com/a",
                "title": "T",
                "platform": "p",
                "source": "s",
            }
        ]
        new = {
            "url": "https://example.com/a",
            "title": "Different",
            "platform": "p",
            "source": "s",
        }
        assert _is_duplicate(existing, new) is True

    def test_detects_title_duplicate(self):
        existing = [
            {"url": None, "title": "Same Title", "platform": "p", "source": "s"}
        ]
        new = {"url": None, "title": "Same Title", "platform": "p", "source": "s"}
        assert _is_duplicate(existing, new) is True

    def test_not_duplicate(self):
        existing = [
            {"url": "https://a.com/1", "title": "T1", "platform": "p", "source": "s"}
        ]
        new = {"url": "https://b.com/2", "title": "T2", "platform": "p", "source": "s"}
        assert _is_duplicate(existing, new) is False


class TestSaveAndLoadResult:
    def test_save_creates_file(self):
        item = TrendingItem(title="T", source="S", platform="test_plat")
        result = CollectionResult(platform="test_plat", items=[item])
        save_result(result, date="2025-01-15")
        data = load_collected_items("2025-01-15")
        assert len(data) == 1
        assert data[0]["title"] == "T"

    def test_dedup_on_second_save(self):
        item = TrendingItem(title="T", url="https://a.com/1", source="S", platform="p")
        result = CollectionResult(platform="p", items=[item])
        save_result(result, date="2025-01-15")
        save_result(result, date="2025-01-15")
        data = load_collected_items("2025-01-15")
        assert len(data) == 1

    def test_appends_new_items(self):
        item1 = TrendingItem(title="A", url="https://a.com/1", source="S", platform="p")
        item2 = TrendingItem(title="B", url="https://a.com/2", source="S", platform="p")
        save_result(CollectionResult(platform="p", items=[item1]), date="2025-01-15")
        save_result(CollectionResult(platform="p", items=[item2]), date="2025-01-15")
        data = load_collected_items("2025-01-15")
        assert len(data) == 2


class TestDailyVerdicts:
    def test_save_and_load_roundtrip(self, sample_verdict):
        save_daily_verdict(sample_verdict)
        loaded = load_daily_verdicts("2025-01-15")
        assert "all" in loaded
        assert loaded["all"]["summary"] == "A test summary."
        assert loaded["all"]["political_score"] == 65

    def test_multiple_scopes(self):
        v1 = DailyVerdict(
            scope_key="all", date="2025-02-01", summary="G.", item_count=5
        )
        v2 = DailyVerdict(
            scope_key="platform:rss", date="2025-02-01", summary="R.", item_count=3
        )
        save_daily_verdict(v1)
        save_daily_verdict(v2)
        loaded = load_daily_verdicts("2025-02-01")
        assert len(loaded) == 2
        assert "all" in loaded
        assert "platform:rss" in loaded

    def test_load_missing_date(self):
        assert load_daily_verdicts("1999-01-01") == {}


class TestFinancialReports:
    def test_save_and_load(self, sample_financial_report):
        save_financial_reports([sample_financial_report])
        loaded, total = load_financial_reports()
        assert len(loaded) == 1
        assert total == 1
        assert loaded[0]["ticker"] == "ACME"

    def test_merge_by_ticker(self):
        r1 = FinancialReport(
            company_name="X", ticker="X", regions=["us_300"], revenue=100
        )
        save_financial_reports([r1])
        r2 = FinancialReport(
            company_name="X", ticker="X", regions=["global_500"], revenue=200
        )
        save_financial_reports([r2])
        loaded, total = load_financial_reports()
        assert len(loaded) == 1
        assert total == 1
        assert set(loaded[0]["regions"]) == {"us_300", "global_500"}
        assert loaded[0]["revenue"] == 200

    def test_save_raw_replaces(self):
        r1 = FinancialReport(company_name="A", ticker="A")
        save_financial_reports([r1])
        save_financial_reports_raw([{"ticker": "B", "company_name": "B"}])
        loaded, total = load_financial_reports()
        assert len(loaded) == 1
        assert total == 1
        assert loaded[0]["ticker"] == "B"


class TestGetCollectedTickers:
    def test_returns_ticker_period_map(self):
        r = FinancialReport(company_name="X", ticker="X", report_period="2025-Q1")
        save_financial_reports([r])
        tickers = get_collected_tickers()
        assert tickers == {"X": "2025-Q1"}

    def test_empty_when_no_reports(self):
        assert get_collected_tickers() == {}


class TestLoadCollectedItems:
    def test_loads_items_for_date(self, seeded_db):
        items = load_collected_items("2025-01-15")
        assert len(items) == 3  # 2 news_rss + 1 weibo

    def test_filter_by_platform(self, seeded_db):
        items = load_collected_items("2025-01-15", platforms=["weibo"])
        assert len(items) == 1
        assert items[0]["platform"] == "weibo"

    def test_filter_by_region(self, seeded_db):
        items = load_collected_items("2025-01-15", region="usa")
        assert len(items) == 1
        assert items[0]["region"] == "usa"

    def test_missing_date_returns_empty(self, seeded_db):
        assert load_collected_items("2000-01-01") == []


class TestSanitizeFloats:
    def test_replaces_inf(self):
        assert _sanitize_floats(float("inf")) is None

    def test_replaces_neg_inf(self):
        assert _sanitize_floats(float("-inf")) is None

    def test_replaces_nan(self):
        assert _sanitize_floats(float("nan")) is None

    def test_preserves_normal_float(self):
        assert _sanitize_floats(3.14) == 3.14

    def test_recursive_dict(self):
        result = _sanitize_floats({"a": float("inf"), "b": 1.0})
        assert result == {"a": None, "b": 1.0}

    def test_recursive_list(self):
        result = _sanitize_floats([float("nan"), 2.0])
        assert result == [None, 2.0]

    def test_non_float_passthrough(self):
        assert _sanitize_floats("hello") == "hello"
        assert _sanitize_floats(42) == 42
        assert _sanitize_floats(None) is None
