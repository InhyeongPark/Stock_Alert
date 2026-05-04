"""
Calls the Claude API for stock analysis.
NO internal retry — retry is managed by main() to avoid 5×5 = 25 calls.
"""

import logging

import anthropic

from Config import CLAUDE_MODEL, MAX_OUTPUT_TOKENS
from Prompts import get_analysis_prompt
from UsageTracker import UsageTracker

log = logging.getLogger(__name__)


def analyze_with_claude(
    stock_data: dict,
    language: str,
    tracker: UsageTracker,
) -> str:
    """
    Call Claude API once with web search to analyze a single ticker.
    Returns the analysis text, or a failure message string.
    Raises on retryable errors (429, 500, 529) so main() can retry.
    """
    ticker = stock_data["ticker"]
    log.info(f"{ticker}: sending to Claude ({CLAUDE_MODEL})")

    client = anthropic.Anthropic()
    prompt = get_analysis_prompt(stock_data, language)

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )

        # Track usage
        tracker.record(ticker, response.usage)

        # Check if response was truncated
        if response.stop_reason == "max_tokens":
            log.warning(f"{ticker}: response truncated (max_tokens hit)")

        # Extract text blocks
        analysis_text = ""
        for block in response.content:
            if block.type == "text":
                analysis_text += block.text

        log.info(f"{ticker}: analysis complete ({len(analysis_text)} chars)")
        return analysis_text

    except anthropic.AuthenticationError as e:
        # 401 — never retryable
        log.error(f"{ticker}: API key invalid — {e}")
        return "분석 실패 (API 키 오류): 키를 확인하세요"

    except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIStatusError) as e:
        # 429, 500, 529 etc. — retryable, re-raise so main() handles it
        log.warning(f"{ticker}: retryable error — {e}")
        raise

    except Exception as e:
        log.error(f"{ticker}: unexpected error — {e}")
        raise