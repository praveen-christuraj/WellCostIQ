"""Which code fields a block must carry, decided by its time classification.

The organisation's rule:

* **Planned** — operation code and activity code are mandatory. NPT code,
  cause and agency stay optional.
* **NPT** — operation, activity, NPT code, cause and agency are all mandatory.
* **UPA** — operation, activity, cause and agency are mandatory; an NPT code is
  *not* required (UPA work is unplanned but productive, so it is not downtime).

The rule is enforced where it matters and explained everywhere else:

* ``missing_fields`` returns the exact fields, in a fixed order, so the editor,
  the bulk-assign dialog and the submit check all quote the same sentence.
* ``bulk_allowed`` says whether a field may be written in bulk for a given
  classification — an NPT code can never be bulk-assigned to Planned work, so a
  gesture cannot create a contradiction.
* Allocation (PT/NPT/UPA/SP) is a separate axis and never substitutes for
  classification.
"""

from __future__ import annotations

from app.models.operations import OpsActivityBlock

#: Human labels, in the order the review dialog lists them.
FIELD_LABELS = {
    "operation_code_id": "operation code",
    "activity_code_id": "activity code",
    "npt_code_id": "NPT code",
    "cause_code": "cause code",
    "agency": "agency (responsible party)",
}

MANDATORY = {
    "Planned": ("operation_code_id", "activity_code_id"),
    "NPT": ("operation_code_id", "activity_code_id", "npt_code_id", "cause_code", "agency"),
    "UPA": ("operation_code_id", "activity_code_id", "cause_code", "agency"),
}

#: Fields that may be bulk-assigned under each classification. A field missing
#: from this tuple is refused in bulk and must be edited on the block itself.
BULK_ALLOWED = {
    "Planned": ("operation_code_id", "activity_code_id", "cause_code", "agency"),
    "NPT": ("operation_code_id", "activity_code_id", "npt_code_id", "cause_code", "agency"),
    "UPA": ("operation_code_id", "activity_code_id", "cause_code", "agency"),
}


def _has_agency(block) -> bool:
    return bool(getattr(block, "agency_id", None)) or bool(block.vendor_id) or bool(
        (block.responsible_party or "").strip()
    )


def is_missing(block, field: str) -> bool:
    if field == "agency":
        return not _has_agency(block)
    if field == "cause_code":
        return not (block.cause_code or "").strip()
    return getattr(block, field, None) is None


def missing_fields(block) -> list[str]:
    """Mandatory fields this block still lacks, in list order."""
    return [field for field in MANDATORY.get(block.classification, ()) if is_missing(block, field)]


def mandatory_fields(classification: str) -> tuple[str, ...]:
    return MANDATORY.get(classification, ())


def describe_missing(block) -> str:
    missing = missing_fields(block)
    if not missing:
        return ""
    labels = ", ".join(FIELD_LABELS[field] for field in missing)
    return f"Block {block.sequence_no} ({block.classification}): select the {labels}."


def validate_blocks(blocks, *, operation_ids=None, activity_ids=None) -> None:
    """Refuse a save that leaves a mandatory code blank.

    ``operation_ids`` / ``activity_ids`` are the workspace code ids the caller
    just validated, so an imported row that names a code outside the library is
    refused with the same message shape as a missing one.
    """
    from fastapi import HTTPException

    for block in blocks:
        if not isinstance(block, OpsActivityBlock):
            continue
        if "operation_code_id" in MANDATORY.get(block.classification, ()) and operation_ids is not None:
            if block.operation_code_id and block.operation_code_id not in operation_ids:
                raise HTTPException(422, f"Block {block.sequence_no}: choose an operation code from the library.")
        if "activity_code_id" in MANDATORY.get(block.classification, ()) and activity_ids is not None:
            if block.activity_code_id and block.activity_code_id not in activity_ids:
                raise HTTPException(422, f"Block {block.sequence_no}: choose an activity code from the library.")
        message = describe_missing(block)
        if message:
            raise HTTPException(422, message)


def bulk_refusal(classification: str, fields: list[tuple[str, object]]) -> str:
    """Explain a bulk gesture that would contradict the classification."""
    blocked = [
        FIELD_LABELS[field]
        for field, value in fields
        if value is not None and field not in BULK_ALLOWED.get(classification, ())
    ]
    if not blocked:
        return ""
    return (
        f"{', '.join(blocked)} cannot be bulk-assigned to {classification} blocks. "
        "Change the classification on the block, or assign that field on the block itself."
    )
