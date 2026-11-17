"""Metrics helpers: ROP, lag/lead."""

from decimal import Decimal, ROUND_HALF_UP


def compute_rop(footage_m: Decimal | None, rotating_hours: Decimal | None) -> Decimal | None:
    if footage_m is None or rotating_hours is None:
        return None
    if rotating_hours == 0:
        return None
    if footage_m <= 0:
        return None
    return (footage_m / rotating_hours).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def lag_days(actual_cum_days: Decimal | None, planned_cum_days: Decimal | None) -> Decimal | None:
    """Lag = actual - planned. Positive = behind."""
    if actual_cum_days is None or planned_cum_days is None:
        return None
    return (actual_cum_days - planned_cum_days).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
