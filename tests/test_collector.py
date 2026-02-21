"""Tests for newscollector.collector orchestrator logic."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from newscollector.collector import (
    _build_daily_analysis_scopes,
    _scope_key,
    collect_all,
    collect_platform,
    create_collector,
    get_available_platforms,
    load_config,
)
from newscollector.models import CollectionResult, TrendingItem
from newscollector.platforms.base import BaseCollector
from newscollector.utils.storage import query_collected_items

pytestmark = pytest.mark.usefixtures("db_setup")


class TestScopeKey:
    def test_both(self):
        assert _scope_key(platform="rss", region="usa") == "platform:rss|region:usa"

    def test_platform_only(self):
        assert _scope_key(platform="rss") == "platform:rss"

    def test_region_only(self):
        assert _scope_key(region="usa") == "region:usa"

    def test_neither(self):
        assert _scope_key() == "all"


class TestBuildDailyAnalysisScopes:
    def _make_result(self, items_data: list[dict]) -> CollectionResult:
        items = [
            TrendingItem(
                title=d["title"],
                source=d.get("source", "S"),
                platform=d["platform"],
                region=d.get("region"),
            )
            for d in items_data
        ]
        return CollectionResult(platform=items_data[0]["platform"], items=items)

    def test_single_platform_single_region(self):
        result = self._make_result(
            [
                {"title": "A", "platform": "rss", "region": "usa"},
                {"title": "B", "platform": "rss", "region": "usa"},
            ]
        )
        scopes = _build_daily_analysis_scopes([result])
        assert "all" in scopes
        assert "platform:rss" in scopes
        assert "region:usa" in scopes
        assert "platform:rss|region:usa" in scopes
        assert len(scopes["all"]["items"]) == 2

    def test_multiple_platforms(self):
        r1 = self._make_result([{"title": "A", "platform": "rss", "region": "usa"}])
        r2 = self._make_result([{"title": "B", "platform": "weibo", "region": "China"}])
        scopes = _build_daily_analysis_scopes([r1, r2])
        assert "platform:rss" in scopes
        assert "platform:weibo" in scopes
        assert len(scopes["all"]["items"]) == 2

    def test_skips_failed_results(self):
        failed = CollectionResult(platform="bad", error="fail")
        ok = self._make_result([{"title": "A", "platform": "rss"}])
        scopes = _build_daily_analysis_scopes([failed, ok])
        assert len(scopes["all"]["items"]) == 1

    def test_empty_results(self):
        assert _build_daily_analysis_scopes([]) == {}


class TestLoadConfig:
    def test_existing_file(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump({"ai": {"ai_model": "test"}}))
        config = load_config(cfg_file)
        assert config["ai"]["ai_model"] == "test"

    def test_missing_file_returns_empty(self, tmp_path):
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config == {}


class TestGetAvailablePlatforms:
    def test_returns_sorted_list(self):
        platforms = get_available_platforms()
        assert isinstance(platforms, list)
        assert platforms == sorted(platforms)
        assert "news_rss" in platforms
        assert "weibo" in platforms


class TestCreateCollector:
    def test_valid_platform(self):
        collector = create_collector("weibo", {})
        assert isinstance(collector, BaseCollector)
        assert collector.platform_name == "weibo"

    def test_unknown_platform_raises(self):
        with pytest.raises(ValueError, match="Unknown platform"):
            create_collector("nonexistent_platform", {})


class TestCollectPlatform:
    @pytest.mark.asyncio
    async def test_saves_result_on_success(self):
        item = TrendingItem(title="T", source="S", platform="weibo", region="China")
        mock_result = CollectionResult(platform="weibo", region="China", items=[item])

        with patch("newscollector.collector.create_collector") as mock_create:
            mock_collector = MagicMock()
            mock_collector.safe_collect = AsyncMock(return_value=mock_result)
            mock_create.return_value = mock_collector

            result = await collect_platform("weibo", {})

        assert result.success
        assert result.count == 1
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        items, total = query_collected_items(date=date_str, platform="weibo")
        assert len(items) == 1
        assert total == 1

    @pytest.mark.asyncio
    async def test_labels_assigned_without_ai(self):
        item = TrendingItem(title="Stock market crash", source="S", platform="p")
        mock_result = CollectionResult(platform="p", items=[item])

        with patch("newscollector.collector.create_collector") as mock_create:
            mock_collector = MagicMock()
            mock_collector.safe_collect = AsyncMock(return_value=mock_result)
            mock_create.return_value = mock_collector

            result = await collect_platform("p", {})

        assert "financial" in result.items[0].labels

    @pytest.mark.asyncio
    async def test_error_result_not_saved(self):
        mock_result = CollectionResult(platform="p", error="boom")

        with patch("newscollector.collector.create_collector") as mock_create:
            mock_collector = MagicMock()
            mock_collector.safe_collect = AsyncMock(return_value=mock_result)
            mock_create.return_value = mock_collector

            result = await collect_platform("p", {})

        assert not result.success
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        items, total = query_collected_items(date=date_str, platform="p")
        assert items == []
        assert total == 0


class TestCollectAll:
    @pytest.mark.asyncio
    async def test_concurrent_dispatch(self, tmp_path):
        item = TrendingItem(title="T", source="S", platform="weibo")
        mock_result = CollectionResult(platform="weibo", items=[item])

        with patch(
            "newscollector.collector.collect_platform", new_callable=AsyncMock
        ) as mock_cp:
            mock_cp.return_value = mock_result
            results = await collect_all(
                platforms=["weibo"],
                config={},
                output_dir=tmp_path,
            )

        assert len(results) == 1
        assert results[0].success

    @pytest.mark.asyncio
    async def test_exception_converted_to_error(self, tmp_path):
        with patch(
            "newscollector.collector.collect_platform", new_callable=AsyncMock
        ) as mock_cp:
            mock_cp.side_effect = RuntimeError("network down")
            results = await collect_all(
                platforms=["weibo"],
                config={},
                output_dir=tmp_path,
            )

        assert len(results) == 1
        assert not results[0].success
        assert "network down" in results[0].error
