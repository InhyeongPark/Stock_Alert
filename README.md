# 📈 Daily Stock Analysis Report System

Automatically analyzes your watchlist stocks with **news collection + technical chart analysis + options/liquidity analysis + entry/stop-loss recommendations** and sends a daily email report.

---

## Features

- **News Collection**: Collects latest news via Claude API web search
- **Technical Analysis**: RSI, MACD, Bollinger Bands, SMA (20/50/200), Stochastic, ATR, Support/Resistance
- **Fibonacci Analysis**: Auto-calculated retracement levels fed to Claude for interpretation
- **Volume Profile**: Identifies price zones with concentrated trading volume (120-day)
- **Options & Liquidity Analysis**: Options OI, Max Pain, Put/Call Ratio, Short Interest (via web search), Liquidity Sweep risk assessment
- **Entry/Stop-Loss Recommendations**: 1st, 2nd, 3rd entry and stop-loss prices with rationale
- **API Cost Tracking**: Per-ticker and monthly cumulative cost displayed in every email
- **Market Holiday Detection**: Automatically skips weekends and NYSE holidays
- **Multi-language Support**: Korean (default) or English reports

---

## 🏗️ Architecture

```
Watchlist (Watchlist.txt)
    ↓
⓪ Check if NYSE is open today (skip holidays)
    ↓
① Collect price data, technical indicators & options chain via yfinance
    ↓
② Analyze via Claude API (Sonnet 4.6 + web search)
   — News, short interest, technical + options + liquidity sweep analysis
    ↓
③ Generate HTML email with usage cost summary
    ↓
④ Send via Gmail SMTP
    ↓
⑤ Auto-run daily at 9 AM ET via cron-job.org → GitHub Actions
```

---

## 📁 Project Structure

```
Stock_Alert/
├── stock_report.py              # Main orchestrator (~100 lines)
├── config.py                   # Models, pricing, settings (single source of truth)
├── data_fetcher.py              # yfinance data collection + options chain
├── analyzer.py                 # Claude API call (no internal retry)
├── prompts.py                  # Prompt templates (Korean & English)
├── email_builder.py             # HTML generation + markdown conversion
├── email_sender.py              # Gmail SMTP
├── usage_tracker.py             # Token/cost tracking + monthly persistence
├── market_calendar.py           # NYSE holiday detection
├── watchlist.txt               # Your stock tickers (one per line)
├── usage_log.json              # Monthly cost log (auto-generated, committed by CI)
├── requirements.txt            # Python dependencies
├── .env                        # Environment variables (gitignored)
├── .github/
│   └── workflows/
│       ├── daily_stock_report.yml  # Daily report (triggered externally)
│       └── check_dst.yml           # Weekly DST check
├── OldCodes/                # Old Codes
└── README.md
```

---

## 🚀 Setup

### Step 1: Prepare API Keys

| Item | How to Get |
|------|-----------|
| **Anthropic API Key** | [console.anthropic.com](https://console.anthropic.com) → Sign up → API Keys |
| **Gmail App Password** | Google Account → Security → 2-Step Verification → App Passwords |

### Step 2: GitHub Repository Setup

1. Create a new **private** repository on GitHub
2. Push all project files
3. Go to **Settings → Secrets and variables → Actions** and add these 4 secrets:
   - `ANTHROPIC_API_KEY`
   - `GMAIL_ADDRESS`
   - `GMAIL_APP_PASSWORD`
   - `RECIPIENT_EMAIL`

### Step 3: Edit Your Watchlist

Edit `Watchlist.txt` — one ticker per line, `#` for comments:

```
MSFT    # Microsoft
NVDA    # NVIDIA
TSLA    # Tesla
```

### Step 4: Choose Your Model (Optional)

Edit `config.py` to change the Claude model:

```python
# Recommended (best price/performance)
CLAUDE_MODEL = "claude-sonnet-4-6"          # $3/$15 per MTok

# Highest quality (costs ~3x more)
# CLAUDE_MODEL = "claude-opus-4-7"          # $5/$25 per MTok

# Cheapest
# CLAUDE_MODEL = "claude-haiku-4-5-20251001" # $1/$5 per MTok
```

### Step 5: Language Setting (Optional)

In `config.py`:

```python
REPORT_LANGUAGE = "ko"   # "ko" (Korean, default) or "en" (English)
```

### Step 6: Set Up External Trigger (cron-job.org)

GitHub Actions' built-in cron is unreliable (15–60 min delays). Use [cron-job.org](https://cron-job.org) (free) for precise timing:

1. Create a free account at cron-job.org
2. Create a **GitHub Personal Access Token** (Fine-grained, Actions: Read & Write)
3. Create a cron job with these settings:

| Setting | Value |
|---------|-------|
| URL | `https://api.github.com/repos/YOUR_USERNAME/Stock_Alert/actions/workflows/daily_stock_report.yml/dispatches` |
| Schedule | Weekdays 9:00 AM |
| Time Zone | `America/New_York` |
| Method | POST |
| Request Body | `{"ref": "main"}` |

**Headers:**

| Key | Value |
|-----|-------|
| Accept | `application/vnd.github.v3+json` |
| Authorization | `Bearer YOUR_GITHUB_PAT` |
| Content-Type | `application/json` |

> **Note:** cron-job.org handles DST automatically when set to `America/New_York`, so the `check_dst.yml` workflow serves as a backup safety net.

### Step 7: Local Testing (Optional)

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your actual values

# Run
python stock_report.py
```

---

## 🕐 Scheduling & DST

| Method | How It Works |
|--------|-------------|
| **cron-job.org (primary)** | Set timezone to `America/New_York` → auto-handles DST |
| **check_dst.yml (backup)** | Runs weekly to adjust GitHub Actions cron if still enabled |
| **Market holiday check** | `market_calendar.py` skips NYSE holidays automatically |

---

## 💰 Cost

### API Pricing (per million tokens)

| Model | Input | Output | Recommended For |
|-------|-------|--------|-----------------|
| Sonnet 4.6 | $3.00 | $15.00 | Daily reports (default) |
| Opus 4.7 | $5.00 | $25.00 | Highest analysis quality |
| Haiku 4.5 | $1.00 | $5.00 | Budget / high volume |

### Estimated Daily Cost (Sonnet 4.6, 5 stocks)

| Item | Cost |
|------|------|
| GitHub Actions | Free (2,000 min/month) |
| yfinance | Free |
| Gmail SMTP | Free |
| cron-job.org | Free |
| Claude API | ~$0.08–0.12 per stock |
| **Daily Total** | **~$0.40–0.60** |
| **Monthly Total (~22 trading days)** | **~$9–13** |

> Every email includes a cost breakdown table showing per-ticker token usage and monthly cumulative spend.