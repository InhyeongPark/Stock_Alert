"""
Fetches stock price data and computes technical indicators using yfinance + pandas_ta.
Provides pre-computed compressed signals so Claude interprets rather than calculates.
"""

import logging
from datetime import datetime
from math import isfinite
from pathlib import Path

import yfinance as yf
import pandas_ta as ta

from config import MAX_LIVE_PRICE_AGE_MINUTES, SKIP_STALE_LIVE_PRICES, TZ
from market_calendar import get_market_session_status
from watchlist_parser import load_watchlist_tickers

log = logging.getLogger(__name__)


def load_watchlist(filepath: str) -> list[str]:
    """Read tickers from watchlist.txt, ignoring optional profile metadata."""
    watchlist = load_watchlist_tickers(filepath)
    if watchlist:
        log.info(f"Watchlist loaded: {len(watchlist)} tickers")
        return watchlist

    if not Path(filepath).exists():
        log.error(f"Cannot find {filepath}!")

    return []


def fetch_stock_data(ticker: str, include_enrichment: bool = True) -> dict | None:
    """Collect price data and calculate technical indicators for a single ticker."""
    log.info(f"Collecting data for: {ticker}")

    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y", interval="1d", auto_adjust=False)

        if df.empty or len(df) < 200:
            log.warning(f"{ticker}: insufficient data (rows={len(df)})")
            return None

        # Technical indicators
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.bbands(length=20, std=2, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.atr(length=14, append=True)
        df.ta.stoch(append=True)

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        price_snapshot = _fetch_price_snapshot(stock, df, ticker)
        if _should_skip_for_stale_price(price_snapshot):
            log.warning(
                f"{ticker}: stale live price skipped "
                f"(status={price_snapshot['price_status']}, "
                f"as_of={price_snapshot.get('price_as_of')}, "
                f"age={price_snapshot.get('price_age_minutes')})"
            )
            return None

        current_price = price_snapshot["price"]
        prev_close = price_snapshot.get("previous_close") or _safe_float(prev["Close"])
        if current_price is None:
            log.warning(f"{ticker}: no usable current/anchor price")
            return None

        daily_change_pct = (
            (current_price - prev_close) / prev_close * 100
            if prev_close
            else 0
        )

        # Support / Resistance (full-period extremes)
        highs = df["High"].rolling(window=10).max().dropna()
        lows = df["Low"].rolling(window=10).min().dropna()
        resistance_levels = sorted(highs.nlargest(5).unique().tolist(), reverse=True)[:3]
        support_levels = sorted(lows.nsmallest(5).unique().tolist())[:3]

        # Nearest S/R relative to current price
        nearest_resistance = _nearest_levels_above(df, current_price, n=2)
        nearest_support = _nearest_levels_below(df, current_price, n=2)

        # 20-day swing candidates
        swing_candidates = _find_swing_candidates(df.tail(20))

        # Volume analysis
        avg_volume_20 = df["Volume"].tail(20).mean()
        current_volume = latest["Volume"]
        volume_ratio = current_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0

        # Basic info. Skip slower metadata calls for the fast opening snapshot.
        if include_enrichment:
            info = stock.info
            company_name = info.get("shortName", ticker)
            market_cap = info.get("marketCap", "N/A")
            sector = info.get("sector", "N/A")
        else:
            company_name = ticker
            market_cap = "N/A"
            sector = "N/A"

        # Price history summary
        high_120d = df["High"].tail(120)
        low_120d = df["Low"].tail(120)

        price_history_summary = {
            "120d_high": round(high_120d.max(), 2),
            "120d_high_date": high_120d.idxmax().strftime("%Y-%m-%d"),
            "120d_low": round(low_120d.min(), 2),
            "120d_low_date": low_120d.idxmin().strftime("%Y-%m-%d"),
            "60d_high": round(df["High"].tail(60).max(), 2),
            "60d_low": round(df["Low"].tail(60).min(), 2),
            "30d_high": round(df["High"].tail(30).max(), 2),
            "30d_low": round(df["Low"].tail(30).min(), 2),
        }

        # Recent 5-day OHLCV
        recent_5d = []
        for i in range(-5, 0):
            if i + len(df) >= 0:
                row = df.iloc[i]
                recent_5d.append({
                    "date": row.name.strftime("%m/%d"),
                    "open": round(row["Open"], 2),
                    "high": round(row["High"], 2),
                    "low": round(row["Low"], 2),
                    "close": round(row["Close"], 2),
                    "volume": int(row["Volume"]),
                })

        # Volume Profile (120-day) with current + adjacent zones
        volume_profile, top_volume_zones, current_zone, adjacent_zones = (
            _build_volume_profile(df, current_price)
        )

        # Options data (2 expirations, renamed OI strike)
        if include_enrichment:
            options_summary = _fetch_options_summary(stock, current_price)
        else:
            options_summary = {
                "available": False,
                "reason": "Skipped for fast market-open snapshot.",
            }

        result = {
            "ticker": ticker,
            "company_name": company_name,
            "sector": sector,
            "market_cap": market_cap,
            "current_price": round(current_price, 2),
            "prev_close": round(prev_close, 2),
            "daily_change_pct": round(daily_change_pct, 2),
            "price_source": price_snapshot["price_source"],
            "price_as_of": price_snapshot.get("price_as_of"),
            "price_retrieved_at": price_snapshot["price_retrieved_at"],
            "price_age_minutes": price_snapshot.get("price_age_minutes"),
            "price_status": price_snapshot["price_status"],
            "price_is_stale": price_snapshot["price_is_stale"],
            "price_warning": price_snapshot.get("price_warning"),
            "market_session": price_snapshot["market_session"],
            "market_open": price_snapshot.get("market_open"),
            "market_close": price_snapshot.get("market_close"),
            "data_delay_note": "Yahoo/yfinance is not an exchange-certified real-time feed; quote data can be delayed.",
            "indicator_as_of": _format_index_timestamp(latest.name),
            "indicator_basis": "1d unadjusted OHLCV; current_price is anchored to the live price snapshot above.",
            "high_52w": round(df["High"].tail(252).max(), 2) if len(df) >= 252 else round(df["High"].max(), 2),
            "low_52w": round(df["Low"].tail(252).min(), 2) if len(df) >= 252 else round(df["Low"].min(), 2),
            # Technical Indicators
            "rsi_14": round(latest.get("RSI_14", 0), 2),
            "macd": round(latest.get("MACD_12_26_9", 0), 4),
            "macd_signal": round(latest.get("MACDs_12_26_9", 0), 4),
            "macd_hist": round(latest.get("MACDh_12_26_9", 0), 4),
            "bb_upper": round(latest.get("BBU_20_2.0", 0), 2),
            "bb_middle": round(latest.get("BBM_20_2.0", 0), 2),
            "bb_lower": round(latest.get("BBL_20_2.0", 0), 2),
            "sma_20": round(latest.get("SMA_20", 0), 2),
            "sma_50": round(latest.get("SMA_50", 0), 2),
            "sma_200": round(latest.get("SMA_200", 0), 2),
            "atr_14": round(latest.get("ATRr_14", 0), 2),
            "stoch_k": round(latest.get("STOCHk_14_3_3", 0), 2),
            "stoch_d": round(latest.get("STOCHd_14_3_3", 0), 2),
            # Support/Resistance — full-period extremes
            "resistance_levels": [round(r, 2) for r in resistance_levels],
            "support_levels": [round(s, 2) for s in support_levels],
            # Nearest S/R — relative to current price
            "nearest_resistance": nearest_resistance,
            "nearest_support": nearest_support,
            # 20-day swing candidates
            "swing_candidates": swing_candidates,
            # Volume
            "volume_ratio": round(volume_ratio, 2),
            "avg_volume_20d": int(avg_volume_20),
            # Recent closes
            "recent_closes": [round(c, 2) for c in df["Close"].tail(5).tolist()],
            # Extended data
            "price_history_summary": price_history_summary,
            "recent_5d_ohlcv": recent_5d,
            "volume_profile": volume_profile,
            "top_volume_zones": top_volume_zones,
            "current_volume_zone": current_zone,
            "adjacent_volume_zones": adjacent_zones,
            # Options
            "options_summary": options_summary,
        }

        log.info(
            f"{ticker}: ${result['current_price']} "
            f"(RSI={result['rsi_14']}, "
            f"price_status={result['price_status']}, "
            f"as_of={result['price_as_of']})"
        )
        return result

    except Exception as e:
        log.error(f"{ticker}: data fetch failed: {e}")
        return None


# Helper: Live price snapshot

def _fetch_price_snapshot(stock, daily_df, ticker: str) -> dict:
    """Fetch a timestamped live anchor price, falling back only with clear labels."""
    retrieved_at = datetime.now(TZ)
    market_status = get_market_session_status(retrieved_at)
    fast_info = _get_fast_info(stock)
    intraday = _get_intraday_history(stock, ticker)

    price = None
    price_time = None
    price_source = "unavailable"

    if intraday is not None and not intraday.empty:
        close_series = intraday["Close"].dropna()
        if not close_series.empty:
            price = _safe_float(close_series.iloc[-1])
            price_time = _coerce_timestamp(close_series.index[-1])
            price_source = "yfinance_1m_intraday_close"

    if price is None:
        price = _safe_float(_fast_info_value(fast_info, "lastPrice", "last_price"))
        if price is not None:
            price_source = "yfinance_fast_info_last_price"

    if price is None:
        price = _safe_float(daily_df.iloc[-1]["Close"])
        price_time = _coerce_timestamp(daily_df.index[-1])
        price_source = "yfinance_daily_close_fallback"

    previous_close = _safe_float(
        _fast_info_value(
            fast_info,
            "regularMarketPreviousClose",
            "regular_market_previous_close",
            "previousClose",
            "previous_close",
        )
    )
    if previous_close is None:
        previous_close = _safe_float(daily_df.iloc[-2]["Close"])

    price_age_minutes = _price_age_minutes(retrieved_at, price_time)
    price_status, price_is_stale, price_warning = _classify_price_snapshot(
        price_source=price_source,
        price_age_minutes=price_age_minutes,
        market_status=market_status,
    )

    return {
        "price": price,
        "previous_close": previous_close,
        "price_source": price_source,
        "price_as_of": price_time.isoformat() if price_time else None,
        "price_retrieved_at": retrieved_at.isoformat(),
        "price_age_minutes": (
            round(price_age_minutes, 1)
            if price_age_minutes is not None
            else None
        ),
        "price_status": price_status,
        "price_is_stale": price_is_stale,
        "price_warning": price_warning,
        "market_session": market_status["session_state"],
        "market_open": market_status.get("market_open"),
        "market_close": market_status.get("market_close"),
    }


def _get_intraday_history(stock, ticker: str):
    try:
        return stock.history(
            period="2d",
            interval="1m",
            prepost=False,
            auto_adjust=False,
        )
    except Exception as e:
        log.warning(f"{ticker}: intraday quote unavailable: {e}")
        return None


def _get_fast_info(stock):
    try:
        return stock.fast_info
    except Exception as e:
        log.warning(f"fast_info unavailable: {e}")
        return {}


def _fast_info_value(fast_info, *keys):
    for key in keys:
        try:
            value = getattr(fast_info, key)
            if value is not None:
                return value
        except Exception:
            pass

        try:
            value = fast_info.get(key)
            if value is not None:
                return value
        except Exception:
            pass

        try:
            value = fast_info[key]
            if value is not None:
                return value
        except Exception:
            pass

    return None


def _classify_price_snapshot(
    price_source: str,
    price_age_minutes: float | None,
    market_status: dict,
) -> tuple[str, bool, str | None]:
    session_state = market_status["session_state"]
    has_timestamp = price_age_minutes is not None

    if session_state == "regular":
        if (
            price_source == "yfinance_1m_intraday_close"
            and has_timestamp
            and price_age_minutes <= MAX_LIVE_PRICE_AGE_MINUTES
        ):
            return "fresh", False, None

        if has_timestamp:
            return (
                "stale_regular_session",
                True,
                f"Latest quote is {price_age_minutes:.1f} minutes old during regular session.",
            )

        return (
            "timestamp_unavailable",
            True,
            "Live quote timestamp is unavailable during regular session.",
        )

    if price_source == "yfinance_1m_intraday_close" and has_timestamp:
        return (
            f"{session_state}_last_regular_bar",
            False,
            "Market is outside regular session; price is the latest regular-session minute bar.",
        )

    return (
        f"{session_state}_unverified_quote",
        session_state == "regular",
        "Quote timestamp is unavailable; do not treat this as a verified live price.",
    )


def _should_skip_for_stale_price(snapshot: dict) -> bool:
    return (
        SKIP_STALE_LIVE_PRICES
        and snapshot["market_session"] == "regular"
        and snapshot["price_status"] != "fresh"
    )


def _price_age_minutes(retrieved_at: datetime, price_time: datetime | None) -> float | None:
    if price_time is None:
        return None
    return max(0.0, (retrieved_at - price_time).total_seconds() / 60)


def _coerce_timestamp(value) -> datetime | None:
    if value is None:
        return None

    try:
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        if value.tzinfo is None:
            return value.replace(tzinfo=TZ)
        return value.astimezone(TZ)
    except Exception:
        return None


def _format_index_timestamp(value) -> str | None:
    timestamp = _coerce_timestamp(value)
    if timestamp:
        return timestamp.isoformat()
    try:
        return value.strftime("%Y-%m-%d")
    except Exception:
        return None


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


# Helper: Nearest Support/Resistance

def _nearest_levels_above(df, current_price: float, n: int = 2) -> list[dict]:
    """Find n nearest resistance levels above current price using rolling highs."""
    rolling_highs = df["High"].rolling(window=5).max().dropna()
    above = rolling_highs[rolling_highs > current_price * 1.005]
    if above.empty:
        return []
    unique_above = sorted(above.unique())
    return [{"price": round(p, 2)} for p in unique_above[:n]]


def _nearest_levels_below(df, current_price: float, n: int = 2) -> list[dict]:
    """Find n nearest support levels below current price using rolling lows."""
    rolling_lows = df["Low"].rolling(window=5).min().dropna()
    below = rolling_lows[rolling_lows < current_price * 0.995]
    if below.empty:
        return []
    unique_below = sorted(below.unique(), reverse=True)
    return [{"price": round(p, 2)} for p in unique_below[:n]]


# Helper: Swing Candidates

def _find_swing_candidates(df_20d) -> list[dict]:
    """Find local swing highs/lows in last 20 days. Up to 3 each."""
    candidates = []
    highs = df_20d["High"]
    lows = df_20d["Low"]

    for i in range(1, len(highs) - 1):
        if highs.iloc[i] > highs.iloc[i - 1] and highs.iloc[i] > highs.iloc[i + 1]:
            candidates.append({
                "date": highs.index[i].strftime("%m/%d"),
                "price": round(highs.iloc[i], 2),
                "type": "high",
            })

    for i in range(1, len(lows) - 1):
        if lows.iloc[i] < lows.iloc[i - 1] and lows.iloc[i] < lows.iloc[i + 1]:
            candidates.append({
                "date": lows.index[i].strftime("%m/%d"),
                "price": round(lows.iloc[i], 2),
                "type": "low",
            })

    swing_highs = sorted(
        [c for c in candidates if c["type"] == "high"],
        key=lambda x: x["price"], reverse=True
    )[:3]
    swing_lows = sorted(
        [c for c in candidates if c["type"] == "low"],
        key=lambda x: x["price"]
    )[:3]

    # Sort combined list by date so Claude can read the trend flow
    combined = swing_highs + swing_lows
    combined.sort(key=lambda x: x["date"])
    return combined


# Helper: Volume Profile

def _build_volume_profile(df, current_price: float):
    """Build 10-bin volume profile. Returns (full, top3, current_zone, adjacent)."""
    tail = df.tail(120)
    price_min = tail["Close"].min()
    price_max = tail["Close"].max()
    price_range = price_max - price_min
    num_bins = 10

    volume_profile = []
    current_zone = None
    current_idx = None

    for i in range(num_bins):
        bin_low = price_min + (price_range / num_bins) * i
        bin_high = price_min + (price_range / num_bins) * (i + 1)
        # Last bin uses <= to include price exactly at 120d high
        if i == num_bins - 1:
            mask = (tail["Close"] >= bin_low) & (tail["Close"] <= bin_high)
            is_current = bin_low <= current_price <= bin_high
        else:
            mask = (tail["Close"] >= bin_low) & (tail["Close"] < bin_high)
            is_current = bin_low <= current_price < bin_high
        bin_volume = tail["Volume"][mask].sum()

        zone = {
            "price_range": f"${bin_low:.2f} - ${bin_high:.2f}",
            "volume": int(bin_volume),
            "is_current": is_current,
        }
        volume_profile.append(zone)
        if is_current:
            current_zone = zone
            current_idx = i

    top_3 = sorted(volume_profile, key=lambda x: x["volume"], reverse=True)[:3]

    adjacent = {}
    if current_idx is not None:
        if current_idx > 0:
            adjacent["below"] = volume_profile[current_idx - 1]
        if current_idx < num_bins - 1:
            adjacent["above"] = volume_profile[current_idx + 1]

    return volume_profile, top_3, current_zone, adjacent


# Helper: Options Summary

def _fetch_options_summary(stock, current_price: float) -> dict:
    """Pull options for 2 nearest expirations. Uses highest_combined_oi_strike."""
    try:
        expirations = stock.options
        if not expirations:
            return {"available": False}

        result = {"available": True, "expirations": []}

        for exp in expirations[:2]:
            exp_data = _process_single_expiration(stock, exp)
            if exp_data:
                result["expirations"].append(exp_data)

        if not result["expirations"]:
            return {"available": False}

        first = result["expirations"][0]
        result.update({
            "nearest_expiration": first["expiration"],
            "total_call_oi": first["total_call_oi"],
            "total_put_oi": first["total_put_oi"],
            "put_call_ratio": first["put_call_ratio"],
            "highest_combined_oi_strike": first["highest_combined_oi_strike"],
            "top_call_oi_strikes": first["top_call_oi_strikes"],
            "top_put_oi_strikes": first["top_put_oi_strikes"],
        })

        return result

    except Exception as e:
        log.warning(f"Options data unavailable: {e}")
        return {"available": False}


def _process_single_expiration(stock, expiration: str) -> dict | None:
    """Process a single options expiration date."""
    try:
        chain = stock.option_chain(expiration)
        calls = chain.calls
        puts = chain.puts

        if calls.empty and puts.empty:
            return None

        top_call_oi = (
            calls.nlargest(5, "openInterest")[["strike", "openInterest"]]
            .rename(columns={"openInterest": "oi"})
            .to_dict("records")
        )
        top_put_oi = (
            puts.nlargest(5, "openInterest")[["strike", "openInterest"]]
            .rename(columns={"openInterest": "oi"})
            .to_dict("records")
        )

        total_call_oi = int(calls["openInterest"].sum())
        total_put_oi = int(puts["openInterest"].sum())
        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 0

        all_strikes = set(calls["strike"].tolist() + puts["strike"].tolist())
        best_strike = None
        best_oi = 0
        for strike in all_strikes:
            c_oi = calls.loc[calls["strike"] == strike, "openInterest"].sum()
            p_oi = puts.loc[puts["strike"] == strike, "openInterest"].sum()
            if c_oi + p_oi > best_oi:
                best_oi = c_oi + p_oi
                best_strike = strike

        return {
            "expiration": expiration,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "put_call_ratio": pcr,
            "highest_combined_oi_strike": round(best_strike, 2) if best_strike else None,
            "top_call_oi_strikes": top_call_oi,
            "top_put_oi_strikes": top_put_oi,
        }

    except Exception as e:
        log.warning(f"Options chain for {expiration} failed: {e}")
        return None
