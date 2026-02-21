"""Tests for platform base class and collectors with mocked HTTP."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from newscollector.models import CollectionResult
from newscollector.platforms.base import BaseCollector
from newscollector.platforms.bilibili import BilibiliCollector
from newscollector.platforms.weibo import WeiboCollector


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
