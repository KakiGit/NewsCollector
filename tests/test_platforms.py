"""Tests for platform base class and collectors with mocked HTTP."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from newscollector.models import CollectionResult
from newscollector.platforms.base import BaseCollector
from newscollector.platforms.bilibili import BilibiliCollector
from newscollector.platforms.news_rss import (
    NewsRSSCollector,
    _clean_summary,
    _load_sources,
    _normalize_region,
)
from newscollector.platforms.twitter import TwitterCollector
from newscollector.platforms.weibo import WeiboCollector
from newscollector.platforms.youtube import YouTubeCollector


class _DummyCollector(BaseCollector):
    @property
    def platform_name(self) -> str:
        return "dummy"

    async def collect(self, region=None, topic=None):
        raise RuntimeError("intentional error")


class _GoodCollector(BaseCollector):
    @property
    def platform_name(self) -> str:
        return "good"

    async def collect(self, region=None, topic=None):
        return CollectionResult(
            platform=self.platform_name,
            items=[self._make_item(title="T", source="S")],
        )


class TestBaseCollectorSafeCollect:
    @pytest.mark.asyncio
    async def test_wraps_exception_in_error_result(self):
        collector = _DummyCollector()
        result = await collector.safe_collect()
        assert result.success is False
        assert "intentional error" in result.error

    @pytest.mark.asyncio
    async def test_successful_collect(self):
        collector = _GoodCollector()
        result = await collector.safe_collect()
        assert result.success is True
        assert result.count == 1


class TestBaseCollectorMakeItem:
    def test_prefills_platform(self):
        collector = _GoodCollector()
        item = collector._make_item(title="Hello", source="World")
        assert item.platform == "good"
        assert item.title == "Hello"

    def test_can_override_platform(self):
        collector = _GoodCollector()
        item = collector._make_item(title="T", source="S", platform="override")
        assert item.platform == "override"


class TestWeiboCollector:
    @pytest.mark.asyncio
    async def test_parses_hot_search_response(self):
        mock_data = {
            "data": {
                "realtime": [
                    {
                        "word": "热搜话题",
                        "label_name": "热",
                        "raw_hot": 1234567,
                        "category": "社会",
                        "is_hot": 1,
                        "is_new": 0,
                    },
                    {
                        "word": "第二个话题",
                        "note": "备注",
                        "num": 999999,
                        "category": "娱乐",
                        "is_hot": 0,
                        "is_new": 1,
                    },
                ]
            }
        }

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_data

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "newscollector.platforms.weibo.create_client", return_value=mock_client
        ):
            collector = WeiboCollector()
            result = await collector.collect()

        assert result.success
        assert result.count == 2
        assert result.items[0].title == "热搜话题"
        assert result.items[0].heat == 1234567
        assert result.items[0].rank == 1
        assert result.items[1].rank == 2


class TestBilibiliCollector:
    @pytest.mark.asyncio
    async def test_parses_ranking_and_hot_search(self):
        ranking_data = {
            "data": {
                "list": [
                    {
                        "title": "Video Title",
                        "bvid": "BV1234",
                        "desc": "Description",
                        "owner": {"name": "Author"},
                        "stat": {
                            "view": 100000,
                            "like": 5000,
                            "danmaku": 200,
                            "reply": 300,
                            "coin": 100,
                        },
                        "duration": 600,
                    },
                ]
            }
        }
        hot_search_data = {
            "list": [
                {"keyword": "热门搜索", "hot_id": 5000, "icon": "icon_url"},
            ]
        }

        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "ranking" in url:
                resp.json.return_value = ranking_data
            else:
                resp.json.return_value = hot_search_data
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "newscollector.platforms.bilibili.create_client", return_value=mock_client
        ):
            collector = BilibiliCollector()
            result = await collector.collect()

        assert result.success
        assert result.count == 2
        video = result.items[0]
        assert video.title == "Video Title"
        assert video.heat == 100000
        search = result.items[1]
        assert search.title == "热门搜索"


# RSS Collector Tests
class TestNormalizeRegion:
    def test_lowercase(self):
        assert _normalize_region("USA") == "usa"

    def test_aliases(self):
        assert _normalize_region("us") == "usa"
        assert _normalize_region("eu") == "europe"
        assert _normalize_region("cn") == "china"

    def test_preserves_existing(self):
        assert _normalize_region("finland") == "finland"


class TestCleanSummary:
    def test_strips_html_tags(self):
        # BeautifulSoup get_text() removes tags but doesn't add spaces between them
        html = "<p>Hello</p><p>World</p>"
        assert _clean_summary(html) == "HelloWorld"

    def test_strips_complex_html(self):
        html = '<a href="http://example.com">Link</a> and <script>alert(1)</script>'
        result = _clean_summary(html)
        assert "Link" in result
        assert "alert" not in result

    def test_preserves_text_without_tags(self):
        text = "Plain text without HTML"
        assert _clean_summary(text) == text

    def test_truncates_long_text(self):
        long_text = "a" * 1000
        result = _clean_summary(long_text)
        assert len(result) == 500

    def test_empty_returns_empty(self):
        assert _clean_summary("") == ""
        assert _clean_summary(None) == ""


class TestLoadSources:
    @pytest.fixture()
    def sources_yaml(self, tmp_path) -> Path:
        data = {
            "rss_sources": {
                "usa": [
                    {"name": "CNN", "url": "http://rss.cnn.com/rss/edition.rss", "language": "en"}
                ],
                "europe": [
                    {"name": "BBC", "url": "http://feeds.bbci.co.uk/news/rss.xml", "language": "en"}
                ],
            },
            "rss_sources_financial": {
                "usa": [
                    {"name": "CNBC", "url": "https://www.cnbc.com/rss", "language": "en"}
                ],
            },
        }
        yaml_path = tmp_path / "sources.yaml"
        yaml_path.write_text(yaml.dump(data))
        return yaml_path

    def test_loads_default_sources(self, sources_yaml):
        with patch("newscollector.platforms.news_rss.SOURCES_FILE", sources_yaml):
            sources = _load_sources()
        assert "usa" in sources
        assert "europe" in sources

    def test_loads_financial_sources(self, sources_yaml):
        with patch("newscollector.platforms.news_rss.SOURCES_FILE", sources_yaml):
            sources = _load_sources(topic="financial")
        assert "usa" in sources

    def test_missing_file_returns_empty(self, tmp_path):
        with patch("newscollector.platforms.news_rss.SOURCES_FILE", tmp_path / "nope.yaml"):
            assert _load_sources() == {}


class TestNewsRSSCollector:
    @pytest.mark.asyncio
    async def test_no_sources_error(self):
        with patch("newscollector.platforms.news_rss._load_sources", return_value={}):
            collector = NewsRSSCollector()
            result = await collector.collect()
        assert result.success is False
        assert "No RSS sources configured" in result.error

    @pytest.mark.asyncio
    async def test_region_filter_error(self):
        sources = {"usa": [{"name": "CNN", "url": "http://x.com", "language": "en"}]}
        with patch("newscollector.platforms.news_rss._load_sources", return_value=sources):
            collector = NewsRSSCollector()
            result = await collector.collect(region="invalid_region")
        assert result.success is False
        assert "No RSS sources found for region" in result.error

    @pytest.mark.asyncio
    async def test_parses_feed_success(self, tmp_path):
        # Create a minimal RSS feed for testing
        rss_content = """<?xml version="1.0" encoding="UTF-8" ?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Test Headline</title>
              <link>https://example.com/article</link>
              <description>A test description</description>
            </item>
            <item>
              <title>Second Headline</title>
              <link>https://example.com/article2</link>
            </item>
          </channel>
        </rss>
        """
        sources = {
            "usa": [
                {"name": "TestSource", "url": "http://test.com/rss", "language": "en"}
            ]
        }

        # Mock feedparser.parse to return our test data
        mock_feed = MagicMock()
        mock_feed.entries = [
            {"title": "Test Headline", "link": "https://example.com/article", "summary": "A test description"},
            {"title": "Second Headline", "link": "https://example.com/article2", "summary": ""},
        ]

        with patch("newscollector.platforms.news_rss._load_sources", return_value=sources):
            with patch("feedparser.parse", return_value=mock_feed):
                collector = NewsRSSCollector()
                result = await collector.collect(region="usa")

        assert result.success is True
        assert result.count == 2
        assert result.items[0].title == "Test Headline"
        assert result.items[0].source == "TestSource"
        assert result.items[0].region == "usa"
        assert result.items[0].rank == 1
        assert result.items[1].rank == 2


# Twitter Collector Tests
class TestTwitterCollector:
    def test_no_bearer_token_error(self):
        collector = TwitterCollector(config={})
        result = collector._get_bearer_token()
        assert result is None

    def test_bearer_token_from_config(self):
        config = {"twitter": {"bearer_token": "test_token"}}
        collector = TwitterCollector(config=config)
        assert collector._get_bearer_token() == "test_token"

    @pytest.mark.asyncio
    async def test_no_bearer_token_returns_error(self):
        collector = TwitterCollector(config={})
        result = await collector.collect()
        assert result.success is False
        assert "not configured" in result.error

    @pytest.mark.asyncio
    async def test_parses_trends_response(self):
        config = {"twitter": {"bearer_token": "test_token"}}
        collector = TwitterCollector(config=config)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [
            {
                "trends": [
                    {"name": "#Trending1", "url": "http://twitter.com/search?q=1", "tweet_volume": 10000},
                    {"name": "#Trending2", "url": "http://twitter.com/search?q=2", "tweet_volume": 5000},
                ]
            }
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("newscollector.platforms.twitter.create_client", return_value=mock_client):
            result = await collector._fetch_trends(mock_client, {"woeid": 1, "name": "Worldwide"})

        assert len(result) == 2
        assert result[0].title == "#Trending1"
        assert result[0].heat == 10000
        assert result[0].source == "Twitter"
        assert result[0].region == "Worldwide"
        assert result[1].heat == 5000


# YouTube Collector Tests
class TestYouTubeCollector:
    def test_no_api_key_error(self):
        collector = YouTubeCollector(config={})
        result = collector._get_api_key()
        assert result is None

    def test_api_key_from_config(self):
        config = {"youtube": {"api_key": "test_key"}}
        collector = YouTubeCollector(config=config)
        assert collector._get_api_key() == "test_key"

    @pytest.mark.asyncio
    async def test_no_api_key_returns_error(self):
        collector = YouTubeCollector(config={})
        result = await collector.collect()
        assert result.success is False
        assert "not configured" in result.error

    @pytest.mark.asyncio
    async def test_region_blocked_error(self):
        config = {"youtube": {"api_key": "test_key"}}
        collector = YouTubeCollector(config=config)
        result = await collector.collect(region="china")
        assert result.success is False
        assert "not available" in result.error

    @pytest.mark.asyncio
    async def test_parses_video_response(self):
        config = {"youtube": {"api_key": "test_key"}}
        collector = YouTubeCollector(config=config)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {
                    "id": "abc123",
                    "snippet": {
                        "title": "Test Video",
                        "description": "A test video description",
                        "channelTitle": "Test Channel",
                        "channelId": "UCxyz",
                        "publishedAt": "2025-01-15T12:00:00Z",
                    },
                    "statistics": {
                        "viewCount": "100000",
                        "likeCount": "5000",
                        "commentCount": "100",
                    },
                },
                {
                    "id": "def456",
                    "snippet": {
                        "title": "Second Video",
                        "description": "",
                        "channelTitle": "Channel 2",
                        "channelId": "UCabc",
                        "publishedAt": "2025-01-14T12:00:00Z",
                    },
                    "statistics": {
                        "viewCount": "50000",
                    },
                },
            ]
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        result = await collector._fetch_trending(mock_client, "test_key", {"code": "US", "name": "United States"})

        assert len(result) == 2
        assert result[0].title == "Test Video"
        assert result[0].url == "https://www.youtube.com/watch?v=abc123"
        assert result[0].source == "Test Channel"
        assert result[0].heat == 100000
        assert result[0].region == "United States"
        assert result[0].rank == 1
        assert result[1].rank == 2
        assert result[1].heat == 50000

    @pytest.mark.asyncio
    async def test_handles_empty_response(self):
        config = {"youtube": {"api_key": "test_key"}}
        collector = YouTubeCollector(config=config)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"items": []}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        result = await collector._fetch_trending(mock_client, "test_key", {"code": "US", "name": "United States"})

        assert result == []
