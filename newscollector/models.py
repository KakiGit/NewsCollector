"""Data models for NewsCollector.

This module defines Pydantic models for representing:
- Trending news items from various platforms
- Collection results
- AI-generated daily verdicts
- Financial reports
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class TrendingItem(BaseModel):
    """A single trending news item or topic."""

    title: str = Field(..., description="Headline or topic name")
    url: str | None = Field(default=None, description="Link to original content")
    source: str = Field(
        ..., description="Publisher or platform name, e.g. 'BBC', 'Weibo'"
    )
    platform: str = Field(
        ..., description="Collector identifier, e.g. 'news_rss', 'weibo'"
    )
    region: str | None = Field(
        default=None, description="Geographic region, e.g. 'UK', 'China'"
    )
    rank: int | None = Field(default=None, description="Position in trending list")
    description: str | None = Field(
        default=None, description="Brief summary from source"
    )
    summary: str | None = Field(
        default=None, description="AI-generated summary when AI is configured"
    )
    heat: int | None = Field(default=None, description="Engagement / popularity metric")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Extra platform-specific data"
    )
    labels: list[str] = Field(
        default_factory=list,
        description="Topic labels: financial, sports, politics, game, entertainment, etc.",
    )
    collected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of collection",
    )


class CollectionResult(BaseModel):
    """Result of a collection run for a single platform."""

    platform: str = Field(..., description="Platform identifier")
    region: str | None = Field(
        default=None, description="Region filter applied, if any"
    )
    items: list[TrendingItem] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    error: str | None = Field(
        default=None, description="Error message if collection failed"
    )

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def count(self) -> int:
        return len(self.items)


class DailyVerdict(BaseModel):
    """AI-generated daily summary and world-state verdict scores."""

    scope_key: str = Field(
        ...,
        description=(
            "Scope identifier: all, platform:<name>, platform:<name>|region:<name>"
        ),
    )
    date: str = Field(..., description="Date in YYYY-MM-DD")
    platform: str | None = Field(default=None, description="Platform scope, if any")
    region: str | None = Field(default=None, description="Region scope, if any")
    summary: str = Field(..., description="AI-generated daily summary")
    political_score: int | None = Field(
        default=None, ge=0, le=100, description="Global political health score"
    )
    economic_score: int | None = Field(
        default=None, ge=0, le=100, description="Global economic health score"
    )
    domestic_political_score: int | None = Field(
        default=None, ge=0, le=100, description="Domestic political health score"
    )
    domestic_economic_score: int | None = Field(
        default=None, ge=0, le=100, description="Domestic economic health score"
    )
    item_count: int = Field(..., ge=0, description="Number of items used for analysis")
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of verdict generation",
    )


class FinancialReport(BaseModel):
    """A single company's financial report with AI analysis."""

    company_name: str = Field(..., description="Full company name")
    ticker: str = Field(..., description="Stock ticker symbol (e.g. AAPL, 0700.HK)")
    regions: list[str] = Field(
        default_factory=list,
        description="Region lists this company belongs to (e.g. ['global_500', 'us_300'])",
    )
    sector: str | None = Field(default=None, description="Business sector")
    industry: str | None = Field(default=None, description="Industry classification")
    currency: str | None = Field(default=None, description="Reporting currency")
    report_period: str | None = Field(
        default=None,
        description="Period of the report (e.g. '2025-Q4', '2024-FY')",
    )
    report_type: str | None = Field(
        default=None,
        description="Type of report: 'quarterly' or 'annual'",
    )
    report_year: int | None = Field(
        default=None,
        description="Year of the report (e.g. 2025)",
    )
    report_quarter: int | None = Field(
        default=None,
        ge=1,
        le=4,
        description="Quarter of the report (1-4). Null for annual reports.",
    )

    # Key financial metrics
    revenue: float | None = Field(default=None, description="Total revenue")
    net_income: float | None = Field(default=None, description="Net income")
    gross_profit: float | None = Field(default=None, description="Gross profit")
    operating_income: float | None = Field(default=None, description="Operating income")
    ebitda: float | None = Field(default=None, description="EBITDA")
    total_assets: float | None = Field(default=None, description="Total assets")
    total_liabilities: float | None = Field(
        default=None, description="Total liabilities"
    )
    total_equity: float | None = Field(default=None, description="Stockholders' equity")
    cash: float | None = Field(default=None, description="Cash and cash equivalents")
    total_debt: float | None = Field(default=None, description="Total debt")
    operating_cash_flow: float | None = Field(
        default=None, description="Operating cash flow"
    )
    free_cash_flow: float | None = Field(default=None, description="Free cash flow")
    market_cap: float | None = Field(default=None, description="Market capitalization")
    pe_ratio: float | None = Field(default=None, description="Price-to-earnings ratio")
    revenue_growth: float | None = Field(
        default=None, description="Revenue growth rate (YoY)"
    )
    profit_margin: float | None = Field(default=None, description="Net profit margin")

    # AI analysis
    summary: str | None = Field(
        default=None,
        description="AI-generated summary of the financial report",
    )
    health_score: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Financial health score (0=critical, 100=excellent)",
    )
    potential_score: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Next-quarter performance potential (0=poor outlook, 100=excellent outlook)",
    )

    collected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of collection",
    )
    error: str | None = Field(
        default=None,
        description="Error message if data fetch failed",
    )
