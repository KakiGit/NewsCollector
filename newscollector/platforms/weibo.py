"""Weibo hot search collector using public endpoint."""

from __future__ import annotations

import logging
from typing import Any

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector
from newscollector.utils.http_client import create_client

logger = logging.getLogger(__name__)

# Weibo's public hot search endpoint (no auth required)
WEIBO_HOT_SEARCH_URL = "https://weibo.com/ajax/side/hotSearch"


class WeiboCollector(BaseCollector):
    """Collect hot search topics from Weibo."""

    @property
    def platform_name(self) -> str:
        return "weibo"

    async def collect(self, region: str | None = None) -> CollectionResult:
        logger.info("Fetching Weibo hot search list")

        async with create_client() as client:
            try:
                resp = await client.get(
                    WEIBO_HOT_SEARCH_URL,
                    headers={"Referer": "https://weibo.com"},
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                return CollectionResult(
                    platform=self.platform_name,
                    region="China",
                    error=f"Weibo hot search request failed: {exc}",
                )

        realtime = data.get("data", {}).get("realtime", [])
        items: list[TrendingItem] = []
        for rank, entry in enumerate(realtime[:50], start=1):
            word = entry.get("word", entry.get("note", ""))
            label_name = entry.get("label_name", "")
            raw_hot = entry.get("raw_hot", entry.get("num", 0))

            items.append(
                self._make_item(
                    title=word,
                    url=f"https://s.weibo.com/weibo?q=%23{word}%23",
                    source="Weibo",
                    region="China",
                    rank=rank,
                    heat=int(raw_hot) if raw_hot else None,
                    metadata={
                        "label": label_name,
                        "category": entry.get("category", ""),
                        "is_hot": entry.get("is_hot", 0),
                        "is_new": entry.get("is_new", 0),
                    },
                )
            )

        return CollectionResult(
            platform=self.platform_name,
            region="China",
            items=items,
        )
