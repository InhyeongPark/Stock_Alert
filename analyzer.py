"""
Calls the Claude API for stock analysis.
NO internal retry — retry is managed by main() to avoid 5×5 = 25 calls.
"""

import json
import logging
import re

import anthropic

from config import (
    CLAUDE_MODEL,
    MAX_OUTPUT_TOKENS,
    POLYMARKET_REVIEW_MAX_TOKENS,
    WEB_SEARCH_MAX_USES,
)
from prompts import get_analysis_prompt, get_polymarket_review_prompt
from usage_tracker import UsageTracker

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
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": WEB_SEARCH_MAX_USES,
            }],
            messages=[{"role": "user", "content": prompt}],
        )

        # Track usage (tokens + web search count)
        tracker.record(ticker, response.usage, call_type="analysis")

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
        log.error(f"{ticker}: API key invalid — {e}")
        return "분석 실패 (API 키 오류): 키를 확인하세요"

    except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIStatusError) as e:
        log.warning(f"{ticker}: retryable error — {e}")
        raise

    except Exception as e:
        log.error(f"{ticker}: unexpected error — {e}")
        raise


def review_polymarket_with_claude(
    summary: dict,
    polymarket_result: dict,
    comparison: dict,
    language: str,
    tracker: UsageTracker,
) -> dict:
    """
    Ask Claude to judge whether a Polymarket market should affect confidence.
    This is a second-pass review without web search and does not alter the
    original detailed analysis text.
    """
    ticker = summary.get("ticker", "?")
    log.info(f"{ticker}: sending Polymarket review to Claude ({CLAUDE_MODEL})")

    client = anthropic.Anthropic()
    prompt = get_polymarket_review_prompt(summary, polymarket_result, comparison, language)

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=POLYMARKET_REVIEW_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )

        tracker.record(ticker, response.usage, call_type="polymarket_review")

        review_text = _extract_text(response)
        review = _try_parse_json_object(review_text)
        if review is None:
            log.warning(f"{ticker}: Polymarket review JSON parse failed")
            return {
                "review_status": "parse_failed",
                "confidence_adjustment": "ignore",
                "adjustment_magnitude": "none",
                "final_direction_after_polymarket": "unchanged",
                "final_confidence_after_polymarket": "unknown",
                "reason": "Claude review did not return parseable JSON.",
                "raw_response": review_text[:1000],
            }

        review.setdefault("review_status", "reviewed")
        review.setdefault("confidence_adjustment", "neutral")
        review.setdefault("adjustment_magnitude", "none")
        review.setdefault("final_direction_after_polymarket", "unchanged")
        review.setdefault("final_confidence_after_polymarket", "unknown")
        log.info(
            f"{ticker}: Polymarket review complete "
            f"({review.get('confidence_adjustment')}/{review.get('adjustment_magnitude')})"
        )
        return review

    except anthropic.AuthenticationError as e:
        log.error(f"{ticker}: API key invalid during Polymarket review — {e}")
        return {
            "review_status": "failed",
            "confidence_adjustment": "ignore",
            "adjustment_magnitude": "none",
            "final_direction_after_polymarket": "unchanged",
            "final_confidence_after_polymarket": "unknown",
            "reason": "Claude API authentication failed during Polymarket review.",
        }

    except Exception as e:
        log.warning(f"{ticker}: Polymarket review failed — {e}")
        return {
            "review_status": "failed",
            "confidence_adjustment": "ignore",
            "adjustment_magnitude": "none",
            "final_direction_after_polymarket": "unchanged",
            "final_confidence_after_polymarket": "unknown",
            "reason": f"Claude Polymarket review failed: {e}",
        }


def _extract_text(response) -> str:
    text = ""
    for block in response.content:
        if block.type == "text":
            text += block.text
    return text


def _try_parse_json_object(text: str) -> dict | None:
    match = re.search(r"```json\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    return None
