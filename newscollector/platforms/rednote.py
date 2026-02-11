"""RedNote (Xiaohongshu / 小红书) trending collector via Playwright scraping."""

from __future__ import annotations

import logging
from typing import Any

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector

logger = logging.getLogger(__name__)

REDNOTE_EXPLORE_URL = "https://www.xiaohongshu.com/explore"


class RedNoteCollector(BaseCollector):
    """Collect trending topics from RedNote (Xiaohongshu).

    Uses Playwright to scrape the explore/hot page. Xiaohongshu is
    primarily a Chinese platform with no public API.
    """

    @property
    def platform_name(self) -> str:
        return "rednote"

    async def collect(self, region: str | None = None) -> CollectionResult:
        logger.info("Fetching RedNote (Xiaohongshu) trending via Playwright")

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
                    locale="zh-CN",
                )
                page = await context.new_page()

                await page.goto(REDNOTE_EXPLORE_URL, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(3000)

                # Attempt to scrape note cards from the explore page
                # Xiaohongshu uses a feed of "note" cards
                note_cards = await page.query_selector_all(
                    'section.note-item, div[class*="note-item"], a[class*="cover"]'
                )

                for rank, card in enumerate(note_cards[:30], start=1):
                    title = ""
                    url = None

                    # Try to get the title from various possible elements
                    title_el = await card.query_selector(
                        'span[class*="title"], div[class*="title"], p[class*="desc"]'
                    )
                    if title_el:
                        title = (await title_el.inner_text()).strip()

                    # Get the link
                    link_el = card if await card.get_attribute("href") else await card.query_selector("a")
                    if link_el:
                        href = await link_el.get_attribute("href")
                        if href:
                            url = href if href.startswith("http") else f"https://www.xiaohongshu.com{href}"

                    # Get author info
                    author_el = await card.query_selector(
                        'span[class*="author"], span[class*="name"]'
                    )
                    author = ""
                    if author_el:
                        author = (await author_el.inner_text()).strip()

                    # Get like count
                    like_el = await card.query_selector(
                        'span[class*="like"], span[class*="count"]'
                    )
                    like_text = ""
                    if like_el:
                        like_text = (await like_el.inner_text()).strip()

                    if title or url:
                        items.append(
                            self._make_item(
                                title=title or f"RedNote post #{rank}",
                                url=url,
                                source=author or "RedNote",
                                region="China",
                                rank=rank,
                                metadata={
                                    "likes": like_text,
                                    "type": "explore_note",
                                },
                            )
                        )

                await browser.close()
        except Exception as exc:
            return CollectionResult(
                platform=self.platform_name,
                region="China",
                error=f"RedNote scraping failed: {exc}",
            )

        return CollectionResult(
            platform=self.platform_name,
            region="China",
            items=items,
        )
