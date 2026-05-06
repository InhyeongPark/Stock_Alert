"""
Investment profile metadata used by prompts, summaries, and proxy backtests.

Profiles describe the intended evaluation horizon before results are known.
This keeps proxy backtests from becoming ticker-by-ticker optimization.
"""

DEFAULT_INVESTMENT_PROFILE = "high_vol_swing"

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

TICKER_INVESTMENT_PROFILES = {
    "MSFT": "core_theme",
    "ORCL": "core_theme",
    "VST": "core_theme",
    "AVAV": "growth_theme",
    "OKLO": "high_vol_swing",
    "CORZ": "high_vol_swing",
    "IREN": "high_vol_swing",
    "ONDS": "high_vol_swing",
    "SMR": "high_vol_swing",
}

TICKER_THEMES = {
    "MSFT": ["ai_infrastructure", "software_platform"],
    "ORCL": ["ai_infrastructure", "software_platform"],
    "VST": ["ai_infrastructure", "energy"],
    "OKLO": ["ai_infrastructure", "energy"],
    "SMR": ["ai_infrastructure", "energy"],
    "IREN": ["ai_infrastructure", "energy"],
    "CORZ": ["ai_infrastructure", "compute"],
    "AVAV": ["defense_ai"],
    "ONDS": ["defense_ai"],
}


def get_ticker_profile_name(ticker: str) -> str:
    return TICKER_INVESTMENT_PROFILES.get(ticker.upper(), DEFAULT_INVESTMENT_PROFILE)


def get_ticker_profile(ticker: str) -> dict:
    profile_name = get_ticker_profile_name(ticker)
    profile = dict(INVESTMENT_PROFILES[profile_name])
    profile["profile_name"] = profile_name
    return profile


def get_ticker_themes(ticker: str) -> list[str]:
    return list(TICKER_THEMES.get(ticker.upper(), []))


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
