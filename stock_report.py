
"""
Environment Variables (.env or GitHub Secrets):
    ANTHROPIC_API_KEY  - Claude API Key
    GMAIL_ADDRESS      - Sender's Gmail Address
    GMAIL_APP_PASSWORD - Gmail App Password (16 characters)
    RECIPIENT_EMAIL    - Recipient's Email Address
"""

import os
import smtplib
import logging
import re
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf
import pandas_ta as ta
import anthropic
from dotenv import load_dotenv

# Settings
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Watchlist File Path
WATCHLIST_FILE = "watchlist.txt"

# Claude Model
CLAUDE_MODEL = "claude-sonnet-4-6"

# Report Language: "ko" (Korean, Default) || "en" (English)
REPORT_LANGUAGE = "ko"

# Timezone
TZ = ZoneInfo("America/New_York")


# Load Watchlist
def load_watchlist(filepath: str) -> list[str]:
    """Read ticker from watchlist.txt """
    watchlist = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                # Remove comments & whitespace
                line = line.split("#")[0].strip()
                if line:
                    watchlist.append(line.upper())
        log.info(f"Watchlist Load: Length of stock: {len(watchlist)}")
        return watchlist
    except FileNotFoundError:
        log.error(f"Cannot find {filepath}!")
        return []


# Step 1: Collect Stock Price Data
def fetch_stock_data(ticker: str) -> dict | None:
    """Calculate stock price data & tech indicators using 'yfinance'"""
    log.info(f"Collecting data for ticker: {ticker}")

    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")

        if df.empty or len(df) < 200:
            log.warning(f"Not enough data for ticker: {ticker} => (rows={len(df)})")
            return None

        # Technical Indicator Calculation 
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.bbands(length=20, std=2, append=True)
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.atr(length=14, append=True)
        df.ta.stoch(append=True)

        # Extract Recent Data
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # Support/Resistance Line Calculation
        highs = df["High"].rolling(window=10).max().dropna()
        lows = df["Low"].rolling(window=10).min().dropna()
        resistance_levels = sorted(highs.nlargest(5).unique().tolist(), reverse=True)[:3]
        support_levels = sorted(lows.nsmallest(5).unique().tolist())[:3]

        # Volume Analysis
        avg_volume_20 = df["Volume"].tail(20).mean()
        current_volume = latest["Volume"]
        volume_ratio = current_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0

        # Basic Info
        info = stock.info
        company_name = info.get("shortName", ticker)
        market_cap = info.get("marketCap", "N/A")
        sector = info.get("sector", "N/A")

        # Additional Price Data (Used by Claude for Fibonacci Analysis)
        high_120d = df["High"].tail(120)
        low_120d = df["Low"].tail(120)
        high_120d_max = high_120d.max()
        low_120d_min = low_120d.min()
        high_120d_date = high_120d.idxmax().strftime("%Y-%m-%d")
        low_120d_date = low_120d.idxmin().strftime("%Y-%m-%d")

        price_history_summary = {
            "120d_high": round(high_120d_max, 2),
            "120d_high_date": high_120d_date,
            "120d_low": round(low_120d_min, 2),
            "120d_low_date": low_120d_date,
            "60d_high": round(df["High"].tail(60).max(), 2),
            "60d_low": round(df["Low"].tail(60).min(), 2),
            "30d_high": round(df["High"].tail(30).max(), 2),
            "30d_low": round(df["Low"].tail(30).min(), 2),
        }

        # Recent 20 Days Price Data (Used by Claude for trend & support/resistance analysis)
        recent_20d = []
        for i in range(-20, 0):
            if i + len(df) >= 0:
                row = df.iloc[i]
                recent_20d.append({
                    "date": row.name.strftime("%m/%d"),
                    "open": round(row["Open"], 2),
                    "high": round(row["High"], 2),
                    "low": round(row["Low"], 2),
                    "close": round(row["Close"], 2),
                    "volume": int(row["Volume"]),
                })

        # Volume Profile Analysis — Total Trading Volume by Price Range
        price_min = df["Close"].tail(120).min()
        price_max = df["Close"].tail(120).max()
        price_range = price_max - price_min
        num_bins = 10

        volume_profile = []
        for i in range(num_bins):
            bin_low = price_min + (price_range / num_bins) * i
            bin_high = price_min + (price_range / num_bins) * (i + 1)
            
            # Total trading volume at this price range
            mask = (df["Close"].tail(120) >= bin_low) & (df["Close"].tail(120) < bin_high)
            bin_volume = df["Volume"].tail(120)[mask].sum()
            
            volume_profile.append({
                "price_range": f"${bin_low:.2f} - ${bin_high:.2f}",
                "volume": int(bin_volume),
                "is_current": bin_low <= latest["Close"] < bin_high
            })

        # Top 3 Volume Zones (Major Supply Zones)
        volume_profile_sorted = sorted(volume_profile, key=lambda x: x["volume"], reverse=True)
        top_volume_zones = volume_profile_sorted[:3]

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
            # Recent 5 Days Closing Price Trend
            "recent_closes": [round(c, 2) for c in df["Close"].tail(5).tolist()],
            # Additional Data for Fibonacci/Supply Zone Analysis
            "price_history_summary": price_history_summary,
            "recent_20d_ohlcv": recent_20d,
            "volume_profile": volume_profile,
            "top_volume_zones": top_volume_zones,
        }

        log.info(f"Ticker {ticker}: ${result['current_price']} (RSI={result['rsi_14']})")
        return result

    except Exception as e:
        log.error(f"Ticker {ticker}: Failed on Collecting Data: {e}")
        return None


# Language Specifc Prompt Templates
def get_analysis_prompt(stock_data: dict, language: str) -> str:
    """Generating Language Specific Prompt Templates"""
    ticker = stock_data["ticker"]

    # Convert the OHLCV data from the past 20 days into text.
    ohlcv_text = ""
    for day in stock_data["recent_20d_ohlcv"]:
        ohlcv_text += f"{day['date']} | ${day['open']} | ${day['high']} | ${day['low']} | ${day['close']} | {day['volume']:,}\n"

    if language == "ko":
        tech_summary = f"""
=== {stock_data['company_name']} ({ticker}) 기술적 분석 데이터 ===
섹터: {stock_data['sector']}
시가총액: {stock_data['market_cap']}

[가격 정보]
현재가: ${stock_data['current_price']}
전일 대비: {stock_data['daily_change_pct']}%
30일 최고: ${stock_data['price_history_summary']['30d_high']}
30일 최저: ${stock_data['price_history_summary']['30d_low']}
60일 최고: ${stock_data['price_history_summary']['60d_high']}
60일 최저: ${stock_data['price_history_summary']['60d_low']}
120일 최고: ${stock_data['price_history_summary']['120d_high']} ({stock_data['price_history_summary']['120d_high_date']})
120일 최저: ${stock_data['price_history_summary']['120d_low']} ({stock_data['price_history_summary']['120d_low_date']})
52주 최고: ${stock_data['high_52w']}
52주 최저: ${stock_data['low_52w']}

최근 5일 종가: {stock_data['recent_closes']}

[기술적 지표]
RSI(14): {stock_data['rsi_14']}
MACD: {stock_data['macd']} / Signal: {stock_data['macd_signal']} / Histogram: {stock_data['macd_hist']}
볼린저밴드: 상단 ${stock_data['bb_upper']} / 중간 ${stock_data['bb_middle']} / 하단 ${stock_data['bb_lower']}
SMA 20: ${stock_data['sma_20']} / SMA 50: ${stock_data['sma_50']} / SMA 200: ${stock_data['sma_200']}
ATR(14): ${stock_data['atr_14']}
Stochastic: K={stock_data['stoch_k']} / D={stock_data['stoch_d']}

[지지/저항선]
저항선: {stock_data['resistance_levels']}
지지선: {stock_data['support_levels']}

[매물대 분석 (Volume Profile) - 최근 120일]
주요 거래 집중 구간 (상위 3개):
- {stock_data['top_volume_zones'][0]['price_range']}: 거래량 {stock_data['top_volume_zones'][0]['volume']:,}
- {stock_data['top_volume_zones'][1]['price_range']}: 거래량 {stock_data['top_volume_zones'][1]['volume']:,}
- {stock_data['top_volume_zones'][2]['price_range']}: 거래량 {stock_data['top_volume_zones'][2]['volume']:,}

[거래량]
거래량 비율 (현재/20일 평균): {stock_data['volume_ratio']}x
20일 평균 거래량: {stock_data['avg_volume_20d']:,}

[최근 20일 OHLCV 데이터]
날짜 | 시가 | 고가 | 저가 | 종가 | 거래량
{ohlcv_text}
"""
        return f"""당신은 20년차 전문 주식 애널리스트이자 퀀트 트레이더입니다. 아래 기술적 분석 데이터를 바탕으로,
그리고 웹 검색을 통해 {ticker}의 최신 뉴스와 이슈를 조사하여 종합 분석 리포트를 작성하세요.

{tech_summary}

다음 형식으로 반드시 작성해주세요:

## 📰 최신 뉴스 & 이슈
- 최근 1주일 내 주요 뉴스 3~5개를 요약 (출처 포함)
- 실적 발표 일정, 애널리스트 의견, 산업 동향 등

## 📊 기술적 분석 요약
- 현재 추세 판단 (상승/하락/횡보)
- 주요 기술적 시그널 해석 (RSI, MACD, 볼린저밴드, MA, Stochastic)
- 거래량 분석

## 📐 피보나치 분석
- 위의 OHLCV 데이터를 바탕으로 현재 추세에 맞는 피보나치 되돌림 분석
- 상승 추세면: 최근 의미 있는 저점→고점 기준으로 되돌림 레벨 계산
- 하락 추세면: 최근 의미 있는 고점→저점 기준으로 되돌림 레벨 계산
- 각 피보나치 레벨(23.6%, 38.2%, 50%, 61.8%, 78.6%)의 가격과 현재가와의 관계 해석

## 📦 매물대 분석 (Volume Profile)
- 최근 20일 데이터를 바탕으로 거래량이 집중된 가격대 분석
- 주요 매물대가 지지/저항으로 작용할 가능성 해석

## 🎯 진입 타이밍 추천
각 진입 포인트는 구체적 가격과 근거를 제시하세요:
- **1차 진입 (공격적)**: 가격 $XX.XX — [근거]
- **2차 진입 (중립적)**: 가격 $XX.XX — [근거]
- **3차 진입 (보수적)**: 가격 $XX.XX — [근거]

## 🛑 손절 타이밍 추천
각 손절 포인트는 구체적 가격과 근거를 제시하세요:
- **1차 손절 (타이트)**: 가격 $XX.XX — [근거]
- **2차 손절 (중간)**: 가격 $XX.XX — [근거]
- **3차 손절 (와이드)**: 가격 $XX.XX — [근거]

## 💡 종합 의견
- 현재 진입 적합성 (매우적극 / 적극 / 중립 / 관망 / 위험)
- 단기(1주) / 중기(1개월) / 장기(3개월) 전망
- 리스크 요인

중요: 모든 가격은 현재가 ${stock_data['current_price']} 기준으로 현실적인 수치를 제시하세요.
기술적 지표, 피보나치, 매물대, 뉴스를 종합적으로 고려하여 판단하세요.
"""

    else:  # English
        ohlcv_text_en = ""
        for day in stock_data["recent_20d_ohlcv"]:
            ohlcv_text_en += f"{day['date']} | ${day['open']} | ${day['high']} | ${day['low']} | ${day['close']} | {day['volume']:,}\n"

        tech_summary = f"""
=== {stock_data['company_name']} ({ticker}) Technical Analysis Data ===
Sector: {stock_data['sector']}
Market Cap: {stock_data['market_cap']}

[Price Information]
Current Price: ${stock_data['current_price']}
Daily Change: {stock_data['daily_change_pct']}%
30-Day High: ${stock_data['price_history_summary']['30d_high']}
30-Day Low: ${stock_data['price_history_summary']['30d_low']}
60-Day High: ${stock_data['price_history_summary']['60d_high']}
60-Day Low: ${stock_data['price_history_summary']['60d_low']}
120-Day High: ${stock_data['price_history_summary']['120d_high']} ({stock_data['price_history_summary']['120d_high_date']})
120-Day Low: ${stock_data['price_history_summary']['120d_low']} ({stock_data['price_history_summary']['120d_low_date']})
52-Week High: ${stock_data['high_52w']}
52-Week Low: ${stock_data['low_52w']}
Recent 5-Day Closes: {stock_data['recent_closes']}

[Technical Indicators]
RSI(14): {stock_data['rsi_14']}
MACD: {stock_data['macd']} / Signal: {stock_data['macd_signal']} / Histogram: {stock_data['macd_hist']}
Bollinger Bands: Upper ${stock_data['bb_upper']} / Middle ${stock_data['bb_middle']} / Lower ${stock_data['bb_lower']}
SMA 20: ${stock_data['sma_20']} / SMA 50: ${stock_data['sma_50']} / SMA 200: ${stock_data['sma_200']}
ATR(14): ${stock_data['atr_14']}
Stochastic: K={stock_data['stoch_k']} / D={stock_data['stoch_d']}

[Support/Resistance]
Resistance Levels: {stock_data['resistance_levels']}
Support Levels: {stock_data['support_levels']}

[Volume Profile Analysis - Last 120 Days]
Key Trading Concentration Zones (Top 3):
- {stock_data['top_volume_zones'][0]['price_range']}: Volume {stock_data['top_volume_zones'][0]['volume']:,}
- {stock_data['top_volume_zones'][1]['price_range']}: Volume {stock_data['top_volume_zones'][1]['volume']:,}
- {stock_data['top_volume_zones'][2]['price_range']}: Volume {stock_data['top_volume_zones'][2]['volume']:,}

[Volume]
Volume Ratio (Current/20D Avg): {stock_data['volume_ratio']}x
20D Avg Volume: {stock_data['avg_volume_20d']:,}

[Recent 20-Day OHLCV Data]
Date | Open | High | Low | Close | Volume
{ohlcv_text_en}
"""
        return f"""You are a professional stock analyst and quantitative trader with 20 years of experience.
Based on the technical analysis data below and by searching the web for the latest news and issues about {ticker},
write a comprehensive analysis report.

{tech_summary}

Please write in the following format:

## 📰 Latest News & Issues
- Summarize 3-5 major news items from the past week (include sources)
- Earnings schedule, analyst opinions, industry trends, etc.

## 📊 Technical Analysis Summary
- Current trend assessment (Bullish/Bearish/Sideways)
- Key technical signal interpretation (RSI, MACD, Bollinger Bands, MA, Stochastic)
- Volume analysis

## 📐 Fibonacci Analysis
- Based on the OHLCV data above, perform Fibonacci retracement analysis aligned with the current trend
- For uptrend: Calculate retracement levels from recent significant low→high
- For downtrend: Calculate retracement levels from recent significant high→low
- Interpret each Fibonacci level (23.6%, 38.2%, 50%, 61.8%, 78.6%) price and its relationship to current price

## 📦 Volume Profile Analysis
- Analyze price zones with concentrated volume based on recent 20-day data
- Interpret how key volume zones may act as support/resistance

## 🎯 Entry Timing Recommendations
Provide specific prices and rationale for each entry point:
- **1st Entry (Aggressive)**: Price $XX.XX — [Rationale]
- **2nd Entry (Neutral)**: Price $XX.XX — [Rationale]
- **3rd Entry (Conservative)**: Price $XX.XX — [Rationale]

## 🛑 Stop-Loss Timing Recommendations
Provide specific prices and rationale for each stop-loss point:
- **1st Stop-Loss (Tight)**: Price $XX.XX — [Rationale]
- **2nd Stop-Loss (Medium)**: Price $XX.XX — [Rationale]
- **3rd Stop-Loss (Wide)**: Price $XX.XX — [Rationale]

## 💡 Overall Opinion
- Entry suitability (Very Bullish / Bullish / Neutral / Wait / Risky)
- Short-term (1 week) / Medium-term (1 month) / Long-term (3 months) outlook
- Risk factors

Important: All prices should be realistic based on current price ${stock_data['current_price']}.
Consider technical indicators, Fibonacci levels, volume profile, and news comprehensively.
"""


# Step 2: News + Analysis with the Claude API
def analyze_with_claude(stock_data: dict, max_retries: int = 5) -> str:
    """News Gathering (including web search) via Claude API + Entry/Stop-Loss Analysis"""
    ticker = stock_data["ticker"]
    log.info(f"{ticker}: Claude Analyzing ")

    client = anthropic.Anthropic()

    # Using Language-Specific Prompts
    prompt = get_analysis_prompt(stock_data, REPORT_LANGUAGE)

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=16000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract Text from the response
            analysis_text = ""
            for block in response.content:
                if block.type == "text":
                    analysis_text += block.text

            log.info(f"Complete Analyzing: {ticker} => ({len(analysis_text)} chars)")
            return analysis_text

        except Exception as e:
            if "401" in str(e) or "authentication" in str(e).lower():
                log.error(f"API key error for {ticker} — skipping retries: {e}")
                return f"Analysis Failed (API Key Error): Check the Key"

            if attempt < max_retries - 1:
                log.warning(f"Retry {attempt + 1}/{max_retries} for {ticker}")
                time.sleep(5)
            else:
                log.error(f"Failed on Analyzing [{ticker}]: {e}")
                return f"Analysis Failed: {e}" if REPORT_LANGUAGE == "ko" else f"Analysis failed: {e}"


# Step 3: Create HTML Email
def build_email_html(analyses: list[tuple[dict, str]]) -> str:
    """Convert analysis results into a visually appealing HTML email"""
    now = datetime.now(TZ)

    # Language-specific Dates and Text
    if REPORT_LANGUAGE == "ko":
        date_str = now.strftime("%Y년 %m월 %d일 %H:%M ET")
        header_title = "📈 일일 주식 분석 리포트"
        header_sub = f"{date_str} | 종목 {len(analyses)}개 분석"
        disclaimer = f"""
            ⚠️ 본 리포트는 AI 기반 자동 분석이며, 투자 권유가 아닙니다.<br>
            투자의 책임은 본인에게 있으며, 반드시 본인의 판단 하에 투자하세요.<br><br>
            <strong>분석 모델:</strong> Claude Opus 4 ({CLAUDE_MODEL})<br>
            Generated by Claude API + yfinance
        """
    else:
        date_str = now.strftime("%B %d, %Y %H:%M ET")
        header_title = "📈 Daily Stock Analysis Report"
        header_sub = f"{date_str} | {len(analyses)} stocks analyzed"
        disclaimer = f"""
            ⚠️ This report is AI-based automated analysis and is not investment advice.<br>
            Investment decisions are your own responsibility. Always use your own judgment.<br><br>
            <strong>Analysis Model:</strong> Claude Opus 4 ({CLAUDE_MODEL})<br>
            Generated by Claude API + yfinance
        """

    # Generate Cards for Each Event
    cards_html = ""
    for stock_data, analysis in analyses:
        ticker = stock_data["ticker"]
        price = stock_data["current_price"]
        change = stock_data["daily_change_pct"]
        change_color = "#22c55e" if change >= 0 else "#ef4444"
        change_arrow = "▲" if change >= 0 else "▼"

        # Markdown to Simple HTML Conversion
        analysis_html = analysis
        analysis_html = analysis_html.replace("## ", "<h3 style='color:#1e40af;margin-top:20px;margin-bottom:8px;border-bottom:2px solid #e5e7eb;padding-bottom:6px;'>")
        analysis_html = analysis_html.replace("\n## ", "</h3>\n<h3 style='color:#1e40af;margin-top:20px;margin-bottom:8px;border-bottom:2px solid #e5e7eb;padding-bottom:6px;'>")
        # Bold
        analysis_html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', analysis_html)
        # New Line
        analysis_html = analysis_html.replace("\n", "<br>")

        cards_html += f"""
        <div style="background:#ffffff;border-radius:12px;padding:24px;margin-bottom:24px;
                    box-shadow:0 1px 3px rgba(0,0,0,0.1);border:1px solid #e5e7eb;">
            <div style="display:flex;justify-content:space-between;align-items:center;
                        margin-bottom:16px;padding-bottom:12px;border-bottom:2px solid #f3f4f6;">
                <div>
                    <h2 style="margin:0;font-size:22px;color:#111827;">
                        {stock_data['company_name']}
                        <span style="color:#6b7280;font-weight:normal;">({ticker})</span>
                    </h2>
                    <span style="font-size:13px;color:#9ca3af;">{stock_data['sector']}</span>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:28px;font-weight:bold;color:#111827;">${price}</div>
                    <div style="font-size:15px;color:{change_color};font-weight:600;">
                        {change_arrow} {abs(change)}%
                    </div>
                </div>
            </div>
            <div style="font-size:14px;line-height:1.7;color:#374151;">
                {analysis_html}
            </div>
        </div>
        """

    # Email Template
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,
                 BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
        <div style="max-width:720px;margin:0 auto;padding:20px;">
            <!-- 헤더 -->
            <div style="background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);
                        border-radius:12px;padding:28px;margin-bottom:24px;text-align:center;">
                <h1 style="margin:0;color:#ffffff;font-size:24px;">
                    {header_title}
                </h1>
                <p style="margin:8px 0 0;color:#bfdbfe;font-size:14px;">
                    {header_sub}
                </p>
            </div>

            <!-- Stock Cards -->
            {cards_html}

            <!-- Disclaimer -->
            <div style="text-align:center;padding:20px;color:#9ca3af;font-size:11px;
                        border-top:1px solid #e5e7eb;margin-top:16px;">
                {disclaimer}
            </div>
        </div>
    </body>
    </html>
    """
    return html


# Step 4: Sending the Email
def send_email(html_content: str, watchlist: list[str]):
    """Send Email via Gmail SMTP"""
    sender = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("RECIPIENT_EMAIL")

    if not all([sender, password, recipient]):
        log.error("The Email Env hasn't been set")
        log.error("Check =>  GMAIL_ADDRESS, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL")
        return False

    now = datetime.now(TZ).strftime("%m/%d")

    # Language-Specific Title
    if REPORT_LANGUAGE == "ko":
        subject = f"📈 일일 주식 분석 리포트 ({now}) — {', '.join(watchlist)}"
    else:
        subject = f"📈 Daily Stock Report ({now}) — {', '.join(watchlist)}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        log.info(f"Email Sent! → {recipient}")
        return True
    except Exception as e:
        log.error(f"Failed to send Email: {e}")
        return False


# Main 
def main():
    # Load Watchlist
    watchlist = load_watchlist(WATCHLIST_FILE)
    if not watchlist:
        log.error("No Stock to Analyze!")
        return

    log.info("=" * 60)
    log.info(f"📈 Start Daily Analyze — {datetime.now(TZ).strftime('%Y-%m-%d %H:%M ET')}")
    log.info(f"   Stock: {', '.join(watchlist)}")
    log.info(f"   Language: {'한글' if REPORT_LANGUAGE == 'ko' else 'English'}")
    log.info("=" * 60)

    analyses = []

    for ticker in watchlist:
        # 1. Collect Stock Data
        stock_data = fetch_stock_data(ticker)
        if stock_data is None:
            continue

        # 2. Analyze via Claude
        analysis = analyze_with_claude(stock_data)

        analyses.append((stock_data, analysis))

        # To avoid Rate Limit
        if ticker != watchlist[-1]:
            log.info(f"Wait for 60s to avoid Rate Limit")
            time.sleep(60)

    if not analyses:
        log.error("No Data to Analyze")
        return

    # 3. Generate HTML Email
    html = build_email_html(analyses)

    # 4. Save HTML to local first
    output_filename = f"report_{datetime.now(TZ).strftime('%Y%m%d_%H%M')}.html"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"Report saved to {output_filename}")

    # 5. Email Sent
    send_email(html, watchlist)

    log.info("=" * 60)
    log.info("Everything Clear!")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
