"""One authoritative definition of operational service duration.

Cost lines may repeat the same activity allocation for simultaneous services or
charge categories.  MIS duration therefore comes only from explicit hourly Day
Rate service allocations and retains the greatest duration for each operational
allocation before rolling hours into days.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TypeAlias

ONE_TIME_SERVICE_CATEGORIES = frozenset({"Mobilization", "Demobilization", "Fixed Charge"})
DURATION_HOURS_QUANT = Decimal("0.01")
DURATION_DAYS_QUANT = Decimal("0.0001")

AllocationKey: TypeAlias = tuple[str, date, str, str, str, str, str, str]


def record_service_allocation(
    allocations: dict[AllocationKey, Decimal],
    *,
    well_id: str,
    cost_date: date,
    classification: str,
    entry_id: str,
    activity_id: str | None,
    sub_activity_id: str | None,
    hole_section_id: str | None,
    phase_id: str | None,
    charging_basis: str | None,
    charge_category: str | None,
    quantity_unit: str | None,
    quantity: Decimal | str | int | float | None,
    parties: dict[AllocationKey, str] | None = None,
    party_key: str = "",
) -> AllocationKey | None:
    """Record one eligible line and return its deduplicated allocation key.

    ``parties`` maps an allocation to the responsible party of the line that
    recorded the greatest duration. Vendor and service-subcategory NPT/UPA
    totals therefore sum back to the well totals: every hour is attributed once,
    to one party, exactly as it is counted once.
    """
    if (
        charging_basis != "Day Rate"
        or charge_category in ONE_TIME_SERVICE_CATEGORIES
        or quantity_unit != "hours"
    ):
        return None
    key: AllocationKey = (
        well_id,
        cost_date,
        classification,
        entry_id,
        activity_id or "",
        sub_activity_id or "",
        hole_section_id or "",
        phase_id or "",
    )
    hours = Decimal(str(quantity or 0))
    previous = allocations.get(key)
    if previous is None or hours > previous:
        allocations[key] = hours
        if parties is not None:
            parties[key] = party_key
    return key


def hours_to_days(hours: Decimal) -> Decimal:
    return (hours / Decimal("24")).quantize(DURATION_DAYS_QUANT)
