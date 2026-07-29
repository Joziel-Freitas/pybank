from datetime import date, datetime
from zoneinfo import ZoneInfo

from settings import SYSTEM_TIMEZONE


def get_today(timezone: ZoneInfo = SYSTEM_TIMEZONE) -> date:
    """
    Returns the current system calendar date fixed to the specified timezone.

    Ensures deterministic accrual calculations regardless of the host OS timezone.

    Args:
        timezone (ZoneInfo, optional): The target timezone for date evaluation.
            Defaults to SYSTEM_TIMEZONE.

    Returns:
        date: The current system calendar date.
    """
    dt = datetime.now(tz=timezone)
    return dt.date()


def get_now(timezone: ZoneInfo = SYSTEM_TIMEZONE) -> datetime:
    """
    Returns the current system date and time fixed to the specified timezone.

    Provides the canonical timestamp for all time-sensitive operations,
    ensuring deterministic behavior regardless of the host operating
    system's local timezone.

    Args:
        timezone (ZoneInfo, optional): The target timezone for datetime evaluation.
            Defaults to SYSTEM_TIMEZONE.

    Returns:
        datetime: The current system date and time with timezone info.
    """
    dt = datetime.now(tz=timezone)
    return dt
