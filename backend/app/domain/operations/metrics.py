"""Measured penetration, independent of costs, forecast rates and shift length."""

from decimal import ROUND_HALF_UP, Decimal
from app.core.precision import DECIMAL_QUANT

QUANTUM = DECIMAL_QUANT


def period_balance(report_type, period_minutes, logged_minutes):
    """A measurement-only mud report is not a shift with a missing 24 hours."""
    return 0 if report_type == "DMR" and not logged_minutes else max(0, period_minutes - logged_minutes)


def penetration(report, blocks):
    """Return footage and the denominator for exactly that footage, or unknown."""
    gain = report.progress_m
    if report.depth_end_m is not None and report.depth_start_m is not None:
        gain = report.depth_end_m - report.depth_start_m
    if gain is not None and gain >= 0 and report.rotating_hours and report.rotating_hours > 0:
        return gain, report.rotating_hours
    pairs = [
        (b.footage_m, b.rotating_hours)
        for b in blocks
        if b.footage_m is not None and b.footage_m >= 0 and b.rotating_hours and b.rotating_hours > 0
    ]
    if pairs:
        return sum(p[0] for p in pairs), sum(p[1] for p in pairs)
    return gain if gain is not None and gain >= 0 else None, None


def compute_rop(footage_m, rotating_hours):
    if footage_m is None or footage_m < 0 or not rotating_hours or rotating_hours <= 0:
        return None
    return (footage_m / rotating_hours).quantize(QUANTUM, rounding=ROUND_HALF_UP)


def lag_days(actual_cum_days, planned_cum_days):
    if actual_cum_days is None or planned_cum_days is None:
        return None
    return (actual_cum_days - planned_cum_days).quantize(QUANTUM, rounding=ROUND_HALF_UP)
