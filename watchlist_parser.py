"""Parse watchlist.txt ticker rows with optional profile metadata."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WatchlistEntry:
    ticker: str
    profile: str | None = None
    themes: tuple[str, ...] = ()


def parse_watchlist(filepath: str) -> list[WatchlistEntry]:
    entries = []
    path = Path(filepath)

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []

    for raw_line in lines:
        content = raw_line.split("#", 1)[0].strip()
        if not content:
            continue

        entry = _parse_line(content)
        if entry:
            entries.append(entry)

    return entries


def load_watchlist_tickers(filepath: str) -> list[str]:
    return [entry.ticker for entry in parse_watchlist(filepath)]


def get_watchlist_entry(ticker: str, filepath: str) -> WatchlistEntry | None:
    target = ticker.upper()
    for entry in parse_watchlist(filepath):
        if entry.ticker == target:
            return entry
    return None


def _parse_line(content: str) -> WatchlistEntry | None:
    parts = content.split()
    if not parts:
        return None

    ticker = parts[0].upper()
    profile = None
    themes: tuple[str, ...] = ()

    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key in ("profile", "profile_name"):
                profile = _normalize_token(value)
            elif key in ("theme", "themes", "tags"):
                themes = _parse_themes(value)
            continue

        if profile is None:
            profile = _normalize_token(part)
        elif not themes:
            themes = _parse_themes(part)

    return WatchlistEntry(ticker=ticker, profile=profile, themes=themes)


def _normalize_token(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _parse_themes(value: str) -> tuple[str, ...]:
    themes = [
        _normalize_token(theme)
        for theme in value.split(",")
        if theme.strip()
    ]
    return tuple(dict.fromkeys(themes))
