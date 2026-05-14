"""
📈 Daily Stock Analysis & Email Report — Main Orchestrator
===========================================================
Runs the full pipeline: market check → fetch → analyze → email.
All formatting, templates, and HTML live in separate modules.

Usage:
    python stock_report.py

Environment Variables (.env or GitHub Secrets):
    ANTHROPIC_API_KEY  - Claude API Key
    GMAIL_ADDRESS      - Sender Gmail address
    GMAIL_APP_PASSWORD - Gmail App Password (16 chars)
    RECIPIENT_EMAIL    - Recipient email address
"""

import logging
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Imports from project modules
from config import (
    TZ,
    REPORT_LANGUAGE,
    WATCHLIST_FILE,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    TICKER_DELAY_SECONDS,
    ENABLE_EMAIL_REPORT,
    ENABLE_SUMMARY_JSON,
    ENABLE_DISCORD_DIGEST,
    ENABLE_DISCORD_OPEN_SNAPSHOT,
    ENABLE_POLYMARKET,
    ENABLE_POLYMARKET_CLAUDE_REVIEW,
    REQUIRE_REGULAR_MARKET_SESSION,
    WAIT_FOR_REGULAR_SESSION_ON_PREMARKET,
    REGULAR_SESSION_START_DELAY_MINUTES,
    MAX_PREMARKET_WAIT_MINUTES,
)
from market_calendar import get_market_session_status
from data_fetcher import load_watchlist, fetch_stock_data
from analyzer import analyze_with_claude, review_polymarket_with_claude
from email_builder import build_email_html
from email_sender import send_email
from usage_tracker import UsageTracker
from summary_builder import extract_summary_from_analysis, save_daily_summary
from discord_notifier import send_discord_digest, send_market_open_snapshot
from polymarket_client import search_polymarket, compare_directions
from portfolio_monitor import attach_portfolio_context


def main():
    log.info("=" * 60)
    log.info(f"📈 Stock Report — {datetime.now(TZ).strftime('%Y-%m-%d %H:%M ET')}")
    log.info("=" * 60)

    # Step 0: Market session check
    market_status = get_market_session_status()
    _log_market_session(market_status)

    if not market_status["is_trading_day"]:
        log.info("Market is closed today. Skipping report.")
        return

    if REQUIRE_REGULAR_MARKET_SESSION:
        market_status = _wait_for_regular_session_if_early(market_status)
        if not market_status["is_regular_session"]:
            log.info("Market is not in regular session. Skipping live-price alert.")
            return

    # Step 1: Load watchlist
    watchlist = load_watchlist(WATCHLIST_FILE)
    if not watchlist:
        log.error("No tickers to analyze!")
        return

    log.info(f"   Tickers: {', '.join(watchlist)}")
    log.info(f"   Language: {'한글' if REPORT_LANGUAGE == 'ko' else 'English'}")

    # Step 2: Fetch lightweight ticker data first so the fast Discord snapshot can
    # go out before slower metadata, options, and Claude analysis.
    tracker = UsageTracker()
    analyses: list[tuple[dict, str]] = []
    summaries: list[dict] = []
    if ENABLE_DISCORD_OPEN_SNAPSHOT:
        snapshot_data_list, snapshot_failed_tickers = _fetch_watchlist_data(
            watchlist,
            include_enrichment=False,
        )
        if snapshot_data_list:
            if not send_market_open_snapshot(snapshot_data_list):
                log.warning("Market-open Discord snapshot was not sent")
        else:
            log.warning("No successful fast snapshot data; continuing with detailed report")

        if snapshot_failed_tickers:
            log.warning(
                "Fast snapshot skipped tickers: "
                f"{', '.join(snapshot_failed_tickers)}"
            )

    # Step 3: Run the full fetch + slower Claude analysis after the fast snapshot.
    failed_tickers: list[str] = []
    for i, ticker in enumerate(watchlist):
        success = False

        for attempt in range(MAX_RETRIES):
            try:
                # 3a. Fetch full stock data, including slower enrichment for Claude.
                stock_data = fetch_stock_data(ticker)
                if stock_data is None:
                    log.warning(f"{ticker}: no data, skipping")
                    failed_tickers.append(ticker)
                    break

                # 3b. Analyze with Claude.
                analysis = analyze_with_claude(stock_data, REPORT_LANGUAGE, tracker)

                # 3c. Check if analysis is a failure message
                if analysis.startswith("분석 실패") or analysis.startswith("Analysis Failed"):
                    log.warning(f"{ticker}: analysis returned failure message")
                    failed_tickers.append(ticker)
                    break  # non-retryable failure (e.g., auth error)

                analyses.append((stock_data, analysis))

                if ENABLE_SUMMARY_JSON:
                    summary = extract_summary_from_analysis(
                        ticker=stock_data["ticker"],
                        stock_data=stock_data,
                        analysis_text=analysis,
                    )
                    summaries.append(summary)

                success = True
                log.info(f"{ticker}: done (attempt {attempt + 1})")
                break

            except Exception as e:
                log.warning(
                    f"{ticker}: attempt {attempt + 1}/{MAX_RETRIES} failed — {e}"
                )
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAY_SECONDS * (attempt + 1)  # progressive backoff
                    log.info(f"Waiting {wait}s before retry...")
                    time.sleep(wait)
                else:
                    log.error(f"{ticker}: all {MAX_RETRIES} attempts failed")
                    failed_tickers.append(ticker)

        # Delay between Claude calls to avoid rate limits.
        if success and i < len(watchlist) - 1:
            log.info(f"Waiting {TICKER_DELAY_SECONDS}s before next ticker...")
            time.sleep(TICKER_DELAY_SECONDS)

    if not analyses:
        log.error("No successful analyses — aborting")
        return

    analyzed_tickers = [sd["ticker"] for sd, _ in analyses]

    # Step 4: Optional machine-readable summary, Polymarket enrichment, Discord digest
    if ENABLE_SUMMARY_JSON:
        if ENABLE_POLYMARKET:
            stock_data_by_ticker = {sd["ticker"]: sd for sd, _ in analyses}
            for summary in summaries:
                ticker = summary.get("ticker", "?")
                if summary.get("summary_parse_status") == "failed":
                    log.warning(f"{ticker}: skipping Polymarket because summary JSON parse failed")
                    continue

                try:
                    stock_data = stock_data_by_ticker.get(ticker, {})
                    company_name = stock_data.get("company_name", ticker)
                    polymarket_result = search_polymarket(ticker, company_name)
                    comparison = compare_directions(
                        summary.get("direction", "unknown"),
                        polymarket_result,
                    )
                    summary["polymarket"] = polymarket_result
                    summary["polymarket_comparison"] = comparison

                    if ENABLE_POLYMARKET_CLAUDE_REVIEW and _should_review_polymarket(polymarket_result):
                        summary["polymarket_claude_review"] = review_polymarket_with_claude(
                            summary=summary,
                            polymarket_result=polymarket_result,
                            comparison=comparison,
                            language=REPORT_LANGUAGE,
                            tracker=tracker,
                        )
                    elif ENABLE_POLYMARKET_CLAUDE_REVIEW:
                        summary["polymarket_claude_review"] = {
                            "review_status": "skipped",
                            "confidence_adjustment": "ignore",
                            "adjustment_magnitude": "none",
                            "final_direction_after_polymarket": "unchanged",
                            "final_confidence_after_polymarket": "unknown",
                            "reason": "Polymarket market was unavailable, weak, neutral, or directionally unclear.",
                        }
                except Exception as e:
                    log.warning(f"{ticker}: Polymarket enrichment failed: {e}")
                    summary["polymarket"] = {
                        "available": False,
                        "ticker": ticker,
                        "reason": f"Polymarket enrichment failed: {e}",
                    }

        portfolio_context = attach_portfolio_context(summaries)
        if portfolio_context.get("warnings"):
            log.warning(f"Portfolio concentration warnings: {portfolio_context['warnings']}")

        summary_path = save_daily_summary(summaries)
        log.info(f"Summary JSON ready: {summary_path}")

        if ENABLE_DISCORD_DIGEST:
            if not send_discord_digest(summaries):
                log.warning("Discord digest was not sent")
    else:
        log.info("Summary JSON disabled; skipping Discord and Polymarket integrations")

    # Step 5: Save usage after all Claude calls, including optional second-pass reviews
    usage_summary = tracker.get_summary()  # BEFORE save_daily to avoid double-counting
    tracker.save_daily()

    # Step 6: Optional detailed email report
    if ENABLE_EMAIL_REPORT:
        html = build_email_html(
            analyses,
            usage_summary,
            summaries=summaries if ENABLE_SUMMARY_JSON else None,
        )

        # Save local copy
        output_filename = f"report_{datetime.now(TZ).strftime('%Y%m%d_%H%M')}.html"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(html)
        log.info(f"Report saved to {output_filename}")

        send_email(html, analyzed_tickers)
    else:
        log.info("Email report disabled")

    # Summary
    log.info("=" * 60)
    log.info(f"Complete! Analyzed: {len(analyses)}/{len(watchlist)} tickers")
    if failed_tickers:
        log.warning(f"Failed: {', '.join(failed_tickers)}")
    log.info(f"Today's cost: ${usage_summary['today_cost_usd']:.2f}")
    log.info(f"Monthly total: ${usage_summary['monthly_cost_usd']:.2f}")
    log.info("=" * 60)


def _fetch_watchlist_data(
    watchlist: list[str],
    include_enrichment: bool = True,
) -> tuple[list[dict], list[str]]:
    """Fetch ticker data before Claude so the fast snapshot can be sent early."""
    stock_data_list: list[dict] = []
    failed_tickers: list[str] = []

    for ticker in watchlist:
        for attempt in range(MAX_RETRIES):
            try:
                stock_data = fetch_stock_data(
                    ticker,
                    include_enrichment=include_enrichment,
                )
                if stock_data is None:
                    log.warning(f"{ticker}: no data, skipping")
                    failed_tickers.append(ticker)
                    break

                stock_data_list.append(stock_data)
                log.info(f"{ticker}: data ready (attempt {attempt + 1})")
                break

            except Exception as e:
                log.warning(
                    f"{ticker}: data attempt {attempt + 1}/{MAX_RETRIES} failed ??{e}"
                )
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAY_SECONDS * (attempt + 1)
                    log.info(f"Waiting {wait}s before retry...")
                    time.sleep(wait)
                else:
                    log.error(f"{ticker}: all {MAX_RETRIES} data attempts failed")
                    failed_tickers.append(ticker)

    return stock_data_list, failed_tickers


def _log_market_session(market_status: dict) -> None:
    log.info(
        "Market session: "
        f"{market_status['session_state']} "
        f"(now={market_status['now']}, "
        f"open={market_status.get('market_open')}, "
        f"close={market_status.get('market_close')})"
    )


def _wait_for_regular_session_if_early(
    market_status: dict,
    status_fn=get_market_session_status,
    sleep_fn=time.sleep,
) -> dict:
    """Wait through a bounded pre-market dispatch instead of dropping the alert."""
    if market_status.get("is_regular_session"):
        return market_status

    if not WAIT_FOR_REGULAR_SESSION_ON_PREMARKET:
        return market_status

    if market_status.get("session_state") != "pre_market":
        return market_status

    market_open_raw = market_status.get("market_open")
    if not market_open_raw:
        return market_status

    try:
        market_open = datetime.fromisoformat(market_open_raw)
        now_et = datetime.fromisoformat(market_status["now"])
    except (KeyError, ValueError) as e:
        log.warning(f"Could not parse market session timestamps for pre-market wait: {e}")
        return market_status

    target_time = market_open + timedelta(minutes=REGULAR_SESSION_START_DELAY_MINUTES)
    wait_seconds = max(0.0, (target_time - now_et).total_seconds())
    max_wait_seconds = MAX_PREMARKET_WAIT_MINUTES * 60

    if wait_seconds > max_wait_seconds:
        log.info(
            "Pre-market trigger is too early to wait for regular-session prices "
            f"({wait_seconds / 60:.1f} min until target, max {MAX_PREMARKET_WAIT_MINUTES} min)."
        )
        return market_status

    if wait_seconds > 0:
        log.info(
            "Pre-market trigger detected; waiting "
            f"{wait_seconds / 60:.1f} min until {target_time.isoformat()} "
            "before fetching live prices."
        )
        sleep_fn(wait_seconds)

    refreshed_status = status_fn()
    _log_market_session(refreshed_status)
    return refreshed_status


def _should_review_polymarket(polymarket_result: dict) -> bool:
    """Return True only when the Polymarket signal is strong enough to spend a Claude call."""
    if not polymarket_result.get("available"):
        return False

    if polymarket_result.get("question_direction") == "unknown":
        return False

    probability_yes = polymarket_result.get("probability_yes_pct")
    if probability_yes is None or 40 < probability_yes < 60:
        return False

    liquidity = polymarket_result.get("liquidity_usd") or 0
    return liquidity >= 1000


if __name__ == "__main__":
    main()
