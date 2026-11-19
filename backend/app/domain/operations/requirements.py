"""Which criteria a block must carry, decided by its Activity type.

The organisation's rule, in the order the daily report lists the fields:

* **Hole Section, Phase, Activity and Allocation** are always mandatory — they
  say *where* and *what* the time was spent on, whichever type of time it was.
* **Cause** is mandatory only when the Activity type is **NPT** or **UPA**.
  Planned work needs no cause: nothing went wrong, so there is nothing to
  explain. NPT and UPA both need one, because unplanned time has to say why.
* **Operations** (the Code Library downtime work list), **Agency / service
  vendor** and the **Responsible agency label** stay optional. They are filled
  by a correlation when one exists, and the engineer may always add them.

The Activity type is a property of the Master Data Activity record the engineer
selects, so ``classification`` on the block is a stored copy of that type. The
copy is what historical days and totals keep being read against: correcting an
activity's type later must never rewrite a completed day.

The rule is enforced where it matters and explained everywhere else:

* ``missing_fields`` returns the exact fields, in a fixed order, so the editor,
  the bulk-assign dialog and the submit check all quote the same sentence.
* ``bulk_allowed`` says whether a field may be written in bulk for a given
  Activity type — a cause can never be bulk-assigned to Planned work, so a
  gesture cannot create a contradiction.
* Allocation (PT/NPT/UPA/SP) is a separate axis and never substitutes for the
  Activity.
"""

from __future__ import annotations

#: Human labels, in the order the review dialog lists them.
FIELD_LABELS = {
    "hole_section_id": "hole section",
    "phase_id": "phase",
    "sub_phase_id": "sub-phase",
    "activity_id": "activity",
    "allocation": "allocation",
    "cause_code": "cause code",
    "operation_id": "operations",
    "responsible_agency_id": "responsible agency label",
    "vendor_id": "agency / service vendor",
}

#: Always required, whatever the Activity type.
BASE_MANDATORY = ("hole_section_id", "phase_id", "activity_id", "allocation")

#: Added on top of ``BASE_MANDATORY`` when the Activity type is NPT or UPA.
CAUSE_TYPES = ("NPT", "UPA")

#: Kept for the reference payload the pages read: keyed by Activity type.
MANDATORY = {
    "Planned": BASE_MANDATORY,
    "NPT": (*BASE_MANDATORY, "cause_code"),
    "UPA": (*BASE_MANDATORY, "cause_code"),
}

#: Fields that may be bulk-assigned under each Activity type. A field missing
#: from this tuple is refused in bulk and must be edited on the block itself.
#: The names are the stored block fields, so a request key and this table can be
#: compared directly — a rename here must never leave a field silently unwritable.
BULK_ALLOWED = {
    "Planned": (
        "hole_section_id",
        "phase_id",
        "sub_phase_id",
        "activity_id",
        "allocation",
        "operation_id",
        "responsible_agency_id",
        "vendor_id",
    ),
    "NPT": (
        "hole_section_id",
        "phase_id",
        "sub_phase_id",
        "activity_id",
        "allocation",
        "cause_code",
        "operation_id",
        "responsible_agency_id",
        "vendor_id",
    ),
    "UPA": (
        "hole_section_id",
        "phase_id",
        "sub_phase_id",
        "activity_id",
        "allocation",
        "cause_code",
        "operation_id",
        "responsible_agency_id",
        "vendor_id",
    ),
}


def is_missing(block, field: str) -> bool:
    if field == "cause_code":
        return not (getattr(block, "cause_code", "") or "").strip()
    if field == "allocation":
        return not (getattr(block, "allocation", "") or "").strip()
    return getattr(block, field, None) is None


def mandatory_fields(classification: str) -> tuple[str, ...]:
    """The fields a block of this Activity type must carry."""
    return MANDATORY.get(classification, BASE_MANDATORY)


def missing_fields(block) -> list[str]:
    """Mandatory fields this block still lacks, in list order."""
    return [field for field in mandatory_fields(block.classification) if is_missing(block, field)]


def describe_missing(block) -> str:
    missing = missing_fields(block)
    if not missing:
        return ""
    labels = ", ".join(FIELD_LABELS[field] for field in missing)
    return f"Block {block.sequence_no} ({block.classification}): select the {labels}."


def validate_blocks(blocks) -> None:
    """Refuse a save that leaves a mandatory criterion blank."""
    from fastapi import HTTPException

    for block in blocks:
        message = describe_missing(block)
        if message:
            raise HTTPException(422, message)


def bulk_refusal(classification: str, fields: list[tuple[str, object]]) -> str:
    """Explain a bulk gesture that would contradict the Activity type."""
    blocked = [
        FIELD_LABELS[field]
        for field, value in fields
        if value is not None and field not in BULK_ALLOWED.get(classification, ())
    ]
    if not blocked:
        return ""
    return (
        f"{', '.join(blocked)} cannot be bulk-assigned to {classification} blocks. "
        "Change the Activity on the block, or assign that field on the block itself."
    )
