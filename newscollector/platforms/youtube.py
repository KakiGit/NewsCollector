"""YouTube trending videos collector using Data API v3."""

from __future__ import annotations

import logging
from typing import Any

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector
from newscollector.utils.http_client import create_client

logger = logging.getLogger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Map regions to ISO 3166-1 alpha-2 region codes for YouTube
REGION_CODES: dict[str, list[dict[str, str]]] = {
    "global": [{"code": "US", "name": "United States"}],
    "usa": [{"code": "US", "name": "United States"}],
    "europe": [
        {"code": "GB", "name": "United Kingdom"},
        {"code": "FR", "name": "France"},
        {"code": "DE", "name": "Germany"},
        {"code": "ES", "name": "Spain"},
        {"code": "IT", "name": "Italy"},
        {"code": "NL", "name": "Netherlands"},
    ],
    "china": [],  # YouTube is blocked in China
    "japan": [{"code": "JP", "name": "Japan"}],
    "south_korea": [{"code": "KR", "name": "South Korea"}],
    "india": [{"code": "IN", "name": "India"}],
    "vietnam": [{"code": "VN", "name": "Vietnam"}],
}


class YouTubeCollector(BaseCollector):
    """Collect trending videos from YouTube Data API v3."""

    @property
    def platform_name(self) -> str:
        return "youtube"

    def _get_api_key(self) -> str | None:
        return self.config.get("youtube", {}).get("api_key")

    async def collect(
        self,
        region: str | None = None,
        topic: str | None = None,
    ) -> CollectionResult:
        api_key = self._get_api_key()
        if not api_key:
            return CollectionResult(
                platform=self.platform_name,
                region=region,
                error="YouTube API key not configured. "
                "Set 'youtube.api_key' in config.yaml.",
            )

        region_key = (region or "global").lower().replace(" ", "_")
        regions = REGION_CODES.get(region_key, REGION_CODES["global"])
        if not regions:
            return CollectionResult(
                platform=self.platform_name,
                region=region,
                error=f"YouTube is not available in region '{region}'.",
            )

        items: list[TrendingItem] = []
        async with create_client() as client:
            for reg in regions:
                reg_items = await self._fetch_trending(client, api_key, reg)
                items.extend(reg_items)

        return CollectionResult(
            platform=self.platform_name,
            region=region,
            items=items,
        )

    async def _fetch_trending(
        self, client: Any, api_key: str, region_info: dict[str, str]
    ) -> list[TrendingItem]:
        """Fetch trending videos for a single region."""
        region_code = region_info["code"]
        region_name = region_info["name"]
        logger.info("Fetching YouTube trending for %s", region_name)

        try:
            resp = await client.get(
                f"{YOUTUBE_API_BASE}/videos",
                params={
                    "part": "snippet,statistics",
                    "chart": "mostPopular",
                    "regionCode": region_code,
                    "maxResults": 25,
                    "key": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("YouTube API request failed for %s: %s", region_name, exc)
            return []

        items: list[TrendingItem] = []
        for rank, video in enumerate(data.get("items", []), start=1):
            snippet = video.get("snippet", {})
            stats = video.get("statistics", {})
            video_id = video.get("id", "")
            view_count = stats.get("viewCount")

            items.append(
                self._make_item(
                    title=snippet.get("title", "Untitled"),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    source=snippet.get("channelTitle", "Unknown"),
                    region=region_name,
                    rank=rank,
                    description=snippet.get("description", "")[:300],
                    heat=int(view_count) if view_count else None,
                    metadata={
                        "channel_id": snippet.get("channelId"),
                        "category_id": snippet.get("categoryId"),
                        "like_count": stats.get("likeCount"),
                        "comment_count": stats.get("commentCount"),
                        "published_at": snippet.get("publishedAt"),
                    },
                )
            )
        return items
