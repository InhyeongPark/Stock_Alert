"""Portfolio-level concentration checks for the daily digest."""

from collections import Counter, defaultdict

from investment_profiles import get_ticker_themes


def build_portfolio_context(summaries: list[dict]) -> dict:
    valid = [s for s in summaries if s.get("ticker")]
    total = len(valid)
    directions = Counter((s.get("direction") or "unknown").lower() for s in valid)
    warnings = []

    if total:
        direction, count = directions.most_common(1)[0]
        if direction in ("bullish", "bearish") and count >= max(4, int(total * 0.8)):
            warnings.append({
                "type": "direction_crowding",
                "severity": "high" if direction == "bearish" else "medium",
                "direction": direction,
                "count": count,
                "total": total,
                "message": f"{count}/{total} tickers are {direction}; watch portfolio-level crowding.",
            })

    theme_direction = defaultdict(Counter)
    theme_tickers = defaultdict(set)
    for summary in valid:
        ticker = summary.get("ticker", "?")
        direction = (summary.get("direction") or "unknown").lower()
        for theme in get_ticker_themes(ticker):
            theme_direction[theme][direction] += 1
            theme_tickers[theme].add(ticker)

    for theme, counts in theme_direction.items():
        if len(theme_tickers[theme]) < 3:
            continue
        direction, count = counts.most_common(1)[0]
        if direction in ("bullish", "bearish") and count >= 3:
            tickers = sorted(theme_tickers[theme])
            warnings.append({
                "type": "theme_concentration",
                "severity": "high" if direction == "bearish" else "medium",
                "theme": theme,
                "direction": direction,
                "count": count,
                "tickers": tickers,
                "message": (
                    f"{theme}: {count}/{len(tickers)} mapped tickers are {direction} "
                    f"({', '.join(tickers)})."
                ),
            })

    return {
        "total_tickers": total,
        "direction_counts": dict(directions),
        "warnings": warnings,
    }


def attach_portfolio_context(summaries: list[dict]) -> dict:
    context = build_portfolio_context(summaries)
    for summary in summaries:
        summary["portfolio_context"] = context
    return context
