"""
Central configuration for the Stock Alert system.
Edit this file to change models, language, watchlist, etc.
"""

from zoneinfo import ZoneInfo

# ─── Claude API ──────────────────────────────────────────────────
# Available models (uncomment the one you want):
CLAUDE_MODEL = "claude-sonnet-4-6"          # $3/$15 per MTok — recommended
# CLAUDE_MODEL = "claude-opus-4-7"          # $5/$25 per MTok — highest quality

# Pricing lookup (used for cost tracking)
MODEL_PRICING = {
    "claude-sonnet-4-6":          {"input": 3.0,  "output": 15.0},
    "claude-opus-4-7":            {"input": 5.0,  "output": 25.0},
}

MAX_OUTPUT_TOKENS = 8000        # Reduced from 16000; paired with conciseness prompt
WEB_SEARCH_MAX_USES = 5        # Limit web searches per ticker for cost control

# Report Settings
REPORT_LANGUAGE = "ko"          # "ko" (Korean) or "en" (English)
WATCHLIST_FILE = "watchlist.txt"

# Timezone
TZ = ZoneInfo("America/New_York")

# Retry / Rate Limit
MAX_RETRIES = 5                 # Per ticker: covers both fetch + analyze
RETRY_DELAY_SECONDS = 10        # Wait between retries on failure
TICKER_DELAY_SECONDS = 45       # Wait between tickers to avoid rate limit

# Market Calendar
# ISO 10383 MIC code for NYSE (exchange_calendars standard)
EXCHANGE_MIC = "XNYS"
