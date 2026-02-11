"""Orchestrator — loads config, dispatches to platform collectors, saves results."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml

from newscollector.models import CollectionResult
from newscollector.platforms import PLATFORM_REGISTRY
from newscollector.platforms.base import BaseCollector
from newscollector.utils.storage import save_result

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


def load_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load configuration from config.yaml."""
    path = Path(config_path) if config_path else CONFIG_FILE
    if not path.exists():
        logger.warning("Config file not found at %s, using empty config", path)
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_available_platforms() -> list[str]:
    """Return sorted list of registered platform names."""
    return sorted(PLATFORM_REGISTRY.keys())


def create_collector(platform: str, config: dict[str, Any]) -> BaseCollector:
    """Instantiate a collector by platform name."""
    cls = PLATFORM_REGISTRY.get(platform)
    if cls is None:
        raise ValueError(
            f"Unknown platform '{platform}'. "
            f"Available: {', '.join(get_available_platforms())}"
        )
    return cls(config=config)


async def collect_platform(
    platform: str,
    config: dict[str, Any],
    region: str | None = None,
    output_dir: Path | str | None = None,
) -> CollectionResult:
    """Collect trending items from a single platform and save to JSON."""
    collector = create_collector(platform, config)
    result = await collector.safe_collect(region=region)

    if result.success and result.items:
        save_result(result, output_dir=output_dir)
        logger.info(
            "Collected %d items from %s", result.count, platform
        )
    elif result.error:
        logger.error("Error from %s: %s", platform, result.error)
    else:
        logger.warning("No items collected from %s", platform)

    return result


async def collect_all(
    platforms: list[str] | None = None,
    config: dict[str, Any] | None = None,
    region: str | None = None,
    output_dir: Path | str | None = None,
) -> list[CollectionResult]:
    """Collect from multiple platforms concurrently.

    Args:
        platforms: List of platform names. If None, collects from all.
        config: Configuration dict. If None, loaded from config.yaml.
        region: Optional region filter.
        output_dir: Output directory override.

    Returns:
        List of CollectionResult for each platform.
    """
    if config is None:
        config = load_config()

    target_platforms = platforms or get_available_platforms()

    tasks = [
        collect_platform(p, config, region=region, output_dir=output_dir)
        for p in target_platforms
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert exceptions to error results
    final: list[CollectionResult] = []
    for platform_name, result in zip(target_platforms, results):
        if isinstance(result, Exception):
            logger.error("Unexpected error for %s: %s", platform_name, result)
            final.append(
                CollectionResult(
                    platform=platform_name,
                    region=region,
                    error=str(result),
                )
            )
        else:
            final.append(result)

    return final
