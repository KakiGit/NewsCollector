"""RedNote (Xiaohongshu / 小红书) trending collector via Playwright scraping."""

from __future__ import annotations

import logging
import random
from typing import Any

from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector
from newscollector.utils.ai import extract_items_from_html, is_ai_configured
from newscollector.utils.web_content import truncate_text

logger = logging.getLogger(__name__)

REDNOTE_EXPLORE_URL = "https://www.xiaohongshu.com/explore"

# Stealth JavaScript to hide automation signals
STEALTH_JS = """
() => {
    // Override webdriver property
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });
    
    // Override plugins to look more realistic
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', filename: 'internal-nacl-plugin' }
        ]
    });
    
    // Override languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en-US', 'en']
    });
    
    // Override permissions
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
    
    // Add chrome runtime
    window.chrome = {
        runtime: {}
    };
    
    // Override connection rtt
    Object.defineProperty(navigator, 'connection', {
        get: () => ({
            effectiveType: '4g',
            rtt: 50,
            downlink: 10,
            saveData: false
        })
    });
}
"""


class RedNoteCollector(BaseCollector):
    """Collect trending topics from RedNote (Xiaohongshu).

    Uses Playwright to scrape the explore/hot page. Xiaohongshu is
    primarily a Chinese platform with no public API.

    Due to strong bot detection, this collector requires session cookies
    to be provided in the config file under rednote.cookies as a string.
    """

    @property
    def platform_name(self) -> str:
        return "rednote"

    def _get_cookies_from_config(self) -> list[dict[str, Any]]:
        """Parse cookies from config string into Playwright cookie format."""
        rednote_cfg = (self.config.get("rednote") or {}) if self.config else {}
        cookie_str = rednote_cfg.get("cookies", "")
        if not cookie_str:
            return []

        cookies = []
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                name, value = part.split("=", 1)
                cookies.append(
                    {
                        "name": name.strip(),
                        "value": value.strip(),
                        "domain": ".xiaohongshu.com",
                        "path": "/",
                    }
                )
        return cookies

    async def collect(
        self,
        region: str | None = None,
        topic: str | None = None,
    ) -> CollectionResult:
        logger.info("Fetching RedNote (Xiaohongshu) trending via Playwright")

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return CollectionResult(
                platform=self.platform_name,
                region=region,
                error="Playwright is not installed. Run: pip install playwright && playwright install chromium",
            )

        # Get cookies from config
        cookies = self._get_cookies_from_config()
        if cookies:
            logger.info("Using %d cookies from config for RedNote", len(cookies))

        items: list[TrendingItem] = []
        rendered_html: str = ""

        try:
            async with async_playwright() as p:
                # Use non-headless mode with headless flag via args for better stealth
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-infobars",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1920, "height": 1080},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    color_scheme="light",
                    device_scale_factor=1,
                    is_mobile=False,
                    has_touch=False,
                )

                # Add cookies if available
                if cookies:
                    await context.add_cookies(cookies)

                page = await context.new_page()

                # Inject stealth script before navigation
                await page.add_init_script(STEALTH_JS)

                # Navigate with realistic behavior
                await page.goto(
                    REDNOTE_EXPLORE_URL, wait_until="domcontentloaded", timeout=30000
                )

                # Wait for content with random human-like delay
                await page.wait_for_timeout(random.randint(2000, 4000))

                # Check if we hit a verification page
                page_title = await page.title()
                if "验证" in page_title or "安全" in page_title:
                    logger.warning("RedNote verification page detected")
                    if not cookies:
                        await browser.close()
                        return CollectionResult(
                            platform=self.platform_name,
                            region="China",
                            error=(
                                "RedNote requires session cookies to bypass bot detection. "
                                "Add your browser cookies to config.yaml under 'rednote.cookies'."
                            ),
                        )
                    # With cookies, try waiting for redirect
                    await page.wait_for_timeout(3000)
                    try:
                        await page.mouse.move(
                            random.randint(100, 500), random.randint(100, 500)
                        )
                        await page.wait_for_timeout(1000)
                    except Exception:
                        pass

                # Wait for network to settle
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

                await page.wait_for_timeout(2000)

                # Re-check if still on verification page
                page_title = await page.title()
                if "验证" in page_title or "安全" in page_title:
                    await browser.close()
                    return CollectionResult(
                        platform=self.platform_name,
                        region="China",
                        error=(
                            "RedNote verification page detected. "
                            "Your cookies may be expired. Please update rednote.cookies in config.yaml "
                            "with fresh cookies from your browser."
                        ),
                    )

                # Get rendered HTML for AI extraction
                rendered_html = await page.content()

                # Try AI extraction first if configured
                ai_items = await self._extract_via_ai(rendered_html)
                if ai_items:
                    await browser.close()
                    return CollectionResult(
                        platform=self.platform_name,
                        region="China",
                        items=ai_items,
                    )

                # Fall back to selector-based scraping
                # Xiaohongshu uses a feed of "note" cards - select CONTAINER elements only
                # (not child <a> elements) to avoid title/URL mismatch
                note_cards = await page.query_selector_all(
                    "section.note-item, "
                    'div[class*="note-item"], '
                    'div[class*="feed-item"], '
                    'div[class*="explore-feed"] > div, '
                    'div[class*="feeds-page"] section'
                )

                # Track seen note IDs to deduplicate (same note can have URLs with/without xsec_token)
                # Key: note_id, Value: dict with title, url, author, likes
                seen_notes: dict[str, dict[str, Any]] = {}

                def extract_note_id(url: str) -> str | None:
                    """Extract note ID from URL like /explore/645b8f4e00000000140266e3"""
                    import re

                    match = re.search(r"/explore/([a-f0-9]+)", url)
                    if match:
                        return match.group(1)
                    match = re.search(r"/discovery/item/([a-f0-9]+)", url)
                    if match:
                        return match.group(1)
                    return None

                for card in note_cards[:50]:
                    title = ""
                    url = None
                    best_url = None

                    # Find ALL links in the card and pick the best one
                    # Prefer links with xsec_token (they work), skip user profile links
                    link_els = await card.query_selector_all("a[href]")
                    for link_el in link_els:
                        href = await link_el.get_attribute("href")
                        if not href:
                            continue
                        # Skip user profile links
                        if "/user/profile/" in href:
                            continue
                        # Only consider explore/discovery links (actual posts)
                        if "/explore/" not in href and "/discovery/item/" not in href:
                            continue

                        full_url = (
                            href
                            if href.startswith("http")
                            else f"https://www.xiaohongshu.com{href}"
                        )

                        # Prefer URL with xsec_token (it actually works)
                        if "xsec_token=" in full_url:
                            best_url = full_url
                            break  # This is the best, stop looking
                        elif not best_url:
                            best_url = full_url

                    url = best_url
                    if not url:
                        continue

                    # Extract note ID for deduplication
                    note_id = extract_note_id(url)
                    if not note_id:
                        continue

                    # Get title from the container
                    title_el = await card.query_selector(
                        'span[class*="title"], '
                        'div[class*="title"], '
                        'p[class*="desc"], '
                        "span.title, "
                        "div.title, "
                        "a.title, "
                        "footer span:first-child"
                    )
                    if title_el:
                        title = (await title_el.inner_text()).strip()

                    # If no title found, try getting text from the card itself
                    if not title:
                        try:
                            card_text = await card.inner_text()
                            # Get first non-empty line as title
                            lines = [
                                line.strip()
                                for line in card_text.split("\n")
                                if line.strip()
                            ]
                            if lines:
                                # Skip lines that look like counts (e.g., "1.2万")
                                for line in lines:
                                    if (
                                        not line.replace(".", "")
                                        .replace("万", "")
                                        .replace("k", "")
                                        .replace("K", "")
                                        .isdigit()
                                    ):
                                        title = line[:100]  # Limit length
                                        break
                        except Exception:
                            pass

                    # Get author info (but not from profile links)
                    author_el = await card.query_selector(
                        'span[class*="author"], '
                        'span[class*="name"], '
                        'div[class*="author"]'
                    )
                    author = ""
                    if author_el:
                        author = (await author_el.inner_text()).strip()

                    # Get like count
                    like_el = await card.query_selector(
                        'span[class*="like"], '
                        'span[class*="count"], '
                        'span[class*="interact"]'
                    )
                    like_text = ""
                    if like_el:
                        like_text = (await like_el.inner_text()).strip()

                    # Deduplicate by note ID, merge info, prefer URL with xsec_token
                    if note_id in seen_notes:
                        existing = seen_notes[note_id]
                        # Update title if we have a better one
                        if title and not existing.get("title"):
                            existing["title"] = title
                        # Prefer URL with xsec_token
                        if "xsec_token=" in url and "xsec_token=" not in existing.get(
                            "url", ""
                        ):
                            existing["url"] = url
                        # Update author/likes if missing
                        if author and not existing.get("author"):
                            existing["author"] = author
                        if like_text and not existing.get("likes"):
                            existing["likes"] = like_text
                    else:
                        seen_notes[note_id] = {
                            "title": title,
                            "url": url,
                            "author": author,
                            "likes": like_text,
                        }

                # Build final items from deduplicated notes
                for rank, (note_id, data) in enumerate(seen_notes.items(), start=1):
                    if rank > 30:
                        break
                    items.append(
                        self._make_item(
                            title=data["title"] or f"RedNote post #{rank}",
                            url=data["url"],
                            source=data["author"] or "RedNote",
                            region="China",
                            rank=rank,
                            metadata={
                                "likes": data["likes"],
                                "type": "explore_note",
                            },
                        )
                    )

                await browser.close()
        except Exception as exc:
            logger.error("RedNote scraping failed: %s", exc)
            return CollectionResult(
                platform=self.platform_name,
                region="China",
                error=f"RedNote scraping failed: {exc}",
            )

        if not items:
            return CollectionResult(
                platform=self.platform_name,
                region="China",
                error="RedNote scraping returned no items. Page structure may have changed.",
            )

        return CollectionResult(
            platform=self.platform_name,
            region="China",
            items=items,
        )

    async def _extract_via_ai(self, rendered_html: str) -> list[TrendingItem]:
        """Try AI-based extraction from rendered HTML."""
        ai_cfg = (self.config.get("ai") or {}) if self.config else {}
        if not is_ai_configured(self.config):
            return []
        if not ai_cfg.get("ai_platform_collection_enabled", True):
            return []

        base_url = ai_cfg.get("ai_base_url", "")
        model = ai_cfg.get("ai_model", "")
        api_key = ai_cfg.get("ai_api_key", "")
        response_language = ai_cfg.get("ai_response_language") or None
        ai_input_limit = int(ai_cfg.get("ai_extract_html_prompt_char_limit", 8000))
        max_items = int(ai_cfg.get("ai_platform_extract_max_items", 30))
        min_items = int(ai_cfg.get("ai_platform_min_items_before_fallback", 6))
        ai_timeout = float(ai_cfg.get("ai_request_timeout", 60.0))

        if not rendered_html:
            return []
        html_excerpt = truncate_text(rendered_html, char_limit=ai_input_limit)

        try:
            extracted = await extract_items_from_html(
                platform=self.platform_name,
                page_url=REDNOTE_EXPLORE_URL,
                html_excerpt=html_excerpt,
                base_url=base_url,
                model=model,
                api_key=api_key,
                response_language=response_language,
                max_items=max_items,
                timeout=ai_timeout,
            )
        except Exception as exc:
            logger.warning("RedNote AI extraction failed: %s", exc)
            return []

        if len(extracted) < min_items:
            logger.info(
                "RedNote AI extraction returned %d item(s); falling back to selectors",
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
                    source=entry.get("source") or "RedNote",
                    region="China",
                    rank=rank,
                    description=entry.get("description"),
                    heat=entry.get("heat"),
                    metadata=entry.get("metadata") or {"type": "ai_html_extract"},
                )
            )
        return items
