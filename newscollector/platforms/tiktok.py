"""TikTok trending collector via Playwright scraping."""

from __future__ import annotations

import logging
from typing import Any

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector
from newscollector.utils.ai import extract_items_from_html, is_ai_configured
from newscollector.utils.web_content import fetch_html, truncate_text

logger = logging.getLogger(__name__)

TIKTOK_DISCOVER_URL = "https://www.tiktok.com/discover"


class TikTokCollector(BaseCollector):
    """Collect trending content from TikTok.

    Uses Playwright to scrape the TikTok discover page, which contains
    trending hashtags/topics and popular creators.
    """

    @property
    def platform_name(self) -> str:
        return "tiktok"

    async def collect(
        self,
        region: str | None = None,
        topic: str | None = None,
    ) -> CollectionResult:
        logger.info("Fetching TikTok trending via Playwright")

        ai_items = await self._collect_via_ai()
        if ai_items:
            return CollectionResult(
                platform=self.platform_name,
                region=region or "Global",
                items=ai_items,
            )

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return CollectionResult(
                platform=self.platform_name,
                region=region,
                error="Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium",
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

                await page.goto(
                    TIKTOK_DISCOVER_URL,
                    wait_until="networkidle",
                    timeout=30000,
                )
                await page.wait_for_timeout(5000)

                # 1) Trending topics / hashtags
                topic_items = await self._extract_topics(page)
                items.extend(topic_items)

                # 2) Trending creators
                creator_items = await self._extract_creators(page)
                items.extend(creator_items)

                await browser.close()
        except Exception as exc:
            return CollectionResult(
                platform=self.platform_name,
                region=region or "Global",
                error=f"TikTok scraping failed: {exc}",
            )

        if not items:
            return CollectionResult(
                platform=self.platform_name,
                region=region or "Global",
                error="Could not extract TikTok trending data. "
                "The page structure may have changed.",
            )

        return CollectionResult(
            platform=self.platform_name,
            region=region or "Global",
            items=items,
        )

    async def _extract_topics(self, page: Any) -> list[TrendingItem]:
        """Extract trending hashtag/topic feeds from the discover page."""
        logger.info("Extracting TikTok trending topics")

        try:
            topics = await page.evaluate("""
                () => {
                    const results = [];
                    const feedItems = document.querySelectorAll(
                        '[data-e2e="explore-feed-item"]'
                    );
                    feedItems.forEach((item, i) => {
                        const titleEl = item.querySelector(
                            '[data-e2e="explore-feed-title"]'
                        );
                        const descEl = item.querySelector(
                            '[data-e2e="explore-feed-desc"]'
                        );
                        const videos = item.querySelectorAll(
                            '[data-e2e="explore-feed-video"] a'
                        );
                        const videoLinks = [];
                        videos.forEach(v => {
                            if (v.href) videoLinks.push(v.href);
                        });
                        const title = titleEl?.textContent?.trim() || '';
                        if (title) {
                            results.push({
                                title: title,
                                desc: descEl?.textContent?.trim()?.substring(0, 300) || '',
                                videoCount: videoLinks.length,
                                sampleVideo: videoLinks[0] || null,
                            });
                        }
                    });
                    return results;
                }
            """)
        except Exception as exc:
            logger.error("Failed to extract TikTok topics: %s", exc)
            return []

        items: list[TrendingItem] = []
        for rank, topic in enumerate(topics, start=1):
            title = topic["title"]
            # Build a URL: hashtag titles start with #
            tag_name = title.lstrip("#")
            url = f"https://www.tiktok.com/tag/{tag_name}"

            items.append(
                self._make_item(
                    title=title,
                    url=url,
                    source="TikTok",
                    region="Global",
                    rank=rank,
                    description=topic.get("desc") or None,
                    metadata={
                        "type": "trending_topic",
                        "video_count": topic.get("videoCount", 0),
                        "sample_video": topic.get("sampleVideo"),
                    },
                )
            )

        logger.info("Extracted %d trending topics from TikTok", len(items))
        return items

    async def _extract_creators(self, page: Any) -> list[TrendingItem]:
        """Extract trending/popular creators from the discover page."""
        logger.info("Extracting TikTok trending creators")

        try:
            creators = await page.evaluate("""
                () => {
                    const results = [];
                    const items = document.querySelectorAll(
                        '[data-e2e="discover-user-item"]'
                    );
                    items.forEach((item, i) => {
                        const titleEl = item.querySelector(
                            '[data-e2e="discover-user-title"]'
                        );
                        const subEl = item.querySelector(
                            '[data-e2e="discover-user-subtitle"]'
                        );
                        const followersEl = item.querySelector(
                            '[data-e2e="discover-user-followers-vv"]'
                        );
                        const link = item.querySelector('a[href]');
                        results.push({
                            name: titleEl?.textContent?.trim() || '',
                            username: subEl?.textContent?.trim() || '',
                            followers: followersEl?.textContent?.trim() || '',
                            href: link?.getAttribute('href') || '',
                        });
                    });
                    return results;
                }
            """)
        except Exception as exc:
            logger.error("Failed to extract TikTok creators: %s", exc)
            return []

        items: list[TrendingItem] = []
        for rank, creator in enumerate(creators, start=1):
            name = creator.get("name", "")
            username = creator.get("username", "")
            if not name and not username:
                continue

            title = f"{name} ({username})" if name and username else (name or username)
            handle = username.lstrip("@")
            url = f"https://www.tiktok.com/@{handle}" if handle else None

            items.append(
                self._make_item(
                    title=title,
                    url=url,
                    source="TikTok",
                    region="Global",
                    rank=rank,
                    description=f"Followers: {creator.get('followers', 'N/A')}",
                    metadata={
                        "type": "trending_creator",
                        "username": username,
                        "followers": creator.get("followers", ""),
                    },
                )
            )

        logger.info("Extracted %d trending creators from TikTok", len(items))
        return items

    async def _collect_via_ai(self) -> list[TrendingItem]:
        ai_cfg = (self.config.get("ai") or {}) if self.config else {}
        if not is_ai_configured(self.config):
            return []
        if not ai_cfg.get("ai_platform_collection_enabled", True):
            return []

        base_url = ai_cfg.get("ai_base_url", "")
        model = ai_cfg.get("ai_model", "")
        api_key = ai_cfg.get("ai_api_key", "")
        response_language = ai_cfg.get("ai_response_language") or None
        html_char_limit = int(ai_cfg.get("ai_html_char_limit", 160000))
        ai_input_limit = int(ai_cfg.get("ai_extract_html_prompt_char_limit", 8000))
        max_items = int(ai_cfg.get("ai_platform_extract_max_items", 30))
        min_items = int(ai_cfg.get("ai_platform_min_items_before_fallback", 6))
        ai_timeout = float(ai_cfg.get("ai_request_timeout", 60.0))

        html = await fetch_html(TIKTOK_DISCOVER_URL, char_limit=html_char_limit)
        if not html:
            return []
        html_excerpt = truncate_text(html, char_limit=ai_input_limit)

        extracted = await extract_items_from_html(
            platform=self.platform_name,
            page_url=TIKTOK_DISCOVER_URL,
            html_excerpt=html_excerpt,
            base_url=base_url,
            model=model,
            api_key=api_key,
            response_language=response_language,
            max_items=max_items,
            timeout=ai_timeout,
        )
        if len(extracted) < min_items:
            logger.info(
                "TikTok AI extraction returned %d item(s); falling back to selectors",
                len(extracted),
            )
            return []

        items: list[TrendingItem] = []
        for idx, entry in enumerate(extracted, start=1):
            rank = entry.get("rank")
            try:
                rank = int(rank) if rank is not None else idx
            except (TypeError, ValueError):
                rank = idx
            items.append(
                self._make_item(
                    title=entry["title"],
                    url=entry.get("url"),
                    source=entry.get("source") or "TikTok",
                    region="Global",
                    rank=rank,
                    description=entry.get("description"),
                    heat=entry.get("heat"),
                    metadata=entry.get("metadata") or {"type": "ai_html_extract"},
                )
            )
        return items
