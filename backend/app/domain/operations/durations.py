"""Period and duration helpers — pure, testable."""

from datetime import date, datetime, time, timedelta, timezone

COMPLETENESS_TOLERANCE_MINUTES = 2


def resolve_period(report_date: date, day_boundary_hour: int = 0) -> tuple[datetime, datetime]:
    """Resolve a report_date to UTC period [start, end)."""
    # For now assume operating timezone is UTC or Lagos (UTC+1 no DST)
    # Use naive local then attach UTC — caller converts to local for display
    start = datetime.combine(report_date, time(day_boundary_hour, 0), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def duration_minutes(started_at: datetime, ended_at: datetime) -> int:
    """Minutes between two UTC instants, rounded."""
    delta = ended_at - started_at
    return int(round(delta.total_seconds() / 60))


def completeness_check(sum_minutes: int, period_minutes: int, tolerance: int = COMPLETENESS_TOLERANCE_MINUTES) -> tuple[bool, int]:
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
    for (idx_a, (s_a, e_a)), (idx_b, (s_b, e_b)) in zip(sorted_blocks, sorted_blocks[1:]):
        if s_b < e_a:
            return True, idx_a, idx_b
    return False, None, None
