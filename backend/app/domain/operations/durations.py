"""Period and duration helpers — pure, testable."""

import itertools
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

COMPLETENESS_TOLERANCE_MINUTES = 2


def resolve_period(
    report_date: date, day_boundary_hour: int = 0, zone: str = "Africa/Lagos"
) -> tuple[datetime, datetime]:
    start = datetime.combine(report_date, time(day_boundary_hour), ZoneInfo(zone))
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def utc(value: datetime) -> datetime:
    # SQLite returns stored UTC instants without their offset.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def duration_minutes(started_at: datetime, ended_at: datetime) -> int:
    """Minutes between two UTC instants, rounded."""
    delta = ended_at - started_at
    return round(delta.total_seconds() / 60)


def completeness_check(
    sum_minutes: int, period_minutes: int, tolerance: int = COMPLETENESS_TOLERANCE_MINUTES
) -> tuple[bool, int]:
    """Return (is_complete, unaccounted_minutes)."""
    diff = period_minutes - sum_minutes
    if abs(diff) <= tolerance:
        return True, 0
    if diff > 0:
        return False, diff
    return False, diff  # over-logged


def has_overlap(blocks: list[tuple[datetime, datetime]]) -> tuple[bool, int | None, int | None]:
    """Check for overlaps in sorted blocks. Return (has_overlap, idx_a, idx_b)."""
    sorted_blocks = sorted(enumerate(blocks), key=lambda x: x[1][0])
    for (idx_a, (s_a, e_a)), (idx_b, (s_b, e_b)) in itertools.pairwise(sorted_blocks):
        if s_b < e_a:
            return True, idx_a, idx_b
    return False, None, None
