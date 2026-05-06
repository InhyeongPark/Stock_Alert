"""
Investment profile metadata used by prompts, summaries, and proxy backtests.

Profiles describe the intended evaluation horizon before results are known.
This keeps proxy backtests from becoming ticker-by-ticker optimization.
"""

import logging

from config import WATCHLIST_FILE
from watchlist_parser import get_watchlist_entry

log = logging.getLogger(__name__)

DEFAULT_INVESTMENT_PROFILE = "high_vol_swing"
PROFILE_ALIASES = {
    "core": "core_theme",
    "growth": "growth_theme",
    "high_vol": "high_vol_swing",
    "swing": "high_vol_swing",
}

INVESTMENT_PROFILES = {
    "core_theme": {
        "label": "Core Theme",
        "investment_horizon": "3-12 months",
        "proxy_holding_days": 20,
        "stop_atr_multiple": 1.5,
        "target_r_multiple": 1.5,
        "entry_style": "1-4 week pullback / staged accumulation",
        "risk_style": "technical invalidation plus thesis risk",
    },
    "growth_theme": {
        "label": "Growth Theme",
        "investment_horizon": "2-6 months",
        "proxy_holding_days": 10,
        "stop_atr_multiple": 1.5,
        "target_r_multiple": 2.0,
        "entry_style": "1-3 week pullback or constructive momentum continuation",
        "risk_style": "technical invalidation plus catalyst or backlog risk",
    },
    "high_vol_swing": {
        "label": "High-Vol Swing",
        "investment_horizon": "1-8 weeks within a longer theme",
        "proxy_holding_days": 5,
        "stop_atr_multiple": 1.5,
        "target_r_multiple": 2.0,
        "entry_style": "short-term momentum continuation or sharp pullback",
        "risk_style": "technical invalidation with tighter ATR-defined risk",
    },
}


def get_ticker_profile_name(ticker: str) -> str:
    entry = get_watchlist_entry(ticker, WATCHLIST_FILE)
    return resolve_profile_name(entry.profile if entry else None, ticker=ticker)


def get_ticker_profile(ticker: str) -> dict:
    profile_name = get_ticker_profile_name(ticker)
    return get_profile(profile_name, ticker=ticker)


def get_profile(profile_name: str | None, ticker: str | None = None) -> dict:
    profile_name = resolve_profile_name(profile_name, ticker=ticker)
    profile = dict(INVESTMENT_PROFILES[profile_name])
    profile["profile_name"] = profile_name
    return profile


def resolve_profile_name(profile_name: str | None, ticker: str | None = None) -> str:
    raw_name = (profile_name or DEFAULT_INVESTMENT_PROFILE).strip().lower().replace("-", "_")
    resolved = PROFILE_ALIASES.get(raw_name, raw_name)

    if resolved not in INVESTMENT_PROFILES:
        subject = f" for {ticker}" if ticker else ""
        log.warning(
            f"Unknown investment profile '{profile_name}'{subject}; "
            f"using {DEFAULT_INVESTMENT_PROFILE}"
        )
        return DEFAULT_INVESTMENT_PROFILE

    return resolved


def get_ticker_themes(ticker: str) -> list[str]:
    entry = get_watchlist_entry(ticker, WATCHLIST_FILE)
    return list(entry.themes) if entry else []


def profile_context_for_summary(ticker: str) -> dict:
    profile = get_ticker_profile(ticker)
    return {
        "investment_profile": profile["profile_name"],
        "investment_horizon": profile["investment_horizon"],
        "entry_style": profile["entry_style"],
        "risk_style": profile["risk_style"],
    }


def format_profile_context(ticker: str, language: str) -> str:
    profile = get_ticker_profile(ticker)
    themes = get_ticker_themes(ticker)
    themes_text = ", ".join(themes) if themes else "N/A"

    if language == "ko":
        return f"""[투자 프로파일]
프로파일: {profile['profile_name']} ({profile['label']})
투자 시간 프레임: {profile['investment_horizon']}
진입 스타일: {profile['entry_style']}
리스크 스타일: {profile['risk_style']}
Proxy 평가 기준: {profile['proxy_holding_days']} 거래일, stop {profile['stop_atr_multiple']} ATR, target {profile['target_r_multiple']}R
테마 태그: {themes_text}"""

    return f"""[Investment Profile]
Profile: {profile['profile_name']} ({profile['label']})
Investment horizon: {profile['investment_horizon']}
Entry style: {profile['entry_style']}
Risk style: {profile['risk_style']}
Proxy evaluation: {profile['proxy_holding_days']} trading days, stop {profile['stop_atr_multiple']} ATR, target {profile['target_r_multiple']}R
Theme tags: {themes_text}"""
