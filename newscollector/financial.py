"""Financial report collector — fetches latest reports via yfinance and analyzes with AI.

This module handles collecting financial reports from Yahoo Finance (yfinance),
analyzing them with AI to generate health and potential scores, and managing
the financial data including history collection and cleanup operations.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

import yaml

from newscollector.models import FinancialReport
from newscollector.utils.ai import analyze_financial_report, is_ai_configured
from newscollector.utils.storage import (
    get_collected_tickers,
    load_financial_reports,
    save_financial_history_record,
    save_financial_reports,
    save_financial_reports_raw,
    upsert_financial_report,
)

logger = logging.getLogger(__name__)

COMPANIES_FILE = Path(__file__).resolve().parent.parent / "config" / "companies.yaml"

REGION_LABELS: dict[str, str] = {
    "us_300": "US Top 300",
    "china_300": "China Top 300",
    "finland_100": "Finland Top 100",
    "europe_300": "Europe Top 300",
    "global_500": "Global Top 500",
}


def load_companies(
    regions: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Load companies from companies.yaml, returning {ticker: {name, regions}}.

    Args:
        regions: List of region keys (e.g. ['us_300', 'china_300']).
                 If None, loads all regions.

    Returns:
        Dict mapping ticker -> {name: str, regions: list[str]}
    """
    if not COMPANIES_FILE.exists():
        logger.warning("companies.yaml not found at %s", COMPANIES_FILE)
        return {}

    with open(COMPANIES_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    all_companies = data.get("companies") or {}
    target_regions = regions or list(all_companies.keys())

    result: dict[str, dict[str, Any]] = {}
    for region_key in target_regions:
        region_data = all_companies.get(region_key)
        if not region_data or not isinstance(region_data, dict):
            logger.warning(
                "Region '%s' not found or empty in companies.yaml", region_key
            )
            continue
        for ticker, name in region_data.items():
            ticker = str(ticker).strip()
            name = str(name).strip()
            if not ticker:
                continue
            if ticker in result:
                result[ticker]["regions"].append(region_key)
            else:
                result[ticker] = {"name": name, "regions": [region_key]}

    return result


def _quarter_from_date(dt: datetime) -> str:
    """Convert a date to 'YYYY-QN' format.

    :param dt: DateTime object.
    :return: Quarter string in format 'YYYY-QN'.
    """
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def _parse_report_period(
    period_str: str | None,
) -> tuple[int | None, int | None, str | None]:
    """Parse report_period string into year, quarter, and type.

    Args:
        period_str: Period string like '2025-Q4' or '2024-FY'

    Returns:
        Tuple of (year, quarter, type) where:
        - year: int or None
        - quarter: int (1-4) or None for annual reports
        - type: 'quarterly' or 'annual' or None
    """
    if not period_str:
        return None, None, None

    period_str = period_str.strip().upper()

    # Handle quarterly format: "2025-Q4"
    if "-Q" in period_str:
        parts = period_str.split("-Q")
        try:
            year = int(parts[0])
            quarter = int(parts[1])
            if 1 <= quarter <= 4:
                return year, quarter, "quarterly"
        except (ValueError, IndexError):
            pass

    # Handle annual format: "2024-FY" or "2024"
    if "-FY" in period_str:
        try:
            year = int(period_str.replace("-FY", ""))
            return year, None, "annual"
        except ValueError:
            pass

    # Try just year
    try:
        year = int(period_str)
        if 1900 <= year <= 2100:
            return year, None, "annual"
    except ValueError:
        pass

    return None, None, None


def _fetch_company_data(ticker_str: str, company_name: str) -> dict[str, Any] | None:
    """Fetch latest financial data for a company using yfinance.

    This is a synchronous function designed to be run in an executor.
    Returns a dict with financial metrics or None on failure.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance is not installed. Run: pip install yfinance")
        return None

    try:
        ticker = yf.Ticker(ticker_str)
        info = ticker.info or {}

        # Determine company name from yfinance or fallback to config
        name = info.get("longName") or info.get("shortName") or company_name

        # Try quarterly financials first, fall back to annual
        report_period = None
        revenue = None
        net_income = None
        gross_profit = None
        operating_income = None
        ebitda = None

        try:
            q_financials = ticker.quarterly_financials
            if q_financials is not None and not q_financials.empty:
                for col in q_financials.columns:
                    col_data = q_financials[col]
                    rev = _safe_float(col_data, "Total Revenue")
                    if rev is not None:
                        report_period = _quarter_from_date(col.to_pydatetime())
                        revenue = rev
                        net_income = _safe_float(col_data, "Net Income")
                        gross_profit = _safe_float(col_data, "Gross Profit")
                        operating_income = _safe_float(col_data, "Operating Income")
                        ebitda = _safe_float(col_data, "EBITDA")
                        break
        except Exception as e:
            logger.debug("Quarterly financials unavailable for %s: %s", ticker_str, e)

        # If no quarterly data, try annual
        if revenue is None:
            try:
                a_financials = ticker.financials
                if a_financials is not None and not a_financials.empty:
                    for col in a_financials.columns:
                        col_data = a_financials[col]
                        rev = _safe_float(col_data, "Total Revenue")
                        if rev is not None:
                            report_period = f"{col.year}-FY"
                            revenue = rev
                            net_income = _safe_float(col_data, "Net Income")
                            gross_profit = _safe_float(col_data, "Gross Profit")
                            operating_income = _safe_float(col_data, "Operating Income")
                            ebitda = _safe_float(col_data, "EBITDA")
                            break
            except Exception as e:
                logger.debug("Annual financials unavailable for %s: %s", ticker_str, e)

        # Balance sheet
        total_assets = None
        total_liabilities = None
        total_equity = None
        cash = None
        total_debt = None

        try:
            q_balance = ticker.quarterly_balance_sheet
            if q_balance is not None and not q_balance.empty:
                for col in q_balance.columns:
                    col_data = q_balance[col]
                    ta = _safe_float(col_data, "Total Assets")
                    if ta is not None:
                        total_assets = ta
                        total_liabilities = _safe_float(
                            col_data, "Total Liabilities Net Minority Interest"
                        )
                        if total_liabilities is None:
                            total_liabilities = _safe_float(col_data, "Total Liab")
                        total_equity = _safe_float(col_data, "Stockholders Equity")
                        if total_equity is None:
                            total_equity = _safe_float(
                                col_data, "Total Stockholders Equity"
                            )
                        cash = _safe_float(col_data, "Cash And Cash Equivalents")
                        if cash is None:
                            cash = _safe_float(col_data, "Cash")
                        total_debt = _safe_float(col_data, "Total Debt")
                        break
        except Exception as e:
            logger.debug("Balance sheet unavailable for %s: %s", ticker_str, e)

        # Cash flow
        operating_cash_flow = None
        free_cash_flow = None

        try:
            q_cashflow = ticker.quarterly_cashflow
            if q_cashflow is not None and not q_cashflow.empty:
                for col in q_cashflow.columns:
                    col_data = q_cashflow[col]
                    for ocf_key in (
                        "Total Cash From Operating Activities",
                        "Operating Cash Flow",
                        "Cash Flow From Continuing Operating Activities",
                        "Cash Flowsfrom Operating Activities",
                    ):
                        operating_cash_flow = _safe_float(col_data, ocf_key)
                        if operating_cash_flow is not None:
                            break
                    if operating_cash_flow is not None:
                        for fcf_key in (
                            "Free Cash Flow",
                            "FreeCashFlow",
                        ):
                            free_cash_flow = _safe_float(col_data, fcf_key)
                            if free_cash_flow is not None:
                                break
                        break
        except Exception as e:
            logger.debug("Cash flow unavailable for %s: %s", ticker_str, e)

        # Fall back to annual cash flow if quarterly is empty
        if operating_cash_flow is None:
            try:
                a_cashflow = ticker.cashflow
                if a_cashflow is not None and not a_cashflow.empty:
                    for col in a_cashflow.columns:
                        col_data = a_cashflow[col]
                        for ocf_key in (
                            "Total Cash From Operating Activities",
                            "Operating Cash Flow",
                            "Cash Flow From Continuing Operating Activities",
                            "Cash Flowsfrom Operating Activities",
                        ):
                            operating_cash_flow = _safe_float(col_data, ocf_key)
                            if operating_cash_flow is not None:
                                break
                        if operating_cash_flow is not None:
                            if free_cash_flow is None:
                                for fcf_key in (
                                    "Free Cash Flow",
                                    "FreeCashFlow",
                                ):
                                    free_cash_flow = _safe_float(col_data, fcf_key)
                                    if free_cash_flow is not None:
                                        break
                            break
            except Exception as e:
                logger.debug("Annual cash flow unavailable for %s: %s", ticker_str, e)

        # Info-based metrics
        market_cap = info.get("marketCap")
        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        revenue_growth = info.get("revenueGrowth")
        profit_margin = info.get("profitMargins")
        sector = info.get("sector")
        industry = info.get("industry")
        # Use financialCurrency for financial values (revenue, net_income, etc.)
        # from quarterly_financials/financials - fall back to currency if not set
        currency = info.get("financialCurrency") or info.get("currency")

        return {
            "company_name": name,
            "sector": sector,
            "industry": industry,
            "currency": currency,
            "report_period": report_period,
            "revenue": revenue,
            "net_income": net_income,
            "gross_profit": gross_profit,
            "operating_income": operating_income,
            "ebitda": ebitda,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "cash": cash,
            "total_debt": total_debt,
            "operating_cash_flow": operating_cash_flow,
            "free_cash_flow": free_cash_flow,
            "market_cap": market_cap,
            "pe_ratio": pe_ratio,
            "revenue_growth": revenue_growth,
            "profit_margin": profit_margin,
        }

    except Exception as e:
        logger.warning("Failed to fetch data for %s: %s", ticker_str, e)
        return None


def _parse_report_date(period_str: str) -> datetime | None:
    """Parse report period string to datetime for sorting.

    Handles formats like '2025-Q1', '2025-Q2', '2025-Q3', '2025-Q4', '2025-FY'
    """
    try:
        if "-Q" in period_str:
            year, q = period_str.split("-Q")
            month = (int(q) - 1) * 3 + 1  # Q1=1, Q2=4, Q3=7, Q4=10
            return datetime(int(year), month, 1)
        elif "-FY" in period_str:
            year = period_str.replace("-FY", "")
            return datetime(int(year), 12, 31)
    except (ValueError, AttributeError):
        pass
    return None


def _fetch_company_history(
    ticker_str: str, company_name: str, max_periods: int = 8
) -> list[dict[str, Any]]:
    """Fetch historical financial data for a company (last N quarters).

    This is a synchronous function designed to be run in an executor.
    Returns a list of dicts with historical financial metrics.

    Args:
        ticker_str: Stock ticker symbol
        company_name: Company name from config
        max_periods: Maximum number of quarters to fetch (default 8 = 2 years)

    Returns:
        List of historical financial records, most recent first.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance is not installed. Run: pip install yfinance")
        return []

    try:
        ticker = yf.Ticker(ticker_str)
        info = ticker.info or {}

        # Determine company name from yfinance or fallback to config
        name = info.get("longName") or info.get("shortName") or company_name
        sector = info.get("sector")
        industry = info.get("industry")
        # Use financialCurrency for financial values - fall back to currency if not set
        currency = info.get("financialCurrency") or info.get("currency")

        history: list[dict[str, Any]] = []

        # Try quarterly financials first
        try:
            q_financials = ticker.quarterly_financials
            if q_financials is not None and not q_financials.empty:
                for col in q_financials.columns:
                    if len(history) >= max_periods:
                        break
                    col_data = q_financials[col]
                    period_str = _quarter_from_date(col.to_pydatetime())
                    report_date = col.to_pydatetime()

                    record = _build_history_record(
                        period_str,
                        report_date,
                        name,
                        sector,
                        industry,
                        currency,
                        col_data,
                    )
                    if record:
                        history.append(record)
        except Exception as e:
            logger.debug("Quarterly financials unavailable for %s: %s", ticker_str, e)

        # If not enough quarterly data, try annual
        if len(history) < max_periods:
            try:
                a_financials = ticker.financials
                if a_financials is not None and not a_financials.empty:
                    for col in a_financials.columns:
                        if len(history) >= max_periods:
                            break
                        col_data = a_financials[col]
                        period_str = f"{col.year}-FY"
                        report_date = col.to_pydatetime()

                        record = _build_history_record(
                            period_str,
                            report_date,
                            name,
                            sector,
                            industry,
                            currency,
                            col_data,
                        )
                        if record:
                            # Avoid duplicates (same period might appear in both)
                            existing_periods = {h.get("report_period") for h in history}
                            if period_str not in existing_periods:
                                history.append(record)
            except Exception as e:
                logger.debug("Annual financials unavailable for %s: %s", ticker_str, e)

        # Sort by report date descending (most recent first)
        history.sort(
            key=lambda x: (
                _parse_report_date(x.get("report_period", "")) or datetime.min
            ),
            reverse=True,
        )

        return history[:max_periods]

    except Exception as e:
        logger.warning("Failed to fetch history for %s: %s", ticker_str, e)
        return []


def _build_history_record(
    period_str: str,
    report_date: datetime,
    name: str,
    sector: str | None,
    industry: str | None,
    currency: str | None,
    col_data: Any,
) -> dict[str, Any] | None:
    """Build a historical record from financial data column."""
    revenue = _safe_float(col_data, "Total Revenue")
    if revenue is None:
        return None

    return {
        "ticker": "",  # Will be set by caller
        "report_period": period_str,
        "report_date": (
            report_date.date() if hasattr(report_date, "date") else report_date
        ),
        "company_name": name,
        "sector": sector,
        "industry": industry,
        "currency": currency,
        "revenue": revenue,
        "net_income": _safe_float(col_data, "Net Income"),
        "gross_profit": _safe_float(col_data, "Gross Profit"),
        "operating_income": _safe_float(col_data, "Operating Income"),
        "ebitda": _safe_float(col_data, "EBITDA"),
        "total_assets": None,  # Not in financials, needs balance sheet
        "total_liabilities": None,
        "total_equity": None,
        "cash": None,
        "total_debt": None,
        "operating_cash_flow": None,  # Not in financials, needs cash flow
        "free_cash_flow": None,
        "market_cap": None,  # From info, changes daily
        "pe_ratio": None,
        "revenue_growth": None,  # Needs comparison
        "profit_margin": (
            _safe_float(col_data, "Net Income") / revenue if revenue else None
        ),
        "collected_at": datetime.now(timezone.utc),
    }


def _safe_float(series: Any, key: str) -> float | None:
    """Safely extract a float value from a pandas Series."""
    try:
        val = series.get(key)
        if val is None:
            return None
        import math

        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (KeyError, TypeError, ValueError):
        return None


def _has_meaningful_data(data: dict[str, Any]) -> bool:
    """Return True if the fetched data has at least some meaningful financial metrics."""
    key_fields = (
        "revenue",
        "net_income",
        "total_assets",
        "total_equity",
        "market_cap",
        "ebitda",
        "gross_profit",
    )
    return any(data.get(f) is not None for f in key_fields)


async def collect_financial_reports(
    regions: list[str] | None = None,
    config: dict[str, Any] | None = None,
    output_dir: Path | str | None = None,
    batch_delay: float = 0.5,
    progress_callback: Any | None = None,
) -> list[FinancialReport]:
    """Collect financial reports for companies in the specified region(s).

    Args:
        regions: List of region keys (e.g. ['us_300', 'china_300']).
                 If None, collects from all regions.
        config: Configuration dict for AI settings.
        output_dir: Output directory override.
        batch_delay: Delay in seconds between yfinance requests.
        progress_callback: Optional callable(current, total, ticker, status) for progress.

    Returns:
        List of collected FinancialReport objects.
    """
    companies = load_companies(regions=regions)
    if not companies:
        logger.warning("No companies to collect")
        return []

    # Check which tickers are already collected
    collected_tickers = get_collected_tickers(output_dir)
    total = len(companies)
    reports: list[FinancialReport] = []
    skipped = 0
    errors = 0

    # AI config
    ai_enabled = is_ai_configured(config or {})
    ai_cfg = (config or {}).get("ai") or {}
    ai_base_url = ai_cfg.get("ai_base_url", "")
    ai_model = ai_cfg.get("ai_model", "")
    ai_api_key = ai_cfg.get("ai_api_key", "")
    ai_response_language = ai_cfg.get("ai_response_language") or None
    ai_timeout = float(ai_cfg.get("ai_request_timeout", 60.0))
    ai_json_retry = int(ai_cfg.get("ai_json_number_retry", 3))
    ai_failures = 0
    ai_max_failures = int(ai_cfg.get("ai_max_failures_before_disable", 5))
    ai_disabled = False

    loop = asyncio.get_running_loop()

    for idx, (ticker, info) in enumerate(companies.items(), 1):
        company_name = info["name"]
        company_regions = info["regions"]

        if progress_callback:
            progress_callback(idx, total, ticker, "checking")

        # Skip if already collected with same report period
        existing_period = collected_tickers.get(ticker)
        if existing_period is not None:
            logger.debug(
                "Skipping %s — already collected (period: %s)", ticker, existing_period
            )
            skipped += 1
            if progress_callback:
                progress_callback(idx, total, ticker, "skipped")
            continue

        # Fetch data via yfinance (in executor to avoid blocking)
        if progress_callback:
            progress_callback(idx, total, ticker, "fetching")

        try:
            data = await loop.run_in_executor(
                None, partial(_fetch_company_data, ticker, company_name)
            )
        except Exception as e:
            logger.warning("Error fetching %s: %s", ticker, e)
            data = None

        if data is None:
            errors += 1
            report = FinancialReport(
                company_name=company_name,
                ticker=ticker,
                regions=company_regions,
                error=f"Failed to fetch data for {ticker}",
            )
            reports.append(report)
            if progress_callback:
                progress_callback(idx, total, ticker, "error")
            await asyncio.sleep(batch_delay)
            continue

        # Check if yfinance returned any meaningful financial data
        if not _has_meaningful_data(data):
            errors += 1
            report = FinancialReport(
                company_name=data.get("company_name") or company_name,
                ticker=ticker,
                regions=company_regions,
                sector=data.get("sector"),
                industry=data.get("industry"),
                currency=data.get("currency"),
                error=f"No financial data available for {ticker}",
            )
            reports.append(report)
            if progress_callback:
                progress_callback(idx, total, ticker, "no_data")
            logger.info(
                "[%d/%d] No financial data for %s (%s)",
                idx,
                total,
                ticker,
                company_name,
            )
            await asyncio.sleep(batch_delay)
            continue

        # Parse report_period to get year, quarter, and type
        report_period = data.get("report_period")
        report_year, report_quarter, report_type = _parse_report_period(report_period)

        # Build report
        report = FinancialReport(
            company_name=data.get("company_name") or company_name,
            ticker=ticker,
            regions=company_regions,
            sector=data.get("sector"),
            industry=data.get("industry"),
            currency=data.get("currency"),
            report_period=report_period,
            report_type=report_type,
            report_year=report_year,
            report_quarter=report_quarter,
            revenue=data.get("revenue"),
            net_income=data.get("net_income"),
            gross_profit=data.get("gross_profit"),
            operating_income=data.get("operating_income"),
            ebitda=data.get("ebitda"),
            total_assets=data.get("total_assets"),
            total_liabilities=data.get("total_liabilities"),
            total_equity=data.get("total_equity"),
            cash=data.get("cash"),
            total_debt=data.get("total_debt"),
            operating_cash_flow=data.get("operating_cash_flow"),
            free_cash_flow=data.get("free_cash_flow"),
            market_cap=data.get("market_cap"),
            pe_ratio=data.get("pe_ratio"),
            revenue_growth=data.get("revenue_growth"),
            profit_margin=data.get("profit_margin"),
        )

        # AI analysis
        if ai_enabled and not ai_disabled:
            try:
                report_dict = report.model_dump(mode="json")
                summary, health, potential = await analyze_financial_report(
                    report_dict,
                    base_url=ai_base_url,
                    model=ai_model,
                    api_key=ai_api_key,
                    response_language=ai_response_language,
                    timeout=ai_timeout,
                    ai_json_number_retry=ai_json_retry,
                )
                if summary:
                    report.summary = summary
                    report.health_score = health
                    report.potential_score = potential
                    ai_failures = 0
                else:
                    ai_failures += 1
            except Exception as e:
                logger.warning("AI analysis failed for %s: %s", ticker, e)
                ai_failures += 1

            if ai_failures >= ai_max_failures:
                ai_disabled = True
                logger.warning(
                    "Disabling AI analysis after %d consecutive failures", ai_failures
                )

        reports.append(report)
        if progress_callback:
            progress_callback(idx, total, ticker, "done")

        logger.info(
            "[%d/%d] Collected %s (%s) — period: %s",
            idx,
            total,
            ticker,
            company_name,
            report.report_period or "N/A",
        )

        # Rate limiting
        await asyncio.sleep(batch_delay)

    # Save all collected reports (excludes error-only reports with no data)
    valid_reports = [r for r in reports if r.error is None]
    if valid_reports:
        save_financial_reports(valid_reports, output_dir=output_dir)

    logger.info(
        "Financial report collection complete: %d collected, %d skipped, %d errors",
        len(valid_reports),
        skipped,
        errors,
    )
    return reports


async def collect_financial_history(
    regions: list[str] | None = None,
    output_dir: Path | str | None = None,
    max_periods: int = 8,
    batch_delay: float = 0.5,
    progress_callback: Any | None = None,
) -> list[dict[str, Any]]:
    """Collect historical financial data (last N quarters) for companies.

    Fetches quarterly and annual financial data for the last N periods
    and stores them in the financial_history table for trend analysis.

    Args:
        regions: List of region keys (e.g. ['us_300', 'china_300']).
                 If None, collects from all regions.
        output_dir: Output directory override (deprecated).
        max_periods: Maximum number of quarters to fetch (default 8 = 2 years).
        batch_delay: Delay in seconds between yfinance requests.
        progress_callback: Optional callable(current, total, ticker, status).

    Returns:
        List of collected historical financial records.
    """
    companies = load_companies(regions=regions)
    if not companies:
        logger.warning("No companies to collect history for")
        return []

    total = len(companies)
    all_history: list[dict[str, Any]] = []
    errors = 0
    loop = asyncio.get_running_loop()

    for idx, (ticker, info) in enumerate(companies.items(), 1):
        company_name = info["name"]

        if progress_callback:
            progress_callback(idx, total, ticker, "fetching")

        try:
            history = await loop.run_in_executor(
                None, partial(_fetch_company_history, ticker, company_name, max_periods)
            )
        except Exception as e:
            logger.warning("Error fetching history for %s: %s", ticker, e)
            errors += 1
            if progress_callback:
                progress_callback(idx, total, ticker, "error")
            await asyncio.sleep(batch_delay)
            continue

        if not history:
            errors += 1
            if progress_callback:
                progress_callback(idx, total, ticker, "no_data")
            logger.info(
                "[%d/%d] No historical data for %s (%s)",
                idx,
                total,
                ticker,
                company_name,
            )
        else:
            # Add ticker to each record and save immediately
            for record in history:
                record["ticker"] = ticker
                save_financial_history_record(record)
            all_history.extend(history)
            if progress_callback:
                progress_callback(idx, total, ticker, "done")
            logger.info(
                "[%d/%d] Collected %d periods for %s (%s)",
                idx,
                total,
                len(history),
                ticker,
                company_name,
            )

        # Rate limiting
        await asyncio.sleep(batch_delay)

    logger.info(
        "Financial history collection complete: %d records, %d errors",
        len(all_history),
        errors,
    )
    return all_history


async def evaluate_financial_reports(
    config: dict[str, Any],
    output_dir: Path | str | None = None,
    region: str | None = None,
    ticker_filter: str | None = None,
    only_missing: bool = False,
    progress_callback: Any | None = None,
) -> int:
    """Re-evaluate existing financial reports with AI.

    Loads already-collected reports, runs AI analysis on each, and saves
    the updated reports back.

    Args:
        config: Configuration dict (must have AI configured).
        output_dir: Output directory override.
        region: Optional region filter (e.g. 'us_300').
        ticker_filter: Optional ticker substring filter (e.g. 'AAPL').
        only_missing: If True, only evaluate reports that lack a summary.
        progress_callback: Optional callable(current, total, ticker, status).

    Returns:
        Number of reports successfully evaluated.
    """
    if not is_ai_configured(config):
        logger.error("AI is not configured — cannot evaluate reports")
        return 0

    reports, _ = load_financial_reports(output_dir)
    if not reports:
        logger.warning("No financial reports found to evaluate")
        return 0

    # Always exclude reports that have errors or no meaningful data
    targets = [r for r in reports if not r.get("error") and _has_meaningful_data(r)]
    if region:
        region_lower = region.lower()
        targets = [
            r
            for r in targets
            if region_lower in [reg.lower() for reg in (r.get("regions") or [])]
        ]
    if ticker_filter:
        tf = ticker_filter.upper()
        targets = [r for r in targets if tf in (r.get("ticker") or "").upper()]
    if only_missing:
        # Check for missing health_score as indicator of missing AI evaluation
        targets = [r for r in targets if r.get("health_score") is None]

    if not targets:
        logger.info("No reports match the filter criteria")
        return 0

    ai_cfg = config.get("ai") or {}
    base_url = ai_cfg.get("ai_base_url", "")
    model = ai_cfg.get("ai_model", "")
    api_key = ai_cfg.get("ai_api_key", "")
    response_language = ai_cfg.get("ai_response_language") or None
    ai_timeout = float(ai_cfg.get("ai_request_timeout", 60.0))
    ai_json_retry = int(ai_cfg.get("ai_json_number_retry", 3))

    # Build a lookup so we can mutate the original list in-place
    by_ticker: dict[str, dict[str, Any]] = {
        r["ticker"]: r for r in reports if r.get("ticker")
    }

    total = len(targets)
    evaluated = 0

    for idx, report in enumerate(targets, 1):
        ticker = report.get("ticker", "???")
        if progress_callback:
            progress_callback(idx, total, ticker, "evaluating")

        try:
            summary, health, potential = await analyze_financial_report(
                report,
                base_url=base_url,
                model=model,
                api_key=api_key,
                response_language=response_language,
                timeout=ai_timeout,
                ai_json_number_retry=ai_json_retry,
            )
            if summary:
                by_ticker[ticker]["summary"] = summary
                by_ticker[ticker]["health_score"] = health
                by_ticker[ticker]["potential_score"] = potential
                evaluated += 1
                # Save immediately after successful evaluation
                upsert_financial_report(by_ticker[ticker], output_dir=output_dir)
                if progress_callback:
                    progress_callback(idx, total, ticker, "done")
            else:
                if progress_callback:
                    progress_callback(idx, total, ticker, "failed")
        except Exception as e:
            logger.warning("AI evaluation failed for %s: %s", ticker, e)
            if progress_callback:
                progress_callback(idx, total, ticker, "error")

    logger.info("Evaluated %d / %d reports", evaluated, total)
    return evaluated


def _fetch_ticker_info(ticker_str: str) -> dict[str, Any] | None:
    """Fetch minimal info for a ticker to validate and get canonical name."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        t = yf.Ticker(ticker_str)
        info = t.info or {}
        name = info.get("longName") or info.get("shortName")
        if not name:
            return None
        return {
            "name": name,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency"),
            "exchange": info.get("exchange"),
            "quote_type": info.get("quoteType"),
        }
    except Exception:
        return None


async def update_companies_yaml(
    regions: list[str] | None = None,
    batch_delay: float = 0.3,
    remove_invalid: bool = False,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Update config/companies.yaml with latest info from yfinance.

    For each ticker in the YAML, fetches the canonical company name from
    yfinance and updates the YAML entry. Optionally removes tickers that
    yfinance cannot resolve.

    Args:
        regions: Region keys to update. None = all.
        batch_delay: Delay between API calls.
        remove_invalid: If True, remove tickers that yfinance can't find.
        progress_callback: Optional callable(current, total, ticker, status).

    Returns:
        Summary dict with counts of updated, invalid, unchanged tickers.
    """
    if not COMPANIES_FILE.exists():
        logger.error("companies.yaml not found at %s", COMPANIES_FILE)
        return {"updated": 0, "invalid": 0, "unchanged": 0, "total": 0}

    with open(COMPANIES_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    all_companies = data.get("companies") or {}
    target_regions = regions or list(all_companies.keys())

    # Collect all unique tickers across targeted regions
    unique_tickers: dict[str, list[str]] = {}  # ticker -> [region_keys]
    for region_key in target_regions:
        region_data = all_companies.get(region_key)
        if not region_data or not isinstance(region_data, dict):
            continue
        for ticker in region_data:
            t = str(ticker).strip()
            if t:
                unique_tickers.setdefault(t, []).append(region_key)

    total = len(unique_tickers)
    updated = 0
    invalid = 0
    unchanged = 0
    invalid_tickers: list[str] = []
    loop = asyncio.get_running_loop()

    for idx, (ticker, region_keys) in enumerate(unique_tickers.items(), 1):
        if progress_callback:
            progress_callback(idx, total, ticker, "checking")

        info = await loop.run_in_executor(None, partial(_fetch_ticker_info, ticker))

        if info is None:
            invalid += 1
            invalid_tickers.append(ticker)
            if progress_callback:
                progress_callback(idx, total, ticker, "invalid")
            if remove_invalid:
                for rk in region_keys:
                    rd = all_companies.get(rk)
                    if rd and ticker in rd:
                        del rd[ticker]
                        logger.info("Removed invalid ticker %s from %s", ticker, rk)
        else:
            new_name = info["name"]
            changed = False
            for rk in region_keys:
                rd = all_companies.get(rk)
                if rd and ticker in rd:
                    old_name = str(rd[ticker]).strip()
                    if old_name != new_name:
                        rd[ticker] = new_name
                        changed = True
            if changed:
                updated += 1
                if progress_callback:
                    progress_callback(idx, total, ticker, "updated")
            else:
                unchanged += 1
                if progress_callback:
                    progress_callback(idx, total, ticker, "ok")

        await asyncio.sleep(batch_delay)

    # Write back
    # Preserve the YAML structure: dump the data dict, then re-insert the
    # header comment manually.
    header = (
        "# Company lists for financial report collection.\n"
        "# Organized by region/list. Ticker symbols are yfinance-compatible.\n"
        '# Format: ticker: "Company Name"\n'
        "#\n"
        "# Auto-updated by: python -m newscollector update-companies\n\n"
    )
    yaml_body = yaml.dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    COMPANIES_FILE.write_text(header + yaml_body, encoding="utf-8")
    logger.info(
        "Updated companies.yaml: %d updated, %d invalid, %d unchanged",
        updated,
        invalid,
        unchanged,
    )

    return {
        "updated": updated,
        "invalid": invalid,
        "invalid_tickers": invalid_tickers,
        "unchanged": unchanged,
        "total": total,
        "removed": len(invalid_tickers) if remove_invalid else 0,
    }


async def clean_financial_reports(
    output_dir: Path | str | None = None,
    remove_no_data: bool = True,
    remove_errors: bool = True,
    refetch: bool = False,
    batch_delay: float = 0.5,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Clean up financial reports by removing or re-fetching broken entries.

    Args:
        output_dir: Output directory override.
        remove_no_data: Remove reports with no meaningful financial data.
        remove_errors: Remove reports that have error fields set.
        refetch: If True, try to re-fetch data for problematic reports
                 instead of removing them.
        batch_delay: Delay between yfinance requests when re-fetching.
        progress_callback: Optional callable(current, total, ticker, status).

    Returns:
        Summary dict with counts.
    """
    reports, _ = load_financial_reports(output_dir)
    if not reports:
        logger.info("No financial reports to clean")
        return {"total": 0, "removed": 0, "refetched": 0, "kept": 0}

    clean: list[dict[str, Any]] = []
    problematic: list[dict[str, Any]] = []

    for r in reports:
        has_error = bool(r.get("error"))
        has_data = _has_meaningful_data(r)

        if (has_error and remove_errors) or (not has_data and remove_no_data):
            problematic.append(r)
        else:
            clean.append(r)

    removed = 0
    refetched = 0
    total_problematic = len(problematic)

    if refetch and problematic:
        loop = asyncio.get_running_loop()
        for idx, r in enumerate(problematic, 1):
            ticker = r.get("ticker", "???")
            company_name = r.get("company_name", ticker)

            if progress_callback:
                progress_callback(idx, total_problematic, ticker, "refetching")

            try:
                data = await loop.run_in_executor(
                    None, partial(_fetch_company_data, ticker, company_name)
                )
            except Exception as e:
                logger.warning("Re-fetch failed for %s: %s", ticker, e)
                data = None

            if data and _has_meaningful_data(data):
                updated = dict(r)
                updated.update(data)
                updated["company_name"] = data.get("company_name") or company_name
                updated["error"] = None
                updated["collected_at"] = datetime.now(timezone.utc).isoformat()
                clean.append(updated)
                refetched += 1
                if progress_callback:
                    progress_callback(idx, total_problematic, ticker, "refetched")
            else:
                removed += 1
                if progress_callback:
                    progress_callback(idx, total_problematic, ticker, "removed")

            await asyncio.sleep(batch_delay)
    else:
        removed = total_problematic

    save_financial_reports_raw(clean, output_dir=output_dir)
    logger.info(
        "Cleaned financial reports: %d kept, %d removed, %d re-fetched",
        len(clean),
        removed,
        refetched,
    )
    return {
        "total": len(reports),
        "removed": removed,
        "refetched": refetched,
        "kept": len(clean),
    }


def get_available_regions() -> list[str]:
    """Return list of available region keys from companies.yaml."""
    if not COMPANIES_FILE.exists():
        return []
    with open(COMPANIES_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    companies = data.get("companies") or {}
    return sorted(companies.keys())
