"""
Checks whether today is a US stock market trading day.
Uses the exchange_calendars library with ISO 10383 MIC codes.
"""

import logging
from datetime import datetime, time

import exchange_calendars as xcals

from config import EXCHANGE_MIC, TZ

log = logging.getLogger(__name__)


def is_market_open_today() -> bool:
    """Return True if today is a regular NYSE trading session."""
    cal = xcals.get_calendar(EXCHANGE_MIC)
    today = datetime.now(TZ).date()
    is_open = cal.is_session(today)

    if is_open:
        log.info(f"{today} is a trading day")
    else:
        log.info(f"{today} is NOT a trading day (weekend or holiday)")

    return is_open


def get_market_session_status(now: datetime | None = None) -> dict:
    """Return trading-day and regular-session status for the configured exchange."""
    cal = xcals.get_calendar(EXCHANGE_MIC)
    now_et = _as_et(now or datetime.now(TZ))
    today = now_et.date()
    is_trading_day = cal.is_session(today)

    if not is_trading_day:
        return {
            "is_trading_day": False,
            "is_regular_session": False,
            "session_state": "closed",
            "now": now_et.isoformat(),
            "market_open": None,
            "market_close": None,
        }

    market_open, market_close = _session_bounds(cal, today)
    if market_open <= now_et < market_close:
        session_state = "regular"
        is_regular_session = True
    elif now_et < market_open:
        session_state = "pre_market"
        is_regular_session = False
    else:
        session_state = "after_hours"
        is_regular_session = False

    return {
        "is_trading_day": True,
        "is_regular_session": is_regular_session,
        "session_state": session_state,
        "now": now_et.isoformat(),
        "market_open": market_open.isoformat(),
        "market_close": market_close.isoformat(),
    }


def _session_bounds(cal, session_date) -> tuple[datetime, datetime]:
    """Use exchange_calendars session bounds, with a conservative fallback."""
    try:
        market_open = cal.session_open(session_date).to_pydatetime()
        market_close = cal.session_close(session_date).to_pydatetime()
        return _as_et(market_open), _as_et(market_close)
    except Exception as e:
        log.warning(f"Falling back to standard NYSE hours for {session_date}: {e}")
        return (
            datetime.combine(session_date, time(9, 30), tzinfo=TZ),
            datetime.combine(session_date, time(16, 0), tzinfo=TZ),
        )


def _as_et(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ)
    return value.astimezone(TZ)
