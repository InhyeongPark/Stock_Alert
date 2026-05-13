"""
Phase 1: Builds machine-readable report_summary.json from Claude analysis.

The JSON is extracted from a structured block that Claude outputs at the end
of each analysis (prompted via get_analysis_prompt). This summary powers:
  - Discord digest (Phase 2)
  - Polymarket validation (Phase 3)
  - Live backtest (Phase 5a)
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from config import TZ
from investment_profiles import profile_context_for_summary

log = logging.getLogger(__name__)

SUMMARY_DIR = "report_summaries"


def extract_summary_from_analysis(ticker: str, stock_data: dict, analysis_text: str) -> dict:
    """
    Extract the JSON summary block from Claude's analysis output.
    Falls back to a minimal skeleton if JSON parsing fails.
    """
    summary = _try_parse_json_block(analysis_text)

    if summary:
        # Ensure required fields exist
        summary["summary_parse_status"] = "ok"
        summary.setdefault("ticker", ticker)
        summary.setdefault("current_price", stock_data.get("current_price"))
        log.info(f"📋 {ticker}: summary extracted (direction={summary.get('direction', '?')})")
    else:
        # Fallback: minimal summary from stock_data only
        log.warning(f"⚠️ {ticker}: could not parse JSON block, using fallback")
        summary = {
            "ticker": ticker,
            "current_price": stock_data.get("current_price"),
            "summary_parse_status": "failed",
            "summary_parse_error": "json_block_missing_or_invalid",
            "entry_suitability": "unknown",
            "direction": "unknown",
            "entry_prices": [],
            "stop_prices": [],
            "outlook_short": "N/A",
            "outlook_mid": "N/A",
            "outlook_long": "N/A",
            "key_reasons": ["JSON extraction failed - review full report"],
        }

    return _normalize_summary(summary, ticker, stock_data)


def save_daily_summary(summaries: list[dict]):
    """Save all ticker summaries to report_summaries/YYYY-MM-DD.json"""
    Path(SUMMARY_DIR).mkdir(exist_ok=True)

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    filepath = Path(SUMMARY_DIR) / f"{today}.json"

    report = {
        "date": today,
        "generated_at": datetime.now(TZ).isoformat(),
        "tickers": summaries,
    }

    filepath.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    log.info(f"📋 Summary saved to {filepath}")
    return filepath


def _try_parse_json_block(text: str) -> dict | None:
    """
    Find and parse the ```json ... ``` block in Claude's output.
    Tries multiple patterns to be resilient.
    """
    # Pattern 1: ```json ... ```
    match = re.search(r"```json\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Pattern 2: ```\n{...}\n```
    match = re.search(r"```\s*\n(\{.*?\})\n\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Pattern 3: raw JSON object at end of text
    match = re.search(r"\{[^{}]*\"ticker\"[^{}]*\"direction\"[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _normalize_summary(summary: dict, ticker: str, stock_data: dict) -> dict:
    """Ensure downstream Discord/backtest code sees stable field types."""
    summary.setdefault("ticker", ticker)
    _normalize_price_fields(summary, stock_data)
    profile_context = profile_context_for_summary(ticker)
    for key, value in profile_context.items():
        summary.setdefault(key, value)
    summary.setdefault("summary_parse_status", "ok")
    summary.setdefault("entry_suitability", "unknown")
    summary.setdefault("direction", "unknown")
    summary.setdefault("outlook_short", "N/A")
    summary.setdefault("outlook_mid", "N/A")
    summary.setdefault("outlook_long", "N/A")

    summary["entry_prices"] = _as_list(summary.get("entry_prices"))
    summary["stop_prices"] = _as_list(summary.get("stop_prices"))
    summary["key_reasons"] = _as_list(summary.get("key_reasons"))

    return summary


def _normalize_price_fields(summary: dict, stock_data: dict) -> None:
    """Keep downstream alerts anchored to the canonical fetched price."""
    canonical_price = stock_data.get("current_price")
    claude_price = summary.get("current_price")

    if canonical_price is not None:
        if (
            claude_price is not None
            and _float_or_none(claude_price) != _float_or_none(canonical_price)
        ):
            summary["claude_current_price"] = claude_price
        summary["current_price"] = canonical_price
    else:
        summary.setdefault("current_price", None)

    for key in (
        "prev_close",
        "daily_change_pct",
        "price_source",
        "price_as_of",
        "price_retrieved_at",
        "price_age_minutes",
        "price_status",
        "price_is_stale",
        "price_warning",
        "market_session",
        "market_open",
        "market_close",
        "data_delay_note",
        "indicator_as_of",
        "indicator_basis",
    ):
        if key in stock_data:
            summary[key] = stock_data.get(key)


def _float_or_none(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
