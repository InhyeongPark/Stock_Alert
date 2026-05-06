"""
Phase 2: Sends a compact stock digest to Discord via webhook.

Each ticker gets a color-coded embed with:
  - Direction + entry suitability
  - Entry prices (1st/2nd/3rd)
  - Stop-loss prices (1st/2nd/3rd)
  - Key reasons (1-2 lines)

Designed for quick morning review on mobile.
"""

import json
import logging
import os
from datetime import datetime

import urllib.request
import urllib.error

from config import TZ

log = logging.getLogger(__name__)

# Color mapping for Discord embeds
DIRECTION_COLORS = {
    "bullish": 0x22C55E,       # green
    "bearish": 0xEF4444,       # red
    "neutral": 0xF59E0B,       # yellow
    "unknown": 0x6B7280,       # gray
}

SUITABILITY_EMOJI = {
    "매우적극": "🟢🟢",
    "적극": "🟢",
    "중립": "🟡",
    "관망": "🟠",
    "위험": "🔴",
    "highly aggressive": "🟢🟢",
    "aggressive": "🟢",
    "neutral": "🟡",
    "watch & wait": "🟠",
    "risky": "🔴",
    "unknown": "❓",
}


def send_discord_digest(summaries: list[dict]) -> bool:
    """Send all ticker summaries as Discord embeds via webhook."""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        log.error("❌ DISCORD_WEBHOOK_URL not set")
        return False

    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d %H:%M ET")

    embeds = []
    for s in summaries:
        embed = _build_embed(s)
        if embed:
            embeds.append(embed)

    if not embeds:
        log.warning("No embeds to send")
        return False

    # Discord allows max 10 embeds per message
    payload = {
        "content": f"📈 **일일 주식 분석 요약** — {date_str}",
        "embeds": embeds[:10],
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            if resp.status in (200, 204):
                log.info(f"✅ Discord digest sent ({len(embeds)} tickers)")
                return True
            else:
                log.error(f"❌ Discord returned status {resp.status}")
                return False
    except urllib.error.HTTPError as e:
        log.error(f"❌ Discord webhook failed: {e.code} — {e.read().decode()}")
        return False
    except Exception as e:
        log.error(f"❌ Discord send error: {e}")
        return False


def _build_embed(summary: dict) -> dict | None:
    """Build a single Discord embed for one ticker."""

    ticker = summary.get("ticker", "?")
    price = summary.get("current_price", "?")
    direction = summary.get("direction", "unknown").lower()
    suitability = summary.get("entry_suitability", "unknown").lower()

    color = DIRECTION_COLORS.get(direction, 0x6B7280)
    emoji = SUITABILITY_EMOJI.get(suitability, "❓")

    # Format entry prices
    entries = summary.get("entry_prices", [])
    stops = summary.get("stop_prices", [])
    reasons = summary.get("key_reasons", [])

    entry_str = " / ".join(f"${p}" for p in entries) if entries else "N/A"
    stop_str = " / ".join(f"${p}" for p in stops) if stops else "N/A"
    reason_str = "\n".join(f"• {r}" for r in reasons[:3]) if reasons else "N/A"

    # Outlook
    outlook_short = summary.get("outlook_short", "N/A")
    outlook_mid = summary.get("outlook_mid", "N/A")

    fields = [
        {"name": "💰 현재가", "value": f"${price}", "inline": True},
        {"name": "📊 방향", "value": f"{direction.upper()} {emoji}", "inline": True},
        {"name": "🎯 진입가 (1st/2nd/3rd)", "value": entry_str, "inline": False},
        {"name": "🛑 손절가 (1st/2nd/3rd)", "value": stop_str, "inline": False},
        {"name": "📅 전망 (단기/중기)", "value": f"{outlook_short} / {outlook_mid}", "inline": False},
        {"name": "💡 핵심 근거", "value": reason_str, "inline": False},
    ]

    parse_status = summary.get("summary_parse_status", "unknown")
    if parse_status == "failed":
        color = 0xEF4444
        fields.insert(0, {
            "name": "JSON 추출 실패",
            "value": "기계판독 요약을 파싱하지 못했습니다. 상세 이메일을 확인하세요.",
            "inline": False,
        })

    return {
        "title": f"**{ticker}**",
        "color": color,
        "fields": fields,
        "footer": {"text": f"Entry Suitability: {suitability}"},
    }