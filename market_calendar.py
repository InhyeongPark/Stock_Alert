"""
Checks whether today is a US stock market trading day.
Uses the exchange_calendars library with ISO 10383 MIC codes.
"""

import logging
from datetime import datetime

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