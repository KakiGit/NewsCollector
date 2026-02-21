"""Platform collectors registry."""

from newscollector.platforms.bilibili import BilibiliCollector
from newscollector.platforms.douyin import DouyinCollector
from newscollector.platforms.instagram import InstagramCollector
from newscollector.platforms.news_rss import NewsRSSCollector
from newscollector.platforms.rednote import RedNoteCollector
from newscollector.platforms.tiktok import TikTokCollector
from newscollector.platforms.twitter import TwitterCollector
from newscollector.platforms.weibo import WeiboCollector
from newscollector.platforms.youtube import YouTubeCollector

PLATFORM_REGISTRY: dict[str, type] = {
    "news_rss": NewsRSSCollector,
    "twitter": TwitterCollector,
    "instagram": InstagramCollector,
    "rednote": RedNoteCollector,
    "tiktok": TikTokCollector,
    "weibo": WeiboCollector,
    "youtube": YouTubeCollector,
    "bilibili": BilibiliCollector,
    "douyin": DouyinCollector,
}

__all__ = ["PLATFORM_REGISTRY"]
