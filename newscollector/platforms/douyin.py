"""Douyin (抖音) hot list collector via Playwright scraping."""

from __future__ import annotations

import json
import logging
from typing import Any

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector
from newscollector.utils.http_client import create_client

logger = logging.getLogger(__name__)

# Douyin's hot list page
DOUYIN_HOT_URL = "https://www.douyin.com/hot"
# Douyin hot board API (may work without browser)
DOUYIN_HOT_API = "https://www.douyin.com/aweme/v1/web/hot/search/list/"


class DouyinCollector(BaseCollector):
    """Collect hot/trending topics from Douyin (Chinese TikTok).

    First tries the public web API, falls back to Playwright scraping.
    """

    @property
    def platform_name(self) -> str:
        return "douyin"

    async def collect(self, region: str | None = None) -> CollectionResult:
        # Try API first
        items = await self._fetch_via_api()

        # Fall back to Playwright if API fails
        if not items:
            items = await self._fetch_via_playwright()

        if not items:
            return CollectionResult(
                platform=self.platform_name,
                region="China",
                error="Could not fetch Douyin hot list via API or browser scraping.",
            )

        return CollectionResult(
            platform=self.platform_name,
            region="China",
            items=items,
        )

    async def _fetch_via_api(self) -> list[TrendingItem]:
        """Try fetching Douyin hot list via web API."""
        logger.info("Trying Douyin hot list API")

        async with create_client() as client:
            try:
                resp = await client.get(
                    DOUYIN_HOT_API,
                    headers={
                        "Referer": "https://www.douyin.com/",
                        "Cookie": "",  # May need valid cookies
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.debug("Douyin API request failed (expected): %s", exc)
                return []

        word_list = data.get("data", {}).get("word_list", [])
        items: list[TrendingItem] = []
        for rank, entry in enumerate(word_list[:50], start=1):
            word = entry.get("word", "")
            hot_value = entry.get("hot_value", 0)
            sentence_id = entry.get("sentence_id", "")

            items.append(
                self._make_item(
                    title=word,
                    url=f"https://www.douyin.com/search/{word}",
                    source="Douyin",
                    region="China",
                    rank=rank,
                    heat=int(hot_value) if hot_value else None,
                    metadata={
                        "sentence_id": sentence_id,
                        "label": entry.get("label", ""),
                    },
                )
            )
        return items

    async def _fetch_via_playwright(self) -> list[TrendingItem]:
        """Fall back to Playwright-based scraping for Douyin hot list."""
        logger.info("Fetching Douyin hot list via Playwright")

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright not installed, cannot scrape Douyin")
            return []

        items: list[TrendingItem] = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1920, "height": 1080},
                    locale="zh-CN",
                )
                page = await context.new_page()

                await page.goto(DOUYIN_HOT_URL, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(3000)

                # Look for hot list items on the page
                hot_items = await page.query_selector_all(
                    'div[class*="hot-list"] li, '
                    'ul[class*="rank-list"] li, '
                    'div[class*="trending"] a'
                )

                for rank, item in enumerate(hot_items[:50], start=1):
                    text = (await item.inner_text()).strip()
                    link_el = await item.query_selector("a")
                    href = None
                    if link_el:
                        href = await link_el.get_attribute("href")
                        if href and not href.startswith("http"):
                            href = f"https://www.douyin.com{href}"

                    # Clean up the text (may include rank numbers)
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    title = ""
                    for line in lines:
                        # Skip pure numbers (rank indicators)
                        if not line.isdigit():
                            title = line
                            break

                    if title:
                        items.append(
                            self._make_item(
                                title=title,
                                url=href or f"https://www.douyin.com/search/{title}",
                                source="Douyin",
                                region="China",
                                rank=rank,
                                metadata={"type": "hot_list"},
                            )
                        )

                await browser.close()
        except Exception as exc:
            logger.error("Douyin Playwright scraping failed: %s", exc)

        return items
