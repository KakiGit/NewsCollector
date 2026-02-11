"""NewsAPI.org collector for top headlines."""

from __future__ import annotations

import logging
from typing import Any

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector
from newscollector.utils.http_client import create_client

logger = logging.getLogger(__name__)

NEWSAPI_BASE = "https://newsapi.org/v2"

# Map region names to NewsAPI country codes
REGION_TO_COUNTRIES: dict[str, list[str]] = {
    "europe": ["gb", "fr", "de", "it", "es", "nl"],
    "usa": ["us"],
    "china": ["cn"],
    "japan": ["jp"],
    "south_korea": ["kr"],
    "india": ["in"],
    "vietnam": [],  # NewsAPI has limited Vietnam support
}

COUNTRY_NAMES: dict[str, str] = {
    "gb": "United Kingdom",
    "fr": "France",
    "de": "Germany",
    "it": "Italy",
    "es": "Spain",
    "nl": "Netherlands",
    "us": "United States",
    "cn": "China",
    "jp": "Japan",
    "kr": "South Korea",
    "in": "India",
}


class NewsAPICollector(BaseCollector):
    """Collect top headlines from NewsAPI.org."""

    @property
    def platform_name(self) -> str:
        return "news_api"

    def _get_api_key(self) -> str | None:
        return self.config.get("newsapi", {}).get("api_key")

    async def collect(self, region: str | None = None) -> CollectionResult:
        api_key = self._get_api_key()
        if not api_key:
            return CollectionResult(
                platform=self.platform_name,
                region=region,
                error="NewsAPI key not configured. Set 'newsapi.api_key' in config.yaml.",
            )

        # Determine which countries to fetch
        if region:
            region_lower = region.lower().replace(" ", "_")
            countries = REGION_TO_COUNTRIES.get(region_lower, [])
            if not countries:
                return CollectionResult(
                    platform=self.platform_name,
                    region=region,
                    error=f"No NewsAPI country mapping for region '{region}'. "
                    f"Available: {', '.join(REGION_TO_COUNTRIES.keys())}",
                )
        else:
            # Fetch from all supported countries
            countries = []
            for country_list in REGION_TO_COUNTRIES.values():
                countries.extend(country_list)

        items: list[TrendingItem] = []
        async with create_client() as client:
            for country_code in countries:
                country_items = await self._fetch_country(client, api_key, country_code)
                items.extend(country_items)

        return CollectionResult(
            platform=self.platform_name,
            region=region,
            items=items,
        )

    async def _fetch_country(
        self, client: Any, api_key: str, country_code: str
    ) -> list[TrendingItem]:
        """Fetch top headlines for a single country."""
        country_name = COUNTRY_NAMES.get(country_code, country_code.upper())
        logger.info("Fetching NewsAPI headlines for %s", country_name)

        try:
            resp = await client.get(
                f"{NEWSAPI_BASE}/top-headlines",
                params={"country": country_code, "pageSize": 20},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("NewsAPI request failed for %s: %s", country_code, exc)
            return []

        items: list[TrendingItem] = []
        for rank, article in enumerate(data.get("articles", []), start=1):
            source_name = article.get("source", {}).get("name", "Unknown")
            items.append(
                self._make_item(
                    title=article.get("title", "Untitled"),
                    url=article.get("url"),
                    source=source_name,
                    region=country_name,
                    rank=rank,
                    description=article.get("description", ""),
                    metadata={
                        "author": article.get("author"),
                        "published_at": article.get("publishedAt"),
                        "image_url": article.get("urlToImage"),
                    },
                )
            )
        return items
