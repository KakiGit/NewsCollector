"""Orchestrator — loads config, dispatches to platform collectors, saves results.

This module is the main orchestrator for collecting news from various platforms.
It handles configuration loading, platform collection dispatching, AI enrichment,
item storage, and daily verdict generation.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from newscollector.models import CollectionResult, DailyVerdict
from newscollector.platforms import PLATFORM_REGISTRY
from newscollector.platforms.base import BaseCollector
from newscollector.utils.ai import (
    generate_daily_verdict,
    is_ai_configured,
    summarize_and_label,
    summarize_and_label_from_page,
)
from newscollector.utils.labeller import label_item
from newscollector.utils.storage import configure_storage, save_daily_verdict, save_item
from newscollector.utils.web_content import fetch_page_text

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "config.yaml"


def _scope_key(platform: str | None = None, region: str | None = None) -> str:
    """Generate a scope key from platform and/or region.

    :param platform: Platform name.
    :param region: Region name.
    :return: Scope key string in format "platform:X", "region:Y", or "all".
    """
    if platform and region:
        return f"platform:{platform}|region:{region}"
    if platform:
        return f"platform:{platform}"
    if region:
        return f"region:{region}"
    return "all"


def _build_daily_analysis_scopes(
    results: list[CollectionResult],
) -> dict[str, dict[str, Any]]:
    """Build item scopes for daily verdict generation.

    :param results: List of collection results.
    :return: Dictionary mapping scope keys to scope data.
    """
    all_items: list[dict[str, Any]] = []
    by_platform: dict[str, list[dict[str, Any]]] = {}
    by_region: dict[str, list[dict[str, Any]]] = {}
    by_platform_region: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for result in results:
        if not result.success:
            continue
        for item in result.items:
            item_dict = item.model_dump(mode="json")
            all_items.append(item_dict)

            platform = str(item_dict.get("platform") or "").strip()
            if platform:
                by_platform.setdefault(platform, []).append(item_dict)

            region = str(item_dict.get("region") or "").strip()
            if region:
                by_region.setdefault(region, []).append(item_dict)
            if platform and region:
                by_platform_region.setdefault((platform, region), []).append(item_dict)

    scopes: dict[str, dict[str, Any]] = {}
    if all_items:
        scopes["all"] = {"platform": None, "region": None, "items": all_items}
    for platform, items in by_platform.items():
        scopes[_scope_key(platform=platform)] = {
            "platform": platform,
            "region": None,
            "items": items,
        }
    for region, items in by_region.items():
        scopes[_scope_key(region=region)] = {
            "platform": None,
            "region": region,
            "items": items,
        }
    for (platform, region), items in by_platform_region.items():
        scopes[_scope_key(platform=platform, region=region)] = {
            "platform": platform,
            "region": region,
            "items": items,
        }
    return scopes


async def _generate_and_save_daily_verdicts(
    results: list[CollectionResult],
    config: dict[str, Any],
    output_dir: Path | str | None = None,
) -> None:
    """Generate daily verdicts for all scopes and persist them."""
    if not is_ai_configured(config):
        return

    ai_cfg = (config.get("ai") or {}) if config else {}
    base_url = ai_cfg.get("ai_base_url", "")
    model = ai_cfg.get("ai_model", "")
    api_key = ai_cfg.get("ai_api_key", "")
    response_language = ai_cfg.get("ai_response_language") or None
    ai_timeout = float(ai_cfg.get("ai_request_timeout", 60.0))
    ai_max_verdict_items = int(ai_cfg.get("ai_max_verdict_items", 400))
    ai_json_number_retry = int(ai_cfg.get("ai_json_number_retry", 3))
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    scopes = _build_daily_analysis_scopes(results)
    for scope_key, scope in scopes.items():
        items = scope.get("items") or []
        if not items:
            continue
        try:
            (
                summary,
                global_political_score,
                global_economic_score,
                domestic_political_score,
                domestic_economic_score,
            ) = await generate_daily_verdict(
                items,
                base_url=base_url,
                model=model,
                api_key=api_key,
                response_language=response_language,
                max_items=ai_max_verdict_items,
                timeout=ai_timeout,
                ai_json_number_retry=ai_json_number_retry,
            )
            # Use defaults when AI fails to ensure verdict is always shown
            if summary is None:
                summary = "(Verdict evaluation failed — scores unavailable)"
                logger.warning(
                    "AI verdict for %s returned incomplete data, saving with default values",
                    scope_key,
                )

            verdict = DailyVerdict(
                scope_key=scope_key,
                date=date_str,
                platform=scope.get("platform"),
                region=scope.get("region"),
                summary=summary,
                political_score=global_political_score,
                economic_score=global_economic_score,
                domestic_political_score=domestic_political_score,
                domestic_economic_score=domestic_economic_score,
                item_count=len(items),
            )
            save_daily_verdict(verdict, output_dir=output_dir)
        except Exception as exc:
            logger.warning("Daily verdict generation failed for %s: %s", scope_key, exc)
            # Save a fallback verdict so the UI still shows something
            fallback_verdict = DailyVerdict(
                scope_key=scope_key,
                date=date_str,
                platform=scope.get("platform"),
                region=scope.get("region"),
                summary="(Verdict evaluation failed — scores unavailable)",
                political_score=None,
                economic_score=None,
                domestic_political_score=None,
                domestic_economic_score=None,
                item_count=len(items),
            )
            save_daily_verdict(fallback_verdict, output_dir=output_dir)


def load_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load configuration from config.yaml.

    :param config_path: Path to config file. If None, uses default location.
    :return: Configuration dictionary.
    """
    path = Path(config_path) if config_path else CONFIG_FILE
    if not path.exists():
        logger.warning("Config file not found at %s, using empty config", path)
        return {}
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    storage_cfg = config.get("storage") or {}
    db_url = storage_cfg.get("database_url")
    if db_url:
        configure_storage(db_url)
    return config


def get_available_platforms() -> list[str]:
    """Return sorted list of registered platform names.

    :return: List of platform identifiers.
    """
    return sorted(PLATFORM_REGISTRY.keys())


def create_collector(platform: str, config: dict[str, Any]) -> BaseCollector:
    """Instantiate a collector by platform name.

    :param platform: Platform identifier.
    :param config: Configuration dictionary.
    :return: Collector instance for the platform.
    :raises ValueError: If platform is not registered.
    """
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
    topic: str | None = None,
    output_dir: Path | str | None = None,
) -> CollectionResult:
    """Collect trending items from a single platform and save to JSON.

    :param platform: Platform identifier.
    :param config: Configuration dictionary.
    :param region: Optional region filter.
    :param topic: Optional topic filter.
    :param output_dir: Optional output directory override.
    :return: CollectionResult with collected items.
    """
    collector = create_collector(platform, config)
    result = await collector.safe_collect(region=region, topic=topic)

    # Enrich items: AI summary + labels when configured, else keyword labels
    if result.success and result.items:
        ai_cfg = (config.get("ai") or {}) if config else {}
        if is_ai_configured(config):
            base_url = ai_cfg.get("ai_base_url", "")
            model = ai_cfg.get("ai_model", "")
            api_key = ai_cfg.get("ai_api_key", "")
            response_language = ai_cfg.get("ai_response_language") or None
            ai_timeout = float(ai_cfg.get("ai_request_timeout", 60.0))
            ai_max_failures = int(ai_cfg.get("ai_max_failures_before_disable", 3))
            page_summary_enabled = ai_cfg.get("ai_page_summary_enabled", True)
            page_text_char_limit = int(ai_cfg.get("ai_page_char_limit", 12000))
            page_html_char_limit = int(ai_cfg.get("ai_page_html_char_limit", 200000))
            page_text_cache: dict[str, str | None] = {}
            page_summary_cache: dict[str, tuple[str | None, list[str]]] = {}
            ai_failures = 0
            ai_disabled = False
            for item in result.items:
                if ai_disabled:
                    item.labels = label_item(item.title, item.description)
                    save_item(
                        item.model_dump(mode="json"),
                        platform=result.platform,
                        region=result.region,
                        db_url=(
                            config.get("storage", {}).get("database_url")
                            if config
                            else None
                        ),
                    )
                    continue
                try:
                    summary: str | None = None
                    labels: list[str] = []

                    if page_summary_enabled and item.url:
                        cache_key = item.url
                        if cache_key in page_summary_cache:
                            summary, labels = page_summary_cache[cache_key]
                        else:
                            page_text = page_text_cache.get(cache_key)
                            if cache_key not in page_text_cache:
                                page_text = await fetch_page_text(
                                    cache_key,
                                    html_char_limit=page_html_char_limit,
                                    text_char_limit=page_text_char_limit,
                                )
                                page_text_cache[cache_key] = page_text
                            if page_text:
                                summary, labels = await summarize_and_label_from_page(
                                    item.title,
                                    page_text,
                                    base_url=base_url,
                                    model=model,
                                    api_key=api_key,
                                    response_language=response_language,
                                    timeout=ai_timeout,
                                )
                            page_summary_cache[cache_key] = (summary, labels)

                    if summary is None and not labels:
                        summary, labels = await summarize_and_label(
                            item.title,
                            item.description,
                            base_url=base_url,
                            model=model,
                            api_key=api_key,
                            response_language=response_language,
                            timeout=ai_timeout,
                        )

                    if summary is not None:
                        item.summary = summary
                    if labels:
                        item.labels = labels
                        ai_failures = 0
                    else:
                        ai_failures += 1
                        item.labels = label_item(item.title, item.description)
                except Exception as e:
                    logger.warning(
                        "AI enrichment failed for item %r: %s", item.title[:50], e
                    )
                    item.labels = label_item(item.title, item.description)
                    ai_failures += 1

                # Save item immediately after enrichment
                save_item(
                    item.model_dump(mode="json"),
                    platform=result.platform,
                    region=result.region,
                    db_url=(
                        config.get("storage", {}).get("database_url")
                        if config
                        else None
                    ),
                )

                if ai_failures >= ai_max_failures:
                    ai_disabled = True
                    logger.warning(
                        "Disabling AI enrichment for remaining %s items after %s failures",
                        result.platform,
                        ai_failures,
                    )
        else:
            for item in result.items:
                item.labels = label_item(item.title, item.description)
                if result.success:
                    save_item(
                        item.model_dump(mode="json"),
                        platform=result.platform,
                        region=result.region,
                        db_url=(
                            config.get("storage", {}).get("database_url")
                            if config
                            else None
                        ),
                    )

    if result.success and result.items:
        logger.info("Collected %d items from %s", result.count, platform)
    elif result.error:
        logger.error("Error from %s: %s", platform, result.error)
    else:
        logger.warning("No items collected from %s", platform)

    return result


async def collect_all(
    platforms: list[str] | None = None,
    config: dict[str, Any] | None = None,
    region: str | None = None,
    topic: str | None = None,
    output_dir: Path | str | None = None,
) -> list[CollectionResult]:
    """Collect from multiple platforms concurrently.

    Args:
        platforms: List of platform names. If None, collects from all.
        config: Configuration dict. If None, loaded from config.yaml.
        region: Optional region filter.
        topic: Optional topic filter (e.g. 'financial' for business-only).
        output_dir: Output directory override.

    Returns:
        List of CollectionResult for each platform.
    """
    if config is None:
        config = load_config()

    target_platforms = platforms or get_available_platforms()

    tasks = [
        collect_platform(p, config, region=region, topic=topic, output_dir=output_dir)
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

    await _generate_and_save_daily_verdicts(final, config=config, output_dir=output_dir)

    return final


def _build_scopes_from_items(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build item scopes for daily verdict generation from raw item dicts."""
    all_items: list[dict[str, Any]] = []
    by_platform: dict[str, list[dict[str, Any]]] = {}
    by_region: dict[str, list[dict[str, Any]]] = {}
    by_platform_region: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for item_dict in items:
        all_items.append(item_dict)

        platform = str(item_dict.get("platform") or "").strip()
        if platform:
            by_platform.setdefault(platform, []).append(item_dict)

        region = str(item_dict.get("region") or "").strip()
        if region:
            by_region.setdefault(region, []).append(item_dict)
        if platform and region:
            by_platform_region.setdefault((platform, region), []).append(item_dict)

    scopes: dict[str, dict[str, Any]] = {}
    if all_items:
        scopes["all"] = {"platform": None, "region": None, "items": all_items}
    for platform, platform_items in by_platform.items():
        scopes[_scope_key(platform=platform)] = {
            "platform": platform,
            "region": None,
            "items": platform_items,
        }
    for region, region_items in by_region.items():
        scopes[_scope_key(region=region)] = {
            "platform": None,
            "region": region,
            "items": region_items,
        }
    for (platform, region), pr_items in by_platform_region.items():
        scopes[_scope_key(platform=platform, region=region)] = {
            "platform": platform,
            "region": region,
            "items": pr_items,
        }
    return scopes


async def generate_verdicts_from_items(
    items: list[dict[str, Any]],
    date: str,
    config: dict[str, Any] | None = None,
    output_dir: Path | str | None = None,
) -> int:
    """Generate daily verdicts from pre-loaded items.

    Args:
        items: List of item dicts (loaded from JSON files).
        date: Date string in YYYY-MM-DD format for the verdict.
        config: Configuration dict. If None, loaded from config.yaml.
        output_dir: Output directory override.

    Returns:
        Number of verdicts generated.
    """
    if config is None:
        config = load_config()

    if not is_ai_configured(config):
        logger.warning("AI is not configured, cannot generate verdicts")
        return 0

    if not items:
        logger.warning("No items provided for verdict generation")
        return 0

    ai_cfg = (config.get("ai") or {}) if config else {}
    base_url = ai_cfg.get("ai_base_url", "")
    model = ai_cfg.get("ai_model", "")
    api_key = ai_cfg.get("ai_api_key", "")
    response_language = ai_cfg.get("ai_response_language") or None
    ai_timeout = float(ai_cfg.get("ai_request_timeout", 60.0))
    ai_max_verdict_items = int(ai_cfg.get("ai_max_verdict_items", 400))
    ai_json_number_retry = int(ai_cfg.get("ai_json_number_retry", 3))

    scopes = _build_scopes_from_items(items)
    verdicts_generated = 0

    for scope_key, scope in scopes.items():
        scope_items = scope.get("items") or []
        if not scope_items:
            continue
        try:
            (
                summary,
                global_political_score,
                global_economic_score,
                domestic_political_score,
                domestic_economic_score,
            ) = await generate_daily_verdict(
                scope_items,
                base_url=base_url,
                model=model,
                api_key=api_key,
                response_language=response_language,
                max_items=ai_max_verdict_items,
                timeout=ai_timeout,
                ai_json_number_retry=ai_json_number_retry,
            )
            # Use defaults when AI fails to ensure verdict is always shown
            if summary is None:
                summary = "(Verdict evaluation failed — scores unavailable)"
                logger.warning(
                    "AI verdict for %s returned incomplete data, saving with default values",
                    scope_key,
                )

            verdict = DailyVerdict(
                scope_key=scope_key,
                date=date,
                platform=scope.get("platform"),
                region=scope.get("region"),
                summary=summary,
                political_score=global_political_score,
                economic_score=global_economic_score,
                domestic_political_score=domestic_political_score,
                domestic_economic_score=domestic_economic_score,
                item_count=len(scope_items),
            )
            save_daily_verdict(verdict, output_dir=output_dir)
            verdicts_generated += 1
            logger.info("Generated verdict for scope: %s", scope_key)
        except Exception as exc:
            logger.warning("Daily verdict generation failed for %s: %s", scope_key, exc)
            # Save a fallback verdict so the UI still shows something
            fallback_verdict = DailyVerdict(
                scope_key=scope_key,
                date=date,
                platform=scope.get("platform"),
                region=scope.get("region"),
                summary="(Verdict evaluation failed — scores unavailable)",
                political_score=None,
                economic_score=None,
                domestic_political_score=None,
                domestic_economic_score=None,
                item_count=len(scope_items),
            )
            save_daily_verdict(fallback_verdict, output_dir=output_dir)
            verdicts_generated += 1

    return verdicts_generated
