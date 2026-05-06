# Stock Alert

Daily stock analysis pipeline for a personal watchlist.

The system collects market data, asks Claude for a detailed analysis, sends a full email report, saves a machine-readable JSON summary, optionally sends a Discord digest, optionally compares direction with Polymarket, and keeps the JSON history needed for later live backtesting.

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
    +-- watchlist.txt            load tickers
    +-- data_fetcher.py          yfinance price, indicators, options data
    +-- analyzer.py/prompts.py   Claude detailed report + JSON block
    +-- email_builder.py         full HTML email
    +-- email_sender.py          Gmail SMTP
    +-- summary_builder.py       report_summaries/YYYY-MM-DD.json
    +-- discord_notifier.py      compact Discord digest
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
- Discord morning digest for fast mobile review.
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
├── watchlist.txt                # One ticker per line
├── data_fetcher.py              # yfinance data and indicators
├── market_calendar.py           # NYSE open/closed check
├── analyzer.py                  # Claude API call
├── prompts.py                   # Korean/English prompt templates
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
ENABLE_POLYMARKET = True         # Optional prediction-market comparison
ENABLE_POLYMARKET_CLAUDE_REVIEW = True   # Optional second-pass Claude review
ENABLE_BACKTEST_EXPORT = False   # Reserved; backtests are currently manual
```

Recommended defaults:

- Keep `ENABLE_SUMMARY_JSON = True` so GitHub Actions accumulates backtestable history.
- Set `ENABLE_POLYMARKET = False` if matching quality is not good enough for your watchlist.
- Set `ENABLE_POLYMARKET_CLAUDE_REVIEW = False` if you want to avoid extra Claude calls.
- Use `ENABLE_DISCORD_DIGEST = True` only after adding `DISCORD_WEBHOOK_URL`.

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
MSFT
NVDA
TSLA
```

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

For precise daily timing, use cron-job.org to call GitHub's workflow dispatch endpoint at 9:00 AM America/New_York on trading days. `stock_report.py` still checks the NYSE calendar, so a mistaken trigger on a holiday exits without sending a report.

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

Bullish live targets are no longer a fixed percent. The target is derived from the saved stop distance:

```text
target = entry + 2R
R = entry - stop
```

Bearish avoidance metrics answer a different question: did staying out avoid a loss, or did it miss upside?

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

- Repeated signals now use a cooldown equal to `HOLDING_DAYS`, so one trend stretch is not counted as a fresh trade every day.
- `bullish` signals are evaluated as long trades with ATR-based stops and targets.
- `bearish` signals are evaluated as long avoidance / risk warning, not short trades.
- The proxy target is now `entry + ATR * 2.0` for bullish trades instead of a fixed 3% target.

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

For a 5-stock watchlist using the default Sonnet model, the rough target is:

```text
Daily:   about $0.40-$0.60 before optional Polymarket Claude reviews
Monthly: about $9-$13 on trading days before optional Polymarket Claude reviews
```

Each run updates `usage_log.json`.

Usage tracking separates primary stock analysis calls from optional second-pass calls:

- `analysis`: the full Claude report for a ticker
- `polymarket_review`: the no-web-search second-pass review of a Polymarket signal

The total cost includes both, while `tickers_analyzed` counts only primary stock analyses.

---

## Verification

Syntax verification used for this project:

```powershell
uv run --python 3.12 --with-requirements requirements.txt python -m py_compile stock_report.py backtester.py summary_builder.py discord_notifier.py polymarket_client.py proxy_backtest.py
```

Targeted checks should cover:

- summary JSON parse failure produces `summary_parse_status = failed`
- Polymarket below/under questions invert YES into bearish
- live/proxy backtests mark same-day stop/target hits as `ambiguous_same_day`
- bearish backtest signals are evaluated as long avoidance, not short P&L
- proxy cooldown and ATR target parameters are present in saved metrics

---

## Known Design Choices

- Daily CI commits summary JSON, not backtest result JSON.
- Backtests are manual so the daily report stays fast and predictable.
- `ENABLE_BACKTEST_EXPORT` is currently reserved and not wired into the daily orchestrator.
- `ENABLE_POLYMARKET_CLAUDE_REVIEW` adds optional second-pass confidence review but does not rewrite the original recommendation.
- Daily OHLC data cannot prove intraday ordering, so ambiguous same-day outcomes are explicitly labeled.
- Backtests separate executable long-trade metrics from bearish long-avoidance metrics.
- Proxy backtest uses fixed rules with cooldown and ATR targets; changing those after seeing results creates overfitting risk.
