"""PostgreSQL storage utilities."""

from __future__ import annotations

import logging
import math
import os
import re
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from newscollector.models import CollectionResult, DailyVerdict, FinancialReport

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "output"
DAILY_ANALYSIS_DIR_NAME = "daily_analysis"
FINANCIAL_REPORTS_DIR_NAME = "financial_reports"

_DB_URL: str | None = None
_DB_ENV = "NEWSCOLLECTOR_DATABASE_URL"


# Simple connection pool implementation for psycopg3
class _SimpleConnectionPool:
    """Simple thread-safe connection pool for psycopg3."""

    def __init__(self, dsn: str, minconn: int = 2, maxconn: int = 10) -> None:
        self._dsn = dsn
        self._minconn = minconn
        self._maxconn = maxconn
        self._pool: deque[psycopg.Connection] = deque()
        self._lock = threading.Lock()
        self._size = 0
        # Lazy connection creation - don't pre-create connections here
        # Connections will be created on-demand in getconn()

    def getconn(self) -> psycopg.Connection:
        with self._lock:
            if self._pool:
                return self._pool.popleft()
            if self._size < self._maxconn:
                conn = psycopg.connect(self._dsn)
                self._size += 1
                return conn
        # Pool exhausted, create new connection anyway
        return psycopg.connect(self._dsn)

    def putconn(self, conn: psycopg.Connection) -> None:
        with self._lock:
            if len(self._pool) < self._maxconn:
                self._pool.append(conn)
            else:
                conn.close()
                self._size -= 1

    def closeall(self) -> None:
        with self._lock:
            while self._pool:
                conn = self._pool.popleft()
                conn.close()
            self._size = 0


_CONNECTION_POOL: _SimpleConnectionPool | None = None
_POOL_MIN_CONN = 2
_POOL_MAX_CONN = 10


# ---------------------------------------------------------------------------
# Connection + schema
# ---------------------------------------------------------------------------


def configure_storage(db_url: str | None) -> None:
    """Configure the default database URL for storage operations."""
    global _DB_URL, _CONNECTION_POOL
    _DB_URL = db_url
    if db_url and _CONNECTION_POOL is None:
        _CONNECTION_POOL = _SimpleConnectionPool(
            dsn=db_url,
            minconn=_POOL_MIN_CONN,
            maxconn=_POOL_MAX_CONN,
        )
        logger.info(
            "Created database connection pool (min=%d, max=%d)",
            _POOL_MIN_CONN,
            _POOL_MAX_CONN,
        )


def _get_connection() -> psycopg.Connection:
    """Get a connection from the pool or create a new one."""
    if _CONNECTION_POOL is not None:
        return _CONNECTION_POOL.getconn()
    return psycopg.connect(_resolve_db_url())


class _Connection:
    """Context manager for database connections that returns to pool."""

    def __init__(self) -> None:
        self.conn = _get_connection()

    def __enter__(self) -> psycopg.Connection:
        return self.conn

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if _CONNECTION_POOL:
            _CONNECTION_POOL.putconn(self.conn)
        else:
            self.conn.close()


def close_pool() -> None:
    """Close the connection pool. Call on application shutdown."""
    global _CONNECTION_POOL
    if _CONNECTION_POOL is not None:
        _CONNECTION_POOL.closeall()
        _CONNECTION_POOL = None
        logger.info("Closed database connection pool")


def _use_connection() -> _Connection:
    """Context manager for database connections."""
    return _Connection()


def _resolve_db_url(db_url: str | None = None) -> str:
    if db_url:
        return db_url
    if _DB_URL:
        return _DB_URL
    env_url = os.getenv(_DB_ENV)
    if env_url:
        return env_url
    raise RuntimeError(
        "Database URL not configured. Set NEWSCOLLECTOR_DATABASE_URL or "
        "storage.database_url in config.yaml, or pass db_url explicitly."
    )


def _ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS collected_items (
                id BIGSERIAL PRIMARY KEY,
                platform TEXT NOT NULL,
                region TEXT,
                date DATE NOT NULL,
                url TEXT,
                normalized_url TEXT,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                rank INTEGER,
                description TEXT,
                summary TEXT,
                heat INTEGER,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                labels TEXT[] NOT NULL DEFAULT '{}',
                collected_at TIMESTAMPTZ NOT NULL,
                identity_type TEXT NOT NULL,
                identity_value TEXT NOT NULL,
                UNIQUE (date, platform, identity_type, identity_value)
            );
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_verdicts (
                id BIGSERIAL PRIMARY KEY,
                date DATE NOT NULL,
                scope_key TEXT NOT NULL,
                platform TEXT,
                region TEXT,
                summary TEXT NOT NULL,
                political_score INTEGER,
                economic_score INTEGER,
                domestic_political_score INTEGER,
                domestic_economic_score INTEGER,
                item_count INTEGER NOT NULL,
                generated_at TIMESTAMPTZ NOT NULL,
                UNIQUE (date, scope_key)
            );
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS financial_reports (
                ticker TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                regions TEXT[] NOT NULL DEFAULT '{}',
                sector TEXT,
                industry TEXT,
                currency TEXT,
                report_period TEXT,
                report_type TEXT,
                report_year INTEGER,
                report_quarter INTEGER,
                revenue DOUBLE PRECISION,
                net_income DOUBLE PRECISION,
                gross_profit DOUBLE PRECISION,
                operating_income DOUBLE PRECISION,
                ebitda DOUBLE PRECISION,
                total_assets DOUBLE PRECISION,
                total_liabilities DOUBLE PRECISION,
                total_equity DOUBLE PRECISION,
                cash DOUBLE PRECISION,
                total_debt DOUBLE PRECISION,
                operating_cash_flow DOUBLE PRECISION,
                free_cash_flow DOUBLE PRECISION,
                market_cap DOUBLE PRECISION,
                pe_ratio DOUBLE PRECISION,
                revenue_growth DOUBLE PRECISION,
                profit_margin DOUBLE PRECISION,
                summary TEXT,
                health_score INTEGER,
                potential_score INTEGER,
                collected_at TIMESTAMPTZ NOT NULL,
                error TEXT
            );
            """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_collected_items_date_platform ON collected_items(date, platform);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_collected_items_region ON collected_items(region);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_collected_items_labels ON collected_items USING GIN(labels);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_daily_verdicts_date ON daily_verdicts(date);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_financial_reports_regions ON financial_reports USING GIN(regions);"
        )
        # Historical financial data table (last 8 quarters per company)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS financial_history (
                id BIGSERIAL PRIMARY KEY,
                ticker TEXT NOT NULL,
                report_period TEXT NOT NULL,
                report_date DATE NOT NULL,
                company_name TEXT NOT NULL,
                sector TEXT,
                industry TEXT,
                currency TEXT,
                revenue DOUBLE PRECISION,
                net_income DOUBLE PRECISION,
                gross_profit DOUBLE PRECISION,
                operating_income DOUBLE PRECISION,
                ebitda DOUBLE PRECISION,
                total_assets DOUBLE PRECISION,
                total_liabilities DOUBLE PRECISION,
                total_equity DOUBLE PRECISION,
                cash DOUBLE PRECISION,
                total_debt DOUBLE PRECISION,
                operating_cash_flow DOUBLE PRECISION,
                free_cash_flow DOUBLE PRECISION,
                market_cap DOUBLE PRECISION,
                pe_ratio DOUBLE PRECISION,
                revenue_growth DOUBLE PRECISION,
                profit_margin DOUBLE PRECISION,
                collected_at TIMESTAMPTZ NOT NULL,
                UNIQUE (ticker, report_period)
            );
            """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_financial_history_ticker ON financial_history(ticker);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_financial_history_period ON financial_history(report_period);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_financial_history_date ON financial_history(report_date);"
        )
    conn.commit()


def clear_storage(db_url: str | None = None) -> None:
    """Delete all stored data (intended for tests)."""
    _resolve_db_url(db_url)  # validates db_url is valid
    conn = _get_connection()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("TRUNCATE collected_items, daily_verdicts, financial_reports;")
        conn.commit()
    finally:
        if _CONNECTION_POOL:
            _CONNECTION_POOL.putconn(conn)
        else:
            conn.close()


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------


def _normalize_url(url: str | None) -> str | None:
    """Normalize URL for deduplication: strip fragment, lowercase host."""
    if not url or not url.strip():
        return None
    try:
        parsed = urlparse(url.strip())
        netloc = parsed.netloc.lower() if parsed.netloc else ""
        normalized = urlunparse(
            (
                parsed.scheme or "",
                netloc,
                parsed.path or "",
                parsed.params,
                parsed.query,
                "",  # no fragment
            )
        )
        return normalized if normalized.strip() else None
    except Exception:
        return None


def _item_identity(item: dict) -> tuple:
    """Return a stable identity tuple for deduplication."""
    url = _normalize_url(item.get("url"))
    if url:
        return ("url", url)
    platform = (item.get("platform") or "").strip()
    source = (item.get("source") or "").strip()
    title = (item.get("title") or "").strip().lower()
    title = re.sub(r"\s+", " ", title)
    return ("title", platform, source, title)


def _is_duplicate(existing: list[dict], new_item: dict) -> bool:
    """Return True if new_item is already present in existing (by identity)."""
    new_id = _item_identity(new_item)
    for old in existing:
        if _item_identity(old) == new_id:
            return True
    return False


def _identity_for_row(item: dict) -> tuple[str, str, str | None]:
    """Return identity_type, identity_value, normalized_url."""
    url = _normalize_url(item.get("url"))
    if url:
        return "url", url, url
    source = (item.get("source") or "").strip().lower()
    title = (item.get("title") or "").strip().lower()
    title = re.sub(r"\s+", " ", title)
    identity_value = f"{source}|{title}"
    return "title", identity_value, None


# ---------------------------------------------------------------------------
# Storage functions
# ---------------------------------------------------------------------------


def save_item(
    item: dict[str, Any],
    platform: str,
    region: str | None = None,
    *,
    db_url: str | None = None,
    date: str | None = None,
) -> bool:
    """Save a single item to PostgreSQL.

    Returns:
        True if item was inserted, False if it was a duplicate.
    """
    if not item:
        return False

    _ = db_url  # URL resolved via _get_connection
    date_str = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    identity_type, identity_value, normalized_url = _identity_for_row(item)

    conn = _get_connection()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO collected_items (
                    platform, region, date, url, normalized_url, source, title,
                    rank, description, summary, heat, metadata, labels, collected_at,
                    identity_type, identity_value
                )
                VALUES (
                    %(platform)s, %(region)s, %(date)s, %(url)s, %(normalized_url)s,
                    %(source)s, %(title)s, %(rank)s, %(description)s, %(summary)s,
                    %(heat)s, %(metadata)s, %(labels)s, %(collected_at)s,
                    %(identity_type)s, %(identity_value)s
                )
                ON CONFLICT (date, platform, identity_type, identity_value)
                DO NOTHING
                RETURNING 1;
                """,
                {
                    "platform": platform,
                    "region": region,
                    "date": date_str,
                    "url": item.get("url"),
                    "normalized_url": normalized_url,
                    "source": item.get("source"),
                    "title": item.get("title"),
                    "rank": item.get("rank"),
                    "description": item.get("description"),
                    "summary": item.get("summary"),
                    "heat": item.get("heat"),
                    "metadata": Json(item.get("metadata") or {}),
                    "labels": item.get("labels") or [],
                    "collected_at": item.get("collected_at")
                    or datetime.now(timezone.utc),
                    "identity_type": identity_type,
                    "identity_value": identity_value,
                },
            )
            inserted = cur.fetchone() is not None
        conn.commit()
    finally:
        if _CONNECTION_POOL:
            _CONNECTION_POOL.putconn(conn)
        else:
            conn.close()

    return inserted


def save_result(
    result: CollectionResult,
    output_dir: Path | str | None = None,
    *,
    db_url: str | None = None,
    date: str | None = None,
) -> int:
    """Save a CollectionResult to PostgreSQL.

    Returns:
        Number of items inserted.
    """
    _ = output_dir  # deprecated
    if not result.items:
        return 0

    _ = db_url  # URL resolved via _get_connection
    date_str = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_dicts = [item.model_dump(mode="json") for item in result.items]

    seen_identities: set[tuple] = set()
    unique_new: list[dict] = []
    for d in new_dicts:
        identity = _item_identity(d)
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        unique_new.append(d)

    if not unique_new:
        return 0

    # Build batch values for executemany
    values = []
    for d in unique_new:
        identity_type, identity_value, normalized_url = _identity_for_row(d)
        values.append(
            (
                d.get("platform"),
                d.get("region"),
                date_str,
                d.get("url"),
                normalized_url,
                d.get("source"),
                d.get("title"),
                d.get("rank"),
                d.get("description"),
                d.get("summary"),
                d.get("heat"),
                Json(d.get("metadata") or {}),
                d.get("labels") or [],
                d.get("collected_at") or datetime.now(timezone.utc),
                identity_type,
                identity_value,
            )
        )

    conn = _get_connection()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO collected_items (
                    platform, region, date, url, normalized_url, source, title,
                    rank, description, summary, heat, metadata, labels, collected_at,
                    identity_type, identity_value
                )
                VALUES (
                    %(platform)s, %(region)s, %(date)s, %(url)s, %(normalized_url)s,
                    %(source)s, %(title)s, %(rank)s, %(description)s, %(summary)s,
                    %(heat)s, %(metadata)s, %(labels)s, %(collected_at)s,
                    %(identity_type)s, %(identity_value)s
                )
                ON CONFLICT (date, platform, identity_type, identity_value)
                DO NOTHING
                RETURNING 1;
                """,
                values,
            )
            inserted = len(cur.fetchall())
        conn.commit()
    finally:
        if _CONNECTION_POOL:
            _CONNECTION_POOL.putconn(conn)
        else:
            conn.close()

    if inserted == 0 and unique_new:
        logger.info("Skipped %d duplicate(s) for %s", len(unique_new), result.platform)
    elif inserted:
        logger.info("Saved %d items for %s on %s", inserted, result.platform, date_str)

    return inserted


def load_daily_verdicts(
    date: str,
    output_dir: Path | str | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Load daily verdict entries for a date, keyed by scope_key."""
    _ = output_dir  # deprecated
    _ = db_url  # resolved via _use_connection
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM daily_verdicts
                WHERE date = %(date)s
                ORDER BY scope_key;
                """,
                {"date": date},
            )
            rows = cur.fetchall()

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        scope_key = str(row.get("scope_key") or "").strip()
        if not scope_key:
            continue
        result[scope_key] = dict(row)
    return result


def save_daily_verdict(
    verdict: DailyVerdict,
    output_dir: Path | str | None = None,
    *,
    db_url: str | None = None,
) -> None:
    """Save or update a DailyVerdict entry."""
    _ = output_dir  # deprecated
    _ = db_url  # resolved via _use_connection
    data = verdict.model_dump(mode="json")
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO daily_verdicts (
                    date, scope_key, platform, region, summary,
                    political_score, economic_score,
                    domestic_political_score, domestic_economic_score,
                    item_count, generated_at
                )
                VALUES (
                    %(date)s, %(scope_key)s, %(platform)s, %(region)s, %(summary)s,
                    %(political_score)s, %(economic_score)s,
                    %(domestic_political_score)s, %(domestic_economic_score)s,
                    %(item_count)s, %(generated_at)s
                )
                ON CONFLICT (date, scope_key) DO UPDATE SET
                    platform = EXCLUDED.platform,
                    region = EXCLUDED.region,
                    summary = EXCLUDED.summary,
                    political_score = EXCLUDED.political_score,
                    economic_score = EXCLUDED.economic_score,
                    domestic_political_score = EXCLUDED.domestic_political_score,
                    domestic_economic_score = EXCLUDED.domestic_economic_score,
                    item_count = EXCLUDED.item_count,
                    generated_at = EXCLUDED.generated_at;
                """,
                {
                    "date": data.get("date"),
                    "scope_key": data.get("scope_key"),
                    "platform": data.get("platform"),
                    "region": data.get("region"),
                    "summary": data.get("summary"),
                    "political_score": data.get("political_score"),
                    "economic_score": data.get("economic_score"),
                    "domestic_political_score": data.get("domestic_political_score"),
                    "domestic_economic_score": data.get("domestic_economic_score"),
                    "item_count": data.get("item_count"),
                    "generated_at": data.get("generated_at")
                    or datetime.now(timezone.utc),
                },
            )
        conn.commit()

    logger.info("Saved daily verdict for %s on %s", verdict.scope_key, verdict.date)


# ---------------------------------------------------------------------------
# Financial reports
# ---------------------------------------------------------------------------


def _sanitize_floats(obj: Any) -> Any:
    """Replace inf, -inf, and nan float values with None recursively."""
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


def load_financial_reports(
    output_dir: Path | str | None = None,
    *,
    region: str | None = None,
    search: str | None = None,
    include_errors: bool = False,
    require_health_score: bool = False,
    sector: str | None = None,
    industry: str | None = None,
    min_health: int | None = None,
    max_health: int | None = None,
    min_potential: int | None = None,
    max_potential: int | None = None,
    sort_by: str = "ticker",
    limit: int | None = None,
    offset: int | None = None,
    db_url: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Load financial reports with optional filters and pagination.

    Args:
        require_health_score: If True, only return reports with a health_score.

    Returns:
        Tuple of (reports list, total count).
    """
    _ = output_dir  # deprecated
    _resolve_db_url(db_url)

    clauses: list[str] = []
    params: dict[str, Any] = {}

    if not include_errors:
        clauses.append("(error IS NULL OR error = '')")
    if require_health_score:
        clauses.append("health_score IS NOT NULL")
    if region:
        clauses.append("%(region)s = ANY(regions)")
        params["region"] = region
    if search:
        clauses.append(
            "(company_name ILIKE %(search)s OR ticker ILIKE %(search)s "
            "OR sector ILIKE %(search)s OR industry ILIKE %(search)s "
            "OR summary ILIKE %(search)s)"
        )
        params["search"] = f"%{search}%"
    if sector:
        clauses.append("sector = %(sector)s")
        params["sector"] = sector
    if industry:
        clauses.append("industry = %(industry)s")
        params["industry"] = industry
    if min_health is not None:
        clauses.append("health_score >= %(min_health)s")
        params["min_health"] = min_health
    if max_health is not None:
        clauses.append("health_score <= %(max_health)s")
        params["max_health"] = max_health
    if min_potential is not None:
        clauses.append("potential_score >= %(min_potential)s")
        params["min_potential"] = min_potential
    if max_potential is not None:
        clauses.append("potential_score <= %(max_potential)s")
        params["max_potential"] = max_potential

    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""

    # Determine sort column and direction
    valid_sort_fields = {
        "ticker",
        "company_name",
        "health_score",
        "potential_score",
        "revenue",
        "market_cap",
        "net_income",
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
        sort_by = "ticker"

    # Sort direction: use parsed direction or default based on field type
    if sort_dir not in ("ASC", "DESC"):
        sort_dir = "DESC" if sort_by not in ("ticker", "company_name") else "ASC"
    # Nulls should always be last (at bottom), regardless of sort direction
    nulls_order = "NULLS LAST" if sort_dir == "DESC" else "NULLS LAST"
    order_sql = f"ORDER BY {sort_by} {sort_dir} {nulls_order}"

    # Get total count
    count_query = f"SELECT COUNT(*) as total FROM financial_reports {where_sql}"

    query = f"""
        SELECT * FROM financial_reports
        {where_sql}
        {order_sql}
    """

    # Add pagination
    if limit is not None and limit > 0:
        query += " LIMIT %(limit)s"
        params["limit"] = limit
    if offset is not None and offset > 0:
        query += " OFFSET %(offset)s"
        params["offset"] = offset

    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            # Get total count
            cur.execute(count_query, params)
            total_result = cur.fetchone()
            total = total_result["total"] if total_result else 0

            # Get paginated results
            cur.execute(query, params)
            rows = cur.fetchall()

    return _sanitize_floats([dict(r) for r in rows]), total


def save_financial_reports(
    reports: list[FinancialReport],
    output_dir: Path | str | None = None,
    *,
    db_url: str | None = None,
) -> None:
    """Save financial reports, merging with existing data by ticker."""
    _ = output_dir  # deprecated
    _ = db_url  # resolved via _use_connection
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            for report in reports:
                report_dict = _sanitize_floats(report.model_dump(mode="json"))
                ticker = report_dict.get("ticker")
                if not ticker:
                    continue
                regions = report_dict.get("regions") or []
                cur.execute(
                    """
                    INSERT INTO financial_reports (
                        ticker, company_name, regions, sector, industry, currency, report_period,
                        report_type, report_year, report_quarter,
                        revenue, net_income, gross_profit, operating_income, ebitda,
                        total_assets, total_liabilities, total_equity, cash, total_debt,
                        operating_cash_flow, free_cash_flow, market_cap, pe_ratio,
                        revenue_growth, profit_margin, summary, health_score, potential_score,
                        collected_at, error
                    )
                    VALUES (
                        %(ticker)s, %(company_name)s, %(regions)s, %(sector)s, %(industry)s,
                        %(currency)s, %(report_period)s,
                        %(report_type)s, %(report_year)s, %(report_quarter)s,
                        %(revenue)s, %(net_income)s, %(gross_profit)s, %(operating_income)s,
                        %(ebitda)s, %(total_assets)s, %(total_liabilities)s, %(total_equity)s,
                        %(cash)s, %(total_debt)s, %(operating_cash_flow)s, %(free_cash_flow)s,
                        %(market_cap)s, %(pe_ratio)s, %(revenue_growth)s, %(profit_margin)s,
                        %(summary)s, %(health_score)s, %(potential_score)s,
                        %(collected_at)s, %(error)s
                    )
                    ON CONFLICT (ticker) DO UPDATE SET
                        company_name = EXCLUDED.company_name,
                        regions = (
                            SELECT ARRAY(
                                SELECT DISTINCT UNNEST(financial_reports.regions || EXCLUDED.regions)
                            )
                        ),
                        sector = EXCLUDED.sector,
                        industry = EXCLUDED.industry,
                        currency = EXCLUDED.currency,
                        report_period = EXCLUDED.report_period,
                        report_type = EXCLUDED.report_type,
                        report_year = EXCLUDED.report_year,
                        report_quarter = EXCLUDED.report_quarter,
                        revenue = EXCLUDED.revenue,
                        net_income = EXCLUDED.net_income,
                        gross_profit = EXCLUDED.gross_profit,
                        operating_income = EXCLUDED.operating_income,
                        ebitda = EXCLUDED.ebitda,
                        total_assets = EXCLUDED.total_assets,
                        total_liabilities = EXCLUDED.total_liabilities,
                        total_equity = EXCLUDED.total_equity,
                        cash = EXCLUDED.cash,
                        total_debt = EXCLUDED.total_debt,
                        operating_cash_flow = EXCLUDED.operating_cash_flow,
                        free_cash_flow = EXCLUDED.free_cash_flow,
                        market_cap = EXCLUDED.market_cap,
                        pe_ratio = EXCLUDED.pe_ratio,
                        revenue_growth = EXCLUDED.revenue_growth,
                        profit_margin = EXCLUDED.profit_margin,
                        summary = EXCLUDED.summary,
                        health_score = EXCLUDED.health_score,
                        potential_score = EXCLUDED.potential_score,
                        collected_at = EXCLUDED.collected_at,
                        error = EXCLUDED.error;
                    """,
                    {
                        **report_dict,
                        "regions": regions,
                        "collected_at": report_dict.get("collected_at")
                        or datetime.now(timezone.utc),
                    },
                )
        conn.commit()

    logger.info("Saved %d financial reports", len(reports))


def save_financial_reports_raw(
    reports: list[dict[str, Any]],
    output_dir: Path | str | None = None,
    *,
    db_url: str | None = None,
) -> None:
    """Save raw report dicts directly, replacing the entire dataset."""
    _ = output_dir  # deprecated
    _ = db_url  # resolved via _use_connection
    clean = _sanitize_floats(reports)
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("TRUNCATE financial_reports;")
            for report in clean:
                if not report.get("ticker"):
                    continue
                cur.execute(
                    """
                    INSERT INTO financial_reports (
                        ticker, company_name, regions, sector, industry, currency, report_period,
                        report_type, report_year, report_quarter,
                        revenue, net_income, gross_profit, operating_income, ebitda,
                        total_assets, total_liabilities, total_equity, cash, total_debt,
                        operating_cash_flow, free_cash_flow, market_cap, pe_ratio,
                        revenue_growth, profit_margin, summary, health_score, potential_score,
                        collected_at, error
                    )
                    VALUES (
                        %(ticker)s, %(company_name)s, %(regions)s, %(sector)s, %(industry)s,
                        %(currency)s, %(report_period)s,
                        %(report_type)s, %(report_year)s, %(report_quarter)s,
                        %(revenue)s, %(net_income)s, %(gross_profit)s, %(operating_income)s,
                        %(ebitda)s, %(total_assets)s, %(total_liabilities)s, %(total_equity)s,
                        %(cash)s, %(total_debt)s, %(operating_cash_flow)s, %(free_cash_flow)s,
                        %(market_cap)s, %(pe_ratio)s, %(revenue_growth)s, %(profit_margin)s,
                        %(summary)s, %(health_score)s, %(potential_score)s,
                        %(collected_at)s, %(error)s
                    );
                    """,
                    {
                        **report,
                        "regions": report.get("regions") or [],
                        "collected_at": report.get("collected_at")
                        or datetime.now(timezone.utc),
                    },
                )
        conn.commit()

    logger.info("Saved %d financial reports (raw)", len(clean))


def upsert_financial_report(
    report: dict[str, Any],
    output_dir: Path | str | None = None,
    *,
    db_url: str | None = None,
) -> bool:
    """Upsert a single financial report (update if exists, insert if new).

    Uses ticker as the unique key for conflict resolution.

    Returns:
        True if report was saved, False if skipped (missing ticker).
    """
    _ = output_dir  # deprecated
    _ = db_url  # resolved via _use_connection
    ticker = report.get("ticker")
    if not ticker:
        return False

    clean = _sanitize_floats([report])[0]
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO financial_reports (
                    ticker, company_name, regions, sector, industry, currency, report_period,
                    report_type, report_year, report_quarter,
                    revenue, net_income, gross_profit, operating_income, ebitda,
                    total_assets, total_liabilities, total_equity, cash, total_debt,
                    operating_cash_flow, free_cash_flow, market_cap, pe_ratio,
                    revenue_growth, profit_margin, summary, health_score, potential_score,
                    collected_at, error
                )
                VALUES (
                    %(ticker)s, %(company_name)s, %(regions)s, %(sector)s, %(industry)s,
                    %(currency)s, %(report_period)s,
                    %(report_type)s, %(report_year)s, %(report_quarter)s,
                    %(revenue)s, %(net_income)s, %(gross_profit)s, %(operating_income)s,
                    %(ebitda)s, %(total_assets)s, %(total_liabilities)s, %(total_equity)s,
                    %(cash)s, %(total_debt)s, %(operating_cash_flow)s, %(free_cash_flow)s,
                    %(market_cap)s, %(pe_ratio)s, %(revenue_growth)s, %(profit_margin)s,
                    %(summary)s, %(health_score)s, %(potential_score)s,
                    %(collected_at)s, %(error)s
                )
                ON CONFLICT (ticker) DO UPDATE SET
                    company_name = EXCLUDED.company_name,
                    regions = EXCLUDED.regions,
                    sector = EXCLUDED.sector,
                    industry = EXCLUDED.industry,
                    currency = EXCLUDED.currency,
                    report_period = EXCLUDED.report_period,
                    report_type = EXCLUDED.report_type,
                    report_year = EXCLUDED.report_year,
                    report_quarter = EXCLUDED.report_quarter,
                    revenue = EXCLUDED.revenue,
                    net_income = EXCLUDED.net_income,
                    gross_profit = EXCLUDED.gross_profit,
                    operating_income = EXCLUDED.operating_income,
                    ebitda = EXCLUDED.ebitda,
                    total_assets = EXCLUDED.total_assets,
                    total_liabilities = EXCLUDED.total_liabilities,
                    total_equity = EXCLUDED.total_equity,
                    cash = EXCLUDED.cash,
                    total_debt = EXCLUDED.total_debt,
                    operating_cash_flow = EXCLUDED.operating_cash_flow,
                    free_cash_flow = EXCLUDED.free_cash_flow,
                    market_cap = EXCLUDED.market_cap,
                    pe_ratio = EXCLUDED.pe_ratio,
                    revenue_growth = EXCLUDED.revenue_growth,
                    profit_margin = EXCLUDED.profit_margin,
                    summary = EXCLUDED.summary,
                    health_score = EXCLUDED.health_score,
                    potential_score = EXCLUDED.potential_score,
                    collected_at = EXCLUDED.collected_at,
                    error = EXCLUDED.error
                ;
                """,
                {
                    **clean,
                    "regions": clean.get("regions") or [],
                    "collected_at": clean.get("collected_at")
                    or datetime.now(timezone.utc),
                },
            )
        conn.commit()

    logger.debug("Upserted financial report for ticker: %s", ticker)
    return True


def save_financial_history_record(
    record: dict[str, Any],
    *,
    db_url: str | None = None,
) -> bool:
    """Save a single historical financial record.

    Returns:
        True if record was saved, False if skipped (missing ticker/period).
    """
    if not record.get("ticker") or not record.get("report_period"):
        return False

    _ = db_url  # resolved via _use_connection
    clean = _sanitize_floats([record])[0]

    # Fill in defaults for optional fields
    defaults = {
        "sector": None,
        "industry": None,
        "currency": None,
        "gross_profit": None,
        "operating_income": None,
        "ebitda": None,
        "total_assets": None,
        "total_liabilities": None,
        "total_equity": None,
        "cash": None,
        "total_debt": None,
        "operating_cash_flow": None,
        "free_cash_flow": None,
        "market_cap": None,
        "pe_ratio": None,
        "revenue_growth": None,
        "profit_margin": None,
    }
    for k, v in defaults.items():
        if k not in clean:
            clean[k] = v

    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO financial_history (
                    ticker, report_period, report_date, company_name, sector, industry, currency,
                    revenue, net_income, gross_profit, operating_income, ebitda,
                    total_assets, total_liabilities, total_equity, cash, total_debt,
                    operating_cash_flow, free_cash_flow, market_cap, pe_ratio,
                    revenue_growth, profit_margin, collected_at
                )
                VALUES (
                    %(ticker)s, %(report_period)s, %(report_date)s, %(company_name)s,
                    %(sector)s, %(industry)s, %(currency)s,
                    %(revenue)s, %(net_income)s, %(gross_profit)s, %(operating_income)s,
                    %(ebitda)s, %(total_assets)s, %(total_liabilities)s, %(total_equity)s,
                    %(cash)s, %(total_debt)s, %(operating_cash_flow)s, %(free_cash_flow)s,
                    %(market_cap)s, %(pe_ratio)s, %(revenue_growth)s, %(profit_margin)s,
                    %(collected_at)s
                )
                ON CONFLICT (ticker, report_period) DO UPDATE SET
                    company_name = EXCLUDED.company_name,
                    sector = EXCLUDED.sector,
                    industry = EXCLUDED.industry,
                    currency = EXCLUDED.currency,
                    revenue = EXCLUDED.revenue,
                    net_income = EXCLUDED.net_income,
                    gross_profit = EXCLUDED.gross_profit,
                    operating_income = EXCLUDED.operating_income,
                    ebitda = EXCLUDED.ebitda,
                    total_assets = EXCLUDED.total_assets,
                    total_liabilities = EXCLUDED.total_liabilities,
                    total_equity = EXCLUDED.total_equity,
                    cash = EXCLUDED.cash,
                    total_debt = EXCLUDED.total_debt,
                    operating_cash_flow = EXCLUDED.operating_cash_flow,
                    free_cash_flow = EXCLUDED.free_cash_flow,
                    market_cap = EXCLUDED.market_cap,
                    pe_ratio = EXCLUDED.pe_ratio,
                    revenue_growth = EXCLUDED.revenue_growth,
                    profit_margin = EXCLUDED.profit_margin,
                    collected_at = EXCLUDED.collected_at;
                """,
                {
                    **clean,
                    "collected_at": clean.get("collected_at")
                    or datetime.now(timezone.utc),
                },
            )
        conn.commit()

    return True


def save_financial_history(
    history: list[dict[str, Any]],
    *,
    db_url: str | None = None,
) -> None:
    """Save historical financial data (quarterly reports for multiple periods)."""
    _ = db_url  # resolved via _use_connection
    clean = _sanitize_floats(history)
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            for record in clean:
                if not record.get("ticker") or not record.get("report_period"):
                    continue
                cur.execute(
                    """
                    INSERT INTO financial_history (
                        ticker, report_period, report_date, company_name, sector, industry, currency,
                        revenue, net_income, gross_profit, operating_income, ebitda,
                        total_assets, total_liabilities, total_equity, cash, total_debt,
                        operating_cash_flow, free_cash_flow, market_cap, pe_ratio,
                        revenue_growth, profit_margin, collected_at
                    )
                    VALUES (
                        %(ticker)s, %(report_period)s, %(report_date)s, %(company_name)s,
                        %(sector)s, %(industry)s, %(currency)s,
                        %(revenue)s, %(net_income)s, %(gross_profit)s, %(operating_income)s,
                        %(ebitda)s, %(total_assets)s, %(total_liabilities)s, %(total_equity)s,
                        %(cash)s, %(total_debt)s, %(operating_cash_flow)s, %(free_cash_flow)s,
                        %(market_cap)s, %(pe_ratio)s, %(revenue_growth)s, %(profit_margin)s,
                        %(collected_at)s
                    )
                    ON CONFLICT (ticker, report_period) DO UPDATE SET
                        company_name = EXCLUDED.company_name,
                        sector = EXCLUDED.sector,
                        industry = EXCLUDED.industry,
                        currency = EXCLUDED.currency,
                        revenue = EXCLUDED.revenue,
                        net_income = EXCLUDED.net_income,
                        gross_profit = EXCLUDED.gross_profit,
                        operating_income = EXCLUDED.operating_income,
                        ebitda = EXCLUDED.ebitda,
                        total_assets = EXCLUDED.total_assets,
                        total_liabilities = EXCLUDED.total_liabilities,
                        total_equity = EXCLUDED.total_equity,
                        cash = EXCLUDED.cash,
                        total_debt = EXCLUDED.total_debt,
                        operating_cash_flow = EXCLUDED.operating_cash_flow,
                        free_cash_flow = EXCLUDED.free_cash_flow,
                        market_cap = EXCLUDED.market_cap,
                        pe_ratio = EXCLUDED.pe_ratio,
                        revenue_growth = EXCLUDED.revenue_growth,
                        profit_margin = EXCLUDED.profit_margin,
                        collected_at = EXCLUDED.collected_at;
                    """,
                    {
                        **record,
                        "collected_at": record.get("collected_at")
                        or datetime.now(timezone.utc),
                    },
                )
        conn.commit()

    logger.info("Saved %d historical financial records", len(clean))


def load_financial_history(
    ticker: str | None = None,
    periods: int | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """Load historical financial data.

    Args:
        ticker: Optional ticker filter. If None, loads all tickers.
        periods: Number of most recent periods to load per ticker. If None, loads all.

    Returns:
        List of historical financial records sorted by ticker and report_date descending.
    """
    _ = db_url  # resolved via _use_connection
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            if ticker:
                if periods:
                    cur.execute(
                        """
                        SELECT * FROM (
                            SELECT *, ROW_NUMBER() OVER (
                                PARTITION BY ticker ORDER BY report_date DESC
                            ) as rn
                            FROM financial_history
                            WHERE ticker = %s
                        ) ranked
                        WHERE rn <= %s
                        ORDER BY ticker, report_date DESC;
                        """,
                        (ticker, periods),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM financial_history WHERE ticker = %s ORDER BY report_date DESC;",
                        (ticker,),
                    )
            else:
                if periods:
                    cur.execute(
                        """
                        SELECT * FROM (
                            SELECT *, ROW_NUMBER() OVER (
                                PARTITION BY ticker ORDER BY report_date DESC
                            ) as rn
                            FROM financial_history
                        ) ranked
                        WHERE rn <= %s
                        ORDER BY ticker, report_date DESC;
                        """,
                        (periods,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM financial_history ORDER BY ticker, report_date DESC;"
                    )
            rows = cur.fetchall()
    return _sanitize_floats([dict(r) for r in rows])


def get_collected_tickers(
    output_dir: Path | str | None = None,
    *,
    db_url: str | None = None,
) -> dict[str, str | None]:
    """Return a dict of ticker -> report_period for already-collected reports."""
    _ = output_dir  # deprecated
    _ = db_url  # resolved via _use_connection
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT ticker, report_period FROM financial_reports;")
            rows = cur.fetchall()
    return {r["ticker"]: r["report_period"] for r in rows if r.get("ticker")}


# ---------------------------------------------------------------------------
# Query helpers for API
# ---------------------------------------------------------------------------


def list_platforms(db_url: str | None = None) -> list[str]:
    _ = db_url  # resolved via _use_connection
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT DISTINCT platform FROM collected_items ORDER BY platform;"
            )
            rows = cur.fetchall()
    return [r["platform"] for r in rows if r.get("platform")]


def list_dates(platform: str | None = None, db_url: str | None = None) -> list[str]:
    _ = db_url  # resolved via _use_connection
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            if platform:
                cur.execute(
                    """
                    SELECT DISTINCT date FROM collected_items
                    WHERE platform = %(platform)s
                    ORDER BY date DESC;
                    """,
                    {"platform": platform},
                )
            else:
                cur.execute(
                    "SELECT DISTINCT date FROM collected_items ORDER BY date DESC;"
                )
            rows = cur.fetchall()
    return [r["date"].strftime("%Y-%m-%d") for r in rows if r.get("date")]


def list_regions(db_url: str | None = None) -> list[str]:
    _ = db_url  # resolved via _use_connection
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT DISTINCT region FROM collected_items
                WHERE region IS NOT NULL AND region <> ''
                ORDER BY region;
                """)
            rows = cur.fetchall()
    regions = [r["region"] for r in rows if r.get("region")]
    return sorted({str(r).strip().title() for r in regions if str(r).strip()})


def list_labels(db_url: str | None = None) -> list[str]:
    _ = db_url  # resolved via _use_connection
    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT DISTINCT label FROM (
                    SELECT UNNEST(labels) AS label FROM collected_items
                ) AS labels
                WHERE label IS NOT NULL AND label <> ''
                ORDER BY label;
                """)
            rows = cur.fetchall()
    return [r["label"] for r in rows if r.get("label")]


def query_collected_items(
    *,
    date: str | None = None,
    platform: str | None = None,
    region: str | None = None,
    search: str | None = None,
    labels: list[str] | None = None,
    limit: int | None = None,
    offset: int | None = None,
    db_url: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Query collected items with optional filters and pagination.

    Returns:
        Tuple of (items list, total count).
    """
    _ = db_url  # resolved via _use_connection

    clauses: list[str] = []
    params: dict[str, Any] = {}

    if date:
        clauses.append("date = %(date)s")
        params["date"] = date
    if platform:
        clauses.append("platform = %(platform)s")
        params["platform"] = platform
    if region:
        clauses.append("LOWER(region) = LOWER(%(region)s)")
        params["region"] = region
    if search:
        clauses.append(
            "(title ILIKE %(search)s OR description ILIKE %(search)s "
            "OR summary ILIKE %(search)s OR source ILIKE %(search)s)"
        )
        params["search"] = f"%{search}%"
    if labels:
        clauses.append("labels && %(labels)s")
        params["labels"] = labels

    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""

    # Get total count
    count_query = f"SELECT COUNT(*) as total FROM collected_items {where_sql}"

    query = f"""
        SELECT title, url, source, platform, region, rank, description,
               summary, heat, metadata, labels, collected_at
        FROM collected_items
        {where_sql}
        ORDER BY (rank IS NULL), rank, heat DESC
    """

    # Add pagination
    if limit is not None and limit > 0:
        query += " LIMIT %(limit)s"
        params["limit"] = limit
    if offset is not None and offset > 0:
        query += " OFFSET %(offset)s"
        params["offset"] = offset

    with _use_connection() as conn:
        _ensure_schema(conn)
        with conn.cursor(row_factory=dict_row) as cur:
            # Get total count
            cur.execute(count_query, params)
            total_result = cur.fetchone()
            total = total_result["total"] if total_result else 0

            # Get paginated results
            cur.execute(query, params)
            rows = cur.fetchall()

    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        collected_at = item.get("collected_at")
        if isinstance(collected_at, datetime):
            item["collected_at"] = collected_at.isoformat()
        items.append(item)
    return items, total


def load_collected_items(
    date: str,
    output_dir: Path | str | None = None,
    platforms: list[str] | None = None,
    region: str | None = None,
    *,
    db_url: str | None = None,
) -> list[dict[str, Any]]:
    """Load collected items for a given date from PostgreSQL.

    Args:
        date: Date string in YYYY-MM-DD format.
        output_dir: Deprecated.
        platforms: List of platforms to load. If None, loads from all.
        region: Optional region filter to apply.
    """
    _ = output_dir  # deprecated
    if platforms:
        items: list[dict[str, Any]] = []
        for platform in platforms:
            items.extend(
                query_collected_items(
                    date=date, platform=platform, region=region, db_url=db_url
                )
            )
        return items
    return query_collected_items(date=date, region=region, db_url=db_url)
