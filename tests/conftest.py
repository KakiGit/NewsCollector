"""Shared fixtures for NewsCollector tests."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import pytest

from newscollector.models import (
    CollectionResult,
    DailyVerdict,
    FinancialReport,
    TrendingItem,
)
from newscollector.utils.storage import (
    clear_storage,
    configure_storage,
    save_daily_verdict,
    save_financial_reports,
    save_result,
)


@pytest.fixture()
def sample_item_kwargs() -> dict[str, Any]:
    return {
        "title": "Test headline",
        "url": "https://example.com/article",
        "source": "TestSource",
        "platform": "news_rss",
        "region": "usa",
        "rank": 1,
        "description": "A brief description",
    }


@pytest.fixture()
def sample_item(sample_item_kwargs: dict[str, Any]) -> TrendingItem:
    return TrendingItem(**sample_item_kwargs)


@pytest.fixture()
def sample_collection_result(sample_item: TrendingItem) -> CollectionResult:
    return CollectionResult(
        platform="news_rss",
        region="usa",
        items=[sample_item],
    )


@pytest.fixture()
def sample_verdict() -> DailyVerdict:
    return DailyVerdict(
        scope_key="all",
        date="2025-01-15",
        summary="A test summary.",
        item_count=10,
        political_score=65,
        economic_score=70,
        domestic_political_score=60,
        domestic_economic_score=55,
    )


@pytest.fixture()
def sample_financial_report() -> FinancialReport:
    return FinancialReport(
        company_name="Acme Corp",
        ticker="ACME",
        regions=["us_300"],
        sector="Technology",
        revenue=1_000_000_000.0,
        net_income=200_000_000.0,
        market_cap=50_000_000_000.0,
    )


@pytest.fixture()
def db_url() -> str:
    url = os.getenv("NEWSCOLLECTOR_DATABASE_URL")
    if not url:
        pytest.skip(
            "NEWSCOLLECTOR_DATABASE_URL is not set; skipping PostgreSQL-backed tests."
        )
    return url


@pytest.fixture()
def db_setup(db_url: str):
    configure_storage(db_url)
    clear_storage(db_url)
    yield
    clear_storage(db_url)


@pytest.fixture()
def ai_config() -> dict[str, Any]:
    return {
        "ai": {
            "ai_base_url": "https://api.example.com/v1",
            "ai_model": "test-model",
            "ai_api_key": "sk-test-key",
            "ai_response_language": "English",
            "ai_request_timeout": 30,
            "ai_max_failures_before_disable": 3,
            "ai_page_summary_enabled": True,
            "ai_page_char_limit": 12000,
            "ai_page_html_char_limit": 200000,
            "ai_max_verdict_items": 400,
            "ai_json_number_retry": 3,
        }
    }


@pytest.fixture()
def empty_config() -> dict[str, Any]:
    return {}


@pytest.fixture()
def seeded_db(db_setup, sample_item_kwargs: dict[str, Any]) -> str:
    """Seed PostgreSQL with sample data for API / storage tests."""
    collected_at_1 = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    collected_at_2 = datetime(2025, 1, 15, 12, 1, 0, tzinfo=timezone.utc)
    collected_at_3 = datetime(2025, 1, 15, 13, 0, 0, tzinfo=timezone.utc)

    item1 = TrendingItem(
        **sample_item_kwargs,
        labels=["politics"],
        collected_at=collected_at_1,
    )
    item2 = TrendingItem(
        title="Finance news",
        url="https://example.com/finance",
        source="FinSource",
        platform="news_rss",
        region="europe",
        rank=2,
        description="Stock market update",
        labels=["financial"],
        metadata={},
        collected_at=collected_at_2,
    )
    item3 = TrendingItem(
        title="Hot topic",
        url="https://weibo.com/hot",
        source="Weibo",
        platform="weibo",
        region="China",
        rank=1,
        labels=["entertainment"],
        metadata={},
        collected_at=collected_at_3,
    )

    save_result(
        CollectionResult(platform="news_rss", region="usa", items=[item1, item2]),
        date="2025-01-15",
    )
    save_result(
        CollectionResult(platform="weibo", region="China", items=[item3]),
        date="2025-01-15",
    )

    verdicts = [
        DailyVerdict(
            scope_key="all",
            date="2025-01-15",
            summary="Overall summary.",
            political_score=65,
            economic_score=70,
            domestic_political_score=60,
            domestic_economic_score=55,
            item_count=3,
        ),
        DailyVerdict(
            scope_key="platform:news_rss",
            date="2025-01-15",
            platform="news_rss",
            summary="RSS summary.",
            political_score=62,
            economic_score=68,
            domestic_political_score=58,
            domestic_economic_score=52,
            item_count=2,
        ),
    ]
    for v in verdicts:
        save_daily_verdict(v)

    reports = [
        FinancialReport(
            company_name="Acme Corp",
            ticker="ACME",
            regions=["us_300"],
            sector="Technology",
            revenue=1e9,
            net_income=2e8,
            market_cap=5e10,
            currency="USD",
            health_score=75,
            potential_score=60,
            summary="Strong fundamentals.",
            error=None,
        ),
        FinancialReport(
            company_name="Euro AG",
            ticker="EURO",
            regions=["europe_300"],
            sector="Finance",
            revenue=5e8,
            net_income=1e8,
            market_cap=1e10,
            currency="EUR",
            health_score=None,
            potential_score=None,
            summary=None,
            error=None,
        ),
    ]
    save_financial_reports(reports)

    return "ok"
