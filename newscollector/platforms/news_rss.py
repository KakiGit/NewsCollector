"""RSS feed collector for news publishers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import feedparser
import yaml

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector

logger = logging.getLogger(__name__)

SOURCES_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "sources.yaml"

# Region name normalization map
REGION_ALIASES: dict[str, str] = {
    "eu": "europe",
    "us": "usa",
    "cn": "china",
    "jp": "japan",
    "kr": "south_korea",
    "korea": "south_korea",
    "in": "india",
    "vn": "vietnam",
}


def _load_sources() -> dict[str, list[dict[str, str]]]:
    """Load RSS sources from sources.yaml."""
    if not SOURCES_FILE.exists():
        logger.warning("sources.yaml not found at %s", SOURCES_FILE)
        return {}
    with open(SOURCES_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("rss_sources", {})


def _normalize_region(region: str) -> str:
    return REGION_ALIASES.get(region.lower(), region.lower())


class NewsRSSCollector(BaseCollector):
    """Collect top headlines from RSS feeds of major news publishers."""

    @property
    def platform_name(self) -> str:
        return "news_rss"

    async def collect(self, region: str | None = None) -> CollectionResult:
        sources = _load_sources()
        if not sources:
            return CollectionResult(
                platform=self.platform_name,
                region=region,
                error="No RSS sources configured. Check config/sources.yaml.",
            )

        # Filter by region if specified
        if region:
            norm = _normalize_region(region)
            filtered = {k: v for k, v in sources.items() if _normalize_region(k) == norm}
            if not filtered:
                return CollectionResult(
                    platform=self.platform_name,
                    region=region,
                    error=f"No RSS sources found for region '{region}'. "
                    f"Available: {', '.join(sources.keys())}",
                )
            sources = filtered

        items: list[TrendingItem] = []
        for region_key, feeds in sources.items():
            for feed_info in feeds:
                feed_items = await self._parse_feed(feed_info, region_key)
                items.extend(feed_items)

        return CollectionResult(
            platform=self.platform_name,
            region=region,
            items=items,
        )

    async def _parse_feed(
        self, feed_info: dict[str, str], region_key: str
    ) -> list[TrendingItem]:
        """Parse a single RSS feed and return trending items."""
        name = feed_info.get("name", "Unknown")
        url = feed_info.get("url", "")
        if not url:
            logger.warning("Skipping feed '%s' — no URL", name)
            return []

        logger.info("Parsing RSS feed: %s (%s)", name, url)
        try:
            feed = feedparser.parse(url)
        except Exception as exc:
            logger.error("Failed to parse feed %s: %s", name, exc)
            return []

        items: list[TrendingItem] = []
        for rank, entry in enumerate(feed.entries[:20], start=1):
            items.append(
                self._make_item(
                    title=entry.get("title", "Untitled"),
                    url=entry.get("link"),
                    source=name,
                    region=region_key,
                    rank=rank,
                    description=_clean_summary(entry.get("summary", "")),
                )
            )
        return items


def _clean_summary(text: str) -> str:
    """Strip HTML tags from feed summaries."""
    from bs4 import BeautifulSoup

    if not text:
        return ""
    return BeautifulSoup(text, "lxml").get_text(strip=True)[:500]
