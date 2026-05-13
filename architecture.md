# 📈 Stock Alert — Project Architecture

## System Overview

매일 아침 관심 종목을 자동 분석하고, 진입/손절 추천을 이메일 + Discord로 보내고,
예측시장 대조와 성과 검증까지 하는 end-to-end 주식 분석 시스템.

```
┌─────────────────────────────────────────────────────────────────┐
│                    cron-job.org (9:00 AM ET)                     │
│                    External trigger → GitHub Actions             │
└────────────────────────────┬────────────────────────────────────┘
                             │ workflow_dispatch
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     stock_report.py (Orchestrator)               │
│                                                                  │
│  Step 0: 휴장일 체크 (market_calendar.py)                        │
│  Step 1: watchlist.txt 로드                                      │
│  Step 2: 종목별 데이터 수집 + Claude 분석                         │
│  Step 3: report_summary.json 생성 + Polymarket 대조              │
│  Step 4: portfolio concentration 경고                            │
│  Step 5: JSON 저장 + Discord 요약 알림                            │
│  Step 6: API 사용량 추적                                         │
│  Step 7: HTML 이메일 생성                                        │
│  Step 8: Gmail 발송                                              │
└─────────────────────────────────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         📧 Email       💬 Discord    📋 JSON Summary
       (상세 리포트)    (아침 요약)    (데이터 축적)
                                           │
                              ┌─────────────┤
                              ▼             ▼
                       📊 Live Backtest   📊 Proxy Backtest
                       (backtester.py)    (proxy_backtest.py)
                       Phase 5a           Phase 5b
                       실전 검증           규칙 유효성 검증
```

---

## File Structure

```
Stock_Alert/
│
├── stock_report.py          # 메인 오케스트레이터 (~170줄)
├── config.py                # 모델, 설정, feature flags
├── watchlist.txt            # 관심 종목 + 선택적 profile/theme 메타데이터
├── watchlist_parser.py      # ticker/profile/theme 파서
│
├── ── 데이터 수집 ──
├── data_fetcher.py          # yfinance 가격/지표/옵션 수집
├── market_calendar.py       # NYSE 휴장일 체크
│
├── ── Claude 분석 ──
├── analyzer.py              # Claude API 호출 (web search 포함)
├── prompts.py               # 프롬프트 템플릿 (한국어/영어)
├── investment_profiles.py   # 투자 프로파일별 horizon/risk 설정
├── portfolio_monitor.py     # 포트폴리오 방향/테마 집중 경고
│
├── ── 출력 채널 ──
├── email_builder.py         # HTML 이메일 생성
├── email_sender.py          # Gmail SMTP 발송
├── discord_notifier.py      # Discord webhook 알림 (Phase 2)
├── summary_builder.py       # report_summary.json 생성 (Phase 1)
│
├── ── 검증 ──
├── polymarket_client.py     # Polymarket 방향성 대조 (Phase 3)
├── backtester.py            # Live walk-forward 백테스트 (Phase 5a)
├── proxy_backtest.py        # Proxy 규칙 백테스트 (Phase 5b)
│
├── ── 추적 ──
├── usage_tracker.py         # API 토큰/비용 추적
├── usage_log.json           # 월간 비용 누적 (자동 생성)
├── report_summaries/        # 일일 JSON 요약 (자동 생성, git commit)
├── backtest_results/        # 백테스트 결과 (자동 생성)
│
├── ── 인프라 ──
├── requirements.txt
├── .env / .env.example
├── .gitignore
├── README.md
├── CLAUDE.md                # Claude Code 작업 규칙
├── tasks/todo.md            # 프로젝트 할일
│
└── .github/workflows/
    ├── daily_stock_report.yml  # 매일 리포트 (외부 트리거)
    └── check_dst.yml           # DST 자동 조정
```

---

## Data Flow

```
watchlist.txt
    │
    ▼
┌──────────────────┐
│ watchlist_parser │
│ - ticker         │
│ - profile        │
│ - themes         │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐    ┌──────────────────┐
│  data_fetcher.py │    │   yfinance API   │
│  - 가격/지표     │◄───│   (무료)         │
│  - 옵션 OI       │    └──────────────────┘
│  - 스윙 후보     │
│  - 지지/저항     │
│  - 매물대        │
└────────┬─────────┘
         │ stock_data dict
         ▼
┌──────────────────┐    ┌──────────────────┐
│   analyzer.py    │───▶│  Claude API      │
│   prompts.py     │    │  + web search    │
│                  │◄───│  (Sonnet 4.6)    │
└────────┬─────────┘    └──────────────────┘
         │ analysis_text (markdown + JSON block)
         │
         ├───▶ email_builder.py ───▶ 📧 Gmail (상세 리포트)
         │
         ├───▶ summary_builder.py ───▶ 📋 report_summaries/YYYY-MM-DD.json
         │                                    │
         │                                    ├───▶ discord_notifier.py ───▶ 💬 Discord
         │                                    │
         │                                    ├───▶ polymarket_client.py ───▶ 🔮 방향 대조
         │                                    │
         │                                    └───▶ backtester.py ───▶ 📊 성과 검증
         │
         └───▶ usage_tracker.py ───▶ 💰 비용 추적
```

---

## Feature Flags (config.py)

```python
ENABLE_EMAIL_REPORT = True       # 📧 이메일 리포트
ENABLE_SUMMARY_JSON = True       # 📋 JSON 요약 저장 (다른 기능의 기반)
ENABLE_DISCORD_DIGEST = True     # 💬 Discord 아침 요약
ENABLE_POLYMARKET = True         # 🔮 Polymarket 방향 대조
ENABLE_POLYMARKET_CLAUDE_REVIEW = True   # 🔎 Claude 2차 관련성/확신도 검토
ENABLE_BACKTEST_EXPORT = False   # 📊 백테스트 데이터 export
REQUIRE_REGULAR_MARKET_SESSION = True    # 정규장 밖 라이브 가격 알림 스킵
MAX_LIVE_PRICE_AGE_MINUTES = 20          # 정규장 가격 스냅샷 stale 기준
SKIP_STALE_LIVE_PRICES = True            # stale 가격이면 티커 알림 스킵
```

**의존성 관계:**
- Discord, Polymarket, Backtest 모두 `ENABLE_SUMMARY_JSON = True`가 전제
- 각 기능은 독립적으로 on/off 가능
- Polymarket은 관련 시장이 없으면 자동 N/A
- Polymarket Claude review는 원본 분석을 다시 쓰지 않고 JSON에 `polymarket_claude_review`만 추가
- usage_tracker는 `analysis`와 `polymarket_review` 호출을 구분해서 총 비용에 합산

### Price Freshness Guardrail

- `stock_report.py` checks actual NYSE session state, not only whether today is a trading day.
- `data_fetcher.py` uses daily unadjusted OHLCV for indicators and a separate timestamped 1-minute yfinance snapshot as the alert anchor price.
- The alert path stores and displays `price_source`, `price_as_of`, `price_status`, `market_session`, and stale-price warnings.
- yfinance remains a delayed/free data source, so this is freshness validation rather than broker-grade real-time market data.

---

## Phase 구현 현황

| Phase | 기능 | 파일 | 상태 | API 비용 |
|-------|------|------|------|----------|
| 0 | 기본 리포트 (분석 + 이메일) | stock_report.py 외 | ✅ 운영중 | ~$0.50/일 |
| 1 | report_summary.json 저장 | summary_builder.py | ✅ 완료 | $0 추가 |
| 2 | Discord 아침 요약 | discord_notifier.py | ✅ 완료 | $0 |
| 3 | Polymarket 방향 대조 | polymarket_client.py | ✅ 완료 | $0 (공개 API) |
| 3b | Polymarket Claude 2차 검토 | analyzer.py / prompts.py | ✅ 완료 | 조건부 Claude 비용 |
| 5a | Live walk-forward 백테스트 | backtester.py | ✅ 완료 | $0 |
| 5b | Proxy 규칙 백테스트 | proxy_backtest.py | ✅ 완료 | $0 |

---

## 비용 구조

| 항목 | 일일 비용 | 월간 비용 |
|------|-----------|-----------|
| Claude API (Sonnet 4.6, 현재 9종목) | ~$0.70-1.10 | ~$16-23 |
| GitHub Actions | 무료 | 무료 |
| yfinance | 무료 | 무료 |
| Gmail SMTP | 무료 | 무료 |
| Discord webhook | 무료 | 무료 |
| Polymarket API | 무료 | 무료 |
| cron-job.org | 무료 | 무료 |
| Backtest (yfinance only) | 무료 | 무료 |
| **총계** | **~$0.90** | **~$20** |

---

## 백테스트 전략

### Live Walk-Forward (Phase 5a) — `backtester.py`
- **질문:** "Claude 추천이 실제로 먹혔나?"
- **방법:** 매일 저장된 JSON의 진입/손절가 vs 이후 실제 가격
- **실행:** `python backtester.py` (데이터 쌓인 후)
- **지표:** Win rate, Profit Factor, R-Multiple, MFE, MDD
- **의미:** `bullish`만 롱 트레이드로 평가하고, `bearish`는 숏이 아니라 롱 회피/위험 경고로 평가
- **프로파일:** 저장 summary의 `investment_profile` 또는 현재 `watchlist.txt` metadata로 holding window와 target R을 결정
- **타겟:** bullish live target은 고정 3%가 아니라 `entry + (entry - stop) * target_r_multiple`
- **벤치마크:** 같은 평가 창의 SPY/QQQ 수익률을 붙여 long excess return과 bearish underperformance를 확인
- **리스크:** 롱 평가에는 stop까지의 위험률, target 수익률, target R-multiple을 저장
- **무효 리스크:** stop이 없거나 entry 이상이면 `invalid_risk`/`no_risk_defined`로 분리하고 long 성과 지표에서 제외
- **성능:** live benchmark 수익률은 날짜 창 기준으로 캐시하여 반복 yfinance 호출을 줄임

### Proxy Walk-Forward (Phase 5b) — `proxy_backtest.py`
- **질문:** "Claude에게 주는 기술지표 조합이 유효한가?"
- **방법:** 규칙을 고정하고 과거 데이터를 walk-forward
- **실행:** `python proxy_backtest.py MSFT --years 2`
- **주의:** 규칙을 결과 보고 조정하면 overfitting. FIXED RULES 유지
- **쿨다운:** 한 추세 구간이 매일 독립 신호로 중복 집계되지 않도록 profile holding window만큼 cooldown 적용
- **프로파일:** `watchlist.txt`의 종목별 metadata와 `investment_profiles.py`의 class-level profile 정의로 holding window와 target R을 결정
- **타겟:** bullish proxy target은 고정 3%가 아니라 `entry + (entry - stop) * target_r_multiple`
- **벤치마크/리스크:** SPY/QQQ excess/underperformance와 ATR 기반 risk structure를 함께 저장
- **회피 평가:** bearish avoidance는 절대수익률 기준 성공률과 SPY/QQQ 대비 underperformance 기준 성공률을 함께 제공

### Portfolio Concentration — `portfolio_monitor.py`
- **질문:** "현재 5개 종목이 같은 메가트렌드/방향으로 과도하게 몰려 있나?"
- **방법:** 요약 JSON의 direction과 ticker theme tag를 집계
- **출력:** Discord digest와 저장 JSON에 direction crowding / theme concentration warning 추가
- **해석:** 수익률 상관계수 계산이 아니라 daily risk awareness용 1차 경고

---

## 셋업 가이드

### 필수 환경변수
```
ANTHROPIC_API_KEY=sk-ant-...
GMAIL_ADDRESS=your@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
RECIPIENT_EMAIL=your@gmail.com
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

### Discord Webhook 설정
1. Discord 서버 → 채널 설정 → 연동 → 웹후크
2. 새 웹후크 만들기 → URL 복사
3. GitHub Secrets에 `DISCORD_WEBHOOK_URL` 추가

### 실행 순서
```bash
# 1. 일일 리포트 (매일 자동, 수동 테스트도 가능)
python stock_report.py

# 2. Proxy 백테스트 (언제든 실행 가능)
python proxy_backtest.py MSFT --years 2
python proxy_backtest.py ALL

# 3. Live 백테스트 (JSON 쌓인 후)
python backtester.py --days 30
```
