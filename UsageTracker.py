"""
Tracks Claude API token usage and cost per session and cumulatively per month.
Persists monthly data to usage_log.json so it survives across GitHub Actions runs
(if the file is committed back to the repo).
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from Config import CLAUDE_MODEL, MODEL_PRICING, TZ

log = logging.getLogger(__name__)

USAGE_LOG_FILE = "UsageLog.json"

class UsageTracker:
    """Accumulates token usage across multiple API calls in a single run."""

    def __init__(self):
        self.calls: list[dict] = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def record(self, ticker: str, usage) -> dict:
        """
        Record a single API call's usage.
        `usage` is the response.usage object from Anthropic SDK.
        Returns a dict with cost info for logging.
        """
        input_tok = usage.input_tokens
        output_tok = usage.output_tokens

        self.total_input_tokens += input_tok
        self.total_output_tokens += output_tok

        pricing = MODEL_PRICING.get(CLAUDE_MODEL, {"input": 3.0, "output": 15.0})
        input_cost = input_tok / 1_000_000 * pricing["input"]
        output_cost = output_tok / 1_000_000 * pricing["output"]
        call_cost = input_cost + output_cost

        entry = {
            "ticker": ticker,
            "input_tokens": input_tok,
            "output_tokens": output_tok,
            "cost_usd": round(call_cost, 4),
        }
        self.calls.append(entry)

        log.info(
            f"{ticker}: {input_tok:,} in + {output_tok:,} out = ${call_cost:.4f}"
        )
        return entry

    @property
    def today_cost(self) -> float:
        pricing = MODEL_PRICING.get(CLAUDE_MODEL, {"input": 3.0, "output": 15.0})
        return (
            self.total_input_tokens / 1_000_000 * pricing["input"]
            + self.total_output_tokens / 1_000_000 * pricing["output"]
        )

    def get_summary(self) -> dict:
        """Return a summary dict for display in the email."""
        return {
            "model": CLAUDE_MODEL,
            "tickers_analyzed": len(self.calls),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "today_cost_usd": round(self.today_cost, 4),
            "monthly_cost_usd": round(self._load_monthly_total() + self.today_cost, 4),
            "per_ticker": self.calls,
        }

    # Monthly persistence

    def save_daily(self):
        """Append today's usage to UsageLog.json for monthly tracking."""
        today_str = datetime.now(TZ).strftime("%Y-%m-%d")
        month_str = datetime.now(TZ).strftime("%Y-%m")

        log_path = Path(USAGE_LOG_FILE)
        data = {}
        if log_path.exists():
            try:
                data = json.loads(log_path.read_text())
            except (json.JSONDecodeError, OSError):
                data = {}

        if month_str not in data:
            data[month_str] = {}

        data[month_str][today_str] = {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cost_usd": round(self.today_cost, 4),
            "model": CLAUDE_MODEL,
        }

        log_path.write_text(json.dumps(data, indent=2))
        log.info(f"Usage saved to {USAGE_LOG_FILE}")

    def _load_monthly_total(self) -> float:
        """Load this month's cumulative cost from the log file."""
        month_str = datetime.now(TZ).strftime("%Y-%m")
        log_path = Path(USAGE_LOG_FILE)

        if not log_path.exists():
            return 0.0

        try:
            data = json.loads(log_path.read_text())
            month_data = data.get(month_str, {})
            return sum(day.get("cost_usd", 0) for day in month_data.values())
        except (json.JSONDecodeError, OSError):
            return 0.0