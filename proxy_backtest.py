"""
Phase 5b: Proxy Walk-Forward Signal Backtest

Tests whether the technical indicator conditions we feed to Claude
are historically valid — WITHOUT calling the Claude API.

Rules are FIXED (not tuned to past results) to avoid overfitting.
Uses the same indicators we give Claude: RSI, MACD, SMA, support levels.

Walk-forward: iterates day by day, checks if conditions are met,
then evaluates the next N days.

Bullish signals are executable long candidates. Bearish signals are
long-avoidance / risk-warning calls, not short trades.

Usage:
    python proxy_backtest.py MSFT          # single ticker, default 2 years
    python proxy_backtest.py MSFT --years 3
    python proxy_backtest.py ALL           # all watchlist tickers

Cost: $0 (no API calls, pure yfinance + pandas)
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import yfinance as yf
import pandas as pd
import pandas_ta as ta

from config import TZ

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

RESULTS_DIR = "backtest_results"
HOLDING_DAYS = 5
SIGNAL_COOLDOWN_DAYS = HOLDING_DAYS
STOP_ATR_MULTIPLE = 1.5  # Stop-loss = entry - (ATR * 1.5)
TARGET_ATR_MULTIPLE = 2.0  # Target = entry + (ATR * 2.0)
AMBIGUOUS_EXIT_POLICY = "conservative_stop"
LONG_TRADE = "long_trade"
LONG_AVOIDANCE = "long_avoidance"

# ─── FIXED RULES (do NOT tune these to past results) ────────────
# These match what we give Claude as bullish/bearish signals.

BULLISH_RULES = {
    "rsi_min": 30,      # RSI above oversold
    "rsi_max": 70,      # RSI below overbought
    "macd_hist": "positive_or_turning",  # MACD histogram > 0 or just crossed
    "price_above_sma20": True,
    "sma20_above_sma50": True,  # Short-term trend confirmation
}

BEARISH_RULES = {
    "rsi_min": 30,
    "rsi_max": 70,
    "macd_hist": "negative_or_turning",
    "price_below_sma20": True,
    "sma20_below_sma50": True,
}


def run_proxy_backtest(ticker: str, years: int = 2):
    """Run walk-forward proxy backtest for a single ticker."""
    log.info(f"📊 Proxy backtest: {ticker} ({years}y)")

    # Fetch historical data
    df = yf.Ticker(ticker).history(period=f"{years}y")
    if df.empty or len(df) < 200:
        log.error(f"❌ {ticker}: insufficient data")
        return

    # Compute indicators
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.sma(length=200, append=True)
    df.ta.atr(length=14, append=True)
    df.dropna(inplace=True)

    trades = []
    last_signal_idx = -SIGNAL_COOLDOWN_DAYS

    # Walk forward: check each day
    for i in range(len(df) - HOLDING_DAYS - 1):
        if i - last_signal_idx < SIGNAL_COOLDOWN_DAYS:
            continue

        row = df.iloc[i]
        signal = _check_signal(row)

        if signal is None:
            continue

        # Evaluate next N days
        entry_price = row["Close"]
        atr = row.get("ATRr_14", entry_price * 0.02)
        future = df.iloc[i + 1: i + 1 + HOLDING_DAYS]

        if signal == "bullish":
            stop_price = entry_price - (atr * STOP_ATR_MULTIPLE)
            target_price = entry_price + (atr * TARGET_ATR_MULTIPLE)
            trade = _evaluate_trade(
                ticker=ticker,
                signal_date=row.name.strftime("%Y-%m-%d"),
                direction=signal,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
                future_data=future,
            )
        else:
            trade = _evaluate_long_avoidance(
                ticker=ticker,
                signal_date=row.name.strftime("%Y-%m-%d"),
                reference_price=entry_price,
                future_data=future,
            )

        trades.append(trade)
        last_signal_idx = i

    if not trades:
        log.warning(f"⚠️ {ticker}: no signals generated")
        return

    # Compute and display metrics
    metrics = _compute_metrics(trades)
    _print_report(ticker, metrics, trades, years)
    _save_results(ticker, metrics, trades, years)


def _check_signal(row) -> str | None:
    """
    Check FIXED rules against current day's indicators.
    Returns 'bullish', 'bearish', or None.
    """
    rsi = row.get("RSI_14", 50)
    macd_hist = row.get("MACDh_12_26_9", 0)
    close = row["Close"]
    sma20 = row.get("SMA_20", close)
    sma50 = row.get("SMA_50", close)

    # Bullish check
    if (BULLISH_RULES["rsi_min"] < rsi < BULLISH_RULES["rsi_max"]
            and macd_hist > 0
            and close > sma20
            and sma20 > sma50):
        return "bullish"

    # Bearish check
    if (BEARISH_RULES["rsi_min"] < rsi < BEARISH_RULES["rsi_max"]
            and macd_hist < 0
            and close < sma20
            and sma20 < sma50):
        return "bearish"

    return None


def _evaluate_trade(
    ticker, signal_date, direction, entry_price, stop_price, target_price, future_data
) -> dict:
    """Evaluate a bullish long trade over the holding period."""
    max_favorable = 0
    max_adverse = 0
    outcome = "expired"
    exit_price = future_data.iloc[-1]["Close"] if len(future_data) > 0 else entry_price

    for _, row in future_data.iterrows():
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

    pnl_pct = (exit_price - entry_price) / entry_price * 100

    risk = abs(entry_price - stop_price)
    reward = exit_price - entry_price
    r_multiple = round(reward / risk, 2) if risk > 0 else 0

    return {
        "ticker": ticker,
        "signal_date": signal_date,
        "evaluation_type": LONG_TRADE,
        "direction": direction,
        "entry_price": round(entry_price, 2),
        "stop_price": round(stop_price, 2),
        "target_price": round(target_price, 2),
        "exit_price": round(exit_price, 2),
        "outcome": outcome,
        "ambiguous_exit_policy": AMBIGUOUS_EXIT_POLICY if outcome == "ambiguous_same_day" else None,
        "pnl_pct": round(pnl_pct, 2),
        "mfe_pct": round(max_favorable, 2),
        "mdd_pct": round(max_adverse, 2),
        "r_multiple": r_multiple,
    }


def _evaluate_long_avoidance(ticker, signal_date, reference_price, future_data) -> dict:
    """
    Evaluate a bearish signal as a long-avoidance call, not a short trade.

    Positive avoided_return_pct means the avoided long would have lost money.
    Positive max_runup_pct is opportunity cost from staying out.
    """
    exit_price = future_data.iloc[-1]["Close"] if len(future_data) > 0 else reference_price
    long_return_pct = (exit_price - reference_price) / reference_price * 100
    avoided_return_pct = -long_return_pct
    max_decline_pct = max(
        0,
        (reference_price - future_data["Low"].min()) / reference_price * 100,
    ) if len(future_data) > 0 else 0
    max_runup_pct = max(
        0,
        (future_data["High"].max() - reference_price) / reference_price * 100,
    ) if len(future_data) > 0 else 0

    if long_return_pct < 0:
        outcome = "avoided_loss"
    elif long_return_pct > 0:
        outcome = "missed_gain"
    else:
        outcome = "flat"

    return {
        "ticker": ticker,
        "signal_date": signal_date,
        "evaluation_type": LONG_AVOIDANCE,
        "direction": "bearish",
        "action": "avoid_long",
        "reference_price": round(reference_price, 2),
        "exit_price": round(exit_price, 2),
        "outcome": outcome,
        "long_return_pct": round(long_return_pct, 2),
        "avoided_return_pct": round(avoided_return_pct, 2),
        "max_decline_pct": round(max_decline_pct, 2),
        "max_runup_pct": round(max_runup_pct, 2),
    }


def _hit_flags(row, stop_price: float, target_price: float) -> tuple[bool, bool]:
    """Return whether stop and target touched inside the same daily bar."""
    stop_hit = row["Low"] <= stop_price
    target_hit = row["High"] >= target_price

    return stop_hit, target_hit


def _compute_metrics(records: list[dict]) -> dict:
    """Compute aggregate performance metrics."""
    long_trades = [r for r in records if r.get("evaluation_type") == LONG_TRADE]
    avoidance = [r for r in records if r.get("evaluation_type") == LONG_AVOIDANCE]

    metrics = {
        "total_signals": len(records),
        "long_trade_signals": len(long_trades),
        "avoidance_signals": len(avoidance),
        "signal_cooldown_days": SIGNAL_COOLDOWN_DAYS,
        "stop_atr_multiple": STOP_ATR_MULTIPLE,
        "target_atr_multiple": TARGET_ATR_MULTIPLE,
    }

    if long_trades:
        wins = [t for t in long_trades if t["pnl_pct"] > 0]
        losses = [t for t in long_trades if t["pnl_pct"] <= 0]
        gross_profit = sum(t["pnl_pct"] for t in wins)
        gross_loss = abs(sum(t["pnl_pct"] for t in losses))
        r_multiples = [t["r_multiple"] for t in long_trades if t["r_multiple"] is not None]
        metrics.update({
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(long_trades) * 100, 1),
            "avg_pnl_pct": round(sum(t["pnl_pct"] for t in long_trades) / len(long_trades), 2),
            "avg_mfe_pct": round(sum(t["mfe_pct"] for t in long_trades) / len(long_trades), 2),
            "avg_mdd_pct": round(sum(t["mdd_pct"] for t in long_trades) / len(long_trades), 2),
            "max_single_loss_pct": round(min(t["pnl_pct"] for t in long_trades), 2),
            "max_single_win_pct": round(max(t["pnl_pct"] for t in long_trades), 2),
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
            "avg_r_multiple": round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else None,
            "stopped_count": len([t for t in long_trades if t["outcome"] == "stopped"]),
            "target_count": len([t for t in long_trades if t["outcome"] == "target"]),
            "ambiguous_same_day_count": len([t for t in long_trades if t["outcome"] == "ambiguous_same_day"]),
            "expired_count": len([t for t in long_trades if t["outcome"] == "expired"]),
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
            "avoided_loss_count": 0,
            "missed_gain_count": 0,
        })

    return metrics


def _print_report(ticker: str, metrics: dict, trades: list[dict], years: int):
    """Print proxy backtest results."""
    log.info("=" * 60)
    log.info(f"PROXY BACKTEST: {ticker} ({years}y)")
    log.info("=" * 60)
    log.info(f"  Total signals: {metrics['total_signals']}")
    log.info(
        f"  Long trade signals: {metrics['long_trade_signals']} | "
        f"Long-avoidance signals: {metrics['avoidance_signals']}"
    )
    log.info(f"  Cooldown: {metrics['signal_cooldown_days']} trading days")

    if metrics["long_trade_signals"]:
        log.info(f"  Long win rate: {metrics['win_rate']}%")
        log.info(f"  Avg long P&L: {metrics['avg_pnl_pct']}%")
        log.info(f"  Avg MFE: {metrics['avg_mfe_pct']}% | Avg MDD: {metrics['avg_mdd_pct']}%")
        log.info(f"  Profit Factor: {metrics['profit_factor']}")
        log.info(f"  Avg R-Multiple: {metrics.get('avg_r_multiple', 'N/A')}")
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

    log.info("  Fixed rules are not tuned to results. Bearish means avoid long, not short.")
    log.info("=" * 60)


def _save_results(ticker: str, metrics: dict, trades: list[dict], years: int):
    """Save proxy backtest results to JSON."""
    Path(RESULTS_DIR).mkdir(exist_ok=True)
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    filepath = Path(RESULTS_DIR) / f"proxy_{ticker}_{years}y_{today}.json"

    result = {
        "ticker": ticker,
        "years": years,
        "run_date": today,
        "rules": {"bullish": BULLISH_RULES, "bearish": BEARISH_RULES},
        "params": {
            "holding_days": HOLDING_DAYS,
            "signal_cooldown_days": SIGNAL_COOLDOWN_DAYS,
            "stop_atr_multiple": STOP_ATR_MULTIPLE,
            "target_atr_multiple": TARGET_ATR_MULTIPLE,
            "bearish_evaluation": "long_avoidance",
        },
        "metrics": metrics,
        "evaluation_count": len(trades),
        # Don't save all trades to keep file small — save summary only
    }
    filepath.write_text(json.dumps(result, indent=2))
    log.info(f"📋 Results saved to {filepath}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python proxy_backtest.py TICKER [--years N]")
        sys.exit(1)

    ticker_arg = sys.argv[1].upper()
    years_arg = 2

    if "--years" in sys.argv:
        idx = sys.argv.index("--years")
        if idx + 1 < len(sys.argv):
            years_arg = int(sys.argv[idx + 1])

    if ticker_arg == "ALL":
        from data_fetcher import load_watchlist
        from config import WATCHLIST_FILE
        for t in load_watchlist(WATCHLIST_FILE):
            run_proxy_backtest(t, years_arg)
    else:
        run_proxy_backtest(ticker_arg, years_arg)
