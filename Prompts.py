"""
Prompt templates for Claude analysis.
Separated from logic so they can be edited without touching code.
"""


def build_tech_summary_ko(d: dict) -> str:
    """Build the Korean technical data block that gets inserted into the prompt."""
    ohlcv = ""
    for day in d["recent_5d_ohlcv"]:
        ohlcv += f"{day['date']} | ${day['open']} | ${day['high']} | ${day['low']} | ${day['close']} | {day['volume']:,}\n"

    options = _format_options_ko(d.get("options_summary", {}))

    return f"""
=== {d['company_name']} ({d['ticker']}) 기술적 분석 데이터 ===
섹터: {d['sector']}
시가총액: {d['market_cap']}

[가격 정보]
현재가: ${d['current_price']}
전일 대비: {d['daily_change_pct']}%
30일 최고/최저: ${d['price_history_summary']['30d_high']} / ${d['price_history_summary']['30d_low']}
60일 최고/최저: ${d['price_history_summary']['60d_high']} / ${d['price_history_summary']['60d_low']}
120일 최고: ${d['price_history_summary']['120d_high']} ({d['price_history_summary']['120d_high_date']})
120일 최저: ${d['price_history_summary']['120d_low']} ({d['price_history_summary']['120d_low_date']})
52주 최고/최저: ${d['high_52w']} / ${d['low_52w']}
최근 5일 종가: {d['recent_closes']}

[기술적 지표]
RSI(14): {d['rsi_14']}
MACD: {d['macd']} / Signal: {d['macd_signal']} / Hist: {d['macd_hist']}
볼린저밴드: 상단 ${d['bb_upper']} / 중간 ${d['bb_middle']} / 하단 ${d['bb_lower']}
SMA 20/50/200: ${d['sma_20']} / ${d['sma_50']} / ${d['sma_200']}
ATR(14): ${d['atr_14']}
Stochastic: K={d['stoch_k']} / D={d['stoch_d']}

[지지/저항선]
저항선: {d['resistance_levels']}
지지선: {d['support_levels']}

[매물대 (Volume Profile) - 최근 120일 상위 3개]
- {d['top_volume_zones'][0]['price_range']}: 거래량 {d['top_volume_zones'][0]['volume']:,}
- {d['top_volume_zones'][1]['price_range']}: 거래량 {d['top_volume_zones'][1]['volume']:,}
- {d['top_volume_zones'][2]['price_range']}: 거래량 {d['top_volume_zones'][2]['volume']:,}

[거래량]
거래량 비율 (현재/20일 평균): {d['volume_ratio']}x
20일 평균 거래량: {d['avg_volume_20d']:,}

{options}

[최근 5일 OHLCV]
날짜 | 시가 | 고가 | 저가 | 종가 | 거래량
{ohlcv}"""


def build_tech_summary_en(d: dict) -> str:
    """Build the English technical data block."""
    ohlcv = ""
    for day in d["recent_5d_ohlcv"]:
        ohlcv += f"{day['date']} | ${day['open']} | ${day['high']} | ${day['low']} | ${day['close']} | {day['volume']:,}\n"

    options = _format_options_en(d.get("options_summary", {}))

    return f"""
=== {d['company_name']} ({d['ticker']}) Technical Analysis Data ===
Sector: {d['sector']}
Market Cap: {d['market_cap']}

[Price Information]
Current: ${d['current_price']} | Daily Change: {d['daily_change_pct']}%
30D High/Low: ${d['price_history_summary']['30d_high']} / ${d['price_history_summary']['30d_low']}
60D High/Low: ${d['price_history_summary']['60d_high']} / ${d['price_history_summary']['60d_low']}
120D High: ${d['price_history_summary']['120d_high']} ({d['price_history_summary']['120d_high_date']})
120D Low: ${d['price_history_summary']['120d_low']} ({d['price_history_summary']['120d_low_date']})
52W High/Low: ${d['high_52w']} / ${d['low_52w']}
Recent 5D Closes: {d['recent_closes']}

[Technical Indicators]
RSI(14): {d['rsi_14']}
MACD: {d['macd']} / Signal: {d['macd_signal']} / Hist: {d['macd_hist']}
Bollinger: Upper ${d['bb_upper']} / Mid ${d['bb_middle']} / Lower ${d['bb_lower']}
SMA 20/50/200: ${d['sma_20']} / ${d['sma_50']} / ${d['sma_200']}
ATR(14): ${d['atr_14']}
Stochastic: K={d['stoch_k']} / D={d['stoch_d']}

[Support/Resistance]
Resistance: {d['resistance_levels']}
Support: {d['support_levels']}

[Volume Profile - Top 3 zones (120D)]
- {d['top_volume_zones'][0]['price_range']}: Vol {d['top_volume_zones'][0]['volume']:,}
- {d['top_volume_zones'][1]['price_range']}: Vol {d['top_volume_zones'][1]['volume']:,}
- {d['top_volume_zones'][2]['price_range']}: Vol {d['top_volume_zones'][2]['volume']:,}

[Volume]
Volume Ratio (Current/20D Avg): {d['volume_ratio']}x
20D Avg Volume: {d['avg_volume_20d']:,}

{options}

[Recent 5-Day OHLCV]
Date | Open | High | Low | Close | Volume
{ohlcv}"""


# ─── Options formatting helpers ──────────────────────────────────

def _format_options_ko(opt: dict) -> str:
    if not opt.get("available"):
        return "[옵션 데이터] 사용 불가"

    calls = ", ".join(f"${c['strike']}(OI:{c['oi']:,})" for c in opt.get("top_call_oi_strikes", []))
    puts = ", ".join(f"${p['strike']}(OI:{p['oi']:,})" for p in opt.get("top_put_oi_strikes", []))

    return f"""[옵션 데이터 — 가장 가까운 만기: {opt['nearest_expiration']}]
총 콜 OI: {opt['total_call_oi']:,} | 총 풋 OI: {opt['total_put_oi']:,}
풋/콜 비율 (PCR): {opt['put_call_ratio']}
Max Pain 추정: ${opt['max_pain_strike']}
콜 OI 상위 행사가: {calls}
풋 OI 상위 행사가: {puts}"""


def _format_options_en(opt: dict) -> str:
    if not opt.get("available"):
        return "[Options Data] Not available"

    calls = ", ".join(f"${c['strike']}(OI:{c['oi']:,})" for c in opt.get("top_call_oi_strikes", []))
    puts = ", ".join(f"${p['strike']}(OI:{p['oi']:,})" for p in opt.get("top_put_oi_strikes", []))

    return f"""[Options Data — Nearest Expiry: {opt['nearest_expiration']}]
Total Call OI: {opt['total_call_oi']:,} | Total Put OI: {opt['total_put_oi']:,}
Put/Call Ratio (PCR): {opt['put_call_ratio']}
Max Pain Estimate: ${opt['max_pain_strike']}
Top Call OI Strikes: {calls}
Top Put OI Strikes: {puts}"""


# ─── Full prompt builders ────────────────────────────────────────

def get_analysis_prompt(stock_data: dict, language: str) -> str:
    """Build the full prompt for Claude analysis."""
    ticker = stock_data["ticker"]
    price = stock_data["current_price"]

    if language == "ko":
        tech = build_tech_summary_ko(stock_data)
        return f"""당신은 20년차 전문 주식 애널리스트이자 퀀트 트레이더입니다. 아래 기술적 분석 데이터를 바탕으로,
그리고 웹 검색을 통해 {ticker}의 최신 뉴스와 이슈를 조사하여 종합 분석 리포트를 작성하세요.
또한 웹 검색으로 {ticker}의 공매도 잔고(Short Interest), 공매도 비율(SI % of Float)도 조사하세요.

{tech}

다음 형식으로 반드시 작성해주세요:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ 핵심 요약 (이 섹션을 가장 먼저, 반드시 작성)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ⚡ 핵심 액션 요약

**현재 진입 적합성: [매우적극 / 적극 / 중립 / 관망 / 위험]**

### 🎯 진입 타이밍
| 구분 | 가격 | 근거 (한 줄) |
|------|------|-------------|
| 1차 진입 (공격적) | $XX.XX | [핵심 근거] |
| 2차 진입 (중립적) | $XX.XX | [핵심 근거] |
| 3차 진입 (보수적) | $XX.XX | [핵심 근거] |

### 🛑 손절 타이밍
| 구분 | 가격 | 근거 (한 줄) |
|------|------|-------------|
| 1차 손절 (타이트) | $XX.XX | [핵심 근거] |
| 2차 손절 (중간) | $XX.XX | [핵심 근거] |
| 3차 손절 (와이드) | $XX.XX | [핵심 근거] |

### 📅 전망
- 단기(1주):
- 중기(1개월):
- 장기(3개월):

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 상세 분석
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📰 최신 뉴스 & 이슈
- 최근 1주일 내 주요 뉴스 3~5개 요약 (출처 포함)
- 실적 발표 일정, 애널리스트 의견, 산업 동향

## 📊 기술적 분석 요약
- 현재 추세 (상승/하락/횡보)
- 주요 시그널 해석 (RSI, MACD, 볼린저밴드, MA, Stochastic)
- 거래량 분석

## 📐 피보나치 분석
- 위의 가격 데이터(30d/60d/120d 고저, 지지/저항선 등)를 바탕으로 현재 추세에 맞는 유의미한 스윙 고점과 저점을 직접 판단하세요
- 해당 구간의 피보나치 되돌림 레벨(23.6%, 38.2%, 50%, 61.8%, 78.6%)을 계산하고 현재가와의 관계를 해석하세요

## 📦 매물대 분석 (Volume Profile)
- 거래량 집중 가격대와 지지/저항 역할 해석

## 🔍 수급 & 유동성 분석
- 공매도 잔고(SI)와 공매도 비율 (웹 검색 결과 기반)
- 옵션 OI 분석: Max Pain(${stock_data['options_summary'].get('max_pain_strike', 'N/A')}), 풋/콜 비율({stock_data['options_summary'].get('put_call_ratio', 'N/A')})
- 콜/풋 OI 집중 행사가 → 마켓메이커 헤지 방향 추정
- Liquidity Sweep(스탑헌팅) 가능성이 높은 가격대
- Short Squeeze 가능성 평가

## 🎯 진입 타이밍 추천 (상세)
각 진입 포인트의 구체적 가격과 상세 근거

## 🛑 손절 타이밍 추천 (상세)
각 손절 포인트의 구체적 가격과 상세 근거

## 💡 종합 의견
- 진입 적합성, 단기/중기/장기 전망, 리스크 요인

중요: 모든 가격은 현재가 ${price} 기준으로 현실적인 수치를 제시하세요.
"""

    else:  # English
        tech = build_tech_summary_en(stock_data)
        return f"""You are a professional stock analyst and quantitative trader with 20 years of experience.
Based on the data below and by searching the web for {ticker}'s latest news, short interest data, and issues,
write a comprehensive analysis report.

{tech}

Write in the following format:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ Executive Summary (write this section FIRST — mandatory)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ⚡ Key Action Summary

**Current Entry Suitability: [Highly Aggressive / Aggressive / Neutral / Watch & Wait / Risky]**

### 🎯 Entry Timing
| Category | Price | Rationale (One Line) |
|------|------|-------------|
| 1st Entry (Aggressive) | $XX.XX | [Key Rationale] |
| 2nd Entry (Neutral) | $XX.XX | [Key Rationale] |
| 3rd Entry (Conservative) | $XX.XX | [Key Rationale] |

### 🛑 Stop-Loss Timing
| Category | Price | Rationale (One Line) |
|------|------|-------------|
| 1st Stop-Loss (Tight) | $XX.XX | [Key Rationale] |
| 2nd Stop-Loss (Intermediate) | $XX.XX | [Key Rationale] |
| 3rd Stop-Loss (Wide) | $XX.XX | [Key Rationale] |

### 📅 Outlook
- Short-Term (1 Week):
- Mid-Term (1 Month):
- Long-Term (3 Months):

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 Detailed Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📰 Latest News & Issues
- 3-5 major news items from the past week (with sources)
- Earnings schedule, analyst opinions, industry trends

## 📊 Technical Analysis Summary
- Trend assessment (Bullish/Bearish/Sideways)
- Key signal interpretation (RSI, MACD, Bollinger, MA, Stochastic)
- Volume analysis

## 📐 Fibonacci Analysis
- Using the price data above (30d/60d/120d highs/lows, support/resistance), identify the most meaningful swing high and swing low for the current trend
- Calculate Fibonacci retracement levels (23.6%, 38.2%, 50%, 61.8%, 78.6%) and interpret their relationship to the current price

## 📦 Volume Profile Analysis
- High-volume price zones as support/resistance

## 🔍 Positioning & Liquidity Analysis
- Short Interest (SI) and SI % of Float (from web search)
- Options OI: Max Pain (${stock_data['options_summary'].get('max_pain_strike', 'N/A')}), Put/Call Ratio ({stock_data['options_summary'].get('put_call_ratio', 'N/A')})
- Call/Put OI concentration → market maker hedging direction
- Liquidity Sweep (stop-hunt) risk zones
- Short Squeeze probability assessment

## 🎯 Entry Timing (Detailed)
Specific prices with detailed rationale

## 🛑 Stop-Loss Timing (Detailed)
Specific prices with detailed rationale

## 💡 Overall Opinion
- Entry suitability, short/mid/long-term outlook, risk factors

Important: All prices must be realistic based on current price ${price}.
"""