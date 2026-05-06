"""
Phase 3: Polymarket API client.

Searches for prediction markets related to a stock ticker and returns
directional probability data. Uses the public Gamma API for market discovery
(no authentication needed for read-only queries).

Docs: https://docs.polymarket.com/api-reference
"""

import json
import logging
import urllib.request
import urllib.error
from urllib.parse import urlencode

log = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
MIN_LIQUIDITY = 1000  # Skip low-liquidity markets
_ACCESS_BLOCK_REASON: str | None = None


def search_polymarket(ticker: str, company_name: str) -> dict:
    """
    Search Polymarket for markets related to a stock ticker.
    Returns a dict with match info, or a 'not found' result.
    """
    log.info(f"🔮 {ticker}: searching Polymarket...")

    if _ACCESS_BLOCK_REASON:
        log.info(f"🔮 {ticker}: skipping Polymarket search ({_ACCESS_BLOCK_REASON})")
        return {
            "available": False,
            "ticker": ticker,
            "reason": _ACCESS_BLOCK_REASON,
        }

    # Try multiple search queries for best coverage
    queries = [
        ticker,                          # "MSFT"
        company_name.split(",")[0],       # "Microsoft Corporation" → "Microsoft Corporation"
        f"{ticker} stock",               # "MSFT stock"
    ]

    best_market = None
    best_relevance = 0

    for query in queries:
        markets = _gamma_search(query)
        if _ACCESS_BLOCK_REASON:
            return {
                "available": False,
                "ticker": ticker,
                "reason": _ACCESS_BLOCK_REASON,
            }

        for market in markets:
            relevance = _score_relevance(market, ticker, company_name)
            if relevance > best_relevance:
                best_relevance = relevance
                best_market = market

    if not best_market or best_relevance < 0.3:
        log.info(f"🔮 {ticker}: no relevant Polymarket market found")
        return {
            "available": False,
            "ticker": ticker,
            "reason": "No relevant prediction market found",
        }

    return _format_market_result(ticker, best_market)


def _gamma_search(query: str, limit: int = 10) -> list[dict]:
    """Search Gamma API for active markets matching query."""
    global _ACCESS_BLOCK_REASON

    params = urlencode({
        "q": query,
        "events_status": "active",
        "limit_per_type": limit,
        "keep_closed_markets": 0,
        "search_tags": "false",
        "search_profiles": "false",
        "sort": "liquidity",
        "ascending": "false",
    })

    url = f"{GAMMA_API_BASE}/public-search?{params}"

    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "Stock-Alert/1.0",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return _extract_markets_from_search_results(data)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            _ACCESS_BLOCK_REASON = "Polymarket API access blocked: HTTP 403 Forbidden"
            log.warning(f"⚠️ {_ACCESS_BLOCK_REASON}; skipping remaining searches this run")
        else:
            body = e.read().decode(errors="replace")[:300]
            log.warning(f"⚠️ Polymarket search failed for '{query}': HTTP {e.code} {body}")
        return []
    except Exception as e:
        log.warning(f"⚠️ Polymarket search failed for '{query}': {e}")
        return []


def _extract_markets_from_search_results(data) -> list[dict]:
    if isinstance(data, list):
        return [market for market in data if _is_active_market(market)]

    if not isinstance(data, dict):
        return []

    markets_by_id: dict[str, dict] = {}

    for market in data.get("markets") or []:
        if _is_active_market(market):
            market_id = str(market.get("id") or market.get("slug") or len(markets_by_id))
            markets_by_id[market_id] = market

    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        event_context = {
            "event_title": event.get("title", ""),
            "event_subtitle": event.get("subtitle", ""),
            "event_description": event.get("description", ""),
        }
        for market in event.get("markets") or []:
            if not _is_active_market(market):
                continue
            enriched_market = {**event_context, **market}
            market_id = str(enriched_market.get("id") or enriched_market.get("slug") or len(markets_by_id))
            markets_by_id[market_id] = enriched_market

    return list(markets_by_id.values())


def _is_active_market(market) -> bool:
    if not isinstance(market, dict):
        return False
    if market.get("active") is False:
        return False
    if market.get("closed") is True:
        return False
    return True


def _score_relevance(market: dict, ticker: str, company_name: str) -> float:
    """
    Score how relevant a Polymarket market is to our stock ticker.
    Returns 0.0 to 1.0.
    """
    text_parts = [
        market.get("question", ""),
        market.get("title", ""),
        market.get("description", ""),
        market.get("event_title", ""),
        market.get("event_subtitle", ""),
        market.get("event_description", ""),
    ]
    question = " ".join(str(part) for part in text_parts if part).lower()
    ticker_lower = ticker.lower()
    company_lower = company_name.lower().split(",")[0].split("(")[0].strip()

    score = 0.0

    # Ticker match in question (strongest signal)
    if ticker_lower in question:
        score += 0.5

    # Company name match
    if company_lower in question and len(company_lower) > 3:
        score += 0.3

    # Stock/price related keywords
    stock_keywords = ["stock", "share", "price", "close", "trading", "market cap"]
    if any(kw in question for kw in stock_keywords):
        score += 0.2

    # Penalty for low liquidity
    liquidity = float(market.get("liquidity", 0) or 0)
    if liquidity < MIN_LIQUIDITY:
        score *= 0.3

    # Penalty for very short time to expiry (< 1 day) — too noisy
    # (would need datetime parsing, skip for now)

    return min(score, 1.0)

def _infer_question_direction(question: str) -> str:
    q = question.lower()

    bearish_terms = ["below", "under", "less than", "lower", "fall", "drop", "decline", "down", "close below"]
    bullish_terms = ["above", "over", "greater than", "higher", "rise", "gain", "up", "close above"]

    bearish = any(term in q for term in bearish_terms)
    bullish = any(term in q for term in bullish_terms)

    if bearish and not bullish:
        return "bearish"
    if bullish and not bearish:
        return "bullish"
    return "unknown"


def _parse_json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _extract_yes_no_probabilities(outcomes, outcome_prices) -> tuple[float | None, float | None]:
    prices = _parse_json_list(outcome_prices)
    labels = [str(label).strip().lower() for label in _parse_json_list(outcomes)]

    if not prices:
        return None, None

    yes_index = 0
    no_index = 1 if len(prices) > 1 else None

    if labels and len(labels) == len(prices):
        if "yes" in labels:
            yes_index = labels.index("yes")
        if "no" in labels:
            no_index = labels.index("no")

    try:
        probability_yes = round(float(prices[yes_index]) * 100, 1)
        probability_no = round(float(prices[no_index]) * 100, 1) if no_index is not None else None
        return probability_yes, probability_no
    except (TypeError, ValueError, IndexError):
        return None, None


def _format_market_result(ticker: str, market: dict) -> dict:
    """Format a Polymarket market into our standard result dict."""
    question = market.get("question", "Unknown")
    liquidity = float(market.get("liquidity", 0) or 0)
    end_date = market.get("endDate", "Unknown")

    # Extract outcome probabilities
    outcomes = market.get("outcomes", [])
    outcome_prices = market.get("outcomePrices", [])

    probability_yes, probability_no = _extract_yes_no_probabilities(outcomes, outcome_prices)

    # Determine Polymarket direction
    question_direction = _infer_question_direction(question)

    if probability_yes is None or question_direction == "unknown":
        pm_direction = "unknown"
    elif 40 < probability_yes < 60:
        pm_direction = "neutral"
    elif question_direction == "bullish":
        pm_direction = "bullish" if probability_yes >= 60 else "bearish"
    else:
        pm_direction = "bearish" if probability_yes >= 60 else "bullish"

    return {
        "available": True,
        "ticker": ticker,
        "question": question,
        "probability_yes_pct": probability_yes,
        "probability_no_pct": probability_no,
        "question_direction": question_direction,
        "polymarket_direction": pm_direction,
        "liquidity_usd": round(liquidity, 0),
        "end_date": end_date,
        "market_id": market.get("id", ""),
        "url": f"https://polymarket.com/event/{market.get('slug', '')}",
    }


def compare_directions(claude_direction: str, polymarket_result: dict) -> dict:
    """
    Compare Claude's direction with Polymarket's direction.
    Returns a judgment dict.
    """
    if not polymarket_result.get("available"):
        return {
            "match": "N/A",
            "message": "Polymarket에 관련 시장 없음",
            "confidence_boost": 0,
        }

    pm_dir = polymarket_result.get("polymarket_direction", "unknown")
    cl_dir = claude_direction.lower()
    prob_yes = polymarket_result.get("probability_yes_pct", 50)

    if cl_dir == pm_dir:
        return {
            "match": "일치",
            "message": f"Claude({cl_dir}) = Polymarket({pm_dir}, {prob_yes}%) — 방향 일치, 신뢰도 보강",
            "confidence_boost": 0.15,
        }
    elif pm_dir in ("neutral", "unknown") or cl_dir in ("unknown", "neutral"):
        return {
            "match": "중립",
            "message": f"Claude({cl_dir}) vs Polymarket({pm_dir}, {prob_yes}%) — 한쪽 불확실, 추가 확인 필요",
            "confidence_boost": 0,
        }
    else:
        return {
            "match": "불일치",
            "message": f"Claude({cl_dir}) ≠ Polymarket({pm_dir}, {prob_yes}%) — ⚠️ 불일치 경고, 진입 전 재검토",
            "confidence_boost": -0.15,
        }
