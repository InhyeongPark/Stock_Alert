"""
Phase 5a: Live Walk-Forward Backtest

Reads saved report_summaries/YYYY-MM-DD.json files, compares each ticker's
recommended entry/stop prices against actual subsequent price action,
and computes performance metrics.

This is the "honest" backtest — it only evaluates what Claude actually
recommended in production, with no lookahead bias.

Usage:
    python backtester.py              # backtest all saved summaries
    python backtester.py --days 30    # last 30 days only

Metrics computed per ticker and overall:
    - Entry hit rate: did price reach recommended entry?
    - Stop hit rate: did price hit stop-loss before target?
    - Win rate: entries that reached +ATR or +3% before stop
    - Max drawdown from entry (MDD)
    - Max favorable excursion (MFE)
    - Profit factor: gross profit / gross loss
    - Average R-multiple: avg(profit / risk_per_trade)
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

from config import TZ

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SUMMARY_DIR = "report_summaries"
RESULTS_DIR = "backtest_results"
HOLDING_DAYS = 5  # Evaluate performance over N trading days after signal
TARGET_PCT = 3.0  # Default profit target: +3%
AMBIGUOUS_EXIT_POLICY = "conservative_stop"


def run_backtest(lookback_days: int = None):
    """Run walk-forward backtest on all saved report summaries."""
    summary_dir = Path(SUMMARY_DIR)
    if not summary_dir.exists():
        log.error(f"❌ No {SUMMARY_DIR}/ directory found. Run stock_report.py first.")
        return

    # Load all summary files
    files = sorted(summary_dir.glob("*.json"))
    if lookback_days:
        cutoff = datetime.now(TZ).date() - timedelta(days=lookback_days)
        files = [f for f in files if f.stem >= cutoff.isoformat()]

    if not files:
        log.error("❌ No summary files to backtest")
        return

    log.info(f"📊 Backtesting {len(files)} report(s)...")

    all_trades = []

    for filepath in files:
        report = json.loads(filepath.read_text())
        report_date = report.get("date")

        for ticker_summary in report.get("tickers", []):
            trades = _evaluate_ticker(report_date, ticker_summary)
            all_trades.extend(trades)

    if not all_trades:
        log.warning("⚠️ No evaluable trades found (need at least 1 trading day after signal)")
        return

    # Compute metrics
    metrics = _compute_metrics(all_trades)
    _print_report(metrics, all_trades)
    _save_results(metrics, all_trades)


def _evaluate_ticker(report_date: str, summary: dict) -> list[dict]:
    """
    Evaluate one ticker's recommendations against actual subsequent prices.
    Returns list of trade dicts with outcomes.
    """
    ticker = summary.get("ticker", "?")
    direction = summary.get("direction", "unknown").lower()
    entries = summary.get("entry_prices", [])
    stops = summary.get("stop_prices", [])

    if not entries or direction not in ("bullish", "bearish"):
        return []

    # Fetch actual prices after the report date
    try:
        start = datetime.strptime(report_date, "%Y-%m-%d") + timedelta(days=1)
        end = start + timedelta(days=HOLDING_DAYS + 5)  # extra days for weekends
        df = yf.Ticker(ticker).history(start=start, end=end)

        if df.empty or len(df) < 1:
            return []

        actual_prices = df.head(HOLDING_DAYS)  # first N trading days
    except Exception as e:
        log.warning(f"⚠️ {ticker}: price fetch failed for backtest: {e}")
        return []

    trades = []

    for i, entry_price in enumerate(entries[:3]):
        stop_price = stops[i] if i < len(stops) else None
        if not entry_price or (stop_price and stop_price == entry_price):
            continue

        trade = _simulate_trade(
            ticker=ticker,
            report_date=report_date,
            entry_level=i + 1,
            direction=direction,
            entry_price=float(entry_price),
            stop_price=float(stop_price) if stop_price else None,
            price_data=actual_prices,
        )
        if trade:
            trades.append(trade)

    return trades


def _simulate_trade(
    ticker: str,
    report_date: str,
    entry_level: int,
    direction: str,
    entry_price: float,
    stop_price: float | None,
    price_data,
) -> dict | None:
    """
    Simulate a single trade entry and check if entry was triggered,
    then evaluate stop-loss and target outcomes.
    """
    entry_triggered = False
    entry_date = None

    for date, row in price_data.iterrows():
        # Check if price reached entry level
        if direction == "bullish" and row["Low"] <= entry_price:
            entry_triggered = True
            entry_date = date
            break
        elif direction == "bearish" and row["High"] >= entry_price:
            entry_triggered = True
            entry_date = date
            break

    if not entry_triggered:
        return {
            "ticker": ticker,
            "report_date": report_date,
            "entry_level": entry_level,
            "direction": direction,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "entry_triggered": False,
            "outcome": "no_fill",
            "pnl_pct": 0,
            "mfe_pct": 0,
            "mdd_pct": 0,
        }

    # Entry was triggered — evaluate subsequent price action
    post_entry = price_data.loc[entry_date:]
    target_price = entry_price * (1 + TARGET_PCT / 100) if direction == "bullish" \
        else entry_price * (1 - TARGET_PCT / 100)

    max_favorable = 0
    max_adverse = 0
    outcome = "open"  # still within holding period
    exit_price = None

    for _, row in post_entry.iterrows():
        if direction == "bullish":
            favorable = (row["High"] - entry_price) / entry_price * 100
            adverse = (entry_price - row["Low"]) / entry_price * 100
        else:
            favorable = (entry_price - row["Low"]) / entry_price * 100
            adverse = (row["High"] - entry_price) / entry_price * 100

        max_favorable = max(max_favorable, favorable)
        max_adverse = max(max_adverse, adverse)

        stop_hit, target_hit = _hit_flags(row, direction, stop_price, target_price)

        if stop_hit and target_hit:
            outcome = "ambiguous_same_day"
            exit_price = stop_price
            break
        elif stop_hit:
            outcome = "stopped"
            exit_price = stop_price
            break
        elif target_hit:
            outcome = "target"
            exit_price = target_price
            break

    # If neither stop nor target hit, use last close
    if outcome == "open":
        last_close = post_entry.iloc[-1]["Close"]
        exit_price = last_close
        outcome = "expired"

    # Calculate P&L
    if direction == "bullish":
        pnl_pct = (exit_price - entry_price) / entry_price * 100
    else:
        pnl_pct = (entry_price - exit_price) / entry_price * 100

    # R-multiple (if stop exists)
    r_multiple = None
    if stop_price:
        risk = abs(entry_price - stop_price)
        if risk > 0:
            reward = exit_price - entry_price if direction == "bullish" else entry_price - exit_price
            r_multiple = round(reward / risk, 2)

    return {
        "ticker": ticker,
        "report_date": report_date,
        "entry_level": entry_level,
        "direction": direction,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": round(target_price, 2),
        "entry_triggered": True,
        "outcome": outcome,
        "ambiguous_exit_policy": AMBIGUOUS_EXIT_POLICY if outcome == "ambiguous_same_day" else None,
        "exit_price": round(exit_price, 2),
        "pnl_pct": round(pnl_pct, 2),
        "mfe_pct": round(max_favorable, 2),
        "mdd_pct": round(max_adverse, 2),
        "r_multiple": r_multiple,
    }


def _hit_flags(row, direction: str, stop_price: float | None, target_price: float) -> tuple[bool, bool]:
    """Return whether stop and target touched inside the same daily bar."""
    if direction == "bullish":
        stop_hit = stop_price is not None and row["Low"] <= stop_price
        target_hit = row["High"] >= target_price
    else:
        stop_hit = stop_price is not None and row["High"] >= stop_price
        target_hit = row["Low"] <= target_price

    return stop_hit, target_hit


def _compute_metrics(trades: list[dict]) -> dict:
    """Compute aggregate performance metrics."""
    triggered = [t for t in trades if t["entry_triggered"]]
    not_triggered = [t for t in trades if not t["entry_triggered"]]

    if not triggered:
        return {"error": "No triggered trades"}

    wins = [t for t in triggered if t["pnl_pct"] > 0]
    losses = [t for t in triggered if t["pnl_pct"] <= 0]

    gross_profit = sum(t["pnl_pct"] for t in wins)
    gross_loss = abs(sum(t["pnl_pct"] for t in losses))

    r_multiples = [t["r_multiple"] for t in triggered if t["r_multiple"] is not None]

    return {
        "total_signals": len(trades),
        "entries_triggered": len(triggered),
        "entries_missed": len(not_triggered),
        "entry_hit_rate": round(len(triggered) / len(trades) * 100, 1),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(triggered) * 100, 1) if triggered else 0,
        "avg_pnl_pct": round(sum(t["pnl_pct"] for t in triggered) / len(triggered), 2),
        "avg_mfe_pct": round(sum(t["mfe_pct"] for t in triggered) / len(triggered), 2),
        "avg_mdd_pct": round(sum(t["mdd_pct"] for t in triggered) / len(triggered), 2),
        "max_single_loss_pct": round(min(t["pnl_pct"] for t in triggered), 2),
        "max_single_win_pct": round(max(t["pnl_pct"] for t in triggered), 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "avg_r_multiple": round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else None,
        "stopped_count": len([t for t in triggered if t["outcome"] == "stopped"]),
        "target_count": len([t for t in triggered if t["outcome"] == "target"]),
        "ambiguous_same_day_count": len([t for t in triggered if t["outcome"] == "ambiguous_same_day"]),
        "expired_count": len([t for t in triggered if t["outcome"] == "expired"]),
    }


def _print_report(metrics: dict, trades: list[dict]):
    """Print backtest results to console."""
    log.info("=" * 60)
    log.info("📊 BACKTEST RESULTS")
    log.info("=" * 60)
    log.info(f"  Total signals: {metrics['total_signals']}")
    log.info(f"  Entry hit rate: {metrics['entry_hit_rate']}%")
    log.info(f"  Win rate: {metrics['win_rate']}%")
    log.info(f"  Avg P&L: {metrics['avg_pnl_pct']}%")
    log.info(f"  Avg MFE: {metrics['avg_mfe_pct']}% | Avg MDD: {metrics['avg_mdd_pct']}%")
    log.info(f"  Profit Factor: {metrics['profit_factor']}")
    log.info(f"  Avg R-Multiple: {metrics.get('avg_r_multiple', 'N/A')}")
    log.info(
        f"  Outcomes: {metrics['target_count']} target / "
        f"{metrics['stopped_count']} stopped / "
        f"{metrics['ambiguous_same_day_count']} ambiguous / "
        f"{metrics['expired_count']} expired"
    )
    log.info("=" * 60)


def _save_results(metrics: dict, trades: list[dict]):
    """Save backtest results to JSON."""
    Path(RESULTS_DIR).mkdir(exist_ok=True)
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    filepath = Path(RESULTS_DIR) / f"backtest_{today}.json"

    result = {
        "run_date": today,
        "metrics": metrics,
        "trades": trades,
    }
    filepath.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    log.info(f"📋 Results saved to {filepath}")


if __name__ == "__main__":
    days = None
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        if idx + 1 < len(sys.argv):
            days = int(sys.argv[idx + 1])
    run_backtest(lookback_days=days)
