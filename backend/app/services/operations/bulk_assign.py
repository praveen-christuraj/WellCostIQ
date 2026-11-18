"""Bulk assignment of operation, activity, NPT, cause and agency codes.

The daily report page lists every extracted block. Correcting fifty rows one
dialog at a time is where review errors come from, so this service applies one
explicit instruction to many blocks and reports exactly what happened:

* ``preview`` never writes. It returns the resulting values, the blocks that
  would be skipped and the reason, so the dialog can be shown before saving.
* ``apply`` writes only editable drafts, keeps machine evidence, marks every
  touched block as ``edited`` with the reviewer's identity, and records one
  audit entry that names the report, the fields and the counts.

Nothing here bypasses the classification rule. A field the chosen
classification does not allow (an NPT code on Planned work) is refused, and a
block that cannot legally hold the value is skipped with a reason rather than
silently changed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.operations.requirements import BULK_ALLOWED, FIELD_LABELS, bulk_refusal, describe_missing
from app.models import User
from app.models.master_data import Activity
from app.models.operations import (
    OpsActivityBlock,
    OpsActivityCode,
    OpsAgency,
    OpsCause,
    OpsDailyReport,
    OpsNptCode,
    OpsOperationCode,
    OpsPhaseCode,
)
from app.models.vendor_master import Vendor
from app.services.audit import record as audit_record

EDITABLE = ("draft", "in_review", "rejected")

# field name -> (workspace model, label attribute)
LIBRARY = {
    "operation_code_id": (OpsOperationCode, "operation_name"),
    "activity_code_id": (OpsActivityCode, "activity_name"),
    "npt_code_id": (OpsNptCode, "npt_name"),
    "cause_id": (OpsCause, "cause_name"),
    "agency_id": (OpsAgency, "agency_name"),
    "phase_id": (OpsPhaseCode, "phase_name"),
}
ASSIGNABLE = ("operation_code_id", "activity_code_id", "npt_code_id", "cause_id", "agency_id")


def _actor(user: User) -> str:
    return user.email or user.full_name or str(user.id)


def _code_field(model) -> str:
    for field in ("operation_code", "activity_code", "npt_code", "cause_code", "agency_code", "phase_code"):
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
        if field == "agency_id":
            vendor_id = getattr(data, "vendor_id", None)
            agency_id = getattr(data, "agency_id", None)
            if vendor_id:
                vendor, label = _resolve_vendor(db, organization_id, vendor_id)
                values["vendor_id"] = vendor
                values["responsible_party"] = vendor.vendor_name
                labels["agency_id"] = f"agency {label}"
            elif agency_id:
                agency, label = _resolve(db, organization_id, "agency_id", agency_id)
                values["agency_id"] = agency
                values["responsible_party"] = agency.agency_name
                labels["agency_id"] = f"library agency {label}"
            continue
        value_id = getattr(data, field, None)
        if not value_id:
            continue
        row, label = _resolve(db, organization_id, field, value_id)
        values[field] = row
        labels[field] = label
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
    if getattr(data, "classification", None):
        values["classification"] = data.classification
        labels["classification"] = f"classification {data.classification}"
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


def _snapshot(block) -> tuple:
    """Every value a bulk instruction can write, in one comparable tuple."""
    return (
        block.operation_code_id,
        block.activity_code_id,
        block.npt_code_id,
        block.cause_code,
        block.responsible_party,
        block.agency_id,
        block.vendor_id,
        block.classification,
    )


def _apply_to_block(block, values: dict) -> list[str]:
    """Write the values onto one block; return the notes worth telling the user.

    A field the classification forbids is skipped on that block — the rest of the
    instruction still lands. The note names the field and the classification, so
    the summary can say "3 changed, 2 NPT codes skipped on Planned work".
    """
    classification = values.get("classification") or block.classification
    notes: list[str] = []
    forbidden = [
        field for field in ("npt_code_id",) if field in values and field not in BULK_ALLOWED.get(classification, ())
    ]
    if forbidden:
        notes.append(bulk_refusal(classification, [(field, values[field]) for field in forbidden]))
    if classification != block.classification and values.get("classification"):
        block.classification = classification
        block.allocation = "PT" if classification == "Planned" else classification
        block.is_productive = classification != "NPT"
        block.classification_source = "reviewer"
    for field, value in values.items():
        if field in ("classification", "responsible_party", "cause_code"):
            continue
        if field in forbidden:
            continue
        if field == "vendor_id":
            block.vendor_id = value.id
            continue
        setattr(block, field, getattr(value, "id", value))
    if "cause_code" in values:
        block.cause_code = values["cause_code"]
    if "responsible_party" in values:
        block.responsible_party = values["responsible_party"]
    if "agency_id" in values and "vendor_id" not in values:
        block.vendor_id = None  # a library agency is not a Master Data vendor
    if block.npt_code_id:
        code = values.get("npt_code_id")
        if code is not None:
            block.npt_code_snapshot = code.npt_code
    return notes


def _describe(values: dict) -> str:
    parts = []
    for field, value in values.items():
        if field == "classification":
            parts.append(f"classification {value}")
        elif field == "responsible_party":
            parts.append(f"agency {value}")
        elif field == "vendor_id":
            parts.append(f"agency {value.vendor_name}")
        elif hasattr(value, "id"):
            parts.append(f"{FIELD_LABELS.get(field, field)} {getattr(value, _code_field(type(value)))}")
        elif field == "cause_code":
            parts.append(f"cause {value}")
    return " · ".join(filter(None, parts))


def preview(db: Session, organization_id: str, data) -> dict:
    values, _labels = _resolve_values(db, organization_id, data)
    if not any(field in values for field in ASSIGNABLE + ("classification",)):
        raise HTTPException(422, "Choose at least one value to assign.")
    reports = _reports(db, organization_id, data.report_ids or [])
    blocks = _blocks(db, organization_id, [r.id for r in reports], data.block_ids or [])
    if not blocks:
        raise HTTPException(422, "No activity blocks match this selection.")
    picks, skipped = _targets(db, organization_id, blocks, data)
    changes = []
    for block in picks:
        before = {
            "operation_code_id": block.operation_code_id,
            "activity_code_id": block.activity_code_id,
            "npt_code_id": block.npt_code_id,
            "cause_code": block.cause_code,
            "responsible_party": block.responsible_party,
            "classification": block.classification,
        }
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
        after = {
            "operation_code_id": block.operation_code_id,
            "activity_code_id": block.activity_code_id,
            "npt_code_id": block.npt_code_id,
            "cause_code": block.cause_code,
            "responsible_party": block.responsible_party,
            "classification": block.classification,
        }
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
    if not any(field in values for field in ASSIGNABLE + ("classification",)):
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
