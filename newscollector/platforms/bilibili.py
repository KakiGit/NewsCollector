"""Bilibili trending/hot videos collector using public API."""

from __future__ import annotations

import logging
from typing import Any

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector
from newscollector.utils.http_client import create_client

logger = logging.getLogger(__name__)

# Bilibili public API endpoints
BILIBILI_HOT_URL = "https://api.bilibili.com/x/web-interface/ranking/v2"
BILIBILI_HOT_SEARCH_URL = "https://s.search.bilibili.com/main/hotword"


class BilibiliCollector(BaseCollector):
    """Collect trending videos and hot searches from Bilibili."""

    @property
    def platform_name(self) -> str:
        return "bilibili"

    async def collect(self, region: str | None = None) -> CollectionResult:
        items: list[TrendingItem] = []

        async with create_client() as client:
            # Fetch ranking (hot videos)
            ranking_items = await self._fetch_ranking(client)
            items.extend(ranking_items)

            # Fetch hot search keywords
            hot_search_items = await self._fetch_hot_search(client)
            items.extend(hot_search_items)

        return CollectionResult(
            platform=self.platform_name,
            region=region or "China",
            items=items,
        )

    async def _fetch_ranking(self, client: Any) -> list[TrendingItem]:
        """Fetch Bilibili video ranking."""
        logger.info("Fetching Bilibili video ranking")

        try:
            resp = await client.get(
                BILIBILI_HOT_URL,
                params={"rid": 0, "type": "all"},
                headers={"Referer": "https://www.bilibili.com"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("Bilibili ranking request failed: %s", exc)
            return []

        items: list[TrendingItem] = []
        result_list = data.get("data", {}).get("list", [])
        for rank, video in enumerate(result_list[:30], start=1):
            stat = video.get("stat", {})
            items.append(
                self._make_item(
                    title=video.get("title", "Untitled"),
                    url=f"https://www.bilibili.com/video/{video.get('bvid', '')}",
                    source=video.get("owner", {}).get("name", "Unknown"),
                    region="China",
                    rank=rank,
                    description=video.get("desc", "")[:300],
                    heat=stat.get("view"),
                    metadata={
                        "bvid": video.get("bvid"),
                        "like": stat.get("like"),
                        "danmaku": stat.get("danmaku"),
                        "reply": stat.get("reply"),
                        "coin": stat.get("coin"),
                        "duration": video.get("duration"),
                    },
                )
            )
        return items

    async def _fetch_hot_search(self, client: Any) -> list[TrendingItem]:
        """Fetch Bilibili hot search keywords."""
        logger.info("Fetching Bilibili hot search keywords")

        try:
            resp = await client.get(
                BILIBILI_HOT_SEARCH_URL,
                headers={"Referer": "https://www.bilibili.com"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("Bilibili hot search request failed: %s", exc)
            return []

        items: list[TrendingItem] = []
        for rank, entry in enumerate(data.get("list", [])[:20], start=1):
            keyword = entry.get("keyword", entry.get("show_name", ""))
            items.append(
                self._make_item(
                    title=keyword,
                    url=f"https://search.bilibili.com/all?keyword={keyword}",
                    source="Bilibili Hot Search",
                    region="China",
                    rank=rank,
                    heat=entry.get("hot_id"),
                    metadata={"icon": entry.get("icon"), "type": "hot_search"},
                )
            )
        return items
