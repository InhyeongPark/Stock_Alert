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
    - Bullish signals: evaluated as long trade candidates
    - Bearish signals: evaluated as long-avoidance / risk-warning calls
    - Entry hit rate: did price reach the recommended bullish entry?
    - Win rate: bullish entries that produced positive long P&L
    - Max drawdown from entry (MDD)
    - Max favorable excursion (MFE)
    - Profit factor: gross profit / gross loss
    - Average R-multiple: avg(profit / risk_per_trade)
    - Avoidance success: bearish calls where avoiding a long prevented a loss
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
TARGET_R_MULTIPLE = 2.0  # Bullish target = entry + 2R, where R is entry-stop risk
AMBIGUOUS_EXIT_POLICY = "conservative_stop"
LONG_TRADE = "long_trade"
LONG_AVOIDANCE = "long_avoidance"
INVALID_RISK = "invalid_risk"
BENCHMARK_TICKERS = ("SPY", "QQQ")


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
    benchmark_cache = {}

    for filepath in files:
        report = json.loads(filepath.read_text())
        report_date = report.get("date")

        for ticker_summary in report.get("tickers", []):
            trades = _evaluate_ticker(report_date, ticker_summary, benchmark_cache=benchmark_cache)
            all_trades.extend(trades)

    if not all_trades:
        log.warning("⚠️ No evaluable trades found (need at least 1 trading day after signal)")
        return

    # Compute metrics
    metrics = _compute_metrics(all_trades)
    _print_report(metrics, all_trades)
    _save_results(metrics, all_trades)


def _evaluate_ticker(
    report_date: str,
    summary: dict,
    benchmark_cache: dict | None = None,
) -> list[dict]:
    """
    Evaluate one ticker's recommendations against actual subsequent prices.
    Returns list of evaluation dicts with outcomes.
    """
    ticker = summary.get("ticker", "?")
    direction = summary.get("direction", "unknown").lower()
    entries = summary.get("entry_prices", [])
    stops = summary.get("stop_prices", [])

    if direction not in ("bullish", "bearish"):
        return []

    if direction == "bullish" and not entries:
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

    benchmark_returns = _fetch_benchmark_returns(
        start,
        end,
        len(actual_prices),
        cache=benchmark_cache,
    )

    if direction == "bearish":
        reference_price = _safe_float(summary.get("current_price"))
        if reference_price is None:
            reference_price = _safe_float(actual_prices.iloc[0].get("Open"))
        if reference_price is None:
            return []

        avoidance = _evaluate_long_avoidance(
            ticker=ticker,
            signal_date=report_date,
            reference_price=reference_price,
            price_data=actual_prices,
            benchmark_returns=benchmark_returns,
        )
        return [avoidance] if avoidance else []

    trades = []

    for i, entry_price in enumerate(entries[:3]):
        entry_price = _safe_float(entry_price)
        stop_price = _safe_float(stops[i]) if i < len(stops) else None
        if entry_price is None:
            continue
        if stop_price is not None and stop_price >= entry_price:
            trades.append(_invalid_risk_record(
                ticker=ticker,
                report_date=report_date,
                entry_level=i + 1,
                entry_price=entry_price,
                stop_price=stop_price,
                reason="stop_not_below_entry",
                benchmark_returns=benchmark_returns,
            ))
            continue
        if stop_price is None:
            trades.append(_invalid_risk_record(
                ticker=ticker,
                report_date=report_date,
                entry_level=i + 1,
                entry_price=entry_price,
                stop_price=stop_price,
                reason="missing_stop",
                benchmark_returns=benchmark_returns,
            ))
            continue

        trade = _simulate_trade(
            ticker=ticker,
            report_date=report_date,
            entry_level=i + 1,
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            price_data=actual_prices,
            benchmark_returns=benchmark_returns,
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
    benchmark_returns: dict[str, float] | None = None,
) -> dict | None:
    """
    Simulate a bullish long entry and evaluate stop-loss and target outcomes.
    """
    entry_triggered = False
    entry_date = None

    for date, row in price_data.iterrows():
        if row["Low"] <= entry_price:
            entry_triggered = True
            entry_date = date
            break

    target_price = _target_from_stop(entry_price, stop_price)
    risk = _risk_structure(entry_price, stop_price, target_price)

    if not entry_triggered:
        return {
            "ticker": ticker,
            "report_date": report_date,
            "entry_level": entry_level,
            "evaluation_type": LONG_TRADE,
            "direction": direction,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": _round_or_none(target_price),
            "risk": risk,
            "benchmark_returns_pct": benchmark_returns or {},
            "excess_vs_benchmark_pct": {},
            "entry_triggered": False,
            "outcome": "no_fill",
            "pnl_pct": 0,
            "mfe_pct": 0,
            "mdd_pct": 0,
        }

    # Entry was triggered — evaluate subsequent price action
    post_entry = price_data.loc[entry_date:]

    max_favorable = 0
    max_adverse = 0
    outcome = "open"  # still within holding period
    exit_price = None

    for _, row in post_entry.iterrows():
        favorable = (row["High"] - entry_price) / entry_price * 100
        adverse = (entry_price - row["Low"]) / entry_price * 100

        max_favorable = max(max_favorable, favorable)
        max_adverse = max(max_adverse, adverse)

        stop_hit, target_hit = _hit_flags(row, stop_price, target_price)

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
    pnl_pct = (exit_price - entry_price) / entry_price * 100

    # R-multiple (if stop exists)
    r_multiple = None
    if stop_price:
        risk_amount = abs(entry_price - stop_price)
        if risk_amount > 0:
            reward = exit_price - entry_price
            r_multiple = _round_or_none(reward / risk_amount)

    return {
        "ticker": ticker,
        "report_date": report_date,
        "entry_level": entry_level,
        "evaluation_type": LONG_TRADE,
        "direction": direction,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": _round_or_none(target_price),
        "risk": risk,
        "benchmark_returns_pct": benchmark_returns or {},
        "excess_vs_benchmark_pct": _excess_returns(pnl_pct, benchmark_returns),
        "entry_triggered": True,
        "outcome": outcome,
        "ambiguous_exit_policy": AMBIGUOUS_EXIT_POLICY if outcome == "ambiguous_same_day" else None,
        "exit_price": _round_or_none(exit_price),
        "pnl_pct": _round_or_none(pnl_pct),
        "mfe_pct": _round_or_none(max_favorable),
        "mdd_pct": _round_or_none(max_adverse),
        "r_multiple": r_multiple,
    }


def _evaluate_long_avoidance(
    ticker: str,
    signal_date: str,
    reference_price: float,
    price_data,
    benchmark_returns: dict[str, float] | None = None,
) -> dict | None:
    """
    Evaluate a bearish signal as a long-avoidance call.

    Positive avoided_return_pct means the avoided long would have lost money.
    Positive max_runup_pct is opportunity cost from staying out.
    """
    if price_data.empty or reference_price <= 0:
        return None

    exit_price = price_data.iloc[-1]["Close"]
    long_return_pct = (exit_price - reference_price) / reference_price * 100
    avoided_return_pct = -long_return_pct
    max_decline_pct = max(
        0,
        (reference_price - price_data["Low"].min()) / reference_price * 100,
    )
    max_runup_pct = max(
        0,
        (price_data["High"].max() - reference_price) / reference_price * 100,
    )

    if long_return_pct < 0:
        outcome = "avoided_loss"
    elif long_return_pct > 0:
        outcome = "missed_gain"
    else:
        outcome = "flat"

    return {
        "ticker": ticker,
        "report_date": signal_date,
        "evaluation_type": LONG_AVOIDANCE,
        "direction": "bearish",
        "action": "avoid_long",
        "reference_price": _round_or_none(reference_price),
        "exit_price": _round_or_none(exit_price),
        "outcome": outcome,
        "long_return_pct": _round_or_none(long_return_pct),
        "avoided_return_pct": _round_or_none(avoided_return_pct),
        "max_decline_pct": _round_or_none(max_decline_pct),
        "max_runup_pct": _round_or_none(max_runup_pct),
        "benchmark_returns_pct": benchmark_returns or {},
        "ticker_vs_benchmark_pct": _ticker_vs_benchmark(long_return_pct, benchmark_returns),
    }


def _invalid_risk_record(
    ticker: str,
    report_date: str,
    entry_level: int,
    entry_price: float,
    stop_price: float | None,
    reason: str,
    benchmark_returns: dict[str, float] | None = None,
) -> dict:
    return {
        "ticker": ticker,
        "report_date": report_date,
        "entry_level": entry_level,
        "evaluation_type": INVALID_RISK,
        "direction": "bullish",
        "entry_price": _round_or_none(entry_price),
        "stop_price": _round_or_none(stop_price),
        "target_price": None,
        "risk": _risk_structure(entry_price, stop_price, None),
        "benchmark_returns_pct": benchmark_returns or {},
        "entry_triggered": None,
        "outcome": "no_risk_defined",
        "invalid_risk_reason": reason,
    }


def _target_from_stop(entry_price: float, stop_price: float | None) -> float | None:
    if stop_price is None:
        return None

    risk = entry_price - stop_price
    if risk <= 0:
        return None

    return entry_price + (risk * TARGET_R_MULTIPLE)


def _risk_structure(
    entry_price: float,
    stop_price: float | None,
    target_price: float | None,
    atr: float | None = None,
) -> dict:
    risk_dollars = entry_price - stop_price if stop_price is not None else None
    target_dollars = target_price - entry_price if target_price is not None else None

    return {
        "risk_pct_to_stop": _round_or_none(
            risk_dollars / entry_price * 100 if risk_dollars and risk_dollars > 0 else None
        ),
        "target_pct": _round_or_none(
            target_dollars / entry_price * 100 if target_dollars and target_dollars > 0 else None
        ),
        "target_r_multiple": _round_or_none(
            target_dollars / risk_dollars
            if risk_dollars and risk_dollars > 0 and target_dollars is not None
            else None
        ),
        "atr_to_stop": _round_or_none(risk_dollars / atr if atr and risk_dollars and risk_dollars > 0 else None),
    }


def _hit_flags(row, stop_price: float | None, target_price: float | None) -> tuple[bool, bool]:
    """Return whether stop and target touched inside the same daily bar."""
    stop_hit = stop_price is not None and row["Low"] <= stop_price
    target_hit = target_price is not None and row["High"] >= target_price

    return stop_hit, target_hit


def _safe_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: float | None) -> float | None:
    return round(float(value), 2) if value is not None else None


def _fetch_benchmark_returns(
    start: datetime,
    end: datetime,
    holding_days: int,
    cache: dict | None = None,
) -> dict[str, float]:
    cache_key = (start.date().isoformat(), end.date().isoformat(), holding_days)
    if cache is not None and cache_key in cache:
        return dict(cache[cache_key])

    returns = {}

    for symbol in BENCHMARK_TICKERS:
        try:
            df = yf.Ticker(symbol).history(start=start, end=end)
            pct = _window_return_pct(df.head(holding_days))
            if pct is not None:
                returns[symbol] = pct
        except Exception as e:
            log.warning(f"⚠️ {symbol}: benchmark fetch failed: {e}")

    if cache is not None:
        cache[cache_key] = dict(returns)

    return returns


def _window_return_pct(price_data) -> float | None:
    if price_data.empty:
        return None

    start_price = _safe_float(price_data.iloc[0].get("Open"))
    end_price = _safe_float(price_data.iloc[-1].get("Close"))
    if start_price is None or end_price is None or start_price <= 0:
        return None

    return round((end_price - start_price) / start_price * 100, 2)


def _excess_returns(pnl_pct: float, benchmark_returns: dict[str, float] | None) -> dict[str, float]:
    if not benchmark_returns:
        return {}

    return {
        symbol: _round_or_none(pnl_pct - benchmark_return)
        for symbol, benchmark_return in benchmark_returns.items()
    }


def _ticker_vs_benchmark(long_return_pct: float, benchmark_returns: dict[str, float] | None) -> dict[str, float]:
    if not benchmark_returns:
        return {}

    return {
        symbol: _round_or_none(long_return_pct - benchmark_return)
        for symbol, benchmark_return in benchmark_returns.items()
    }


def _avg_nested(records: list[dict], field: str) -> dict[str, float]:
    totals = {}
    counts = {}

    for record in records:
        values = record.get(field) or {}
        for symbol, value in values.items():
            totals[symbol] = totals.get(symbol, 0) + value
            counts[symbol] = counts.get(symbol, 0) + 1

    return {
        symbol: _round_or_none(total / counts[symbol])
        for symbol, total in totals.items()
        if counts.get(symbol)
    }


def _underperformance_rates(records: list[dict], field: str) -> dict[str, float]:
    totals = {}
    underperformed = {}

    for record in records:
        values = record.get(field) or {}
        for symbol, value in values.items():
            totals[symbol] = totals.get(symbol, 0) + 1
            if value < 0:
                underperformed[symbol] = underperformed.get(symbol, 0) + 1

    return {
        symbol: round(underperformed.get(symbol, 0) / total * 100, 1)
        for symbol, total in totals.items()
        if total
    }


def _benchmark_relative_success_counts(records: list[dict]) -> dict[str, dict]:
    totals = {}
    successes = {}

    for record in records:
        values = record.get("ticker_vs_benchmark_pct") or {}
        for symbol, value in values.items():
            totals[symbol] = totals.get(symbol, 0) + 1
            if value < 0:
                successes[symbol] = successes.get(symbol, 0) + 1

    return {
        symbol: {
            "successes": successes.get(symbol, 0),
            "failures": total - successes.get(symbol, 0),
            "success_rate": round(successes.get(symbol, 0) / total * 100, 1),
        }
        for symbol, total in totals.items()
        if total
    }


def _count_by(records: list[dict], field: str) -> dict[str, int]:
    counts = {}
    for record in records:
        key = record.get(field, "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _compute_metrics(records: list[dict]) -> dict:
    """Compute aggregate performance metrics."""
    long_trades = [r for r in records if r.get("evaluation_type") == LONG_TRADE]
    avoidance = [r for r in records if r.get("evaluation_type") == LONG_AVOIDANCE]
    invalid_risk = [r for r in records if r.get("evaluation_type") == INVALID_RISK]
    triggered = [t for t in long_trades if t["entry_triggered"]]
    not_triggered = [t for t in long_trades if not t["entry_triggered"]]

    metrics = {
        "total_evaluations": len(records),
        "long_trade_signals": len(long_trades),
        "avoidance_signals": len(avoidance),
        "invalid_risk_signals": len(invalid_risk),
        "invalid_risk_count": len(invalid_risk),
        "invalid_risk_reasons": _count_by(invalid_risk, "invalid_risk_reason"),
        "target_r_multiple": TARGET_R_MULTIPLE,
    }

    if long_trades:
        metrics.update({
            "entries_triggered": len(triggered),
            "entries_missed": len(not_triggered),
            "entry_hit_rate": round(len(triggered) / len(long_trades) * 100, 1),
        })
    else:
        metrics.update({
            "entries_triggered": 0,
            "entries_missed": 0,
            "entry_hit_rate": None,
        })

    if triggered:
        wins = [t for t in triggered if t["pnl_pct"] > 0]
        losses = [t for t in triggered if t["pnl_pct"] <= 0]
        gross_profit = sum(t["pnl_pct"] for t in wins)
        gross_loss = abs(sum(t["pnl_pct"] for t in losses))
        r_multiples = [t["r_multiple"] for t in triggered if t["r_multiple"] is not None]
        metrics.update({
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(triggered) * 100, 1),
            "avg_pnl_pct": round(sum(t["pnl_pct"] for t in triggered) / len(triggered), 2),
            "avg_mfe_pct": round(sum(t["mfe_pct"] for t in triggered) / len(triggered), 2),
            "avg_mdd_pct": round(sum(t["mdd_pct"] for t in triggered) / len(triggered), 2),
            "max_single_loss_pct": round(min(t["pnl_pct"] for t in triggered), 2),
            "max_single_win_pct": round(max(t["pnl_pct"] for t in triggered), 2),
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
            "avg_r_multiple": round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else None,
            "avg_excess_vs_benchmark_pct": _avg_nested(triggered, "excess_vs_benchmark_pct"),
            "stopped_count": len([t for t in triggered if t["outcome"] == "stopped"]),
            "target_count": len([t for t in triggered if t["outcome"] == "target"]),
            "ambiguous_same_day_count": len([t for t in triggered if t["outcome"] == "ambiguous_same_day"]),
            "expired_count": len([t for t in triggered if t["outcome"] == "expired"]),
        })
    else:
        metrics.update({
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "avg_pnl_pct": None,
            "avg_mfe_pct": None,
            "avg_mdd_pct": None,
            "max_single_loss_pct": None,
            "max_single_win_pct": None,
            "profit_factor": None,
            "avg_r_multiple": None,
            "avg_excess_vs_benchmark_pct": {},
            "stopped_count": 0,
            "target_count": 0,
            "ambiguous_same_day_count": 0,
            "expired_count": 0,
        })

    if avoidance:
        successes = [a for a in avoidance if a["avoided_return_pct"] > 0]
        metrics.update({
            "avoidance_successes": len(successes),
            "avoidance_failures": len(avoidance) - len(successes),
            "avoidance_success_rate": round(len(successes) / len(avoidance) * 100, 1),
            "avg_avoided_return_pct": round(
                sum(a["avoided_return_pct"] for a in avoidance) / len(avoidance),
                2,
            ),
            "avg_avoided_drawdown_pct": round(
                sum(a["max_decline_pct"] for a in avoidance) / len(avoidance),
                2,
            ),
            "avg_missed_upside_pct": round(
                sum(a["max_runup_pct"] for a in avoidance) / len(avoidance),
                2,
            ),
            "avg_ticker_vs_benchmark_pct": _avg_nested(avoidance, "ticker_vs_benchmark_pct"),
            "benchmark_underperformance_rate": _underperformance_rates(avoidance, "ticker_vs_benchmark_pct"),
            "benchmark_relative_avoidance": _benchmark_relative_success_counts(avoidance),
            "avoided_loss_count": len([a for a in avoidance if a["outcome"] == "avoided_loss"]),
            "missed_gain_count": len([a for a in avoidance if a["outcome"] == "missed_gain"]),
        })
    else:
        metrics.update({
            "avoidance_successes": 0,
            "avoidance_failures": 0,
            "avoidance_success_rate": None,
            "avg_avoided_return_pct": None,
            "avg_avoided_drawdown_pct": None,
            "avg_missed_upside_pct": None,
            "avg_ticker_vs_benchmark_pct": {},
            "benchmark_underperformance_rate": {},
            "benchmark_relative_avoidance": {},
            "avoided_loss_count": 0,
            "missed_gain_count": 0,
        })

    return metrics


def _print_report(metrics: dict, records: list[dict]):
    """Print backtest results to console."""
    log.info("=" * 60)
    log.info("📊 BACKTEST RESULTS")
    log.info("=" * 60)
    log.info(f"  Total evaluations: {metrics['total_evaluations']}")
    log.info(
        f"  Long trade signals: {metrics['long_trade_signals']} | "
        f"Long-avoidance signals: {metrics['avoidance_signals']} | "
        f"Invalid-risk signals: {metrics['invalid_risk_signals']}"
    )
    if metrics["invalid_risk_signals"]:
        log.info(f"  Invalid-risk reasons: {metrics['invalid_risk_reasons']}")
    if metrics["long_trade_signals"]:
        log.info(f"  Long entry hit rate: {metrics['entry_hit_rate']}%")
        log.info(f"  Long win rate: {metrics['win_rate']}%")
        log.info(f"  Avg long P&L: {metrics['avg_pnl_pct']}%")
        log.info(f"  Avg MFE: {metrics['avg_mfe_pct']}% | Avg MDD: {metrics['avg_mdd_pct']}%")
        log.info(f"  Profit Factor: {metrics['profit_factor']}")
        log.info(f"  Avg R-Multiple: {metrics.get('avg_r_multiple', 'N/A')}")
        if metrics["avg_excess_vs_benchmark_pct"]:
            log.info(f"  Avg excess vs benchmark: {metrics['avg_excess_vs_benchmark_pct']}")
        log.info(
            f"  Long outcomes: {metrics['target_count']} target / "
            f"{metrics['stopped_count']} stopped / "
            f"{metrics['ambiguous_same_day_count']} ambiguous / "
            f"{metrics['expired_count']} expired"
        )
    if metrics["avoidance_signals"]:
        log.info(f"  Avoidance success rate: {metrics['avoidance_success_rate']}%")
        log.info(f"  Avg avoided return: {metrics['avg_avoided_return_pct']}%")
        log.info(f"  Avg avoided drawdown: {metrics['avg_avoided_drawdown_pct']}%")
        log.info(f"  Avg missed upside: {metrics['avg_missed_upside_pct']}%")
        if metrics["avg_ticker_vs_benchmark_pct"]:
            log.info(f"  Avg ticker vs benchmark: {metrics['avg_ticker_vs_benchmark_pct']}")
            log.info(f"  Benchmark underperformance rate: {metrics['benchmark_underperformance_rate']}")
            log.info(f"  Benchmark-relative avoidance: {metrics['benchmark_relative_avoidance']}")
    log.info("=" * 60)


def _save_results(metrics: dict, records: list[dict]):
    """Save backtest results to JSON."""
    Path(RESULTS_DIR).mkdir(exist_ok=True)
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    filepath = Path(RESULTS_DIR) / f"backtest_{today}.json"

    result = {
        "run_date": today,
        "benchmarks": list(BENCHMARK_TICKERS),
        "metrics": metrics,
        "evaluations": records,
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
