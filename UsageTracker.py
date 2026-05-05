"""
Tracks Claude API token usage, web search usage, and cost.
Persists monthly data to usage_log.json.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from Config import CLAUDE_MODEL, MODEL_PRICING, TZ

log = logging.getLogger(__name__)

USAGE_LOG_FILE = "UsageLog.json"

# Web search pricing (per request, approximate)
WEB_SEARCH_COST_PER_REQUEST = 0.01


class UsageTracker:
    """Accumulates token and web search usage across multiple API calls."""

    def __init__(self):
        self.calls: list[dict] = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_web_searches = 0

    def record(self, ticker: str, usage) -> dict:
        """
        Record a single API call's usage.
        `usage` is the response.usage object from Anthropic SDK.
        Includes server_tool_use.web_search_requests if available.
        """
        input_tok = usage.input_tokens
        output_tok = usage.output_tokens

        # Extract web search count from server_tool_use if present
        web_searches = 0
        if hasattr(usage, "server_tool_use") and usage.server_tool_use:
            web_searches = getattr(usage.server_tool_use, "web_search_requests", 0)

        self.total_input_tokens += input_tok
        self.total_output_tokens += output_tok
        self.total_web_searches += web_searches

        pricing = MODEL_PRICING.get(CLAUDE_MODEL, {"input": 3.0, "output": 15.0})
        input_cost = input_tok / 1_000_000 * pricing["input"]
        output_cost = output_tok / 1_000_000 * pricing["output"]
        search_cost = web_searches * WEB_SEARCH_COST_PER_REQUEST
        call_cost = input_cost + output_cost + search_cost

        entry = {
            "ticker": ticker,
            "input_tokens": input_tok,
            "output_tokens": output_tok,
            "web_searches": web_searches,
            "cost_usd": round(call_cost, 4),
        }
        self.calls.append(entry)

        log.info(
            f"{ticker}: {input_tok:,} in + {output_tok:,} out + "
            f"{web_searches} searches = ${call_cost:.4f}"
        )
        return entry

    @property
    def today_cost(self) -> float:
        pricing = MODEL_PRICING.get(CLAUDE_MODEL, {"input": 3.0, "output": 15.0})
        token_cost = (
            self.total_input_tokens / 1_000_000 * pricing["input"]
            + self.total_output_tokens / 1_000_000 * pricing["output"]
        )
        search_cost = self.total_web_searches * WEB_SEARCH_COST_PER_REQUEST
        return token_cost + search_cost

    def get_summary(self) -> dict:
        """Return a summary dict for display in the email."""
        return {
            "model": CLAUDE_MODEL,
            "tickers_analyzed": len(self.calls),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_web_searches": self.total_web_searches,
            "today_cost_usd": round(self.today_cost, 4),
            "monthly_cost_usd": round(self._load_monthly_total() + self.today_cost, 4),
            "per_ticker": self.calls,
        }

    # Monthly persistence

    def save_daily(self):
        """Append today's usage to usage_log.json."""
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
            "web_searches": self.total_web_searches,
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