"""Base collector abstract class."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from newscollector.models import CollectionResult, TrendingItem

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract base class for all platform collectors.

    Subclasses must implement:
        platform_name: str property
        collect() -> CollectionResult
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Unique identifier for this platform (e.g. 'twitter', 'news_rss')."""
        ...

    @abstractmethod
    async def collect(self, region: str | None = None) -> CollectionResult:
        """Collect trending items from this platform.

        Args:
            region: Optional region filter (e.g. 'europe', 'china').

        Returns:
            CollectionResult with the collected items or an error.
        """
        ...

    async def safe_collect(self, region: str | None = None) -> CollectionResult:
        """Wrapper around collect() that catches exceptions."""
        try:
            return await self.collect(region=region)
        except Exception as exc:
            logger.error("Collection failed for %s: %s", self.platform_name, exc)
            return CollectionResult(
                platform=self.platform_name,
                region=region,
                error=str(exc),
            )

    def _make_item(self, **kwargs: Any) -> TrendingItem:
        """Helper to create a TrendingItem with platform pre-filled."""
        kwargs.setdefault("platform", self.platform_name)
        return TrendingItem(**kwargs)
