# 📈 Daily Stock Analysis Report System

Automatically analyzes your watchlist stocks with **news collection + technical chart analysis + entry/stop-loss recommendations** and sends a daily email report.

---

## Features

- **News Collection**: Automatically collects latest news via Claude API web search
- **Technical Analysis**: RSI, MACD, Bollinger Bands, MA, Stochastic, Support/Resistance
- **Fibonacci Analysis**: Claude identifies trends and calculates meaningful Fibonacci levels
- **Volume Profile**: Analyzes price zones with concentrated trading volume
- **Entry/Stop-Loss Recommendations**: Provides 1st, 2nd, 3rd entry and stop-loss prices
- **Multi-language Support**: Choose between Korean/English reports

---


## 🏗️ Architecture

```
Watchlist (Your Stocklist)
    ↓
① Collect price data & technical indicators via yfinance
    ↓
② Comprehensive analysis via Claude API (Opus 4 + web search)
    ↓
③ Generate HTML email
    ↓
④ Send via Gmail SMTP
    ↓
⑤ Auto-run daily at 9 AM via GitHub Actions
```

## 🚀 Setup

### Step 1: Prepare API Keys

| Item | How to Get |
|------|-----------|
| **Anthropic API Key** | [console.anthropic.com](https://console.anthropic.com) Sign up & Create API Key |
| **Gmail App Password** | Google Account → Security → 2-Step Verification → App Passwords |

### Step 2: GitHub Repository Setup

1. Create a new private repository on GitHub
2. Push this project files
3. Go to Settings → Secrets and variables → Actions and add: 
    - ANTHROPIC_API_KEY
    - GMAIL_ADDRESS
    - GMAIL_APP_PASSWORD
    - RECIPIENT_EMAIL   

### Step 3: Edit Your Watchlist

Edit `watchlist.txt` to add your stocks (one ticker per line)


### Step 4: Language Setting (Optional)

Change report language in `stock_report.py`:

```python
# "ko" (Korean, default) or "en" (English)
REPORT_LANGUAGE = "en"
```

### Step 5: Local Testing (Optional)

- Create virtual environment
```python
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

- Install dependencies
```python
pip install -r requirements.txt
```

- Create .env file
```python
cp env.example .env
# Edit .env with your actual values
```

- Runㅇ
```python
python stock_report.py
```

## 📁 Project Structure

```
Stock_Alert/
├── stock_report.py              # Main script
├── watchlist.txt                # Your stock tickers
├── requirements.txt             # Python dependencies
├── .env                         # Environment variables (gitignored)
├── .github/
│   └── workflows/
│       └── daily_stock_report.yml  # GitHub Actions schedule
└── README.md

```

## 💰 Cost

| Item | Cost |
|------|------|
| GitHub Actions | Free (2,000min/month) |
| yfinance | Free |
| Gmail SMTP | Free |
| Claude API | ~$0.05-0.15 per stock (with web search) |
| **Daily Total (5 Stocks)** | **~$0.25-0.75** |

