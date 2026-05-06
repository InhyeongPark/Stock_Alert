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
from datetime import datetime

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
    ENABLE_POLYMARKET,
)
from market_calendar import is_market_open_today
from data_fetcher import load_watchlist, fetch_stock_data
from analyzer import analyze_with_claude
from email_builder import build_email_html
from email_sender import send_email
from usage_tracker import UsageTracker
from summary_builder import extract_summary_from_analysis, save_daily_summary
from discord_notifier import send_discord_digest
from polymarket_client import search_polymarket, compare_directions


def main():
    log.info("=" * 60)
    log.info(f"📈 Stock Report — {datetime.now(TZ).strftime('%Y-%m-%d %H:%M ET')}")
    log.info("=" * 60)

    # Step 0: Market holiday check
    if not is_market_open_today():
        log.info("Market is closed today. Skipping report.")
        return

    # Step 1: Load watchlist
    watchlist = load_watchlist(WATCHLIST_FILE)
    if not watchlist:
        log.error("No tickers to analyze!")
        return

    log.info(f"   Tickers: {', '.join(watchlist)}")
    log.info(f"   Language: {'한글' if REPORT_LANGUAGE == 'ko' else 'English'}")

    # Step 2: Fetch + Analyze each ticker (with unified retry) 
    tracker = UsageTracker()
    analyses: list[tuple[dict, str]] = []
    summaries: list[dict] = []
    failed_tickers: list[str] = []

    for i, ticker in enumerate(watchlist):
        success = False

        for attempt in range(MAX_RETRIES):
            try:
                # 2a. Fetch stock data
                stock_data = fetch_stock_data(ticker)
                if stock_data is None:
                    log.warning(f"{ticker}: no data, skipping")
                    break  # data issue, don't retry

                # 2b. Analyze with Claude
                analysis = analyze_with_claude(stock_data, REPORT_LANGUAGE, tracker)

                # 2c. Check if analysis is a failure message
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

        # Delay between tickers to avoid rate limit
        if success and i < len(watchlist) - 1:
            log.info(f"Waiting {TICKER_DELAY_SECONDS}s before next ticker...")
            time.sleep(TICKER_DELAY_SECONDS)

    if not analyses:
        log.error("No successful analyses — aborting")
        return

    # Step 3: Save usage
    usage_summary = tracker.get_summary()  # BEFORE save_daily to avoid double-counting
    tracker.save_daily()

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
                except Exception as e:
                    log.warning(f"{ticker}: Polymarket enrichment failed: {e}")
                    summary["polymarket"] = {
                        "available": False,
                        "ticker": ticker,
                        "reason": f"Polymarket enrichment failed: {e}",
                    }

        summary_path = save_daily_summary(summaries)
        log.info(f"Summary JSON ready: {summary_path}")

        if ENABLE_DISCORD_DIGEST:
            if not send_discord_digest(summaries):
                log.warning("Discord digest was not sent")
    else:
        log.info("Summary JSON disabled; skipping Discord and Polymarket integrations")

    # Step 5: Optional detailed email report
    if ENABLE_EMAIL_REPORT:
        html = build_email_html(analyses, usage_summary)

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


if __name__ == "__main__":
    main()
