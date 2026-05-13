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

DISCORD_MAX_EMBEDS_PER_MESSAGE = 10
DISCORD_SAFE_EMBED_CHAR_BUDGET = 5500

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

    portfolio_line = _format_portfolio_context(summaries)
    content = f"📈 **일일 주식 분석 요약** — {date_str}"
    if portfolio_line:
        content += f"\n{portfolio_line}"

    chunks = _chunk_embeds(embeds)
    all_sent = True

    for index, chunk in enumerate(chunks, start=1):
        payload = {
            "content": _truncate(_format_chunk_content(content, index, len(chunks)), 2000),
            "embeds": chunk,
            "allowed_mentions": {"parse": []},
        }
        label = f"chunk {index}/{len(chunks)}"
        if _post_webhook(webhook_url, payload, label):
            continue

        if len(chunk) <= 1:
            all_sent = False
            continue

        log.warning(f"Discord {label} failed; retrying its embeds one at a time")
        chunk_sent = True
        for single_index, embed in enumerate(chunk, start=1):
            retry_payload = {
                "content": _truncate(
                    f"{_format_chunk_content(content, index, len(chunks))}\nRetry {single_index}/{len(chunk)}",
                    2000,
                ),
                "embeds": [embed],
                "allowed_mentions": {"parse": []},
            }
            if not _post_webhook(webhook_url, retry_payload, f"{label} retry {single_index}/{len(chunk)}"):
                chunk_sent = False
        if not chunk_sent:
            all_sent = False

    if all_sent:
        log.info(f"✅ Discord digest sent ({len(embeds)} tickers, {len(chunks)} message(s))")
    return all_sent


def _post_webhook(webhook_url: str, payload: dict, label: str) -> bool:
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Stock-Alert/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 204):
                return True
            log.error(f"❌ Discord returned status {resp.status} for {label}")
            return False
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        log.error(f"❌ Discord webhook failed for {label}: {e.code} — {body}")
        return False
    except Exception as e:
        log.error(f"❌ Discord send error for {label}: {e}")
        return False


def _chunk_embeds(embeds: list[dict]) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0

    for embed in embeds:
        embed_chars = _embed_character_count(embed)
        if current and (
            len(current) >= DISCORD_MAX_EMBEDS_PER_MESSAGE
            or current_chars + embed_chars > DISCORD_SAFE_EMBED_CHAR_BUDGET
        ):
            chunks.append(current)
            current = []
            current_chars = 0

        current.append(embed)
        current_chars += embed_chars

    if current:
        chunks.append(current)

    return chunks


def _embed_character_count(embed: dict) -> int:
    total = 0
    for key in ("title", "description"):
        total += len(str(embed.get(key, "") or ""))

    footer = embed.get("footer") or {}
    total += len(str(footer.get("text", "") or ""))

    author = embed.get("author") or {}
    total += len(str(author.get("name", "") or ""))

    for field in embed.get("fields") or []:
        total += len(str(field.get("name", "") or ""))
        total += len(str(field.get("value", "") or ""))

    return total


def _format_chunk_content(content: str, index: int, total: int) -> str:
    if total <= 1:
        return content
    return f"{content}\nPart {index}/{total}"


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

    profile = summary.get("investment_profile")
    horizon = summary.get("investment_horizon")
    profile_str = f"{profile} | {horizon}" if profile or horizon else "N/A"

    fields = [
        _field("💰 현재가", f"${price}", True),
        _field("📊 방향", f"{direction.upper()} {emoji}", True),
        _field("⏱ 가격 기준", _format_price_basis(summary), False),
        _field("🧭 프로파일", profile_str, False),
        _field("🎯 진입가 (1st/2nd/3rd)", entry_str, False),
        _field("🛑 손절가 (1st/2nd/3rd)", stop_str, False),
        _field("📅 전망 (단기/중기)", f"{outlook_short} / {outlook_mid}", False),
        _field("💡 핵심 근거", reason_str, False),
    ]

    review = summary.get("polymarket_claude_review")
    if review:
        adjustment = review.get("confidence_adjustment", "unknown")
        magnitude = review.get("adjustment_magnitude", "unknown")
        final_confidence = review.get("final_confidence_after_polymarket", "unknown")
        review_reason = review.get("reason", "N/A")
        fields.append(_field(
            "🔎 Polymarket Claude 검토",
            (
                f"{adjustment.upper()} ({magnitude}) | "
                f"final confidence: {final_confidence}\n{review_reason}"
            ),
            False,
        ))

    parse_status = summary.get("summary_parse_status", "unknown")
    if parse_status == "failed":
        color = 0xEF4444
        fields.insert(0, _field(
            "JSON 추출 실패",
            "기계판독 요약을 파싱하지 못했습니다. 상세 이메일을 확인하세요.",
            False,
        ))

    return {
        "title": _truncate(f"**{ticker}**", 256),
        "color": color,
        "fields": fields,
        "footer": {"text": _truncate(f"Entry Suitability: {suitability}", 2048)},
    }


def _format_price_basis(summary: dict) -> str:
    status = summary.get("price_status", "unknown")
    source = summary.get("price_source", "unknown")
    as_of = summary.get("price_as_of") or "N/A"
    warning = summary.get("price_warning")
    text = f"{status} | {source}\nas of: {as_of}"
    if warning:
        text += f"\n{warning}"
    return text


def _field(name: str, value, inline: bool, value_limit: int = 300) -> dict:
    text = str(value) if value not in (None, "") else "N/A"
    return {
        "name": _truncate(name, 256),
        "value": _truncate(text, min(value_limit, 1024)),
        "inline": inline,
    }


def _truncate(text: str, limit: int) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _format_portfolio_context(summaries: list[dict]) -> str:
    if not summaries:
        return ""

    context = summaries[0].get("portfolio_context") or {}
    warnings = context.get("warnings") or []
    if not warnings:
        return ""

    lines = []
    for warning in warnings[:3]:
        severity = warning.get("severity", "info").upper()
        lines.append(f"⚠️ {severity}: {warning.get('message', 'Portfolio concentration warning')}")
    return "\n".join(lines)
