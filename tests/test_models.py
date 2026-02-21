"""Tests for newscollector.models."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from newscollector.models import (
    CollectionResult,
    DailyVerdict,
    FinancialReport,
    TrendingItem,
)


class TestTrendingItem:
    def test_required_fields(self):
        item = TrendingItem(title="Hello", source="BBC", platform="news_rss")
        assert item.title == "Hello"
        assert item.source == "BBC"
        assert item.platform == "news_rss"

    def test_defaults(self):
        item = TrendingItem(title="T", source="S", platform="P")
        assert item.url is None
        assert item.region is None
        assert item.rank is None
        assert item.description is None
        assert item.summary is None
        assert item.heat is None
        assert item.metadata == {}
        assert item.labels == []

    def test_collected_at_auto_set(self):
        before = datetime.now(timezone.utc)
        item = TrendingItem(title="T", source="S", platform="P")
        after = datetime.now(timezone.utc)
        assert before <= item.collected_at <= after

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            TrendingItem(source="S", platform="P")  # missing title

    def test_full_item(self, sample_item_kwargs):
        item = TrendingItem(**sample_item_kwargs)
        assert item.title == "Test headline"
        assert item.rank == 1
        assert item.region == "usa"

    def test_model_dump_roundtrip(self):
        item = TrendingItem(title="T", source="S", platform="P", labels=["a", "b"])
        data = item.model_dump(mode="json")
        restored = TrendingItem(**data)
        assert restored.title == item.title
        assert restored.labels == item.labels


class TestCollectionResult:
    def test_success_when_no_error(self, sample_collection_result):
        assert sample_collection_result.success is True

    def test_failure_when_error(self):
        result = CollectionResult(platform="x", error="boom")
        assert result.success is False

    def test_count(self, sample_collection_result):
        assert sample_collection_result.count == 1

    def test_count_empty(self):
        result = CollectionResult(platform="x")
        assert result.count == 0

    def test_default_items(self):
        result = CollectionResult(platform="x")
        assert result.items == []


class TestDailyVerdict:
    def test_required_fields(self):
        v = DailyVerdict(
            scope_key="all", date="2025-01-01", summary="Ok.", item_count=5
        )
        assert v.scope_key == "all"
        assert v.item_count == 5
        assert v.political_score is None

    def test_scores_valid_range(self):
        v = DailyVerdict(
            scope_key="all",
            date="2025-01-01",
            summary="Ok.",
            item_count=1,
            political_score=0,
            economic_score=100,
            domestic_political_score=50,
            domestic_economic_score=50,
        )
        assert v.political_score == 0
        assert v.economic_score == 100

    def test_score_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            DailyVerdict(
                scope_key="all",
                date="2025-01-01",
                summary="Ok.",
                item_count=1,
                political_score=101,
            )
        with pytest.raises(ValidationError):
            DailyVerdict(
                scope_key="all",
                date="2025-01-01",
                summary="Ok.",
                item_count=1,
                economic_score=-1,
            )

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            DailyVerdict(
                date="2025-01-01", summary="Ok.", item_count=1
            )  # missing scope_key


class TestFinancialReport:
    def test_required_fields(self):
        r = FinancialReport(company_name="Acme", ticker="ACME")
        assert r.company_name == "Acme"
        assert r.ticker == "ACME"

    def test_optional_financial_defaults(self):
        r = FinancialReport(company_name="X", ticker="X")
        assert r.revenue is None
        assert r.net_income is None
        assert r.market_cap is None
        assert r.health_score is None
        assert r.potential_score is None
        assert r.error is None
        assert r.regions == []

    def test_score_constraints(self):
        r = FinancialReport(
            company_name="X", ticker="X", health_score=0, potential_score=100
        )
        assert r.health_score == 0
        assert r.potential_score == 100

    def test_score_out_of_range(self):
        with pytest.raises(ValidationError):
            FinancialReport(company_name="X", ticker="X", health_score=101)
        with pytest.raises(ValidationError):
            FinancialReport(company_name="X", ticker="X", potential_score=-1)

    def test_collected_at_auto_set(self):
        before = datetime.now(timezone.utc)
        r = FinancialReport(company_name="X", ticker="X")
        after = datetime.now(timezone.utc)
        assert before <= r.collected_at <= after
