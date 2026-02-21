"""AI summarization and labelling for news items (OpenAI-compatible API)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _err_text(exc: Exception) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__


# Default topic categories for label hints (AI may return others)
LABEL_HINTS = "financial, sports, politics, game, entertainment, technology, science, health, world"


def _extract_json_text(content: str) -> str:
    """Extract JSON payload from raw model content."""
    payload = (content or "").strip()
    if "```" not in payload:
        return payload

    start = payload.find("```")
    if start == -1:
        return payload
    first_newline = payload.find("\n", start)
    if first_newline == -1:
        return payload
    end = payload.find("```", first_newline + 1)
    if end == -1:
        return payload
    return payload[first_newline + 1 : end].strip()


def _first_choice_content(data: dict[str, Any]) -> str:
    """Return first chat completion message content."""
    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        return ""
    return str((choices[0].get("message") or {}).get("content") or "").strip()


def is_ai_configured(config: dict[str, Any]) -> bool:
    """Return True if ai_base_url, ai_model and ai_api_key are all set in config."""
    ai = config.get("ai") or {}
    return bool(ai.get("ai_base_url") and ai.get("ai_model") and ai.get("ai_api_key"))


def _build_prompt(
    title: str, description: str | None, response_language: str | None = None
) -> str:
    content = (title or "").strip()
    if description and description.strip():
        content += "\n\n" + (description or "").strip()
    if not content:
        content = "(no content)"
    lang_instruction = ""
    if response_language and response_language.strip():
        lang_instruction = f" Respond in {response_language.strip()} for both the summary and the labels.\n\n"
    return f"""Summarize this news item in 1–2 short sentences, then assign exactly 3 topic labels that are most relevant.{lang_instruction}
Suggested label categories (use these or similar): {LABEL_HINTS}

Respond with valid JSON only, no other text:
{{"summary": "Your one or two sentence summary here.", "labels": ["label1", "label2", "label3"]}}

Content:
{content}"""


def _build_page_summary_prompt(
    title: str,
    page_text: str,
    response_language: str | None = None,
) -> str:
    """Build prompt to summarize an item using page body text."""
    clean_title = (title or "").strip()
    clean_page = (page_text or "").strip()
    if not clean_page:
        clean_page = "(no page text)"

    lang_instruction = ""
    if response_language and response_language.strip():
        lang_instruction = f" Respond in {response_language.strip()} for both the summary and the labels.\n\n"

    return f"""Summarize this web page in 1-2 short sentences, then assign exactly 3 topic labels that are most relevant.{lang_instruction}
Suggested label categories (use these or similar): {LABEL_HINTS}

Use this title as context: {clean_title or "(no title)"}

Respond with valid JSON only, no other text:
{{"summary": "Your one or two sentence summary here.", "labels": ["label1", "label2", "label3"]}}

Page text:
{clean_page}"""


def _build_html_extract_prompt(
    *,
    platform: str,
    page_url: str,
    html_excerpt: str,
    response_language: str | None = None,
    max_items: int = 30,
) -> str:
    """Build prompt to extract structured trending entries from page HTML."""
    lang_instruction = ""
    if response_language and response_language.strip():
        lang_instruction = (
            f"- Use {response_language.strip()} if text generation is needed.\n"
        )

    return f"""Extract trending entries for platform "{platform}" from this HTML excerpt.
Return valid JSON only: an array of objects, max {max_items} items.

Each object keys:
- title (required, non-empty string)
- url (optional absolute https URL if present)
- source (optional string)
- description (optional short text)
- rank (optional integer)
- heat (optional integer)
- metadata (optional object)

Rules:
- Only include entries clearly present in the HTML.
- Skip ads or navigation items.
- Prefer the top/trending list entries.
- Do not include duplicate titles.
{lang_instruction}
Current page URL: {page_url}

HTML excerpt:
{html_excerpt}"""


def _normalize_labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(lb).strip() for lb in value if str(lb).strip()][:3]


def _normalize_extracted_items(value: Any, max_items: int) -> list[dict[str, Any]]:
    """Normalize AI extracted entries to stable dict payloads."""
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        title_key = " ".join(title.lower().split())
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        url = str(raw.get("url") or "").strip() or None
        if url and not (url.startswith("http://") or url.startswith("https://")):
            url = None

        source = str(raw.get("source") or "").strip() or None
        description = str(raw.get("description") or "").strip() or None

        rank = raw.get("rank")
        try:
            rank = int(rank) if rank is not None else None
        except (TypeError, ValueError):
            rank = None

        heat = raw.get("heat")
        try:
            heat = int(heat) if heat is not None else None
        except (TypeError, ValueError):
            heat = None

        metadata = raw.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        normalized.append(
            {
                "title": title,
                "url": url,
                "source": source,
                "description": description,
                "rank": rank,
                "heat": heat,
                "metadata": metadata,
            }
        )
        if len(normalized) >= max_items:
            break

    return normalized


def _format_items_for_verdict(items: list[dict[str, Any]], start_idx: int = 1) -> str:
    """Format items into a numbered list for verdict prompts."""
    snippets: list[str] = []
    for idx, item in enumerate(items, start=start_idx):
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or item.get("description") or "").strip()
        source = str(item.get("source") or "").strip()
        platform = str(item.get("platform") or "").strip()
        region = str(item.get("region") or "").strip()
        fragments = [f"{idx}. {title}"]
        if summary:
            fragments.append(f"Summary: {summary}")
        if source or platform or region:
            fragments.append(
                f"Meta: source={source or 'unknown'}, "
                f"platform={platform or 'unknown'}, region={region or 'unknown'}"
            )
        snippets.append("\n".join(fragments))
    return "\n\n".join(snippets) if snippets else "(no items)"


def _build_daily_verdict_prompt(
    items: list[dict[str, Any]],
    response_language: str | None = None,
    max_items: int = 400,
) -> str:
    """Build prompt for daily political/economic verdict from collected items."""
    content = _format_items_for_verdict(items[:max_items])
    lang_instruction = ""
    if response_language and response_language.strip():
        lang_instruction = (
            f"Write the daily summary in {response_language.strip()}.\n\n"
        )

    return f"""You are analyzing news signals for one day.
Use only the provided items and avoid certainty. Keep the tone neutral and concise.

Return valid JSON only with exactly these keys:
{{
  "summary": "2-4 short sentences about the day overall.",
  "global_political_score": 0,
  "global_economic_score": 0,
  "domestic_political_score": 0,
  "domestic_economic_score": 0
}}

Scoring rules:
- 0 means severe instability/crisis, 100 means very stable/healthy conditions.
- Scores must be integers between 0 and 100.
- Base scores on the balance and severity of evidence in the provided items.

Score definitions:
- global_political_score: Reflects international/geopolitical political stability (wars, diplomacy, international conflicts, global governance).
- global_economic_score: Reflects international/global economic conditions (trade, global markets, international finance, commodities).
- domestic_political_score: Reflects domestic/internal political stability (local government, elections, civil unrest, policy changes within countries).
- domestic_economic_score: Reflects domestic/local economic conditions (employment, local markets, inflation, business conditions within countries).

{lang_instruction}Items:
{content}"""


def _build_daily_verdict_continuation_prompt(
    items: list[dict[str, Any]],
    previous_verdict: dict[str, Any],
    chunk_number: int,
    total_chunks: int,
    items_processed: int,
    response_language: str | None = None,
) -> str:
    """Build prompt for continuing verdict evaluation with new items."""
    content = _format_items_for_verdict(items, start_idx=items_processed + 1)
    lang_instruction = ""
    if response_language and response_language.strip():
        lang_instruction = (
            f"Write the daily summary in {response_language.strip()}.\n\n"
        )

    prev_summary = previous_verdict.get("summary", "(no previous summary)")
    prev_global_political = previous_verdict.get("global_political_score", "N/A")
    prev_global_economic = previous_verdict.get("global_economic_score", "N/A")
    prev_domestic_political = previous_verdict.get("domestic_political_score", "N/A")
    prev_domestic_economic = previous_verdict.get("domestic_economic_score", "N/A")

    return f"""You are continuing to analyze news signals for one day.
This is batch {chunk_number} of {total_chunks}. You have already analyzed {items_processed} items.

Previous verdict based on items 1-{items_processed}:
- Summary: {prev_summary}
- Global Political Score: {prev_global_political}
- Global Economic Score: {prev_global_economic}
- Domestic Political Score: {prev_domestic_political}
- Domestic Economic Score: {prev_domestic_economic}

Now analyze the following additional items and UPDATE the verdict by combining insights from both the previous analysis and these new items.
Use only the provided items and avoid certainty. Keep the tone neutral and concise.

Return valid JSON only with exactly these keys:
{{
  "summary": "2-4 short sentences about the day overall (incorporating all items analyzed so far).",
  "global_political_score": 0,
  "global_economic_score": 0,
  "domestic_political_score": 0,
  "domestic_economic_score": 0
}}

Scoring rules:
- 0 means severe instability/crisis, 100 means very stable/healthy conditions.
- Scores must be integers between 0 and 100.
- Base scores on the balance and severity of evidence in ALL items analyzed (previous + new).

Score definitions:
- global_political_score: Reflects international/geopolitical political stability (wars, diplomacy, international conflicts, global governance).
- global_economic_score: Reflects international/global economic conditions (trade, global markets, international finance, commodities).
- domestic_political_score: Reflects domestic/internal political stability (local government, elections, civil unrest, policy changes within countries).
- domestic_economic_score: Reflects domestic/local economic conditions (employment, local markets, inflation, business conditions within countries).

{lang_instruction}Additional items ({items_processed + 1}-{items_processed + len(items)}):
{content}"""


async def summarize_and_label(
    title: str,
    description: str | None,
    *,
    base_url: str,
    model: str,
    api_key: str,
    response_language: str | None = None,
    timeout: float = 30.0,
) -> tuple[str | None, list[str]]:
    """Call AI to get a short summary and exactly 3 topic labels for the item.

    Args:
        response_language: If set, instructs the AI to respond in this language
            for both summary and labels (e.g. "English", "中文", "日本語").

    Returns:
        (summary, labels) — summary may be None on parse/API error; labels may be empty.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": _build_prompt(title, description, response_language),
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.warning("AI request failed: %s", _err_text(e))
        return None, []

    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        logger.warning("AI response missing choices")
        return None, []

    content = (choices[0].get("message") or {}).get("content") or ""
    content = content.strip()

    content = _extract_json_text(content)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("AI response not valid JSON: %s", e)
        return None, []

    summary = parsed.get("summary")
    if summary is not None:
        summary = str(summary).strip() or None
    labels = _normalize_labels(parsed.get("labels"))

    return summary, labels


async def summarize_and_label_from_page(
    title: str,
    page_text: str,
    *,
    base_url: str,
    model: str,
    api_key: str,
    response_language: str | None = None,
    timeout: float = 35.0,
) -> tuple[str | None, list[str]]:
    """Call AI to summarize from page text and return labels."""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": _build_page_summary_prompt(
                    title, page_text, response_language
                ),
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.warning("AI page-summary request failed: %s", _err_text(e))
        return None, []

    content = _extract_json_text(_first_choice_content(data))
    if not content:
        logger.warning("AI page-summary response missing content")
        return None, []
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("AI page-summary response not valid JSON: %s", e)
        return None, []

    summary = parsed.get("summary")
    if summary is not None:
        summary = str(summary).strip() or None
    labels = _normalize_labels(parsed.get("labels"))
    return summary, labels


async def extract_items_from_html(
    *,
    platform: str,
    page_url: str,
    html_excerpt: str,
    base_url: str,
    model: str,
    api_key: str,
    response_language: str | None = None,
    max_items: int = 30,
    timeout: float = 45.0,
) -> list[dict[str, Any]]:
    """Call AI to extract structured items from platform page HTML."""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": _build_html_extract_prompt(
                    platform=platform,
                    page_url=page_url,
                    html_excerpt=html_excerpt,
                    response_language=response_language,
                    max_items=max_items,
                ),
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        logger.warning("AI HTML extraction request failed: %s", _err_text(e))
        return []

    content = _extract_json_text(_first_choice_content(data))
    if not content:
        logger.warning("AI HTML extraction response missing content")
        return []
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("AI HTML extraction response not valid JSON: %s", e)
        return []

    return _normalize_extracted_items(parsed, max_items=max_items)


def _clamp_score(value: Any) -> int | None:
    """Clamp a score value to 0-100 range or return None if invalid."""
    try:
        score = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, score))


def _parse_verdict_response(content: str) -> dict[str, Any] | None:
    """Parse AI verdict response and return structured dict or None on failure."""
    if not content:
        logger.warning("Daily AI verdict response missing choices")
        return None

    content = _extract_json_text(content)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning("Daily AI verdict response not valid JSON: %s", e)
        return None

    summary = parsed.get("summary")
    if summary is not None:
        summary = str(summary).strip() or None

    global_political_score = _clamp_score(parsed.get("global_political_score"))
    global_economic_score = _clamp_score(parsed.get("global_economic_score"))
    domestic_political_score = _clamp_score(parsed.get("domestic_political_score"))
    domestic_economic_score = _clamp_score(parsed.get("domestic_economic_score"))

    if (
        summary is None
        or global_political_score is None
        or global_economic_score is None
        or domestic_political_score is None
        or domestic_economic_score is None
    ):
        logger.warning("Daily AI verdict response missing required fields")
        return None

    return {
        "summary": summary,
        "global_political_score": global_political_score,
        "global_economic_score": global_economic_score,
        "domestic_political_score": domestic_political_score,
        "domestic_economic_score": domestic_economic_score,
    }


async def _call_verdict_api(
    prompt: str,
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout: float,
    ai_json_number_retry: int = 3,
) -> dict[str, Any] | None:
    """Make a single verdict API call and parse the response.

    If parsing fails, retries up to ai_json_number_retry times.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }

    for attempt in range(ai_json_number_retry):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning("Daily AI verdict request failed: %s", _err_text(e))
            return None

        content = _first_choice_content(data)
        result = _parse_verdict_response(content)

        if result is not None:
            return result

        # Parse failed - print the response and retry if attempts remain
        logger.warning(
            "Daily AI verdict parse failed (attempt %d/%d). Response:\n%s",
            attempt + 1,
            ai_json_number_retry,
            content,
        )

    logger.error(
        "Daily AI verdict parse failed after %d attempts", ai_json_number_retry
    )
    return None


def _build_financial_analysis_prompt(
    report: dict[str, Any],
    response_language: str | None = None,
) -> str:
    """Build prompt for AI analysis of a financial report."""
    name = report.get("company_name", "Unknown")
    ticker = report.get("ticker", "???")
    sector = report.get("sector") or "N/A"
    industry = report.get("industry") or "N/A"
    currency = report.get("currency") or "N/A"
    period = report.get("report_period") or "N/A"

    def fmt(val: Any) -> str:
        if val is None:
            return "N/A"
        try:
            v = float(val)
            if abs(v) >= 1e12:
                return f"{v / 1e12:.2f}T"
            if abs(v) >= 1e9:
                return f"{v / 1e9:.2f}B"
            if abs(v) >= 1e6:
                return f"{v / 1e6:.2f}M"
            return f"{v:,.0f}"
        except (TypeError, ValueError):
            return str(val)

    def pct(val: Any) -> str:
        if val is None:
            return "N/A"
        try:
            return f"{float(val) * 100:.1f}%"
        except (TypeError, ValueError):
            return str(val)

    lang_instruction = ""
    if response_language and response_language.strip():
        lang_instruction = f"Write the summary in {response_language.strip()}.\n\n"

    return f"""Analyze this company's latest financial report and provide a verdict.

Company: {name} ({ticker})
Sector: {sector} | Industry: {industry}
Reporting Currency: {currency}
Report Period: {period}

Income Statement:
- Revenue: {fmt(report.get("revenue"))}
- Net Income: {fmt(report.get("net_income"))}
- Gross Profit: {fmt(report.get("gross_profit"))}
- Operating Income: {fmt(report.get("operating_income"))}
- EBITDA: {fmt(report.get("ebitda"))}

Balance Sheet:
- Total Assets: {fmt(report.get("total_assets"))}
- Total Liabilities: {fmt(report.get("total_liabilities"))}
- Stockholders' Equity: {fmt(report.get("total_equity"))}
- Cash & Equivalents: {fmt(report.get("cash"))}
- Total Debt: {fmt(report.get("total_debt"))}

Cash Flow:
- Operating Cash Flow: {fmt(report.get("operating_cash_flow"))}
- Free Cash Flow: {fmt(report.get("free_cash_flow"))}

Key Ratios:
- Market Cap: {fmt(report.get("market_cap"))}
- P/E Ratio: {fmt(report.get("pe_ratio"))}
- Revenue Growth (YoY): {pct(report.get("revenue_growth"))}
- Net Profit Margin: {pct(report.get("profit_margin"))}

{lang_instruction}Return valid JSON only with exactly these keys:
{{
  "summary": "2-3 sentences analyzing the company's financial position, recent performance, and outlook.",
  "health_score": 0,
  "potential_score": 0
}}

Scoring rules:
- health_score (0-100): Current financial health based on profitability, balance sheet strength, cash flow, and debt levels. 0 = near-bankruptcy/critical, 50 = average, 100 = exceptionally strong.
- potential_score (0-100): Expected performance in the next quarter based on growth trends, market position, and financial trajectory. 0 = severe decline expected, 50 = stable, 100 = strong growth expected.
- Scores must be integers between 0 and 100.
- Base scores on the financial data provided. Be realistic and data-driven."""


async def analyze_financial_report(
    report_data: dict[str, Any],
    *,
    base_url: str,
    model: str,
    api_key: str,
    response_language: str | None = None,
    timeout: float = 45.0,
    ai_json_number_retry: int = 3,
) -> tuple[str | None, int | None, int | None]:
    """Analyze a financial report using AI and return (summary, health_score, potential_score)."""
    prompt = _build_financial_analysis_prompt(report_data, response_language)
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }

    for attempt in range(ai_json_number_retry):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning("Financial analysis AI request failed: %s", _err_text(e))
            return None, None, None

        content = _first_choice_content(data)
        if not content:
            logger.warning("Financial analysis AI response missing content")
            return None, None, None

        content = _extract_json_text(content)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(
                "Financial analysis AI parse failed (attempt %d/%d)",
                attempt + 1,
                ai_json_number_retry,
            )
            continue

        summary = parsed.get("summary")
        if summary is not None:
            summary = str(summary).strip() or None

        health_score = _clamp_score(parsed.get("health_score"))
        potential_score = _clamp_score(parsed.get("potential_score"))

        if summary and health_score is not None and potential_score is not None:
            return summary, health_score, potential_score

        logger.warning(
            "Financial analysis AI incomplete response (attempt %d/%d)",
            attempt + 1,
            ai_json_number_retry,
        )

    return None, None, None


async def generate_daily_verdict(
    items: list[dict[str, Any]],
    *,
    base_url: str,
    model: str,
    api_key: str,
    response_language: str | None = None,
    max_items: int = 400,
    timeout: float = 45.0,
    ai_json_number_retry: int = 3,
) -> tuple[str | None, int | None, int | None, int | None, int | None]:
    """Generate daily summary and political/economic scores from collected items.

    If the number of items exceeds max_items, evaluation is done in chunks:
    - First chunk evaluates items[0:max_items] and produces an initial verdict
    - Subsequent chunks use the previous verdict as context to evaluate more items
    - Final verdict incorporates insights from all items

    Returns:
        (summary, global_political, global_economic, domestic_political, domestic_economic)
    """
    if not items:
        return None, None, None, None, None

    total_items = len(items)

    # If items fit within max_items, do a single evaluation
    if total_items <= max_items:
        prompt = _build_daily_verdict_prompt(items, response_language, max_items)
        result = await _call_verdict_api(
            prompt,
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout=timeout,
            ai_json_number_retry=ai_json_number_retry,
        )
        if result is None:
            return None, None, None, None, None
        return (
            result["summary"],
            result["global_political_score"],
            result["global_economic_score"],
            result["domestic_political_score"],
            result["domestic_economic_score"],
        )

    # Chunked evaluation for items exceeding max_items
    total_chunks = (total_items + max_items - 1) // max_items
    logger.info(
        "Chunked verdict evaluation: %d items in %d chunks of up to %d",
        total_items,
        total_chunks,
        max_items,
    )

    current_verdict: dict[str, Any] | None = None
    items_processed = 0

    for chunk_num in range(total_chunks):
        chunk_start = chunk_num * max_items
        chunk_end = min(chunk_start + max_items, total_items)
        chunk_items = items[chunk_start:chunk_end]

        if chunk_num == 0:
            # First chunk: use standard prompt
            prompt = _build_daily_verdict_prompt(
                chunk_items, response_language, max_items
            )
        else:
            # Subsequent chunks: use continuation prompt with previous verdict
            prompt = _build_daily_verdict_continuation_prompt(
                chunk_items,
                current_verdict,  # type: ignore[arg-type]
                chunk_number=chunk_num + 1,
                total_chunks=total_chunks,
                items_processed=items_processed,
                response_language=response_language,
            )

        result = await _call_verdict_api(
            prompt,
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout=timeout,
            ai_json_number_retry=ai_json_number_retry,
        )

        if result is None:
            # If a chunk fails, return the last successful verdict or None
            if current_verdict is not None:
                logger.warning(
                    "Chunk %d/%d failed, returning partial verdict from %d items",
                    chunk_num + 1,
                    total_chunks,
                    items_processed,
                )
                return (
                    current_verdict["summary"],
                    current_verdict["global_political_score"],
                    current_verdict["global_economic_score"],
                    current_verdict["domestic_political_score"],
                    current_verdict["domestic_economic_score"],
                )
            return None, None, None, None, None

        current_verdict = result
        items_processed = chunk_end
        logger.info(
            "Completed chunk %d/%d, processed %d/%d items",
            chunk_num + 1,
            total_chunks,
            items_processed,
            total_items,
        )

    return (
        current_verdict["summary"],  # type: ignore[index]
        current_verdict["global_political_score"],  # type: ignore[index]
        current_verdict["global_economic_score"],  # type: ignore[index]
        current_verdict["domestic_political_score"],  # type: ignore[index]
        current_verdict["domestic_economic_score"],  # type: ignore[index]
    )
