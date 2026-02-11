"""Data models for NewsCollector."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TrendingItem(BaseModel):
    """A single trending news item or topic."""

    title: str = Field(..., description="Headline or topic name")
    url: str | None = Field(default=None, description="Link to original content")
    source: str = Field(..., description="Publisher or platform name, e.g. 'BBC', 'Weibo'")
    platform: str = Field(..., description="Collector identifier, e.g. 'news_rss', 'weibo'")
    region: str | None = Field(default=None, description="Geographic region, e.g. 'UK', 'China'")
    rank: int | None = Field(default=None, description="Position in trending list")
    description: str | None = Field(default=None, description="Brief summary")
    heat: int | None = Field(default=None, description="Engagement / popularity metric")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extra platform-specific data")
    collected_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of collection",
    )


class CollectionResult(BaseModel):
    """Result of a collection run for a single platform."""

    platform: str = Field(..., description="Platform identifier")
    region: str | None = Field(default=None, description="Region filter applied, if any")
    items: list[TrendingItem] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    error: str | None = Field(default=None, description="Error message if collection failed")

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def count(self) -> int:
        return len(self.items)
