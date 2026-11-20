"""Sequence codes: link a daily-report line to a programme activity.

Lead/lag is computed per sequence code, never from the wording of a narrative.
Every line of a baseline programme carries a ``sequence_no``; a daily-report line
opts in by carrying that code in ``timeline_code``. The hours of all the lines
sharing a code are summed across the baseline's whole scope and compared with
the programme's planned hours for the code:

* ``variance = planned − Σ actual`` → positive = lead, negative = lag;
* the sum spans every non-deleted block of the same well/scope tied to the same
  baseline version — not just the report being edited — so a job logged over
  three days compares correctly against one programme row;
* lines without a code are excluded and say so; nothing is guessed.

The bulk actions here apply one explicit instruction to many lines. Preview
never writes. Apply writes only editable reports, refreshes the comparison
arithmetic through the baseline recompute, marks the touched lines ``edited``
and records one audit entry.
"""

from __future__ import annotations

from decimal import Decimal

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.precision import rounded
from app.models import User
from app.models.operations import OpsActivityBlock, OpsDailyReport, OpsPlanItem, OpsPlanVersion
from app.services.audit import record as audit_record
from app.services.operations import reports as reports_svc

EDITABLE = ("draft", "in_review", "rejected")


def _actor(user: User) -> str:
    return user.email or user.full_name or str(user.id)


def _baseline_for_report(db: Session, report: OpsDailyReport) -> OpsPlanVersion | None:
    return reports_svc._baseline_for(db, report)


def _baseline_for_plan(db: Session, organization_id: str, plan_id: str) -> OpsPlanVersion:
    baseline = db.scalar(
        select(OpsPlanVersion).where(
            OpsPlanVersion.id == plan_id,
            OpsPlanVersion.organization_id == organization_id,
            OpsPlanVersion.is_deleted.is_(False),
        )
    )
    if baseline is None:
        raise HTTPException(404, "Timeline not found.")
    return baseline


def _items(db: Session, baseline: OpsPlanVersion) -> list[OpsPlanItem]:
    return list(
        db.scalars(
            select(OpsPlanItem)
            .where(
                OpsPlanItem.organization_id == baseline.organization_id,
                OpsPlanItem.plan_version_id == baseline.id,
            )
            .order_by(OpsPlanItem.sequence_no)
        )
    )


def _hours(value) -> Decimal | None:
    return reports_svc._as_decimal(value)


def report_codes(db: Session, organization_id: str, report_id: str) -> dict:
    """The programme a report is compared against, and its linkable codes."""
    report = reports_svc.get_report(db, organization_id, report_id)
    baseline = _baseline_for_report(db, report)
    if baseline is None:
        return {
            "plan_version_id": None,
            "plan_label": "",
            "plan_status": "",
            "basis": "no active programme",
            "codes": [],
        }
    return {
        "plan_version_id": baseline.id,
        "plan_label": baseline.label or f"v{baseline.version_no}",
        "plan_status": baseline.status,
        "basis": f"programme {baseline.label or f'v{baseline.version_no}'}",
        "codes": [
            {
                "sequence_no": item.sequence_no,
                "description": (item.description or "")[:500],
                "planned_hours": _hours(item.planned_hours),
                "target_depth_m": _hours(item.target_depth_m),
                "cum_planned_days": _hours(item.cum_planned_days),
            }
            for item in _items(db, baseline)
        ],
    }


def _blocks(db: Session, organization_id: str, block_ids: list[str]) -> list[OpsActivityBlock]:
    blocks = list(
        db.scalars(
            select(OpsActivityBlock)
            .join(OpsDailyReport, OpsDailyReport.id == OpsActivityBlock.report_id)
            .where(
                OpsActivityBlock.organization_id == organization_id,
                OpsActivityBlock.is_deleted.is_(False),
                OpsDailyReport.is_deleted.is_(False),
                OpsActivityBlock.id.in_(block_ids),
            )
            .order_by(OpsActivityBlock.sequence_no)
            .with_for_update()
        )
    )
    if len(blocks) != len(set(block_ids)):
        raise HTTPException(422, "One or more selected lines no longer exist in this workspace.")
    report_ids = {b.report_id for b in blocks}
    reports = db.scalars(
        select(OpsDailyReport).where(OpsDailyReport.id.in_(report_ids))
    ).all()
    locked = [r for r in reports if r.status not in EDITABLE]
    if locked:
        raise HTTPException(
            409,
            "Sequence codes can only change editable drafts. Reopen the submitted or approved "
            "report(s) first: " + ", ".join(sorted({r.well_code_snapshot or r.id for r in locked})),
        )
    return blocks


def _plan_item(db: Session, baseline: OpsPlanVersion, sequence_no: int) -> OpsPlanItem:
    item = db.scalar(
        select(OpsPlanItem).where(
            OpsPlanItem.organization_id == baseline.organization_id,
            OpsPlanItem.plan_version_id == baseline.id,
            OpsPlanItem.sequence_no == sequence_no,
        )
    )
    if item is None:
        raise HTTPException(
            422, f"Sequence code {sequence_no} is not a line of this well's baseline programme."
        )
    return item


def preview(db: Session, organization_id: str, data) -> dict:
    """Show what linking the selected lines to one code would do. Never writes."""
    if not data.block_ids:
        raise HTTPException(422, "Select at least one line to code.")
    blocks = _blocks(db, organization_id, data.block_ids)
    by_report: dict[str, OpsDailyReport] = {}
    for block in blocks:
        if block.report_id not in by_report:
            report = reports_svc.get_report(db, organization_id, block.report_id)
            by_report[block.report_id] = report
    baselines = {rid: _baseline_for_report(db, r) for rid, r in by_report.items()}
    missing_baseline = [r for r in by_report.values() if baselines[r.id] is None]
    if missing_baseline:
        raise HTTPException(
            422,
            "No baseline programme is linked to "
            + ", ".join(sorted({r.well_code_snapshot or r.id for r in missing_baseline}))
            + ". Activate a timeline first.",
        )
    items = {}
    for report in by_report.values():
        baseline = baselines[report.id]
        item = _plan_item(db, baseline, data.sequence_no)
        items[report.id] = (baseline, item)
    code = str(data.sequence_no)
    out_lines = []
    for block in blocks:
        baseline, item = items[block.report_id]
        out_lines.append(
            {
                "block_id": block.id,
                "report_id": block.report_id,
                "sequence_no": block.sequence_no,
                "before": block.timeline_code,
                "after": code,
                "narrative": (block.narrative or "")[:200],
            }
        )
    item0 = items[blocks[0].report_id][1]
    same_baseline = len({b.id for b, _ in items.values()}) == 1
    return {
        "sequence_no": data.sequence_no,
        "description": item0.description if same_baseline else "(multiple baselines)",
        "planned_hours": _hours(item0.planned_hours) if same_baseline else None,
        "eligible": len(out_lines),
        "lines": out_lines,
        "skipped": [],
        "summary": f"code {code} → {item0.description}" if same_baseline else f"code {code}",
    }


def apply(db: Session, organization_id: str, data, user: User, request=None) -> dict:
    """Link the selected lines to one programme code, then recompute lead/lag."""
    if not data.block_ids:
        raise HTTPException(422, "Select at least one line to code.")
    blocks = _blocks(db, organization_id, data.block_ids)
    by_report: dict[str, list[OpsActivityBlock]] = {}
    for block in blocks:
        by_report.setdefault(block.report_id, []).append(block)
    code = str(data.sequence_no)
    now = datetime.now(UTC)
    applied = 0
    baselines: dict[str, OpsPlanVersion] = {}
    for report_id, rows in by_report.items():
        report = reports_svc.get_report(db, organization_id, report_id)
        baseline = _baseline_for_report(db, report)
        if baseline is None:
            raise HTTPException(422, "The report has no baseline programme. Activate a timeline first.")
        baselines[report_id] = baseline
        item = _plan_item(db, baseline, data.sequence_no)
        for block in rows:
            block.timeline_code = code
            block.review_state = "edited"
            block.reviewer_user_id = user.id
            block.reviewed_at = now
            # The link is explicit: point the plan fields at the chosen code's
            # row so the recompute and every later read agree.
            block.timeline_plan_item_id = item.id
            applied += 1
        report.updated_by = _actor(user)
        report.updated_at = now
    for baseline in {b.id: b for b in baselines.values()}.values():
        reports_svc._recompute_baseline(db, baseline, f"programme {baseline.label or f'v{baseline.version_no}'}")
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="update",
        entity_type="ops_plan_version",
        entity_id=(sorted({b.id for b in baselines.values()})[0] if baselines else code),
        entity_label=f"sequence code {code}",
        summary=(
            f"Linked {applied} line(s) to sequence code {code} "
            f"across {len(baselines)} report(s) and recomputed plan-vs-timeline"
        ),
        request=request,
    )
    db.commit()
    return {
        "applied_count": applied,
        "sequence_no": data.sequence_no,
        "skipped": [],
        "summary": f"{applied} line(s) coded {code}",
    }


def timeline_rollup(db: Session, organization_id: str, plan_id: str, user: User) -> dict:
    """Per-code planned vs actual hours across the baseline's whole scope."""
    baseline = _baseline_for_plan(db, organization_id, plan_id)
    items = _items(db, baseline)
    scoped = reports_svc._scope_blocks(db, baseline)
    members: dict[str, list[OpsActivityBlock]] = {}
    uncoded = 0
    for block in scoped:
        code = (block.timeline_code or "").strip()
        if code:
            members.setdefault(code, []).append(block)
        else:
            uncoded += 1
    codes = []
    total_planned = Decimal(0)
    total_actual = Decimal(0)
    for item in items:
        code = str(item.sequence_no)
        group = members.get(code, [])
        planned = _hours(item.planned_hours)
        report_ids = {b.report_id for b in group}
        if group:
            actual = sum((reports_svc._line_contribution(b) for b in group), Decimal(0))
            total_planned += planned or Decimal(0)
            total_actual += actual
            variance = (planned - actual) if planned is not None else None
        else:
            actual = None
            variance = None  # nothing logged yet: no judgement is invented
        codes.append(
            {
                "sequence_no": item.sequence_no,
                "description": (item.description or "")[:500],
                "planned_hours": planned,
                "target_depth_m": _hours(item.target_depth_m),
                "actual_hours": rounded(actual) if actual is not None else None,
                "variance_hours": rounded(variance) if variance is not None else None,
                "variance_days": rounded(variance / Decimal(24)) if variance is not None else None,
                "comparison": (
                    "ahead"
                    if (variance is not None and variance > 0)
                    else ("behind" if (variance is not None and variance < 0) else "on")
                ),
                "line_count": len(group),
                "report_count": len(report_ids),
            }
        )
    total_variance = total_planned - total_actual
    return {
        "plan_version_id": baseline.id,
        "plan_label": baseline.label or f"v{baseline.version_no}",
        "planned_hours": rounded(total_planned),
        "actual_hours": rounded(total_actual),
        "variance_hours": rounded(total_variance),
        "comparison": (
            "ahead" if total_variance > 0 else ("behind" if total_variance < 0 else "on")
        ),
        "codes": codes,
        "uncoded_lines": uncoded,
    }
