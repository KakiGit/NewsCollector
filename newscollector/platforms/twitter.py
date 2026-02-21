"""X/Twitter trending topics collector using API v2."""

from __future__ import annotations

import logging
from typing import Any

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector
from newscollector.utils.http_client import create_client

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.twitter.com/2"

# WOEID (Where On Earth ID) for trending topics
# See: https://developer.twitter.com/en/docs/twitter-api/v1/trends/locations-with-trending-topics
REGION_WOEIDS: dict[str, list[dict[str, Any]]] = {
    "global": [{"woeid": 1, "name": "Worldwide"}],
    "usa": [{"woeid": 23424977, "name": "United States"}],
    "europe": [
        {"woeid": 23424975, "name": "United Kingdom"},
        {"woeid": 23424819, "name": "France"},
        {"woeid": 23424829, "name": "Germany"},
    ],
    "japan": [{"woeid": 23424856, "name": "Japan"}],
    "south_korea": [{"woeid": 23424868, "name": "South Korea"}],
    "india": [{"woeid": 23424848, "name": "India"}],
}


class TwitterCollector(BaseCollector):
    """Collect trending topics from X/Twitter API v2."""

    @property
    def platform_name(self) -> str:
        return "twitter"

    def _get_bearer_token(self) -> str | None:
        return self.config.get("twitter", {}).get("bearer_token")

    async def collect(
        self,
        region: str | None = None,
        topic: str | None = None,
    ) -> CollectionResult:
        bearer = self._get_bearer_token()
        if not bearer:
            return CollectionResult(
                platform=self.platform_name,
                region=region,
                error="Twitter bearer token not configured. "
                "Set 'twitter.bearer_token' in config.yaml.",
            )

        region_key = (region or "global").lower().replace(" ", "_")
        locations = REGION_WOEIDS.get(region_key, REGION_WOEIDS["global"])

        items: list[TrendingItem] = []
        async with create_client(
            headers={"Authorization": f"Bearer {bearer}"}
        ) as client:
            for loc in locations:
                loc_items = await self._fetch_trends(client, loc)
                items.extend(loc_items)

        return CollectionResult(
            platform=self.platform_name,
            region=region,
            items=items,
        )

    async def _fetch_trends(
        self, client: Any, location: dict[str, Any]
    ) -> list[TrendingItem]:
        """Fetch trends for a single WOEID location.

        Note: The v1.1 trends endpoint is used here because v2 does not yet
        have a direct replacement. Twitter API access tier must support this.
        """
        woeid = location["woeid"]
        loc_name = location["name"]
        logger.info("Fetching Twitter trends for %s (WOEID: %d)", loc_name, woeid)

        try:
            # The trends endpoint is still v1.1
            resp = await client.get(
                "https://api.twitter.com/1.1/trends/place.json",
                params={"id": woeid},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("Twitter API request failed for %s: %s", loc_name, exc)
            return []

        items: list[TrendingItem] = []
        if data and isinstance(data, list) and len(data) > 0:
            trends = data[0].get("trends", [])
            for rank, trend in enumerate(trends[:50], start=1):
                tweet_volume = trend.get("tweet_volume")
                items.append(
                    self._make_item(
                        title=trend.get("name", ""),
                        url=trend.get("url"),
                        source="Twitter",
                        region=loc_name,
                        rank=rank,
                        heat=tweet_volume,
                        metadata={"query": trend.get("query", "")},
                    )
                )
        return items
