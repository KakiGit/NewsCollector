"""Instagram trending collector via Playwright scraping."""

from __future__ import annotations

import json
import logging
from typing import Any

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector

logger = logging.getLogger(__name__)


class InstagramCollector(BaseCollector):
    """Collect trending content from Instagram.

    Uses Playwright to scrape the Instagram explore page. This is fragile
    and may break if Instagram changes its page structure. Login may also
    be required for full access to explore content.
    """

    @property
    def platform_name(self) -> str:
        return "instagram"

    async def collect(self, region: str | None = None) -> CollectionResult:
        logger.info("Fetching Instagram trending via Playwright")

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return CollectionResult(
                platform=self.platform_name,
                region=region,
                error="Playwright is not installed. Run: pip install playwright && playwright install chromium",
            )

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
                )
                page = await context.new_page()

                # Navigate to Instagram explore page
                await page.goto("https://www.instagram.com/explore/", wait_until="networkidle", timeout=30000)

                # Wait for content to load
                await page.wait_for_timeout(3000)

                # Try to extract post data from the page
                # Instagram loads data dynamically; we intercept embedded JSON or scrape visible elements
                posts = await page.query_selector_all('article a[href*="/p/"], article a[href*="/reel/"]')

                for rank, post in enumerate(posts[:30], start=1):
                    href = await post.get_attribute("href")
                    url = f"https://www.instagram.com{href}" if href and not href.startswith("http") else href

                    # Try to get alt text from images inside the link
                    img = await post.query_selector("img")
                    alt_text = ""
                    if img:
                        alt_text = await img.get_attribute("alt") or ""

                    items.append(
                        self._make_item(
                            title=alt_text[:200] if alt_text else f"Trending post #{rank}",
                            url=url,
                            source="Instagram Explore",
                            region=region or "Global",
                            rank=rank,
                            metadata={"type": "explore_post"},
                        )
                    )

                await browser.close()
        except Exception as exc:
            return CollectionResult(
                platform=self.platform_name,
                region=region,
                error=f"Instagram scraping failed: {exc}. "
                "Note: Instagram may require login for explore access.",
            )

        return CollectionResult(
            platform=self.platform_name,
            region=region or "Global",
            items=items,
        )
