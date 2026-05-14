# Stock Alert

Daily stock analysis pipeline for a personal watchlist.

The system collects market data, sends a fast rule-based Discord market-open snapshot, asks Claude for a detailed analysis, sends a full email report, saves a machine-readable JSON summary, optionally sends a detailed Discord digest, optionally compares direction with Polymarket, and keeps the JSON history needed for later live backtesting.

> This is an analysis and journaling tool, not financial advice.

---

## Current Pipeline

```text
cron-job.org or manual workflow_dispatch
    |
    v
GitHub Actions
    |
    v
stock_report.py
    |
    +-- market_calendar.py       skip non-trading days
    +-- watchlist.txt            load tickers + optional profile metadata
    +-- data_fetcher.py          yfinance price, indicators, options data
    +-- analyzer.py/prompts.py   Claude detailed report + JSON block
    +-- email_builder.py         full HTML email
    +-- email_sender.py          Gmail SMTP
    +-- summary_builder.py       report_summaries/YYYY-MM-DD.json
    +-- discord_notifier.py      fast snapshot + compact Discord digest
    +-- polymarket_client.py     optional market direction check
    +-- usage_tracker.py         usage_log.json
```

The daily GitHub Action commits:

- `usage_log.json`
- `report_summaries/`

That means the saved JSON summaries remain in the repository and can later be used by `backtester.py`.

`backtest_results/` is ignored by Git and is not committed by the daily workflow. Backtest result files are local/manual output unless you intentionally change that policy.

---

## Features

- Detailed email report with news, technicals, options/liquidity, entries, stops, and rationale.
- Machine-readable JSON summary per ticker for automation and backtesting.
- Fast Discord market-open snapshot for early technical bias.
- Detailed Discord morning digest for mobile review after Claude finishes.
- Optional Polymarket direction comparison.
- API usage and monthly cost tracking.
- NYSE holiday/weekend skip logic.
- Live walk-forward backtest using actual saved Claude recommendations.
- Proxy backtest using fixed technical rules without Claude API calls.

---

## Project Structure

```text
Stock_Alert/
├── stock_report.py              # Main daily orchestrator
├── config.py                    # Model, timezone, feature flags
├── watchlist.txt                # Tickers with optional profile/theme metadata
├── watchlist_parser.py          # Backward-compatible watchlist parser
├── data_fetcher.py              # yfinance data and indicators
├── market_calendar.py           # NYSE open/closed check
├── analyzer.py                  # Claude API call
├── prompts.py                   # Korean/English prompt templates
├── investment_profiles.py       # Profile-based horizons and risk settings
├── portfolio_monitor.py         # Portfolio concentration warnings
├── email_builder.py             # HTML report generation
├── email_sender.py              # Gmail SMTP
├── summary_builder.py           # Extracts Claude JSON summary
├── discord_notifier.py          # Discord webhook digest
├── polymarket_client.py         # Optional Polymarket direction check
├── backtester.py                # Live walk-forward backtest
├── proxy_backtest.py            # Fixed-rule proxy backtest
├── usage_tracker.py             # Token/cost tracking
├── report_summaries/            # Daily JSON summaries, committed by CI
├── backtest_results/            # Manual backtest outputs
├── .github/workflows/
│   └── daily_stock_report.yml   # Manual/external-trigger daily report
├── architecture.md              # System design notes
└── README.md
```

---

## Feature Flags

Edit `config.py`:

```python
ENABLE_EMAIL_REPORT = True       # Full HTML email
ENABLE_SUMMARY_JSON = True       # Required for Discord/backtesting history
ENABLE_DISCORD_DIGEST = True     # Compact Discord digest
ENABLE_DISCORD_OPEN_SNAPSHOT = True  # Fast rule-based Discord snapshot before Claude
ENABLE_POLYMARKET = True         # Optional prediction-market comparison
ENABLE_POLYMARKET_CLAUDE_REVIEW = True   # Optional second-pass Claude review
ENABLE_BACKTEST_EXPORT = False   # Reserved; backtests are currently manual
REQUIRE_REGULAR_MARKET_SESSION = True    # Skip reports outside regular NYSE hours
WAIT_FOR_REGULAR_SESSION_ON_PREMARKET = True  # Let early triggers wait for the open
REGULAR_SESSION_START_DELAY_MINUTES = 15  # Wait until 9:45 ET on normal NYSE days
MAX_PREMARKET_WAIT_MINUTES = 50           # Bounded wait for accidental early triggers
MAX_LIVE_PRICE_AGE_MINUTES = 20          # Stale-price cutoff during regular session
SKIP_STALE_LIVE_PRICES = True            # Skip ticker alerts when live price is stale
```

Recommended defaults:

- Keep `ENABLE_SUMMARY_JSON = True` so GitHub Actions accumulates backtestable history.
- Set `ENABLE_POLYMARKET = False` if matching quality is not good enough for your watchlist.
- Set `ENABLE_POLYMARKET_CLAUDE_REVIEW = False` if you want to avoid extra Claude calls.
- Use Discord flags only after adding `DISCORD_WEBHOOK_URL`.
- Keep `ENABLE_DISCORD_OPEN_SNAPSHOT = True` if you want the 9:45-ish rule-based opening bias before the slower Claude report.
- The fast Discord snapshot sends before Claude. The detailed Discord digest sends before the detailed email. If email arrives but Discord does not, check the GitHub Actions log for missing/invalid `DISCORD_WEBHOOK_URL` or Discord webhook HTTP errors.

---

## Setup

### 1. Required Secrets

Add these in GitHub repository settings under `Secrets and variables -> Actions`:

```text
ANTHROPIC_API_KEY
GMAIL_ADDRESS
GMAIL_APP_PASSWORD
RECIPIENT_EMAIL
```

Optional:

```text
DISCORD_WEBHOOK_URL
```

### 2. GitHub Actions Permission

The workflow needs repository write access because it commits `usage_log.json` and `report_summaries/`.

The workflow declares:

```yaml
permissions:
  contents: write
```

If repository-level workflow permissions are restricted, set Actions to allow read/write permissions in GitHub settings.

### 3. Watchlist

Edit `watchlist.txt`:

```text
# ticker  profile          themes
MSFT      core_theme       ai_infrastructure,software_platform
VST       core_theme       ai_infrastructure,energy
OKLO      high_vol_swing   ai_infrastructure,nuclear
CORZ      high_vol_swing   ai_infrastructure,compute
AVAV      growth_theme     defense_ai
```

The first column is always the ticker. The second column is optional investment profile, and the third column is optional comma-separated theme tags. Simple one-ticker rows still work:

```text
IREN
```

If metadata is omitted, the system falls back to `high_vol_swing` and no theme tags. Supported profile names are defined in `investment_profiles.py`; aliases such as `high_vol` map to `high_vol_swing`.

Profile metadata affects three places:

- Proxy backtest holding window, cooldown, stop ATR multiple, and target R multiple.
- Live backtest holding window and target R multiple for saved summaries.
- Claude prompt context and portfolio concentration warnings.

### 4. Local Environment

On Windows in this workspace, the plain `python.exe` may be a WindowsApps stub. The verified local command is:

```powershell
uv run --python 3.12 --with-requirements requirements.txt python stock_report.py
```

If your normal Python install is on PATH, this also works:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python stock_report.py
```

---

## Daily Run

The workflow is manual by default:

```yaml
on:
  workflow_dispatch:
```

For precise daily timing, use cron-job.org to call GitHub's workflow dispatch endpoint during regular NYSE hours, preferably after the open such as 9:45 AM America/New_York on trading days. If cron-job.org fires shortly before the open, `stock_report.py` can now wait until the regular-session data target, currently 9:45 AM ET on normal NYSE days, before fetching live prices. It still exits on holidays, after-hours runs, and premarket runs that are earlier than `MAX_PREMARKET_WAIT_MINUTES`.

---

## Fast Discord Snapshot

When `ENABLE_DISCORD_OPEN_SNAPSHOT = True`, `stock_report.py` first fetches lightweight ticker data, sends a fast `[FAST] Market Open Snapshot` to Discord, then continues into the full data fetch, Claude analysis, Polymarket enrichment, JSON persistence, the detailed Discord digest, and email.

The fast snapshot is rule-based and uses current price, day move, 20/50DMA position, RSI, MACD histogram, volume ratio, and price freshness. It skips slower company metadata and options-chain enrichment so it can arrive much closer to the open. It is an opening technical bias, not the final Claude recommendation.

The Discord message begins with this score guide:

```text
+3 이상: bullish bias
+1~+2: mildly bullish
0 근처: mixed / neutral
-1~-2: mildly bearish
-3 이하: bearish bias
```

---

## Price Freshness

Alerts are anchored to a separate live price snapshot, not just the final row of one-year daily history.

Current behavior:

- Daily indicators use explicit `1d` unadjusted OHLCV from yfinance.
- The alert anchor price first tries a timestamped `1m` yfinance bar from the latest regular session.
- During the regular session, the price must be no older than `MAX_LIVE_PRICE_AGE_MINUTES`.
- If a regular-session quote is stale and `SKIP_STALE_LIVE_PRICES = True`, that ticker is skipped instead of being labeled as current.
- Saved JSON, Claude prompts, Discord, and email include `price_source`, `price_as_of`, `price_status`, `market_session`, and any `price_warning`.

Important limitation: yfinance/Yahoo is not an exchange-certified real-time feed. For broker-grade live trading alerts, replace the price snapshot with a paid or broker-backed quote source.

---

## JSON Summary Persistence

Every successful daily run with `ENABLE_SUMMARY_JSON = True` creates:

```text
report_summaries/YYYY-MM-DD.json
```

The GitHub Action stages and commits that folder:

```bash
git add usage_log.json || true
git add report_summaries/ || true
git diff --staged --quiet || git commit -m "Update logs $(date +%Y-%m-%d)"
git push
```

This is the historical dataset for `backtester.py`.

---

## Backtesting

### Live Walk-Forward Backtest

Question: did Claude's actual saved recommendations work?

```powershell
uv run --python 3.12 --with-requirements requirements.txt python backtester.py --days 30
```

Uses `report_summaries/*.json`, then checks later OHLC price action.

Signal semantics:

- `bullish` is evaluated as a long trade candidate using Claude's saved entry and stop prices.
- `bearish` is evaluated as long avoidance / risk warning, not as a short trade.
- `neutral`, missing entries, and parse failures are skipped for executable trade metrics.

Bullish live targets are no longer a fixed percent. The target is derived from the saved stop distance and ticker profile:

```text
target = entry + (entry - stop) * target_r_multiple
R = entry - stop
```

Bearish avoidance metrics answer a different question: did staying out avoid a loss, or did it miss upside?

Benchmark and risk context:

- Each evaluation includes same-window `SPY` and `QQQ` returns when yfinance has data.
- Long trades include `excess_vs_benchmark_pct`, which is trade P&L minus benchmark return.
- Bearish avoidance includes `ticker_vs_benchmark_pct`; negative values mean the avoided ticker underperformed that benchmark.
- Long trades include a `risk` object with `risk_pct_to_stop`, `target_pct`, and `target_r_multiple`.
- Bullish entries with missing stops or stops at/above entry are stored as `invalid_risk` / `no_risk_defined` and excluded from risk-managed long metrics.
- Live benchmark returns are cached by date window during a run to avoid repeated SPY/QQQ yfinance calls.

Important detail: if stop and target both touch inside the same daily candle, the trade is marked:

```text
ambiguous_same_day
```

The result uses a conservative stop exit price, but the ambiguity is counted separately.

### Proxy Backtest

Question: are the fixed technical rules we feed Claude historically useful?

```powershell
uv run --python 3.12 --with-requirements requirements.txt python proxy_backtest.py MSFT --years 2
uv run --python 3.12 --with-requirements requirements.txt python proxy_backtest.py ALL
```

Do not tune proxy rules after looking at results unless you explicitly start a new validation split. Otherwise the test becomes overfit.

Proxy backtest cleanup:

- Repeated signals now use a cooldown equal to the profile holding window, so one trend stretch is not counted as a fresh trade every day.
- `bullish` signals are evaluated as long trades with ATR-based stops and targets.
- `bearish` signals are evaluated as long avoidance / risk warning, not short trades.
- Proxy uses profile-based horizons from `watchlist.txt` metadata and `investment_profiles.py` definitions: core theme names use longer windows, while high-volatility swing names use shorter windows.
- The proxy target is now R-multiple based: `target = entry + (entry - stop) * target_r_multiple`.
- Proxy long trades also store `atr_14` and risk fields, including `atr_to_stop`.
- Proxy metrics include average long excess return versus SPY/QQQ and bearish underperformance rates versus SPY/QQQ when benchmark data is available.
- Avoidance metrics include both absolute success (`avoided_return_pct > 0`) and benchmark-relative success by SPY/QQQ underperformance.

---

## Polymarket Notes

Polymarket is controlled by feature flags and can be disabled at any time.

The client now tries to infer whether a YES price is bullish or bearish from the question wording:

- `above`, `over`, `higher`, `rise`, `gain` -> bullish YES
- `below`, `under`, `fall`, `drop`, `decline` -> bearish YES
- unclear wording -> `unknown`

Treat this as a secondary sanity check, not a trading signal.

If `ENABLE_POLYMARKET_CLAUDE_REVIEW = True`, the pipeline uses a second Claude call after the original analysis:

```text
1. Claude writes the normal independent stock analysis.
2. Polymarket searches for a related market.
3. Claude reviews only the Polymarket result and decides whether it should strengthen, weaken, ignore, or leave unchanged the original view.
```

This second pass does not rewrite the full email analysis and does not change entry/stop prices. It adds `polymarket_claude_review` to the saved JSON summary, shows a separate post-review box in the email, and, when Discord is enabled, shows the adjustment in the digest. The call is skipped when the market is unavailable, directionally unclear, neutral, or below the liquidity threshold.

---

## Cost

Expected daily cost is mostly Claude API usage. yfinance, Gmail SMTP, GitHub Actions, Discord webhook, cron-job.org, and Polymarket read-only queries are free for this use case.

For the current 9-stock watchlist using the default Sonnet model, the rough target is:

```text
Daily:   about $0.70-$1.10 before optional Polymarket Claude reviews
Monthly: about $16-$23 on trading days before optional Polymarket Claude reviews
```

Cost scales roughly linearly with ticker count. Watchlist metadata itself is local config and does not add meaningful token usage.

Each run updates `usage_log.json`.

Usage tracking separates primary stock analysis calls from optional second-pass calls:

- `analysis`: the full Claude report for a ticker
- `polymarket_review`: the no-web-search second-pass review of a Polymarket signal

The total cost includes both, while `tickers_analyzed` counts only primary stock analyses.

---

## Verification

Syntax verification used for this project:

```powershell
uv run --python 3.12 --with-requirements requirements.txt python -m py_compile stock_report.py backtester.py data_fetcher.py summary_builder.py discord_notifier.py polymarket_client.py proxy_backtest.py watchlist_parser.py investment_profiles.py portfolio_monitor.py prompts.py
```

Targeted checks should cover:

- summary JSON parse failure produces `summary_parse_status = failed`
- Polymarket below/under questions invert YES into bearish
- live/proxy backtests mark same-day stop/target hits as `ambiguous_same_day`
- bearish backtest signals are evaluated as long avoidance, not short P&L
- proxy cooldown and ATR target parameters are present in saved metrics
- live/proxy benchmark metrics calculate SPY/QQQ comparison fields without changing trade outcomes
- risk structure fields are present on long-trade evaluations
- watchlist metadata is parsed correctly for both simple ticker rows and ticker/profile/theme rows
- proxy/live profiles are applied before looking at results and are stored in saved backtest JSON
- Discord field values are truncated to avoid webhook rejection from Discord payload limits

---

## Known Design Choices

- Daily CI commits summary JSON, not backtest result JSON.
- Backtests are manual so the daily report stays fast and predictable.
- `ENABLE_BACKTEST_EXPORT` is currently reserved and not wired into the daily orchestrator.
- `ENABLE_POLYMARKET_CLAUDE_REVIEW` adds optional second-pass confidence review but does not rewrite the original recommendation.
- Live alerts require regular NYSE prices by default. Short premarket dispatches can wait for the open, while holidays, after-hours runs, and very early triggers still exit.
- yfinance price snapshots include freshness metadata but are still not broker-grade real-time quotes.
- Daily OHLC data cannot prove intraday ordering, so ambiguous same-day outcomes are explicitly labeled.
- Backtests separate executable long-trade metrics from bearish long-avoidance metrics.
- Proxy backtest uses fixed rules with cooldown and ATR targets; changing those after seeing results creates overfitting risk.
- Live backtest treats missing/invalid stops as recommendation-quality errors, not unmanaged 5-day buy-and-hold trades.
- Investment profiles are class-level assumptions, not ticker-by-ticker backtest tuning knobs. Ticker-to-profile assignment belongs in `watchlist.txt` because it reflects portfolio intent.
