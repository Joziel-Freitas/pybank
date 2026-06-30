from datetime import date, datetime

from settings import SYSTEM_TIMEZONE


def get_today() -> date:
    """
    Returns the current system calendar date fixed to the institution's timezone.
    Ensures deterministic accrual calculations regardless of the host OS timezone.
    """
    dt = datetime.now(tz=SYSTEM_TIMEZONE)
    return dt.date()


def get_now() -> datetime:
    """
    Returns the current system date and time fixed to the institution's timezone.

    Provides the canonical timestamp for all time-sensitive operations,
    ensuring deterministic behavior regardless of the host operating
    system's local timezone.
    """
    dt = datetime.now(tz=SYSTEM_TIMEZONE)

    return dt
