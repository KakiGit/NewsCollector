"""CLI entry point for NewsCollector.

This module provides the command-line interface using Click.
Commands include collecting news from platforms, serving the web UI,
generating verdicts, and managing financial reports.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

from newscollector.collector import (
    collect_all,
    generate_verdicts_from_items,
    get_available_platforms,
    load_config,
)
from newscollector.financial import (
    REGION_LABELS,
    clean_financial_reports,
    collect_financial_history,
    collect_financial_reports,
    evaluate_financial_reports,
    get_available_regions,
    update_companies_yaml,
)
from newscollector.utils.storage import load_collected_items


def _setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity level.

    :param verbose: If True, set log level to DEBUG; otherwise INFO.
    """
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
    "--platform",
    "-p",
    multiple=True,
    help="Platform(s) to collect from. Can be specified multiple times.",
)
@click.option(
    "--all",
    "collect_all_flag",
    is_flag=True,
    default=False,
    help="Collect from all available platforms.",
)
@click.option(
    "--region",
    "-r",
    default=None,
    help="Filter by region (e.g. europe, usa, china, japan, south_korea, india, vietnam).",
)
@click.option(
    "--topic",
    "-t",
    default=None,
    help="Topic filter (e.g. 'financial' for business/finance-only; supported by news_api and news_rss).",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Path to config.yaml file.",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Output directory for JSON files.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging."
)
def collect(
    platform: tuple[str, ...],
    collect_all_flag: bool,
    region: str | None,
    topic: str | None,
    config_path: Path | None,
    output_dir: Path | None,
    verbose: bool,
) -> None:
    """Collect trending items from one or more platforms."""
    _setup_logging(verbose)

    if not platform and not collect_all_flag:
        click.echo(
            "Error: Specify --platform or --all. Use 'list-platforms' to see options."
        )
        sys.exit(1)

    config = load_config(config_path)

    if collect_all_flag:
        platforms = None  # None means all
    else:
        # Validate platform names
        available = get_available_platforms()
        for p in platform:
            if p not in available:
                click.echo(
                    f"Error: Unknown platform '{p}'. Available: {', '.join(available)}"
                )
                sys.exit(1)
        platforms = list(platform)

    click.echo(
        f"Collecting from: {', '.join(platforms) if platforms else 'all platforms'}"
    )
    if region:
        click.echo(f"Region filter: {region}")
    if topic:
        click.echo(f"Topic filter: {topic}")

    results = asyncio.run(
        collect_all(
            platforms=platforms,
            config=config,
            region=region,
            topic=topic,
            output_dir=output_dir,
        )
    )

    # Print summary
    click.echo("\n--- Collection Summary ---")
    total_items = 0
    for result in results:
        status = (
            click.style("OK", fg="green")
            if result.success
            else click.style("FAIL", fg="red")
        )
        count = result.count
        total_items += count
        line = f"  {result.platform:<15} [{status}] {count} items"
        if result.error:
            line += f"  — {result.error[:80]}"
        click.echo(line)

    click.echo(f"\nTotal: {total_items} items collected")


@cli.command()
@click.option(
    "--port",
    default=8000,
    show_default=True,
    help="Port to listen on.",
)
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Host to bind to.",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Path to config.yaml file.",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Output directory containing collected JSON files.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging."
)
def serve(
    port: int,
    host: str,
    config_path: Path | None,
    output_dir: Path | None,
    verbose: bool,
) -> None:
    """Start the web UI to browse collected news items."""
    _setup_logging(verbose)

    import uvicorn

    from newscollector.web import app, configure

    config = load_config(config_path)
    db_url = (config.get("storage") or {}).get("database_url")
    configure(output_dir=output_dir, db_url=db_url)

    click.echo(f"Starting NewsCollector web UI at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="debug" if verbose else "info")


@cli.command("list-platforms")
def list_platforms() -> None:
    """List all available platforms and their status."""
    platforms = get_available_platforms()
    click.echo("Available platforms:\n")

    # Platform descriptions
    descriptions: dict[str, str] = {
        "news_rss": "RSS feeds from major news publishers worldwide",
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


@cli.command()
@click.option(
    "--date",
    "-d",
    default=None,
    help="Date to generate verdicts for (YYYY-MM-DD). Defaults to today.",
)
@click.option(
    "--platform",
    "-p",
    multiple=True,
    help="Platform(s) to include. Can be specified multiple times. Defaults to all.",
)
@click.option(
    "--region",
    "-r",
    default=None,
    help="Filter by region (e.g. europe, usa, china).",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Path to config.yaml file.",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Output directory containing collected JSON files.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging."
)
def verdict(
    date: str | None,
    platform: tuple[str, ...],
    region: str | None,
    config_path: Path | None,
    output_dir: Path | None,
    verbose: bool,
) -> None:
    """Generate daily verdicts from previously collected news items.

    This command evaluates collected items and generates AI-powered verdicts
    with political and economic scores. Use this to regenerate verdicts
    without re-collecting data.
    """
    _setup_logging(verbose)

    config = load_config(config_path)

    # Validate AI configuration
    ai_cfg = config.get("ai") or {}
    if not ai_cfg.get("ai_base_url") or not ai_cfg.get("ai_model"):
        click.echo(
            "Error: AI is not configured. Set ai_base_url and ai_model in config.yaml."
        )
        sys.exit(1)

    # Use today's date if not specified
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Validate platform names if specified
    platforms: list[str] | None = None
    if platform:
        available = get_available_platforms()
        for p in platform:
            if p not in available:
                click.echo(
                    f"Error: Unknown platform '{p}'. Available: {', '.join(available)}"
                )
                sys.exit(1)
        platforms = list(platform)

    click.echo(f"Loading collected items for date: {target_date}")
    if platforms:
        click.echo(f"Platforms: {', '.join(platforms)}")
    if region:
        click.echo(f"Region filter: {region}")

    # Load items from output directory
    items = load_collected_items(
        date=target_date,
        output_dir=output_dir,
        platforms=platforms,
        region=region,
    )

    if not items:
        click.echo(
            f"No items found for {target_date}. Run 'collect' first to gather data."
        )
        sys.exit(1)

    click.echo(f"Found {len(items)} items. Generating verdicts...")

    verdicts_count = asyncio.run(
        generate_verdicts_from_items(
            items=items,
            date=target_date,
            config=config,
            output_dir=output_dir,
        )
    )

    if verdicts_count > 0:
        click.echo(
            click.style(
                f"\nGenerated {verdicts_count} verdict(s) successfully.", fg="green"
            )
        )
    else:
        click.echo(click.style("\nNo verdicts generated.", fg="yellow"))


@cli.command("collect-reports")
@click.option(
    "--region",
    "-r",
    multiple=True,
    help="Region(s) to collect (e.g. us_300, china_300, finland_100, europe_300, global_500). "
    "Can be specified multiple times. Defaults to all.",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Path to config.yaml file.",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Output directory for report files.",
)
@click.option(
    "--delay",
    default=0.5,
    show_default=True,
    type=float,
    help="Delay in seconds between yfinance requests (rate limiting).",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging."
)
def collect_reports_cmd(
    region: tuple[str, ...],
    config_path: Path | None,
    output_dir: Path | None,
    delay: float,
    verbose: bool,
) -> None:
    """Collect financial reports for top companies using yfinance.

    DEPRECATED: Use 'collect-history --latest' instead.
    This command is kept for backward compatibility.

    Fetches the latest available financial report for each company,
    analyzes it with AI (if configured), and assigns Health and
    Potential scores. Reports already collected are skipped.
    """
    _setup_logging(verbose)

    config = load_config(config_path)

    # Validate region names
    available_regions = get_available_regions()
    regions: list[str] | None = None
    if region:
        for r in region:
            if r not in available_regions:
                click.echo(
                    f"Error: Unknown region '{r}'. "
                    f"Available: {', '.join(available_regions)}"
                )
                sys.exit(1)
        regions = list(region)

    region_display = ", ".join(regions) if regions else "all regions"
    click.echo(f"Collecting financial reports for: {region_display}")

    def progress_cb(current: int, total: int, ticker: str, status: str) -> None:
        symbol = {
            "checking": ".",
            "skipped": "~",
            "fetching": ">",
            "done": "+",
            "error": "!",
            "no_data": "-",
        }
        s = symbol.get(status, "?")
        click.echo(f"\r  [{current}/{total}] {s} {ticker:<20}", nl=False)
        if status in ("done", "error", "skipped", "no_data"):
            click.echo()

    reports = asyncio.run(
        collect_financial_reports(
            regions=regions,
            config=config,
            output_dir=output_dir,
            batch_delay=delay,
            progress_callback=progress_cb,
        )
    )

    # Summary
    collected = sum(1 for r in reports if r.error is None)
    errored = sum(1 for r in reports if r.error is not None)
    with_summary = sum(1 for r in reports if r.summary is not None)

    click.echo("\n--- Financial Reports Summary ---")
    click.echo(f"  Collected: {click.style(str(collected), fg='green')}")
    click.echo(
        f"  Errors:    {click.style(str(errored), fg='red') if errored else '0'}"
    )
    click.echo(f"  AI summaries: {with_summary}")
    click.echo(f"  Total:     {len(reports)}")


@cli.command("collect-history")
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Path to config.yaml (default: config/config.yaml).",
)
@click.option(
    "--region",
    "-r",
    multiple=True,
    help="Region(s) to collect (e.g. us_300, china_300, europe_300). "
    "Can be specified multiple times. Defaults to all.",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Output directory for report files.",
)
@click.option(
    "--periods",
    "-p",
    default=8,
    show_default=True,
    type=int,
    help="Number of quarters to collect (default 8 = 2 years).",
)
@click.option(
    "--delay",
    default=0.5,
    show_default=True,
    type=float,
    help="Delay in seconds between yfinance requests (rate limiting).",
)
@click.option(
    "--latest",
    "-l",
    is_flag=True,
    default=False,
    help="Collect only the latest report instead of full history. "
    "Saves to financial_reports table with AI scoring support.",
)
@click.option(
    "--ai-analyze",
    is_flag=True,
    default=False,
    help="Run AI analysis on collected data to generate Health and Potential scores.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging."
)
def collect_history_cmd(
    config_path: Path | None,
    region: tuple[str, ...],
    output_dir: Path | None,
    periods: int,
    delay: float,
    latest: bool,
    ai_analyze: bool,
    verbose: bool,
) -> None:
    """Collect financial data - latest report or historical data for trend analysis.

    By default collects historical quarterly data (last 8 quarters = 2 years).
    Use --latest to collect only the most recent report (like collect-reports).

    Examples:
        collect-history --region us_300              # Collect 8 quarters history
        collect-history --region us_300 --latest    # Collect latest report only
        collect-history --region us_300 --latest --ai-analyze  # Latest + AI scores
    """
    _setup_logging(verbose)

    # Load config to get database URL
    config = load_config(config_path)

    # Validate region names
    available_regions = get_available_regions()
    regions: list[str] | None = None
    if region:
        for r in region:
            if r not in available_regions:
                click.echo(
                    f"Error: Unknown region '{r}. "
                    f"Available: {', '.join(available_regions)}"
                )
                sys.exit(1)
        regions = list(region)

    region_display = ", ".join(regions) if regions else "all regions"

    def progress_cb(current: int, total: int, ticker: str, status: str) -> None:
        symbol = {
            "checking": ".",
            "skipped": "~",
            "fetching": ">",
            "done": "+",
            "error": "!",
            "no_data": "-",
        }
        s = symbol.get(status, "?")
        click.echo(f"\r  [{current}/{total}] {s} {ticker:<20}", nl=False)
        if status in ("done", "error", "skipped", "no_data"):
            click.echo()

    if latest:
        # Collect only the latest report (similar to collect-reports)
        click.echo(f"Collecting latest financial reports for: {region_display}")

        # If AI analyze is requested, we need to call collect_financial_reports
        # which handles the AI analysis internally
        reports = asyncio.run(
            collect_financial_reports(
                regions=regions,
                config=config,
                output_dir=output_dir,
                batch_delay=delay,
                progress_callback=progress_cb,
            )
        )

        # Summary
        collected = sum(1 for r in reports if r.error is None)
        errored = sum(1 for r in reports if r.error is not None)
        with_summary = sum(1 for r in reports if r.summary is not None)

        click.echo("\n--- Financial Reports Summary ---")
        click.echo(f"  Collected: {click.style(str(collected), fg='green')}")
        click.echo(
            f"  Errors:    {click.style(str(errored), fg='red') if errored else '0'}"
        )
        click.echo(f"  AI summaries: {with_summary}")
        click.echo(f"  Total:     {len(reports)}")
    else:
        # Collect full history
        click.echo(f"Collecting {periods}-quarter history for: {region_display}")

        history = asyncio.run(
            collect_financial_history(
                regions=regions,
                output_dir=output_dir,
                max_periods=periods,
                batch_delay=delay,
                progress_callback=progress_cb,
            )
        )

        # Summary
        tickers = set(r.get("ticker") for r in history if r.get("ticker"))
        periods_collected = len(history)

        click.echo("\n--- Financial History Summary ---")
        click.echo(f"  Unique tickers: {click.style(str(len(tickers)), fg='green')}")
        click.echo(f"  Total periods:  {periods_collected}")
        click.echo(
            f"  Periods/ticker: {periods_collected / len(tickers) if tickers else 0:.1f}"
        )


@cli.command("evaluate-reports")
@click.option(
    "--region",
    "-r",
    default=None,
    help="Only evaluate reports from this region (e.g. us_300, china_300).",
)
@click.option(
    "--ticker",
    "-t",
    default=None,
    help="Only evaluate reports matching this ticker (substring, e.g. AAPL).",
)
@click.option(
    "--only-missing",
    "-m",
    is_flag=True,
    default=False,
    help="Only evaluate reports that don't already have an AI summary.",
)
@click.option(
    "--config",
    "-c",
    "config_path",
    default=None,
    type=click.Path(exists=True, path_type=Path),
    help="Path to config.yaml file.",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Output directory containing collected reports.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging."
)
def evaluate_reports_cmd(
    region: str | None,
    ticker: str | None,
    only_missing: bool,
    config_path: Path | None,
    output_dir: Path | None,
    verbose: bool,
) -> None:
    """Re-evaluate financial reports with AI.

    Runs AI analysis on already-collected financial reports to generate
    or regenerate summaries, Health scores, and Potential scores. Useful
    when reports were collected without AI, or to re-evaluate with a
    different model.
    """
    _setup_logging(verbose)

    config = load_config(config_path)

    ai_cfg = config.get("ai") or {}
    if not ai_cfg.get("ai_base_url") or not ai_cfg.get("ai_model"):
        click.echo(
            "Error: AI is not configured. Set ai_base_url and ai_model in config.yaml."
        )
        sys.exit(1)

    filters = []
    if region:
        filters.append(f"region={region}")
    if ticker:
        filters.append(f"ticker={ticker}")
    if only_missing:
        filters.append("only reports missing AI evaluation")

    click.echo("Re-evaluating financial reports with AI")
    if filters:
        click.echo(f"  Filters: {', '.join(filters)}")

    def progress_cb(current: int, total: int, tkr: str, status: str) -> None:
        symbols = {"evaluating": ">", "done": "+", "failed": "!", "error": "!"}
        s = symbols.get(status, "?")
        click.echo(f"\r  [{current}/{total}] {s} {tkr:<20}", nl=False)
        if status in ("done", "failed", "error"):
            click.echo()

    evaluated = asyncio.run(
        evaluate_financial_reports(
            config=config,
            output_dir=output_dir,
            region=region,
            ticker_filter=ticker,
            only_missing=only_missing,
            progress_callback=progress_cb,
        )
    )

    if evaluated > 0:
        click.echo(
            click.style(f"\nEvaluated {evaluated} report(s) successfully.", fg="green")
        )
    else:
        click.echo(click.style("\nNo reports were evaluated.", fg="yellow"))


@cli.command("update-companies")
@click.option(
    "--region",
    "-r",
    multiple=True,
    help="Region(s) to update (e.g. us_300). Defaults to all.",
)
@click.option(
    "--remove-invalid",
    is_flag=True,
    default=False,
    help="Remove tickers that yfinance cannot resolve.",
)
@click.option(
    "--delay",
    default=0.3,
    show_default=True,
    type=float,
    help="Delay in seconds between yfinance lookups.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging."
)
def update_companies_cmd(
    region: tuple[str, ...],
    remove_invalid: bool,
    delay: float,
    verbose: bool,
) -> None:
    """Update config/companies.yaml with latest info from yfinance.

    Fetches the canonical company name for each ticker from yfinance and
    updates the YAML. Identifies invalid or delisted tickers. Use
    --remove-invalid to automatically remove them.
    """
    _setup_logging(verbose)

    available_regions = get_available_regions()
    regions: list[str] | None = None
    if region:
        for r in region:
            if r not in available_regions:
                click.echo(
                    f"Error: Unknown region '{r}'. "
                    f"Available: {', '.join(available_regions)}"
                )
                sys.exit(1)
        regions = list(region)

    region_display = ", ".join(regions) if regions else "all regions"
    click.echo(f"Updating companies.yaml for: {region_display}")
    if remove_invalid:
        click.echo("  Invalid tickers will be removed.")

    def progress_cb(current: int, total: int, tkr: str, status: str) -> None:
        symbols = {
            "checking": ".",
            "updated": "U",
            "ok": ".",
            "invalid": "X",
        }
        s = symbols.get(status, "?")
        click.echo(f"\r  [{current}/{total}] {s} {tkr:<20}", nl=False)
        if status in ("updated", "invalid"):
            click.echo()

    result = asyncio.run(
        update_companies_yaml(
            regions=regions,
            batch_delay=delay,
            remove_invalid=remove_invalid,
            progress_callback=progress_cb,
        )
    )

    click.echo("\n--- Update Summary ---")
    click.echo(f"  Total tickers checked: {result['total']}")
    click.echo(f"  Updated names:  {click.style(str(result['updated']), fg='green')}")
    click.echo(f"  Unchanged:      {result['unchanged']}")
    inv = result["invalid"]
    click.echo(f"  Invalid/broken: {click.style(str(inv), fg='red') if inv else '0'}")
    if result.get("removed"):
        click.echo(
            f"  Removed:        {click.style(str(result['removed']), fg='yellow')}"
        )
    if result.get("invalid_tickers"):
        click.echo(f"\n  Invalid tickers: {', '.join(result['invalid_tickers'][:30])}")
        if len(result["invalid_tickers"]) > 30:
            click.echo(f"    ... and {len(result['invalid_tickers']) - 30} more")


@cli.command("clean-reports")
@click.option(
    "--refetch",
    "-f",
    is_flag=True,
    default=False,
    help="Try to re-fetch data for broken reports instead of just removing them.",
)
@click.option(
    "--delay",
    default=0.5,
    show_default=True,
    type=float,
    help="Delay in seconds between yfinance requests when re-fetching.",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Output directory containing collected reports.",
)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Enable verbose logging."
)
def clean_reports_cmd(
    refetch: bool,
    delay: float,
    output_dir: Path | None,
    verbose: bool,
) -> None:
    """Clean up financial reports by removing entries with no data.

    Removes reports that have errors or no meaningful financial data
    (all financial fields null). Use --refetch to re-download data
    for broken entries before removing them.
    """
    _setup_logging(verbose)

    action = "Re-fetching" if refetch else "Removing"
    click.echo(f"{action} broken/empty financial reports...")

    def progress_cb(current: int, total: int, ticker: str, status: str) -> None:
        symbols = {"refetching": ">", "refetched": "+", "removed": "x"}
        s = symbols.get(status, "?")
        click.echo(f"\r  [{current}/{total}] {s} {ticker:<20}", nl=False)
        if status in ("refetched", "removed"):
            click.echo()

    result = asyncio.run(
        clean_financial_reports(
            output_dir=output_dir,
            refetch=refetch,
            batch_delay=delay,
            progress_callback=progress_cb,
        )
    )

    click.echo("\n--- Cleanup Summary ---")
    click.echo(f"  Total reports:  {result['total']}")
    click.echo(f"  Kept:           {click.style(str(result['kept']), fg='green')}")
    click.echo(
        f"  Removed:        {click.style(str(result['removed']), fg='red') if result['removed'] else '0'}"
    )
    if result.get("refetched"):
        click.echo(
            f"  Re-fetched:     {click.style(str(result['refetched']), fg='cyan')}"
        )


@cli.command("list-regions")
def list_regions_cmd() -> None:
    """List all available company regions for financial report collection."""
    regions = get_available_regions()
    if not regions:
        click.echo("No regions found. Check config/companies.yaml.")
        return
    click.echo("Available regions for financial report collection:\n")
    for r in regions:
        label = REGION_LABELS.get(r, r)
        click.echo(f"  {click.style(r, bold=True):<25} {label}")
    click.echo()


if __name__ == "__main__":
    cli()
