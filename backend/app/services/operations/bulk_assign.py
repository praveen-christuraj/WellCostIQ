"""Bulk assignment of the daily-report criteria.

The daily report page lists every extracted block. Correcting fifty rows one
dialog at a time is where review errors come from, so this service applies one
explicit instruction to many blocks and reports exactly what happened:

* ``preview`` never writes. It returns the resulting values, the blocks that
  would be skipped and the reason, so the dialog can be shown before saving.
* ``apply`` writes only editable drafts, keeps machine evidence, marks every
  touched block as ``edited`` with the reviewer's identity, and records one
  audit entry that names the report, the fields and the counts.

Nothing here bypasses the Activity rule. A field the chosen Activity type does
not allow (a cause on Planned work) is refused, and a block that cannot legally
hold the value is skipped with a reason rather than silently changed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.operations.requirements import BULK_ALLOWED, FIELD_LABELS, bulk_refusal, describe_missing
from app.models import User
from app.models.master_data import Activity, HoleSection, Phase
from app.models.operations import (
    OpsActivityBlock,
    OpsAgency,
    OpsCause,
    OpsDailyReport,
    OpsOperation,
    OpsSubPhase,
)
from app.models.vendor_master import Vendor
from app.services.audit import record as audit_record

EDITABLE = ("draft", "in_review", "rejected")

# field name -> (workspace model, label attribute)
LIBRARY = {
    "hole_section_id": (HoleSection, "section_name"),
    "phase_id": (Phase, "phase_name"),
    "sub_phase_id": (OpsSubPhase, "sub_phase_name"),
    "activity_id": (Activity, "activity_name"),
    "operation_id": (OpsOperation, "operation_name"),
    "cause_id": (OpsCause, "cause_name"),
    "responsible_agency_id": (OpsAgency, "agency_name"),
}
ASSIGNABLE = (
    "hole_section_id",
    "phase_id",
    "sub_phase_id",
    "activity_id",
    "operation_id",
    "cause_id",
    "responsible_agency_id",
)


def _actor(user: User) -> str:
    return user.email or user.full_name or str(user.id)


def _code_field(model) -> str:
    for field in (
        "section_code",
        "phase_code",
        "sub_phase_code",
        "activity_code",
        "operation_code",
        "cause_code",
        "agency_code",
    ):
        if hasattr(model, field):
            return field
    raise KeyError(model.__name__)


def _resolve(db: Session, organization_id: str, field: str, value_id: str):
    model, name_field = LIBRARY[field]
    row = db.scalar(
        select(model).where(
            model.id == value_id,
            model.organization_id == organization_id,
            model.is_deleted.is_(False),
        )
    )
    if not row:
        raise HTTPException(422, f"The selected {FIELD_LABELS.get(field, field)} is not in this workspace's library.")
    return row, f"{getattr(row, _code_field(model))} — {getattr(row, name_field)}"


def _resolve_vendor(db: Session, organization_id: str, vendor_id: str):
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == vendor_id,
            Vendor.organization_id == organization_id,
            Vendor.is_deleted.is_(False),
        )
    )
    if not vendor:
        raise HTTPException(422, "The selected agency vendor is not in this workspace.")
    if vendor.status != "active":
        raise HTTPException(422, "Select an active vendor as the agency.")
    return vendor, f"{vendor.vendor_code} — {vendor.vendor_name}"


def _reports(db: Session, organization_id: str, report_ids: list[str]) -> list[OpsDailyReport]:
    rows = db.scalars(
        select(OpsDailyReport)
        .where(
            OpsDailyReport.organization_id == organization_id,
            OpsDailyReport.id.in_(report_ids),
            OpsDailyReport.is_deleted.is_(False),
        )
        .with_for_update()
    ).all()
    if len(rows) != len(set(report_ids)):
        raise HTTPException(404, "One or more reports are not available in this workspace.")
    locked = [row for row in rows if row.status not in EDITABLE]
    if locked:
        raise HTTPException(
            409,
            "Bulk assignment only changes editable drafts. Reopen the submitted or approved "
            "report(s) first: " + ", ".join(sorted({row.well_code_snapshot or row.id for row in locked})),
        )
    return list(rows)


def _blocks(db: Session, organization_id: str, report_ids: list[str], block_ids: list[str]):
    q = select(OpsActivityBlock).where(
        OpsActivityBlock.organization_id == organization_id,
        OpsActivityBlock.report_id.in_(report_ids),
        OpsActivityBlock.is_deleted.is_(False),
    )
    if block_ids:
        q = q.where(OpsActivityBlock.id.in_(block_ids))
    return db.scalars(q.order_by(OpsActivityBlock.report_id, OpsActivityBlock.sequence_no)).all()


def _resolve_values(db: Session, organization_id: str, data) -> tuple[dict, dict]:
    """Validate every requested assignment once and return {field: value} + labels."""
    values: dict[str, object] = {}
    labels: dict[str, str] = {}
    for field in ASSIGNABLE:
        value_id = getattr(data, field, None)
        if not value_id:
            continue
        row, label = _resolve(db, organization_id, field, value_id)
        values[field] = row
        labels[field] = label
    vendor_id = getattr(data, "vendor_id", None)
    if vendor_id:
        vendor, label = _resolve_vendor(db, organization_id, vendor_id)
        values["vendor_id"] = vendor
        values["responsible_party"] = vendor.vendor_name
        labels["vendor_id"] = f"agency / service vendor {label}"
    if raw_cause := getattr(data, "cause_code", None):
        codes = set(
            db.scalars(
                select(OpsCause.cause_code).where(
                    OpsCause.organization_id == organization_id, OpsCause.is_deleted.is_(False)
                )
            ).all()
        )
        if raw_cause.strip() not in codes:
            raise HTTPException(422, "Choose a cause code from this workspace's library.")
        values["cause_code"] = raw_cause.strip()
        labels["cause_code"] = f"cause {raw_cause.strip()}"
    if "cause_id" in values:
        # Blocks store the printed cause token, not an id. The library row supplies it.
        values["cause_code"] = values.pop("cause_id").cause_code
        labels["cause_code"] = labels.pop("cause_id")
    if getattr(data, "allocation", None):
        values["allocation"] = data.allocation
        labels["allocation"] = f"allocation {data.allocation}"
    return values, labels


def _targets(db: Session, organization_id: str, blocks, data):
    """Blocks the instruction selects, with any per-block refusal reason."""
    wanted_kind = (getattr(data, "block_kind", "") or "").strip().lower()
    chosen = set(data.block_ids or [])
    chosen_reports = set(data.report_ids or [])
    picks = []
    skipped: list[dict] = []
    for block in blocks:
        if chosen and block.id not in chosen:
            continue
        if not chosen and chosen_reports and block.report_id not in chosen_reports:
            continue
        if wanted_kind and not _matches_kind(block, wanted_kind):
            skipped.append(
                {
                    "block_id": block.id,
                    "sequence_no": block.sequence_no,
                    "report_id": block.report_id,
                    "reason": f"Not a {wanted_kind} block.",
                }
            )
            continue
        picks.append(block)
    return picks, skipped


def _matches_kind(block, kind: str) -> bool:
    text = f"{block.narrative or ''} {block.phase_raw or ''}".casefold()
    if kind in ("drilling", "completion"):
        return kind in text
    return True


#: Every value a bulk instruction can write, in one comparable tuple.
SNAPSHOT_FIELDS = (
    "hole_section_id",
    "phase_id",
    "sub_phase_id",
    "activity_id",
    "operation_id",
    "cause_code",
    "responsible_agency_id",
    "vendor_id",
    "responsible_party",
    "allocation",
    "classification",
)


def _snapshot(block) -> tuple:
    return tuple(getattr(block, field, None) for field in SNAPSHOT_FIELDS)


def _apply_to_block(block, values: dict) -> list[str]:
    """Write the values onto one block; return the notes worth telling the user.

    A field the Activity type forbids is skipped on that block — the rest of the
    instruction still lands. The note names the field and the type, so the
    summary can say "3 changed, 1 cause skipped on Planned work".
    """
    notes: list[str] = []
    incoming = {field: value for field, value in values.items() if field not in ("responsible_party",)}
    # The Activity decides the type; a bulk edit may only write what that type
    # allows. Assigning the Activity and its cause in one gesture is therefore
    # judged against the Activity being assigned, not the old one.
    assigned_activity = values.get("activity_id")
    incoming_type = (
        assigned_activity.activity_type
        if assigned_activity is not None
        else block.classification
    )
    forbidden = [
        field
        for field, value in incoming.items()
        if value is not None and field not in BULK_ALLOWED.get(incoming_type, ()) and field in FIELD_LABELS
    ]
    if forbidden:
        notes.append(bulk_refusal(incoming_type, [(field, incoming[field]) for field in forbidden]))

    if (activity := values.get("activity_id")) is not None:
        block.activity_id = activity.id
        # The Master Data Activity's own type is the block's Activity type.
        if block.classification_source != "source_mark":
            block.classification = activity.activity_type
            block.is_productive = activity.activity_type != "NPT"
            if activity.activity_type == "Planned" and block.allocation in ("NPT", "UPA"):
                block.allocation = "PT"
            elif activity.activity_type in ("NPT", "UPA") and block.allocation == "PT":
                block.allocation = activity.activity_type
    for field, value in values.items():
        if field in ("classification", "responsible_party", "activity_id", "cause_code", "allocation"):
            continue
        if field in forbidden or field not in FIELD_LABELS:
            continue
        setattr(block, field, getattr(value, "id", value))
    if "cause_code" in values and "cause_code" not in forbidden:
        block.cause_code = values["cause_code"]
    if "allocation" in values and "allocation" not in forbidden:
        block.allocation = values["allocation"]
        if values["allocation"] == "NPT":
            block.is_productive = False
    if "responsible_party" in values:
        block.responsible_party = values["responsible_party"]
    if "operation_id" in values and (operation := values["operation_id"]) is not None:
        block.operation_snapshot = operation.operation_code
    if "responsible_agency_id" in values and (agency := values["responsible_agency_id"]) is not None:
        block.responsible_party = agency.agency_name
    return notes


def _describe(values: dict) -> str:
    parts = []
    for field, value in values.items():
        if field == "responsible_party":
            continue
        if field in ("classification", "allocation"):
            parts.append(f"{field} {value}")
        elif field == "vendor_id":
            parts.append(f"agency / service vendor {value.vendor_name}")
        elif field == "cause_code":
            parts.append(f"cause {value}")
        elif hasattr(value, "id"):
            parts.append(f"{FIELD_LABELS.get(field, field)} {getattr(value, _code_field(type(value)))}")
    return " · ".join(filter(None, parts))


def preview(db: Session, organization_id: str, data) -> dict:
    values, _labels = _resolve_values(db, organization_id, data)
    if not any(
        field in values
        for field in ASSIGNABLE + ("classification", "allocation", "vendor_id", "cause_code")
    ):
        raise HTTPException(422, "Choose at least one value to assign.")
    reports = _reports(db, organization_id, data.report_ids or [])
    blocks = _blocks(db, organization_id, [r.id for r in reports], data.block_ids or [])
    if not blocks:
        raise HTTPException(422, "No activity blocks match this selection.")
    picks, skipped = _targets(db, organization_id, blocks, data)
    changes = []
    for block in picks:
        before = {field: getattr(block, field, None) for field in SNAPSHOT_FIELDS}
        start = _snapshot(block)
        notes = _apply_to_block(block, values)  # mutated in memory only; never committed here
        if notes:
            skipped.append(
                {
                    "block_id": block.id,
                    "sequence_no": block.sequence_no,
                    "report_id": block.report_id,
                    "reason": " ".join(notes),
                }
            )
        after = {field: getattr(block, field, None) for field in SNAPSHOT_FIELDS}
        end = _snapshot(block)
        if start == end:
            continue
        changes.append(
            {
                "block_id": block.id,
                "sequence_no": block.sequence_no,
                "report_id": block.report_id,
                "before": before,
                "after": after,
            }
        )
    db.rollback()  # preview must not persist the trial mutation
    return {
        "changes": changes,
        "skipped": skipped,
        "summary": _describe(values),
        "assigned_fields": [field for field, value in values.items() if field != "responsible_party"],
    }


def apply(db: Session, organization_id: str, data, user: User, request=None) -> dict:
    values, _labels = _resolve_values(db, organization_id, data)
    if not any(
        field in values
        for field in ASSIGNABLE + ("classification", "allocation", "vendor_id", "cause_code")
    ):
        raise HTTPException(422, "Choose at least one value to assign.")
    reports = _reports(db, organization_id, data.report_ids or [])
    blocks = _blocks(db, organization_id, [r.id for r in reports], data.block_ids or [])
    if not blocks:
        raise HTTPException(422, "No activity blocks match this selection.")
    picks, skipped = _targets(db, organization_id, blocks, data)
    now = datetime.now(UTC)
    changed = 0
    for block in picks:
        before = _snapshot(block)
        notes = _apply_to_block(block, values)
        after = _snapshot(block)
        if notes:
            skipped.append(
                {
                    "block_id": block.id,
                    "sequence_no": block.sequence_no,
                    "report_id": block.report_id,
                    "reason": " ".join(notes),
                }
            )
        if before == after:
            continue  # nothing this instruction can legally change here
        block.review_state = "edited"
        block.reviewer_user_id = user.id
        block.reviewed_at = now
        changed += 1
    remaining = []
    for report in reports:
        for block in _blocks(db, organization_id, [report.id], []):
            if message := describe_missing(block):
                remaining.append(message)
        report.updated_by = _actor(user)
        report.updated_at = now
        if report.extraction_status == "needs_review" and not any(
            b.review_state == "suggested" for b in _blocks(db, organization_id, [report.id], [])
        ):
            report.extraction_status = "reviewed"
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        entity_type="ops_report",
        entity_id=reports[0].id if len(reports) == 1 else None,
        entity_label=f"{len(reports)} report(s)",
        action="bulk-assign",
        summary=(
            f"Bulk assigned {_describe(values)} to {changed} block(s) in "
            f"{len(reports)} report(s); {len(skipped)} skipped"
        ),
        request=request,
    )
    db.commit()
    return {
        "changed_count": changed,
        "skipped": skipped,
        "remaining_mandatory": remaining[:100],
        "summary": _describe(values),
    }
