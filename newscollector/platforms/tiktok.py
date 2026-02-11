"""TikTok trending collector via web scraping."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector
from newscollector.utils.http_client import create_client

logger = logging.getLogger(__name__)

TIKTOK_TRENDING_URL = "https://www.tiktok.com/api/trending/item/list/"
TIKTOK_DISCOVER_URL = "https://www.tiktok.com/node/share/discover"


class TikTokCollector(BaseCollector):
    """Collect trending content from TikTok.

    Uses TikTok's web API endpoints. These may change without notice.
    """

    @property
    def platform_name(self) -> str:
        return "tiktok"

    async def collect(self, region: str | None = None) -> CollectionResult:
        items: list[TrendingItem] = []

        async with create_client() as client:
            # Try the discover endpoint for trending hashtags/topics
            discover_items = await self._fetch_discover(client)
            items.extend(discover_items)

        if not items:
            return CollectionResult(
                platform=self.platform_name,
                region=region,
                error="Could not fetch TikTok trending data. "
                "The endpoints may have changed or access is restricted.",
            )

        return CollectionResult(
            platform=self.platform_name,
            region=region or "Global",
            items=items,
        )

    async def _fetch_discover(self, client: Any) -> list[TrendingItem]:
        """Scrape TikTok trending page for topics and hashtags."""
        logger.info("Fetching TikTok discover/trending page")

        try:
            resp = await client.get(
                "https://www.tiktok.com/discover",
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "Referer": "https://www.tiktok.com/",
                },
            )
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            logger.error("TikTok discover page request failed: %s", exc)
            return []

        items: list[TrendingItem] = []

        # Try to extract embedded JSON data from the page
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")

            # Look for script tags containing trending data
            for script in soup.find_all("script", {"id": "__UNIVERSAL_DATA_FOR_REHYDRATION__"}):
                try:
                    data = json.loads(script.string or "{}")
                    # Navigate the nested structure to find trending items
                    default_scope = data.get("__DEFAULT_SCOPE__", {})
                    for key, value in default_scope.items():
                        if isinstance(value, dict):
                            card_list = value.get("cardList", value.get("data", []))
                            if isinstance(card_list, list):
                                for rank, card in enumerate(card_list[:30], start=1):
                                    title = card.get("title", card.get("desc", ""))
                                    if title:
                                        items.append(
                                            self._make_item(
                                                title=title,
                                                url=card.get("link", card.get("url")),
                                                source="TikTok",
                                                region="Global",
                                                rank=rank,
                                                heat=card.get("stats", {}).get("playCount"),
                                                metadata={
                                                    "type": card.get("type", "topic"),
                                                },
                                            )
                                        )
                except (json.JSONDecodeError, AttributeError):
                    continue

            # Fallback: extract trending hashtags from page links
            if not items:
                tag_links = soup.select('a[href*="/tag/"], a[href*="hashtag"]')
                seen: set[str] = set()
                for rank, link in enumerate(tag_links[:30], start=1):
                    text = link.get_text(strip=True)
                    href = link.get("href", "")
                    if text and text not in seen:
                        seen.add(text)
                        full_url = href if href.startswith("http") else f"https://www.tiktok.com{href}"
                        items.append(
                            self._make_item(
                                title=text,
                                url=full_url,
                                source="TikTok",
                                region="Global",
                                rank=rank,
                                metadata={"type": "hashtag"},
                            )
                        )
        except Exception as exc:
            logger.error("Failed to parse TikTok discover page: %s", exc)

        return items
