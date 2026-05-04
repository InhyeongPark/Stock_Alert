"""
Fetches stock price data and computes technical indicators using yfinance + pandas_ta.
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
            log.warning(f"⚠️ {ticker}: insufficient data (rows={len(df)})")
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

        # Support / Resistance 
        highs = df["High"].rolling(window=10).max().dropna()
        lows = df["Low"].rolling(window=10).min().dropna()
        resistance_levels = sorted(highs.nlargest(5).unique().tolist(), reverse=True)[:3]
        support_levels = sorted(lows.nsmallest(5).unique().tolist())[:3]

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

        # Recent 5-day OHLCV (trimmed from 20 to save ~1,500 tokens/ticker)
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

        # Volume Profile (120-day)
        price_min = df["Close"].tail(120).min()
        price_max = df["Close"].tail(120).max()
        price_range = price_max - price_min
        num_bins = 10

        volume_profile = []
        for i in range(num_bins):
            bin_low = price_min + (price_range / num_bins) * i
            bin_high = price_min + (price_range / num_bins) * (i + 1)
            mask = (df["Close"].tail(120) >= bin_low) & (df["Close"].tail(120) < bin_high)
            bin_volume = df["Volume"].tail(120)[mask].sum()
            volume_profile.append({
                "price_range": f"${bin_low:.2f} - ${bin_high:.2f}",
                "volume": int(bin_volume),
                "is_current": bin_low <= latest["Close"] < bin_high,
            })

        volume_profile_sorted = sorted(volume_profile, key=lambda x: x["volume"], reverse=True)
        top_volume_zones = volume_profile_sorted[:3]

        # Options data (for liquidity sweep analysis)
        options_summary = _fetch_options_summary(stock, latest["Close"])

        result = {
            "ticker": ticker,
            "company_name": company_name,
            "sector": sector,
            "market_cap": market_cap,
            "current_price": round(latest["Close"], 2),
            "prev_close": round(prev["Close"], 2),
            "daily_change_pct": round(
                (latest["Close"] - prev["Close"]) / prev["Close"] * 100, 2
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
            # Support/Resistance
            "resistance_levels": [round(r, 2) for r in resistance_levels],
            "support_levels": [round(s, 2) for s in support_levels],
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
            # Options / Short Interest data
            "options_summary": options_summary,
        }

        log.info(f"{ticker}: ${result['current_price']} (RSI={result['rsi_14']})")
        return result

    except Exception as e:
        log.error(f"{ticker}: data fetch failed: {e}")
        return None


def _fetch_options_summary(stock, current_price: float) -> dict:
    """
    Pull options chain data from yfinance for the nearest expiration.
    Used for OI analysis and max-pain estimation.
    Returns a summary dict (gracefully returns empty if unavailable).
    """
    try:
        expirations = stock.options
        if not expirations:
            return {"available": False}

        # Use the nearest expiration
        nearest_exp = expirations[0]
        chain = stock.option_chain(nearest_exp)
        calls = chain.calls
        puts = chain.puts

        # Top 5 call OI strikes
        top_call_oi = (
            calls.nlargest(5, "openInterest")[["strike", "openInterest"]]
            .rename(columns={"openInterest": "oi"})
            .to_dict("records")
        )

        # Top 5 put OI strikes
        top_put_oi = (
            puts.nlargest(5, "openInterest")[["strike", "openInterest"]]
            .rename(columns={"openInterest": "oi"})
            .to_dict("records")
        )

        # Total OI
        total_call_oi = int(calls["openInterest"].sum())
        total_put_oi = int(puts["openInterest"].sum())
        pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 0

        # Max Pain estimate (strike with highest combined OI)
        all_strikes = set(calls["strike"].tolist() + puts["strike"].tolist())
        max_pain_strike = None
        max_pain_oi = 0
        for strike in all_strikes:
            c_oi = calls.loc[calls["strike"] == strike, "openInterest"].sum()
            p_oi = puts.loc[puts["strike"] == strike, "openInterest"].sum()
            combined = c_oi + p_oi
            if combined > max_pain_oi:
                max_pain_oi = combined
                max_pain_strike = strike

        return {
            "available": True,
            "nearest_expiration": nearest_exp,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "put_call_ratio": pcr,
            "max_pain_strike": round(max_pain_strike, 2) if max_pain_strike else None,
            "top_call_oi_strikes": top_call_oi,
            "top_put_oi_strikes": top_put_oi,
        }

    except Exception as e:
        log.warning(f"Options data unavailable: {e}")
        return {"available": False}