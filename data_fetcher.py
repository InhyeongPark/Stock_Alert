"""
Fetches stock price data and computes technical indicators using yfinance + pandas_ta.
Provides pre-computed compressed signals so Claude interprets rather than calculates.
"""

import logging

import yfinance as yf
import pandas_ta as ta

log = logging.getLogger(__name__)


def load_watchlist(filepath: str) -> list[str]:
    """Read tickers from watchlist.txt (one per line, # for comments)."""
    watchlist = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.split("#")[0].strip()
                if line:
                    watchlist.append(line.upper())
        log.info(f"Watchlist loaded: {len(watchlist)} tickers")
        return watchlist
    except FileNotFoundError:
        log.error(f"Cannot find {filepath}!")
        return []


def fetch_stock_data(ticker: str) -> dict | None:
    """Collect price data and calculate technical indicators for a single ticker."""
    log.info(f"Collecting data for: {ticker}")

    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")

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
        current_price = latest["Close"]

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

        # Basic info
        info = stock.info
        company_name = info.get("shortName", ticker)
        market_cap = info.get("marketCap", "N/A")
        sector = info.get("sector", "N/A")

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
        options_summary = _fetch_options_summary(stock, current_price)

        result = {
            "ticker": ticker,
            "company_name": company_name,
            "sector": sector,
            "market_cap": market_cap,
            "current_price": round(current_price, 2),
            "prev_close": round(prev["Close"], 2),
            "daily_change_pct": round(
                (current_price - prev["Close"]) / prev["Close"] * 100, 2
            ),
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

        log.info(f"{ticker}: ${result['current_price']} (RSI={result['rsi_14']})")
        return result

    except Exception as e:
        log.error(f"{ticker}: data fetch failed: {e}")
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