"""CLI entry point for NewsCollector."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

from newscollector.collector import (
    collect_all,
    collect_platform,
    get_available_platforms,
    load_config,
)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@click.group()
@click.version_option(package_name="newscollector")
def cli() -> None:
    """NewsCollector — Collect trending news and topics from multiple platforms."""


@cli.command()
@click.option(
    "--platform", "-p",
    multiple=True,
    help="Platform(s) to collect from. Can be specified multiple times.",
)
@click.option(
    "--all", "collect_all_flag",
    is_flag=True,
    default=False,
    help="Collect from all available platforms.",
)
@click.option(
    "--region", "-r",
    default=None,
    help="Filter by region (e.g. europe, usa, china, japan, south_korea, india, vietnam).",
)
@click.option(
    "--config", "-c",
    "config_path",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Path to config.yaml file.",
)
@click.option(
    "--output", "-o",
    "output_dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Output directory for JSON files.",
)
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging.")
def collect(
    platform: tuple[str, ...],
    collect_all_flag: bool,
    region: str | None,
    config_path: Path | None,
    output_dir: Path | None,
    verbose: bool,
) -> None:
    """Collect trending items from one or more platforms."""
    _setup_logging(verbose)

    if not platform and not collect_all_flag:
        click.echo("Error: Specify --platform or --all. Use 'list-platforms' to see options.")
        sys.exit(1)

    config = load_config(config_path)

    if collect_all_flag:
        platforms = None  # None means all
    else:
        # Validate platform names
        available = get_available_platforms()
        for p in platform:
            if p not in available:
                click.echo(f"Error: Unknown platform '{p}'. Available: {', '.join(available)}")
                sys.exit(1)
        platforms = list(platform)

    click.echo(f"Collecting from: {', '.join(platforms) if platforms else 'all platforms'}")
    if region:
        click.echo(f"Region filter: {region}")

    results = asyncio.run(
        collect_all(
            platforms=platforms,
            config=config,
            region=region,
            output_dir=output_dir,
        )
    )

    # Print summary
    click.echo("\n--- Collection Summary ---")
    total_items = 0
    for result in results:
        status = click.style("OK", fg="green") if result.success else click.style("FAIL", fg="red")
        count = result.count
        total_items += count
        line = f"  {result.platform:<15} [{status}] {count} items"
        if result.error:
            line += f"  — {result.error[:80]}"
        click.echo(line)

    click.echo(f"\nTotal: {total_items} items collected")


@cli.command("list-platforms")
def list_platforms() -> None:
    """List all available platforms and their status."""
    platforms = get_available_platforms()
    click.echo("Available platforms:\n")

    # Platform descriptions
    descriptions: dict[str, str] = {
        "news_rss": "RSS feeds from major news publishers worldwide",
        "news_api": "NewsAPI.org top headlines (requires API key)",
        "twitter": "X/Twitter trending topics (requires bearer token)",
        "instagram": "Instagram explore page (Playwright scraping)",
        "rednote": "RedNote/Xiaohongshu hot topics (Playwright scraping)",
        "tiktok": "TikTok trending topics and hashtags",
        "weibo": "Weibo hot search list (public API)",
        "youtube": "YouTube trending videos (requires API key)",
        "bilibili": "Bilibili hot videos and search (public API)",
        "douyin": "Douyin hot list (API + Playwright fallback)",
    }

    regions: dict[str, str] = {
        "news_rss": "europe, usa, china, japan, south_korea, india, vietnam",
        "news_api": "europe, usa, china, japan, south_korea, india",
        "twitter": "global, usa, europe, japan, south_korea, india",
        "instagram": "global",
        "rednote": "china",
        "tiktok": "global",
        "weibo": "china",
        "youtube": "usa, europe, japan, south_korea, india, vietnam",
        "bilibili": "china",
        "douyin": "china",
    }

    for p in platforms:
        desc = descriptions.get(p, "")
        region_info = regions.get(p, "")
        click.echo(f"  {click.style(p, bold=True):<25} {desc}")
        if region_info:
            click.echo(f"  {'':25} Regions: {region_info}")
        click.echo()


if __name__ == "__main__":
    cli()
