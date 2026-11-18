"""Timezone-safe time helpers.

SQLite returns naive ``DATETIME`` values and PostgreSQL returns aware ones. The
application stores UTC everywhere, so a naive value is *assumed* to be UTC and an
aware value is *converted* — never relabelled. Using ``.replace(tzinfo=...)`` on
an aware value silently changes the instant; that bug is why every comparison in
this codebase goes through :func:`as_utc`.
"""
from datetime import date, datetime, timedelta, timezone

# West Africa Time (Africa/Lagos) observes UTC+01:00 permanently with no DST.
WAT = timezone(timedelta(hours=1), name="WAT")
WAT_TZ_NAME = "Africa/Lagos"
WAT_LABEL = "WAT (UTC+1:00)"


def utcnow() -> datetime:
    """The current instant, always timezone-aware UTC."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Return ``value`` as an aware UTC datetime, or ``None``."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def as_wat(value: datetime | None) -> datetime | None:
    """Return ``value`` converted to West Africa Time (UTC+01:00), or ``None``."""
    moment = as_utc(value)
    return moment.astimezone(WAT) if moment is not None else None


def wat_now() -> datetime:
    """The current instant in West Africa Time (UTC+01:00)."""
    return utcnow().astimezone(WAT)


def wat_today() -> date:
    """Current calendar date in West Africa Time (UTC+01:00)."""
    return wat_now().date()


def format_wat(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Format a timestamp in West Africa Time (UTC+01:00)."""
    moment = as_wat(value)
    return moment.strftime(fmt) if moment is not None else ""


def is_expired(value: datetime | None, *, now: datetime | None = None) -> bool:
    """True when ``value`` is in the past; ``None`` never expires."""
    moment = as_utc(value)
    return bool(moment is not None and moment <= (as_utc(now) or utcnow()))
