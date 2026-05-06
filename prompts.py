"""
Prompt templates for Claude analysis.
Separated from logic so they can be edited without touching code.
"""


def build_tech_summary_ko(d: dict) -> str:
    """Build the Korean technical data block."""
    ohlcv = ""
    for day in d["recent_5d_ohlcv"]:
        ohlcv += f"{day['date']} | ${day['open']} | ${day['high']} | ${day['low']} | ${day['close']} | {day['volume']:,}\n"

    options = _format_options_ko(d.get("options_summary", {}))
    swings = _format_swings_ko(d.get("swing_candidates", []))
    nearest_sr = _format_nearest_sr_ko(d.get("nearest_resistance", []), d.get("nearest_support", []))
    vol_zones = _format_volume_zones_ko(d)

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

[지지/저항선 — 전체 기간 극값]
저항선: {d['resistance_levels']}
지지선: {d['support_levels']}

{nearest_sr}

{swings}

{vol_zones}

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
    swings = _format_swings_en(d.get("swing_candidates", []))
    nearest_sr = _format_nearest_sr_en(d.get("nearest_resistance", []), d.get("nearest_support", []))
    vol_zones = _format_volume_zones_en(d)

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

[Support/Resistance — Full-period Extremes]
Resistance: {d['resistance_levels']}
Support: {d['support_levels']}

{nearest_sr}

{swings}

{vol_zones}

[Volume]
Volume Ratio (Current/20D Avg): {d['volume_ratio']}x
20D Avg Volume: {d['avg_volume_20d']:,}

{options}

[Recent 5-Day OHLCV]
Date | Open | High | Low | Close | Volume
{ohlcv}"""


# Nearest S/R formatting

def _format_nearest_sr_ko(res_list, sup_list):
    res = ", ".join(f"${r['price']}" for r in res_list) if res_list else "N/A"
    sup = ", ".join(f"${s['price']}" for s in sup_list) if sup_list else "N/A"
    return f"""[현재가 기준 가까운 지지/저항 — 진입/손절 판단용]
가까운 저항 (위): {res}
가까운 지지 (아래): {sup}"""


def _format_nearest_sr_en(res_list, sup_list):
    res = ", ".join(f"${r['price']}" for r in res_list) if res_list else "N/A"
    sup = ", ".join(f"${s['price']}" for s in sup_list) if sup_list else "N/A"
    return f"""[Nearest S/R to Current Price — for entry/stop-loss]
Nearest Resistance (above): {res}
Nearest Support (below): {sup}"""


# Swing candidates formatting

def _format_swings_ko(swings):
    if not swings:
        return "[단기 스윙 후보 (20일)] 감지되지 않음"
    lines = []
    for s in swings:
        label = "고점" if s["type"] == "high" else "저점"
        lines.append(f"  {s['date']} ${s['price']} ({label})")
    return "[단기 스윙 후보 (20일) — 피보나치 기준점 참고용]\n" + "\n".join(lines)


def _format_swings_en(swings):
    if not swings:
        return "[Short-term Swing Candidates (20D)] None detected"
    lines = []
    for s in swings:
        lines.append(f"  {s['date']} ${s['price']} ({s['type']})")
    return "[Short-term Swing Candidates (20D) — Fibonacci reference]\n" + "\n".join(lines)


# Volume zones formatting

def _format_volume_zones_ko(d):
    top = d.get("top_volume_zones", [])
    cur = d.get("current_volume_zone")
    adj = d.get("adjacent_volume_zones", {})

    lines = ["[매물대 (Volume Profile) — 최근 120일]"]
    lines.append("상위 3개 매물대:")
    for z in top:
        lines.append(f"  {z['price_range']}: 거래량 {z['volume']:,}")

    if cur:
        lines.append(f"현재가 위치 매물대: {cur['price_range']} (거래량 {cur['volume']:,})")
    if adj.get("above"):
        lines.append(f"바로 위 매물대: {adj['above']['price_range']} (거래량 {adj['above']['volume']:,})")
    if adj.get("below"):
        lines.append(f"바로 아래 매물대: {adj['below']['price_range']} (거래량 {adj['below']['volume']:,})")

    return "\n".join(lines)


def _format_volume_zones_en(d):
    top = d.get("top_volume_zones", [])
    cur = d.get("current_volume_zone")
    adj = d.get("adjacent_volume_zones", {})

    lines = ["[Volume Profile — 120D]"]
    lines.append("Top 3 zones:")
    for z in top:
        lines.append(f"  {z['price_range']}: Vol {z['volume']:,}")

    if cur:
        lines.append(f"Current price zone: {cur['price_range']} (Vol {cur['volume']:,})")
    if adj.get("above"):
        lines.append(f"Zone above: {adj['above']['price_range']} (Vol {adj['above']['volume']:,})")
    if adj.get("below"):
        lines.append(f"Zone below: {adj['below']['price_range']} (Vol {adj['below']['volume']:,})")

    return "\n".join(lines)


# Options formatting

def _format_options_ko(opt: dict) -> str:
    if not opt.get("available"):
        return "[옵션 데이터] 사용 불가"

    lines = []
    for i, exp in enumerate(opt.get("expirations", [])):
        label = "가장 가까운 만기" if i == 0 else "다음 만기"
        calls = ", ".join(f"${c['strike']}(OI:{c['oi']:,})" for c in exp.get("top_call_oi_strikes", []))
        puts = ", ".join(f"${p['strike']}(OI:{p['oi']:,})" for p in exp.get("top_put_oi_strikes", []))
        hco = exp.get("highest_combined_oi_strike", "N/A")
        hco_str = f"${hco}" if hco else "N/A"

        lines.append(f"[옵션 데이터 — {label}: {exp['expiration']}]")
        lines.append(f"총 콜 OI: {exp['total_call_oi']:,} | 총 풋 OI: {exp['total_put_oi']:,}")
        lines.append(f"풋/콜 비율 (PCR): {exp['put_call_ratio']}")
        lines.append(f"콜+풋 합산 OI 최대 행사가: {hco_str} (주의: 실제 max pain 계산과는 다름)")
        lines.append(f"콜 OI 상위: {calls}")
        lines.append(f"풋 OI 상위: {puts}")
        lines.append("")

    return "\n".join(lines)


def _format_options_en(opt: dict) -> str:
    if not opt.get("available"):
        return "[Options Data] Not available"

    lines = []
    for i, exp in enumerate(opt.get("expirations", [])):
        label = "Nearest Expiry" if i == 0 else "Next Expiry"
        calls = ", ".join(f"${c['strike']}(OI:{c['oi']:,})" for c in exp.get("top_call_oi_strikes", []))
        puts = ", ".join(f"${p['strike']}(OI:{p['oi']:,})" for p in exp.get("top_put_oi_strikes", []))
        hco = exp.get("highest_combined_oi_strike", "N/A")
        hco_str = f"${hco}" if hco else "N/A"

        lines.append(f"[Options — {label}: {exp['expiration']}]")
        lines.append(f"Total Call OI: {exp['total_call_oi']:,} | Total Put OI: {exp['total_put_oi']:,}")
        lines.append(f"Put/Call Ratio (PCR): {exp['put_call_ratio']}")
        lines.append(f"Highest Combined OI Strike: {hco_str} (Note: NOT true max pain calculation)")
        lines.append(f"Top Call OI: {calls}")
        lines.append(f"Top Put OI: {puts}")
        lines.append("")

    return "\n".join(lines)


# Full prompt builders

def get_analysis_prompt(stock_data: dict, language: str) -> str:
    """Build the full prompt: data → analysis rules → output format."""
    ticker = stock_data["ticker"]
    price = stock_data["current_price"]

    if language == "ko":
        tech = build_tech_summary_ko(stock_data)
        return f"""당신은 20년차 전문 주식 애널리스트이자 퀀트 트레이더입니다. 아래 기술적 분석 데이터를 바탕으로,
그리고 웹 검색을 통해 {ticker}의 최신 뉴스와 이슈를 조사하여 종합 분석 리포트를 작성하세요.
또한 웹 검색으로 {ticker}의 공매도 잔고(Short Interest), 공매도 비율(SI % of Float)도 조사하세요.

{tech}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📏 분석 규칙 (반드시 준수)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 출처와 기준일이 없는 최신 데이터는 반드시 N/A로 표기하세요. 추정하지 마세요.
- 가격 추천(진입/손절)은 반드시 위에 제공된 데이터와 현재가 ${price} 기준으로 하세요.
- 각 섹션은 핵심 근거 중심으로 간결하게 작성하세요. 장황한 설명보다 근거 있는 짧은 판단이 낫습니다.
- "콜+풋 합산 OI 최대 행사가"는 실제 max pain 계산이 아닙니다. 과대해석하지 마세요.
- 피보나치 분석 시 "단기 스윙 후보"와 "30/60/120일 고저점"을 참고하여 현재 추세에 맞는 유의미한 기준점을 직접 판단하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 출력 형식 (아래 형식으로 작성)
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

## 📰 최신 뉴스 & 이슈
- 최근 1주일 내 주요 뉴스 3~5개 요약 (출처, 날짜 포함)

## 📊 기술적 분석 요약
- 현재 추세, 주요 시그널 해석, 거래량 분석

## 📐 피보나치 분석
- 단기 스윙 후보와 중기 고저점을 참고하여 유의미한 기준점을 직접 판단
- 피보나치 되돌림 레벨과 현재가의 관계 해석

## 📦 매물대 분석 (Volume Profile)
- 거래량 집중 가격대, 현재가 위치 매물대, 위/아래 매물대 해석

## 🔍 수급 & 유동성 분석
- 공매도 잔고(SI)와 비율 (웹 검색, 출처/기준일 필수, 없으면 N/A)
- 옵션 OI: 콜+풋 합산 OI 최대 행사가, 풋/콜 비율
- 콜/풋 OI 집중 행사가 → 마켓메이커 헤지 방향 추정
- Liquidity Sweep(스탑헌팅) 위험 가격대
- Short Squeeze 가능성

## 🎯 진입 타이밍 (상세 근거)

## 🛑 손절 타이밍 (상세 근거)

## 💡 종합 의견

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 기계 판독용 요약 (반드시 마지막에 출력)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
분석 마지막에 아래 형식의 JSON 블록을 반드시 출력하세요.
값은 위 분석 내용에서 추출하세요. 가격은 숫자만, 방향은 bullish/bearish/neutral 중 하나.

```json
{{
  "ticker": "{ticker}",
  "current_price": {price},
  "entry_suitability": "매우적극/적극/중립/관망/위험 중 하나",
  "direction": "bullish/bearish/neutral 중 하나",
  "entry_prices": [1차진입가, 2차진입가, 3차진입가],
  "stop_prices": [1차손절가, 2차손절가, 3차손절가],
  "outlook_short": "단기 전망 한 줄",
  "outlook_mid": "중기 전망 한 줄",
  "outlook_long": "장기 전망 한 줄",
  "key_reasons": ["핵심 근거 1", "핵심 근거 2", "핵심 근거 3"]
}}
```
"""

    else:
        tech = build_tech_summary_en(stock_data)
        return f"""You are a professional stock analyst and quantitative trader with 20 years of experience.
Based on the data below and by searching the web for {ticker}'s latest news, short interest data, and issues,
write a comprehensive analysis report.

{tech}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📏 Analysis Rules (MUST follow)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Any latest data without a source and date MUST be marked N/A. Do not estimate.
- All price recommendations (entry/stop-loss) must be based on the data above and current price ${price}.
- Write each section concisely, focusing on key rationale. Short, evidence-based judgment > long explanations.
- "Highest Combined OI Strike" is NOT a true max pain calculation. Do not over-interpret it.
- For Fibonacci: use the short-term swing candidates and 30/60/120D highs/lows to identify meaningful swing points yourself.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 Output Format
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

## 📰 Latest News & Issues
- 3-5 major news items from the past week (with sources, dates)

## 📊 Technical Analysis Summary
- Trend, key signal interpretation, volume analysis

## 📐 Fibonacci Analysis
- Use swing candidates and mid-term highs/lows to identify meaningful reference points
- Calculate and interpret retracement levels vs current price

## 📦 Volume Profile Analysis
- High-volume zones, current price zone, above/below zones

## 🔍 Positioning & Liquidity Analysis
- Short Interest (SI) and SI % of Float (web search, source/date required, else N/A)
- Options OI: highest combined OI strike, put/call ratio
- Call/Put OI concentration → market maker hedging direction
- Liquidity Sweep (stop-hunt) risk zones
- Short Squeeze probability

## 🎯 Entry Timing (Detailed)

## 🛑 Stop-Loss Timing (Detailed)

## 💡 Overall Opinion

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 Machine-Readable Summary (MUST output at the very end)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
At the end of your analysis, output a JSON block in exactly this format.
Extract values from your analysis above. Prices as numbers only, direction as bullish/bearish/neutral.

```json
{{
  "ticker": "{ticker}",
  "current_price": {price},
  "entry_suitability": "one of: highly aggressive/aggressive/neutral/watch & wait/risky",
  "direction": "bullish/bearish/neutral",
  "entry_prices": [1st_entry, 2nd_entry, 3rd_entry],
  "stop_prices": [1st_stop, 2nd_stop, 3rd_stop],
  "outlook_short": "one line short-term outlook",
  "outlook_mid": "one line mid-term outlook",
  "outlook_long": "one line long-term outlook",
  "key_reasons": ["reason 1", "reason 2", "reason 3"]
}}
```
"""