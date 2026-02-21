"""FastAPI web server for browsing collected news items.

This module provides a FastAPI web application for browsing and querying
collected news items, financial reports, and AI-generated verdicts.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from functools import partial
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse

from newscollector.utils.storage import (
    configure_storage,
    list_dates,
    list_labels,
    list_platforms,
    list_regions,
    load_daily_verdicts,
    load_financial_history,
    load_financial_reports,
    query_collected_items,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="NewsCollector", docs_url="/api/docs", redoc_url=None)

# Resolved at startup via configure()
_db_url: str | None = None

STATIC_DIR = Path(__file__).resolve().parent / "static"


# ---------------------------------------------------------------------------
# Currency conversion (all financial values served in USD)
# ---------------------------------------------------------------------------

_exchange_rates: dict[str, float] = {"USD": 1.0}
_rates_fetched_at: float = 0
_RATES_TTL = 21600  # 6 hours

_MONETARY_FIELDS = (
    "revenue",
    "net_income",
    "gross_profit",
    "operating_income",
    "ebitda",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "cash",
    "total_debt",
    "operating_cash_flow",
    "free_cash_flow",
    "market_cap",
)


def _fetch_rates_sync(currencies: set[str]) -> dict[str, float]:
    """Fetch exchange rates to USD for the given currency codes via yfinance.

    :param currencies: Set of currency codes to fetch rates for.
    :return: Dictionary mapping currency codes to USD exchange rates.
    """
    rates: dict[str, float] = {"USD": 1.0}
    need = sorted(c for c in currencies if c != "USD")
    if not need:
        return rates
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed — cannot fetch exchange rates")
        return rates

    for cur in need:
        try:
            t = yf.Ticker(f"{cur}USD=X")
            hist = t.history(period="5d")
            if hist is not None and not hist.empty:
                val = float(hist["Close"].dropna().iloc[-1])
                if val > 0:
                    rates[cur] = val
        except Exception as e:
            logger.debug("Failed to fetch rate for %s: %s", cur, e)

    return rates


async def _get_exchange_rates(currencies: set[str]) -> dict[str, float]:
    """Return cached exchange rates to USD, refreshing if stale or incomplete."""
    global _exchange_rates, _rates_fetched_at
    now = time.time()
    missing = any(c not in _exchange_rates for c in currencies)
    stale = (now - _rates_fetched_at) > _RATES_TTL
    if not missing and not stale:
        return _exchange_rates

    loop = asyncio.get_running_loop()
    new_rates = await loop.run_in_executor(None, partial(_fetch_rates_sync, currencies))
    _exchange_rates.update(new_rates)
    _rates_fetched_at = time.time()
    return _exchange_rates


def _convert_report_to_usd(
    report: dict[str, Any],
    rates: dict[str, float],
) -> dict[str, Any]:
    """Convert all monetary fields in a financial report to USD."""
    cur = (report.get("currency") or "USD").upper()
    if cur == "USD":
        return report
    rate = rates.get(cur)
    if not rate or rate <= 0:
        return report
    converted = dict(report)
    for field in _MONETARY_FIELDS:
        val = converted.get(field)
        if val is not None:
            converted[field] = val * rate
    converted["original_currency"] = cur
    converted["currency"] = "USD"
    return converted


def configure(output_dir: Path | str | None = None, db_url: str | None = None) -> None:
    """Configure storage for the API."""
    global _db_url
    _ = output_dir  # deprecated
    _db_url = db_url
    if db_url:
        configure_storage(db_url)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the single-page frontend."""
    html_path = STATIC_DIR / "index.html"
    return FileResponse(html_path, media_type="text/html")


@app.get("/api/platforms")
async def api_platforms():
    """List platforms that have collected data."""
    return list_platforms(db_url=_db_url)


@app.get("/api/dates")
async def api_dates(platform: str | None = Query(default=None)):
    """List available dates, optionally filtered by platform."""
    return list_dates(platform, db_url=_db_url)


@app.get("/api/items")
async def api_items(
    platform: str | None = Query(default=None),
    date: str | None = Query(default=None),
    region: str | None = Query(default=None),
    search: str | None = Query(default=None),
    labels: list[str] | None = Query(default=None),
    offset: int | None = Query(default=0, ge=0),
):
    """Return collected items with optional filters and pagination.

    If no date is specified, defaults to the latest available date.
    Returns total count so frontend can calculate pagination.
    """
    # Default to latest date if none given
    if not date:
        available = list_dates(platform, db_url=_db_url)
        if available:
            date = available[0]

    items, total = query_collected_items(
        platform=platform,
        date=date,
        region=region,
        search=search,
        labels=labels,
        limit=None,  # No limit - show all items
        offset=offset,
        db_url=_db_url,
    )
    return {
        "date": date,
        "count": len(items),
        "total": total,
        "offset": offset,
        "items": items,
    }


@app.get("/api/regions")
async def api_regions():
    """Return distinct regions found across all collected data."""
    return list_regions(db_url=_db_url)


@app.get("/api/labels")
async def api_labels():
    """Return distinct labels found across all collected data."""
    return list_labels(db_url=_db_url)


@app.get("/api/daily-verdict")
async def api_daily_verdict(
    date: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    region: str | None = Query(default=None),
):
    """Return daily verdicts as global/local political/economic scores."""
    if not date:
        available = list_dates(platform, db_url=_db_url)
        if available:
            date = available[0]
    if not date:
        return {"date": None, "verdict": None}

    by_scope = load_daily_verdicts(date, db_url=_db_url)
    global_verdict = by_scope.get("all")
    if not global_verdict:
        return {"date": date, "verdict": None}

    local_keys: list[str] = []
    if platform and region:
        local_keys.append(f"platform:{platform}|region:{region}")
    if platform:
        local_keys.append(f"platform:{platform}")
    if region:
        local_keys.append(f"region:{region}")
    local_keys.append("all")

    local_verdict = global_verdict
    local_scope_key = "all"
    for key in local_keys:
        candidate = by_scope.get(key)
        if candidate:
            local_verdict = candidate
            local_scope_key = key
            break

    # Use the local verdict (filtered by platform/region) for display
    # The verdict contains both global and domestic scores from AI analysis
    verdict = {
        # Global world situation scores (international affairs)
        "global_political_score": local_verdict.get("political_score"),
        "global_economic_score": local_verdict.get("economic_score"),
        # Domestic situation scores (internal affairs)
        "domestic_political_score": local_verdict.get("domestic_political_score"),
        "domestic_economic_score": local_verdict.get("domestic_economic_score"),
        # Summaries and metadata
        "global_summary": global_verdict.get("summary"),
        "local_summary": local_verdict.get("summary"),
        "global_item_count": global_verdict.get("item_count"),
        "local_item_count": local_verdict.get("item_count"),
        "local_scope_key": local_scope_key,
    }
    return {"date": date, "verdict": verdict}


@app.get("/api/daily-analysis")
async def api_daily_analysis(
    date: str | None = Query(default=None),
):
    """Return daily analysis entries (verdicts by scope) for display."""
    if not date:
        available = list_dates(db_url=_db_url)
        if available:
            date = available[0]
    if not date:
        return {"date": None, "entries": []}

    by_scope = load_daily_verdicts(date, db_url=_db_url)
    if not by_scope:
        return {"date": date, "entries": []}

    # Convert to a list of entries for display
    entries: list[dict[str, Any]] = []
    for scope_key, data in sorted(by_scope.items()):
        entry = {
            "scope_key": scope_key,
            "summary": data.get("summary"),
            "political_score": data.get("political_score"),
            "economic_score": data.get("economic_score"),
            "domestic_political_score": data.get("domestic_political_score"),
            "domestic_economic_score": data.get("domestic_economic_score"),
            "item_count": data.get("item_count"),
        }
        entries.append(entry)

    return {"date": date, "entries": entries}


@app.get("/api/financial-reports")
async def api_financial_reports(
    region: str | None = Query(default=None),
    search: str | None = Query(default=None),
    include_errors: bool = Query(default=False),
    sort_by: str = Query(default="health_score"),
    offset: int | None = Query(default=0, ge=0),
):
    """Return collected financial reports with optional filters and pagination."""
    reports, total = load_financial_reports(
        region=region,
        search=search,
        include_errors=include_errors,
        sort_by=sort_by,
        limit=None,  # No limit - show all items
        offset=offset,
        db_url=_db_url,
    )

    # Convert all monetary values to USD
    currencies = {(r.get("currency") or "USD").upper() for r in reports}
    if currencies - {"USD"}:
        rates = await _get_exchange_rates(currencies)
        reports = [_convert_report_to_usd(r, rates) for r in reports]

    # Inject a 'data_status' field for UI display
    _key_fields = (
        "revenue",
        "net_income",
        "total_assets",
        "total_equity",
        "market_cap",
        "ebitda",
        "gross_profit",
    )
    for r in reports:
        has_data = any(r.get(f) is not None for f in _key_fields)
        has_ai = r.get("summary") is not None
        if r.get("error"):
            r["data_status"] = "error"
        elif not has_data:
            r["data_status"] = "no_data"
        elif not has_ai:
            r["data_status"] = "pending_ai"
        else:
            r["data_status"] = "complete"

    # Get summary stats from database (full filtered count)
    all_reports, _ = load_financial_reports(
        region=region,
        search=search,
        include_errors=include_errors,
        db_url=_db_url,
    )
    total_with_data = sum(
        1 for r in all_reports if r.get("data_status") in ("pending_ai", "complete")
    )
    total_with_ai = sum(1 for r in all_reports if r.get("data_status") == "complete")

    return {
        "count": len(reports),
        "total": total,
        "with_data": total_with_data,
        "with_ai": total_with_ai,
        "offset": offset,
        "reports": reports,
    }


@app.get("/api/financial-regions")
async def api_financial_regions():
    """Return distinct region keys found in collected financial reports."""
    reports, _ = load_financial_reports(db_url=_db_url)
    regions: set[str] = set()
    for r in reports:
        for reg in r.get("regions") or []:
            if reg:
                regions.add(reg)
    return sorted(regions)


@app.get("/api/financial-history")
async def api_financial_history(
    ticker: str | None = Query(default=None),
    periods: int = Query(default=100),
):
    """Return historical financial data for trend analysis.

    Args:
        ticker: Optional ticker filter. If None, returns data for all tickers.
        periods: Number of most recent periods to return (default 8 = 2 years).

    Returns:
        Historical financial records sorted by ticker and report_date descending.
    """
    history = load_financial_history(ticker=ticker, periods=periods, db_url=_db_url)

    # Convert to USD
    currencies = {(r.get("currency") or "USD").upper() for r in history}
    if currencies - {"USD"}:
        rates = await _get_exchange_rates(currencies)
        history = [_convert_report_to_usd(r, rates) for r in history]

    # Group by ticker for easier frontend consumption
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for record in history:
        t = record.get("ticker")
        if t:
            by_ticker.setdefault(t, []).append(record)

    return {
        "count": len(history),
        "tickers": len(by_ticker),
        "by_ticker": by_ticker,
    }


@app.get("/api/financial-sectors")
async def api_financial_sectors():
    """Return aggregated statistics by sector and industry.

    Provides aggregated financial metrics (total revenue, avg growth, etc.)
    across companies grouped by sector and industry.
    """
    reports, _ = load_financial_reports(db_url=_db_url)
    # Exclude error reports
    reports = [r for r in reports if not r.get("error")]

    # Convert to USD
    currencies = {(r.get("currency") or "USD").upper() for r in reports}
    if currencies - {"USD"}:
        rates = await _get_exchange_rates(currencies)
        reports = [_convert_report_to_usd(r, rates) for r in reports]

    # Aggregate by sector
    sectors: dict[str, dict[str, Any]] = {}
    industries: dict[str, dict[str, Any]] = {}

    for r in reports:
        sector = r.get("sector") or "Unknown"
        industry = r.get("industry") or "Unknown"

        # Sector aggregation
        if sector not in sectors:
            sectors[sector] = {
                "sector": sector,
                "count": 0,
                "total_revenue": 0,
                "total_net_income": 0,
                "total_market_cap": 0,
                "avg_health_score": 0,
                "avg_potential_score": 0,
                "companies": [],
            }
        s = sectors[sector]
        s["count"] += 1
        s["total_revenue"] += r.get("revenue") or 0
        s["total_net_income"] += r.get("net_income") or 0
        s["total_market_cap"] += r.get("market_cap") or 0
        if r.get("health_score"):
            s["avg_health_score"] = (
                s["avg_health_score"] * (s["count"] - 1) + r["health_score"]
            ) / s["count"]
        if r.get("potential_score"):
            s["avg_potential_score"] = (
                s["avg_potential_score"] * (s["count"] - 1) + r["potential_score"]
            ) / s["count"]
        s["companies"].append(
            {
                "ticker": r.get("ticker"),
                "company_name": r.get("company_name"),
                "revenue": r.get("revenue"),
                "health_score": r.get("health_score"),
            }
        )

        # Industry aggregation
        key = f"{sector}|{industry}"
        if key not in industries:
            industries[key] = {
                "sector": sector,
                "industry": industry,
                "count": 0,
                "total_revenue": 0,
                "total_market_cap": 0,
                "companies": [],
            }
        ind = industries[key]
        ind["count"] += 1
        ind["total_revenue"] += r.get("revenue") or 0
        ind["total_market_cap"] += r.get("market_cap") or 0
        ind["companies"].append(
            {
                "ticker": r.get("ticker"),
                "company_name": r.get("company_name"),
                "revenue": r.get("revenue"),
            }
        )

    # Convert to list and round values
    sector_list = []
    for s in sectors.values():
        sector_list.append(
            {
                "sector": s["sector"],
                "count": s["count"],
                "total_revenue": (
                    round(s["total_revenue"], 2) if s["total_revenue"] else None
                ),
                "total_net_income": (
                    round(s["total_net_income"], 2) if s["total_net_income"] else None
                ),
                "total_market_cap": (
                    round(s["total_market_cap"], 2) if s["total_market_cap"] else None
                ),
                "avg_health_score": (
                    round(s["avg_health_score"], 1) if s["avg_health_score"] else None
                ),
                "avg_potential_score": (
                    round(s["avg_potential_score"], 1)
                    if s["avg_potential_score"]
                    else None
                ),
            }
        )
    sector_list.sort(key=lambda x: x.get("total_revenue") or 0, reverse=True)

    industry_list = []
    for ind in industries.values():
        industry_list.append(
            {
                "sector": ind["sector"],
                "industry": ind["industry"],
                "count": ind["count"],
                "total_revenue": (
                    round(ind["total_revenue"], 2) if ind["total_revenue"] else None
                ),
                "total_market_cap": (
                    round(ind["total_market_cap"], 2)
                    if ind["total_market_cap"]
                    else None
                ),
            }
        )
    industry_list.sort(key=lambda x: x.get("total_revenue") or 0, reverse=True)

    return {
        "sectors": sector_list,
        "industries": industry_list[:50],  # Top 50 industries
    }


@app.get("/api/financial-rankings")
async def api_financial_rankings(
    sort_by: str = Query(default="health_score"),
    sector: str | None = Query(default=None),
):
    """Return company rankings by different metrics.

    Args:
        sort_by: Metric to sort by (health_score, potential_score, revenue, market_cap, profit_margin).
        sector: Optional sector filter.

    Returns:
        Ranked list of companies with their metrics.
    """
    reports, _ = load_financial_reports(db_url=_db_url)
    # Exclude error reports
    reports = [r for r in reports if not r.get("error")]

    # Convert to USD
    currencies = {(r.get("currency") or "USD").upper() for r in reports}
    if currencies - {"USD"}:
        rates = await _get_exchange_rates(currencies)
        reports = [_convert_report_to_usd(r, rates) for r in reports]

    # Filter by sector
    if sector:
        reports = [r for r in reports if r.get("sector") == sector]

    # Sort and rank
    valid_sort_fields = {
        "health_score",
        "potential_score",
        "revenue",
        "net_income",
        "market_cap",
        "profit_margin",
        "revenue_growth",
        "gross_profit",
    }
    # Handle sort_by with optional _asc or _desc suffix
    sort_dir = "DESC"
    if sort_by.endswith("_desc"):
        sort_by = sort_by[:-5]
        sort_dir = "DESC"
    elif sort_by.endswith("_asc"):
        sort_by = sort_by[:-4]
        sort_dir = "ASC"
    if sort_by not in valid_sort_fields:
        sort_by = "health_score"

    # Add rank
    ranked = []
    for r in reports:
        val = r.get(sort_by)
        if val is not None:
            ranked.append({**r, "sort_value": val})

    ranked.sort(key=lambda x: x.get("sort_value") or 0, reverse=(sort_dir == "DESC"))

    # Take top N and add rank
    result = []
    for idx, r in enumerate(ranked, 1):
        result.append(
            {
                "rank": idx,
                "ticker": r.get("ticker"),
                "company_name": r.get("company_name"),
                "sector": r.get("sector"),
                "industry": r.get("industry"),
                "revenue": r.get("revenue"),
                "net_income": r.get("net_income"),
                "gross_profit": r.get("gross_profit"),
                "market_cap": r.get("market_cap"),
                "profit_margin": r.get("profit_margin"),
                "revenue_growth": r.get("revenue_growth"),
                "health_score": r.get("health_score"),
                "potential_score": r.get("potential_score"),
            }
        )

    return {
        "sort_by": sort_by,
        "count": len(result),
        "rankings": result,
    }


@app.get("/api/company-scores")
async def api_company_scores(
    sector: str | None = Query(default=None),
    industry: str | None = Query(default=None),
    min_health: int | None = Query(default=None, ge=0, le=100),
    max_health: int | None = Query(default=None, ge=0, le=100),
    min_potential: int | None = Query(default=None, ge=0, le=100),
    max_potential: int | None = Query(default=None, ge=0, le=100),
    sort_by: str = Query(default="health_score"),
    offset: int | None = Query(default=0, ge=0),
):
    """Return company scores with filtering and pagination.

    This endpoint provides:
    - List of companies with their scores
    - Filterable by sector, industry, score ranges
    - Sortable by various metrics
    - Paginated results with total count
    """
    reports, total = load_financial_reports(
        require_health_score=True,
        sector=sector,
        industry=industry,
        min_health=min_health,
        max_health=max_health,
        min_potential=min_potential,
        max_potential=max_potential,
        sort_by=sort_by,
        limit=None,  # No limit - show all items
        offset=offset,
        db_url=_db_url,
    )

    # Convert to USD first (so frontend can sort by USD values)
    currencies = {(r.get("currency") or "USD").upper() for r in reports}
    if currencies - {"USD"}:
        rates = await _get_exchange_rates(currencies)
        reports = [_convert_report_to_usd(r, rates) for r in reports]

    # Sort by USD-converted values after currency conversion
    sort_by = sort_by or "health_score"
    valid_sort_fields = {
        "health_score",
        "potential_score",
        "revenue",
        "market_cap",
        "profit_margin",
        "revenue_growth",
    }
    # Handle sort_by with optional _asc or _desc suffix
    sort_dir = "DESC"
    if sort_by.endswith("_desc"):
        sort_by = sort_by[:-5]
        sort_dir = "DESC"
    elif sort_by.endswith("_asc"):
        sort_by = sort_by[:-4]
        sort_dir = "ASC"
    if sort_by not in valid_sort_fields:
        sort_by = "health_score"

    # Sort only records that have the sort field value (not None)
    sortable = [r for r in reports if r.get(sort_by) is not None]
    sortable.sort(key=lambda x: x.get(sort_by) or 0, reverse=(sort_dir == "DESC"))
    # Append records without the sort field value at the end
    non_sortable = [r for r in reports if r.get(sort_by) is None]
    reports = sortable + non_sortable

    # Build response with selected fields
    result = []
    for r in reports:
        result.append(
            {
                "ticker": r.get("ticker"),
                "company_name": r.get("company_name"),
                "sector": r.get("sector"),
                "industry": r.get("industry"),
                "health_score": r.get("health_score"),
                "potential_score": r.get("potential_score"),
                "revenue": r.get("revenue"),
                "market_cap": r.get("market_cap"),
                "profit_margin": r.get("profit_margin"),
                "revenue_growth": r.get("revenue_growth"),
            }
        )

    # Compute summary stats from the returned results
    total_returned = len(result)
    avg_health = (
        sum(r["health_score"] for r in result if r.get("health_score")) / total_returned
        if total_returned
        else 0
    )
    avg_potential = (
        sum(r["potential_score"] for r in result if r.get("potential_score"))
        / total_returned
        if total_returned
        else 0
    )

    return {
        "count": total_returned,
        "total": total,
        "avg_health_score": round(avg_health, 1),
        "avg_potential_score": round(avg_potential, 1),
        "offset": offset,
        "companies": result,
    }


@app.get("/api/company-scores/distribution")
async def api_company_scores_distribution(
    sector: str | None = Query(default=None),
):
    """Return distribution statistics for health and potential scores."""
    reports, _ = load_financial_reports(db_url=_db_url)
    # Exclude error reports and those without health scores
    reports = [
        r for r in reports if not r.get("error") and r.get("health_score") is not None
    ]

    # Filter by sector
    if sector:
        reports = [r for r in reports if r.get("sector") == sector]

    # Build distribution buckets (0-20, 21-40, 41-60, 61-80, 81-100)
    health_buckets = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
    potential_buckets = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}

    for r in reports:
        hs = r.get("health_score") or 0
        ps = r.get("potential_score") or 0

        if hs <= 20:
            health_buckets["0-20"] += 1
        elif hs <= 40:
            health_buckets["21-40"] += 1
        elif hs <= 60:
            health_buckets["41-60"] += 1
        elif hs <= 80:
            health_buckets["61-80"] += 1
        else:
            health_buckets["81-100"] += 1

        if ps <= 20:
            potential_buckets["0-20"] += 1
        elif ps <= 40:
            potential_buckets["21-40"] += 1
        elif ps <= 60:
            potential_buckets["41-60"] += 1
        elif ps <= 80:
            potential_buckets["61-80"] += 1
        else:
            potential_buckets["81-100"] += 1

    return {
        "total": len(reports),
        "health_distribution": health_buckets,
        "potential_distribution": potential_buckets,
    }


@app.get("/api/company-scores/filters")
async def api_company_scores_filters():
    """Return available sectors and industries for filtering."""
    reports, _ = load_financial_reports(db_url=_db_url)
    reports = [
        r for r in reports if not r.get("error") and r.get("health_score") is not None
    ]

    sectors = set()
    industries = set()
    for r in reports:
        if r.get("sector"):
            sectors.add(r["sector"])
        if r.get("industry"):
            industries.add(r["industry"])

    return {
        "sectors": sorted(sectors),
        "industries": sorted(industries)[:100],  # Limit to 100
    }
