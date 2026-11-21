"""Sequence codes: link a daily-report line to a programme activity.

Lead and lag are computed per sequence code, never from the wording of a narrative.
Every line of a baseline programme carries a ``sequence_no``; a daily-report line
opts in by carrying that code. The hours of all the lines sharing a code are summed
across the baseline's whole scope and compared with the programme's planned hours
for the code:

    variance (hours) = planned − Σ actual     positive = lead, negative = lag
    variance (days)  = variance (hours) / 24

**Only a closed code carries that verdict.** A plan of 100 h with 12 h logged is not
88 hours early — it is in progress, and the difference is the work still owed. A code
nobody has touched is not started, not "on plan". Hours against no code are Unplanned
Activity: they raise actual hours while planned hours stay put, so they can only
produce lag. A planned activity that will never be done is skipped, and its hours are
reported once as saved.

The arithmetic itself lives in ``app.domain.operations.sequence``. This module is the
write side around it: it validates, previews, applies, records one audit entry per
action, and asks the reports service to recompute the comparison for the baseline.

The bulk actions here apply one explicit instruction to many lines. Preview never
writes. Apply writes only editable reports, refreshes the comparison arithmetic
through the baseline recompute, marks the touched lines ``edited`` and records one
audit entry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.precision import rounded
from app.domain.operations import sequence
from app.domain.operations.durations import utc
from app.models import User
from app.models.operations import (
    OpsActivityBlock,
    OpsActivityBlockCode,
    OpsDailyReport,
    OpsPlanItem,
    OpsPlanVersion,
)
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


def _hours(value) -> Decimal | None:
    return reports_svc._as_decimal(value)


def _ledger(db: Session, baseline: OpsPlanVersion, *, confirmed_only: bool = True) -> sequence.Ledger:
    return reports_svc._ledger(db, baseline, confirmed_only=confirmed_only)


def _policy_out(policy: sequence.Policy) -> dict:
    return {
        "uncoded": policy.uncoded,
        "npt": policy.npt,
        "skipped_credit": policy.skipped_credit,
        "auto_close_tolerance_pct": policy.auto_close_tolerance_pct,
        "auto_close": policy.auto_close,
    }


def _code_out(row: sequence.CodeRow) -> dict:
    return {
        "sequence_no": row.sequence_no,
        "description": (row.description or "")[:500],
        "planned_hours": row.planned_hours,
        "target_depth_m": row.target_depth_m,
        "cum_planned_days": row.saved_cum_days,
        "item_id": row.item_id,
        "state": row.state,
        "remaining_hours": row.remaining_hours,
        "actual_hours": row.actual_hours,
        "is_skipped": row.state == sequence.SKIPPED,
        "closed": row.state == sequence.COMPLETE,
        "effective_cum_days": row.effective_cum_days,
    }


def _resolve_item(db: Session, baseline: OpsPlanVersion, item_id: str | None, sequence_no: int | None) -> OpsPlanItem:
    """Find the programme row a request names, by identity first.

    ``item_id`` is the identity and is preferred. ``sequence_no`` stays for a code
    typed from a printed programme and is resolved **on this baseline only** — a
    code is never carried across wells, scopes or versions.
    """
    if item_id:
        item = db.scalar(
            select(OpsPlanItem).where(
                OpsPlanItem.id == item_id,
                OpsPlanItem.organization_id == baseline.organization_id,
                OpsPlanItem.plan_version_id == baseline.id,
            )
        )
        if item is None:
            raise HTTPException(422, "That sequence code is not a line of this well's baseline programme.")
        return item
    if sequence_no is None:
        raise HTTPException(422, "Choose the programme activity to code these lines against.")
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
            "policy": None,
        }
    ledger = _ledger(db, baseline)
    return {
        "plan_version_id": baseline.id,
        "plan_label": baseline.label or f"v{baseline.version_no}",
        "plan_status": baseline.status,
        "basis": f"programme {baseline.label or f'v{baseline.version_no}'}",
        "codes": [_code_out(row) for row in ledger.codes],
        "policy": _policy_out(ledger.policy),
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
            # Lock only the lines, never the joined report: a join-level FOR UPDATE
            # is an error on PostgreSQL, and the report rows are read after this.
            .with_for_update(of=OpsActivityBlock)
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


def _baselines_for_blocks(db: Session, organization_id: str, blocks) -> dict[str, OpsPlanVersion]:
    out: dict[str, OpsPlanVersion] = {}
    for report_id in {b.report_id for b in blocks}:
        report = reports_svc.get_report(db, organization_id, report_id)
        baseline = _baseline_for_report(db, report)
        if baseline is None:
            raise HTTPException(
                422,
                "No baseline programme is linked to "
                + (report.well_code_snapshot or report_id)
                + ". Activate a timeline first.",
            )
        out[report_id] = baseline
    return out


def preview(db: Session, organization_id: str, data) -> dict:
    """Show what linking the selected lines to one code would do. Never writes."""
    if not data.block_ids:
        raise HTTPException(422, "Select at least one line to code.")
    blocks = _blocks(db, organization_id, data.block_ids)
    baselines = _baselines_for_blocks(db, organization_id, blocks)
    items: dict[str, tuple[OpsPlanVersion, OpsPlanItem]] = {}
    for report_id, baseline in baselines.items():
        items[report_id] = (baseline, _resolve_item(db, baseline, data.item_id, data.sequence_no))
    item0 = items[blocks[0].report_id][1]
    same_baseline = len({b.id for b, _ in items.values()}) == 1
    out_lines = []
    for block in blocks:
        _baseline, item = items[block.report_id]
        out_lines.append(
            {
                "block_id": block.id,
                "report_id": block.report_id,
                "sequence_no": block.sequence_no,
                "before": block.timeline_code,
                "after": str(item.sequence_no),
                "narrative": (block.narrative or "")[:200],
            }
        )
    # What the code's arithmetic will say once these lines carry it. This is where
    # an engineer sees, before applying, that the code is in progress — not that
    # they are about to create an 88-hour lead.
    ledger = _ledger(db, items[blocks[0].report_id][0])
    state = next((row for row in ledger.codes if row.item_id == item0.id), None)
    warnings: list[str] = []
    if same_baseline and state is not None:
        if state.state == sequence.SKIPPED:
            warnings.append(
                f"Sequence {state.sequence_no} is skipped. Hours coded to it will not be attributed: "
                "un-skip the activity first, or code the work to the activity that did it."
            )
        elif state.state == sequence.IN_PROGRESS:
            warnings.append(
                f"Sequence {state.sequence_no} will still be in progress: "
                f"{state.actual_hours or 0} of {state.planned_hours or 0} h logged, "
                f"{state.remaining_hours or 0} h remaining. Close the activity to record a lead or a lag."
            )
    return {
        "sequence_no": item0.sequence_no,
        "description": item0.description if same_baseline else "(multiple baselines)",
        "planned_hours": _hours(item0.planned_hours) if same_baseline else None,
        "eligible": len(out_lines),
        "lines": out_lines,
        "skipped": [],
        "summary": (
            f"code {item0.sequence_no} → {item0.description}" if same_baseline else f"code {item0.sequence_no}"
        ),
        "code_state": state.state if state else "",
        "actual_hours": state.actual_hours if state else None,
        "remaining_hours": state.remaining_hours if state else None,
        "variance_hours": state.variance_hours if state else None,
        "variance_days": state.variance_days if state else None,
        "warnings": warnings,
    }


def apply(db: Session, organization_id: str, data, user: User, request=None) -> dict:
    """Link the selected lines to one programme code, then recompute the comparison."""
    if not data.block_ids:
        raise HTTPException(422, "Select at least one line to code.")
    blocks = _blocks(db, organization_id, data.block_ids)
    by_report: dict[str, list[OpsActivityBlock]] = {}
    for block in blocks:
        by_report.setdefault(block.report_id, []).append(block)
    now = datetime.now(UTC)
    applied = 0
    baselines: dict[str, OpsPlanVersion] = {}
    target_sequence: int | None = None
    target_item_id: str | None = None
    for report_id, rows in by_report.items():
        report = reports_svc.get_report(db, organization_id, report_id)
        baseline = _baseline_for_report(db, report)
        if baseline is None:
            raise HTTPException(422, "The report has no baseline programme. Activate a timeline first.")
        baselines[report_id] = baseline
        item = _resolve_item(db, baseline, data.item_id, data.sequence_no)
        target_sequence = item.sequence_no
        target_item_id = item.id
        for block in rows:
            block.timeline_code = str(item.sequence_no)
            block.timeline_plan_item_id = item.id
            block.timeline_plan_step_no = item.sequence_no
            # Coding the line again reverses an earlier clear.
            block.timeline_split_state = ""
            block.review_state = "edited"
            block.reviewer_user_id = user.id
            block.reviewed_at = now
            # A line that carried a split keeps its allocation unless this action
            # is explicitly re-coding the whole line; the split rows are cleared
            # because they name the codes the hours used to belong to.
            if db.scalars(
                select(OpsActivityBlockCode).where(OpsActivityBlockCode.block_id == block.id).limit(1)
            ).first():
                db.execute(
                    OpsActivityBlockCode.__table__.delete().where(
                        OpsActivityBlockCode.block_id == block.id
                    )
                )
                block.timeline_split_state = ""
            applied += 1
        report.updated_by = _actor(user)
        report.updated_at = now
    ledger = None
    for baseline in {b.id: b for b in baselines.values()}.values():
        ledger = reports_svc._recompute_baseline(
            db, baseline, f"programme {baseline.label or f'v{baseline.version_no}'}"
        )
    state = None
    if ledger is not None and target_item_id:
        state = next((row for row in ledger.codes if row.item_id == target_item_id), None)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="update",
        entity_type="ops_plan_version",
        entity_id=(sorted({b.id for b in baselines.values()})[0] if baselines else str(target_sequence)),
        entity_label=f"sequence code {target_sequence}",
        summary=(
            f"Linked {applied} line(s) to sequence code {target_sequence} "
            f"across {len(baselines)} report(s) and recomputed plan-vs-timeline"
        ),
        request=request,
    )
    db.commit()
    return {
        "applied_count": applied,
        "sequence_no": target_sequence,
        "item_id": target_item_id,
        "skipped": [],
        "summary": (
            f"{applied} line(s) coded {target_sequence}"
            + (f" · {state.state}" if state is not None else "")
        ),
        "code_state": state.state if state is not None else "",
        "variance_hours": state.variance_hours if state is not None else None,
        "variance_days": state.variance_days if state is not None else None,
    }


def apply_split(db: Session, organization_id: str, data, user: User, request=None) -> dict:
    """Share one line's hours between several programme codes.

    A narrative line can genuinely do two programme activities. Picking one code
    would make the other code's actual wrong by construction, so the hours are
    split explicitly:

    * ``Σ allocations ≤ the line's own hours`` — enforced exactly, at three places,
      never "roughly";
    * the remainder stays in the unplanned bucket and is **named** in the response,
      so a split can never quietly lose an hour;
    * the same code twice is refused, and a code that is not on this baseline is
      refused, rather than creating an unattributable hour.
    """
    block = _blocks(db, organization_id, [data.block_id])[0]
    report = reports_svc.get_report(db, organization_id, block.report_id)
    baseline = _baseline_for_report(db, report)
    if baseline is None:
        raise HTTPException(422, "The report has no baseline programme. Activate a timeline first.")
    line_hours = reports_svc._line_contribution(block)
    if line_hours is None or line_hours <= 0:
        raise HTTPException(422, "This line has no hours to split.")

    resolved: list[tuple[OpsPlanItem, Decimal]] = []
    seen: set[str] = set()
    total = Decimal(0)
    for allocation in data.allocations:
        item = _resolve_item(db, baseline, allocation.item_id, allocation.sequence_no)
        if item.id in seen:
            raise HTTPException(422, f"Sequence code {item.sequence_no} appears twice in this split.")
        seen.add(item.id)
        hours = rounded(reports_svc._as_decimal(allocation.hours) or Decimal(0))
        total += hours
        resolved.append((item, hours))
    if total <= 0:
        raise HTTPException(422, "Allocate at least one hour to a sequence code.")
    if total > line_hours:
        raise HTTPException(
            422,
            f"The allocations total {total} h but this line logged {line_hours} h. "
            "Reduce an allocation; hours cannot be invented by splitting.",
        )
    if not data.remainder_to_unplanned and total != line_hours:
        raise HTTPException(
            422,
            f"The allocations total {total} h of {line_hours} h logged. Allocate the whole line, "
            "or allow the remainder to stay unplanned.",
        )

    now = datetime.now(UTC)
    db.execute(OpsActivityBlockCode.__table__.delete().where(OpsActivityBlockCode.block_id == block.id))
    for item, hours in resolved:
        db.add(
            OpsActivityBlockCode(
                organization_id=organization_id,
                block_id=block.id,
                plan_item_id=item.id,
                sequence_no_snapshot=item.sequence_no,
                hours=hours,
                created_by=_actor(user),
                updated_by=_actor(user),
            )
        )
    remainder = rounded(line_hours - total)
    block.timeline_split_state = "split"
    block.review_state = "edited"
    block.reviewer_user_id = user.id
    block.reviewed_at = now
    report.updated_by = _actor(user)
    report.updated_at = now
    # The split is the assignment: a single stored code on the line would be a second,
    # competing claim on the same hours. The split rows alone carry it.
    block.timeline_code = None
    block.timeline_plan_item_id = None
    block.timeline_plan_step_no = None
    db.flush()
    reports_svc._recompute_baseline(
        db, baseline, f"programme {baseline.label or f'v{baseline.version_no}'}"
    )
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="update",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=f"{report.well_code_snapshot} {report.report_date}",
        summary=(
            f"Split line {block.sequence_no} ({line_hours} h) across "
            + ", ".join(f"code {i.sequence_no} ({h} h)" for i, h in resolved)
            + (f"; {remainder} h left unplanned" if remainder else "")
        ),
        request=request,
    )
    db.commit()
    return {
        "block_id": block.id,
        "item_id": resolved[0][0].id if len(resolved) == 1 else None,
        "allocated_hours": rounded(total),
        "line_hours": line_hours,
        "remainder_hours": remainder,
        "allocations": [
            {"item_id": i.id, "sequence_no": i.sequence_no, "hours": h} for i, h in resolved
        ],
        "summary": (
            f"{rounded(total)} h of {line_hours} h allocated to {len(resolved)} code(s)"
            + (f"; {remainder} h remains unplanned" if remainder else "")
        ),
    }


def clear_codes(db: Session, organization_id: str, data, user: User, request=None) -> dict:
    """Remove the code from these lines, deliberately making the hours unplanned."""
    if not data.acknowledge_unplanned:
        raise HTTPException(
            422,
            "Clearing a code makes the line's hours Unplanned Activity, which reads as lag. "
            "Acknowledge that to continue.",
        )
    blocks = _blocks(db, organization_id, data.block_ids)
    baselines = _baselines_for_blocks(db, organization_id, blocks)
    now = datetime.now(UTC)
    cleared = 0
    for block in blocks:
        block.timeline_code = None
        block.timeline_plan_item_id = None
        block.timeline_plan_step_no = None
        # Recorded as a decision, not as an absence: a suggestion must not put the
        # code back the next time the report is saved.
        block.timeline_split_state = "unplanned"
        block.review_state = "edited"
        block.reviewer_user_id = user.id
        block.reviewed_at = now
        db.execute(OpsActivityBlockCode.__table__.delete().where(OpsActivityBlockCode.block_id == block.id))
        cleared += 1
    db.flush()
    for report_id, baseline in baselines.items():
        report = reports_svc.get_report(db, organization_id, report_id)
        report.updated_by = _actor(user)
        report.updated_at = now
        reports_svc._recompute_baseline(
            db, baseline, f"programme {baseline.label or f'v{baseline.version_no}'}"
        )
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="update",
        entity_type="ops_report",
        entity_id=blocks[0].report_id if blocks else None,
        entity_label=f"{cleared} line(s)",
        summary=f"Cleared the sequence code from {cleared} line(s); the hours are now unplanned activity",
        request=request,
    )
    db.commit()
    return {"cleared_count": cleared, "summary": f"{cleared} line(s) are now unplanned activity"}


def set_item_state(
    db: Session, organization_id: str, plan_id: str, item_id: str, data, user: User, request=None
) -> dict:
    """Skip a planned activity, or bring it back into the plan.

    A skipped activity will never be done. Its planned hours leave the plan's scope
    and are reported once as saved; every later activity's *effective* cumulative
    position moves earlier by the saved time. The saved programme curve is never
    rewritten, so a submitted month keeps reading as it was signed.
    """
    baseline = _baseline_for_plan(db, organization_id, plan_id)
    if baseline.status == "superseded":
        # A draft can be adjusted freely and an active programme is the live
        # schedule. A superseded version is history: adjust it by reopening it,
        # never in place, or the month it was compared against changes under it.
        raise HTTPException(409, "A superseded timeline is history. Reopen it, or adjust the active one.")
    item = db.scalar(
        select(OpsPlanItem)
        .where(
            OpsPlanItem.id == item_id,
            OpsPlanItem.organization_id == organization_id,
            OpsPlanItem.plan_version_id == baseline.id,
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(404, "That activity is not a line of this timeline.")
    if data.expected_updated_at and utc(item.updated_at) != utc(data.expected_updated_at):
        raise HTTPException(409, "This activity changed since you opened it. Reload before applying the change.")
    reason = (data.reason or "").strip()
    before = getattr(item, "state", "planned")
    if data.state == "skipped":
        if before == "skipped":
            raise HTTPException(409, "This activity is already skipped.")
        if getattr(item, "closed_at", None) is not None:
            raise HTTPException(
                409,
                "A closed activity cannot be skipped. Reopen the activity first — its hours were already "
                "reported as finished work.",
            )
        coded = db.scalar(
            select(OpsActivityBlock.id)
            .where(OpsActivityBlock.timeline_plan_item_id == item.id, OpsActivityBlock.is_deleted.is_(False))
            .limit(1)
        )
        if coded is not None:
            raise HTTPException(
                409,
                "Hours are already logged against this activity. Move them to the activity that did the "
                "work, then skip it — otherwise its planned hours would be saved while its actual hours "
                "would have nowhere to go.",
            )
        if len(reason) < 3:
            raise HTTPException(422, "Say why this activity is skipped (at least 3 characters). It is kept.")
        item.state = "skipped"
        item.skip_reason = reason[:500]
        item.skipped_by = _actor(user)[:255]
        item.skipped_at = datetime.now(UTC)
    else:
        if before != "skipped":
            raise HTTPException(409, "This activity is not skipped.")
        item.state = "planned"
        item.skip_reason = ""
        item.skipped_by = ""
        item.skipped_at = None
    item.updated_at = datetime.now(UTC)
    ledger = reports_svc._recompute_baseline(
        db, baseline, f"programme {baseline.label or f'v{baseline.version_no}'}"
    )
    state = next((row for row in ledger.codes if row.item_id == item.id), None)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="update",
        entity_type="ops_plan",
        entity_id=baseline.id,
        entity_label=baseline.label,
        summary=(
            f"{'Skipped' if item.state == 'skipped' else 'Un-skipped'} sequence {item.sequence_no} "
            f"({item.description[:80]})"
            + (f": {reason[:200]}" if item.state == "skipped" else "")
        ),
        request=request,
    )
    db.commit()
    return {
        "item_id": item.id,
        "sequence_no": item.sequence_no,
        "state": state.state if state else "",
        "saved_planned_hours": state.saved_planned_hours if state else None,
        "planned_in_scope": ledger.totals.planned_in_scope,
        "planned_saved": ledger.totals.planned_saved,
        "summary": (
            f"Sequence {item.sequence_no} is skipped; {state.saved_planned_hours if state else 0} h of plan "
            "released"
            if item.state == "skipped"
            else f"Sequence {item.sequence_no} is back in the plan"
        ),
    }


def close_item(
    db: Session, organization_id: str, plan_id: str, item_id: str, data, user: User, request=None
) -> dict:
    """State that a planned activity is finished — the only route to a verdict.

    Closing is an explicit, audited act because 100 h finished in 90 and 100 h
    burned without finishing the hole are not the same event. Completion is never
    inferred from the hours, and never from a successor starting.
    """
    baseline = _baseline_for_plan(db, organization_id, plan_id)
    item = db.scalar(
        select(OpsPlanItem)
        .where(
            OpsPlanItem.id == item_id,
            OpsPlanItem.organization_id == organization_id,
            OpsPlanItem.plan_version_id == baseline.id,
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(404, "That activity is not a line of this timeline.")
    if data.expected_updated_at and utc(item.updated_at) != utc(data.expected_updated_at):
        raise HTTPException(409, "This activity changed since you opened it. Reload before closing it.")
    if getattr(item, "state", "planned") == "skipped":
        raise HTTPException(
            409, "A skipped activity cannot be closed: it will never be done. Un-skip it first."
        )
    if getattr(item, "closed_at", None) is not None:
        raise HTTPException(409, "This activity is already closed.")

    # The evidence an engineer closes on is every hour recorded against the
    # activity, drafts included — they are closing what is on the screen. The close
    # then *stamps* that actual, so the verdict no longer depends on which reports
    # happen to be submitted yet.
    ledger_before = _ledger(db, baseline, confirmed_only=False)
    state_before = next((row for row in ledger_before.codes if row.item_id == item.id), None)
    if state_before is None:  # pragma: no cover - defensive: the row was just read
        raise HTTPException(409, "This activity is not part of the current programme.")

    note = (data.note or "").strip()
    actual = reports_svc._as_decimal(data.actual_hours) if data.actual_hours is not None else None
    if actual is None:
        actual = state_before.actual_hours
    if actual is None or actual <= 0:
        raise HTTPException(
            422,
            "This activity has no logged hours. Enter the hours it actually took before closing it: "
            "a finished activity with no hours is a claim, not a record.",
        )
    if state_before.line_count == 0 and not note:
        raise HTTPException(
            422,
            "No daily-report line is coded to this activity. Closing it on typed hours needs a note "
            "saying where those hours are recorded.",
        )
    if not note and data.actual_hours is not None and (
        state_before.actual_hours is None or rounded(actual) != state_before.actual_hours
    ):
        raise HTTPException(
            422, "Entering hours that differ from the log needs a note. It is kept with the close."
        )

    now = datetime.now(UTC)
    item.closed_at = now
    item.closed_by = _actor(user)[:255]
    item.close_source = "confirmed"
    item.close_note = note[:500]
    # Hours typed at the close are kept only for an activity with no daily-report
    # line of its own. Where lines exist they are the record, so a correction or a
    # late submission keeps moving the verdict instead of being frozen here — which
    # is also why typing hours that disagree with the log asks for a note.
    item.closed_actual_hours = (
        rounded(actual) if state_before.line_count == 0 else None
    )
    item.updated_at = now
    reports_svc._recompute_baseline(
        db, baseline, f"programme {baseline.label or f'v{baseline.version_no}'}"
    )
    # Answer on the same evidence the close was made on: for an activity whose
    # hours sit on drafts, the confirmed-only ledger would show no actual at all and
    # report the whole plan as a lead.
    ledger = _ledger(db, baseline, confirmed_only=False)
    state = next((row for row in ledger.codes if row.item_id == item.id), None)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="review",
        entity_type="ops_plan",
        entity_id=baseline.id,
        entity_label=baseline.label,
        summary=(
            f"Closed sequence {item.sequence_no} ({item.description[:80]}) at {actual} h: "
            f"variance {state.variance_hours if state else '—'} h"
            + (f" — {note[:200]}" if note else "")
        ),
        request=request,
    )
    db.commit()
    return {
        "item_id": item.id,
        "sequence_no": item.sequence_no,
        "state": state.state if state else "",
        "planned_hours": state.planned_hours if state else None,
        "actual_hours": state.actual_hours if state else None,
        "variance_hours": state.variance_hours if state else None,
        "variance_days": state.variance_days if state else None,
        "comparison": state.comparison if state else "on",
        "summary": (
            f"Sequence {item.sequence_no} closed · {state.comparison if state else 'on'} "
            f"{abs(state.variance_hours) if state and state.variance_hours is not None else 0} h "
            f"({state.variance_days if state else 0} d)"
        ),
    }


def reopen_item(
    db: Session, organization_id: str, plan_id: str, item_id: str, note: str, user: User, request=None
) -> dict:
    """Undo a close, with a reason. The hours stay; only the verdict is withdrawn."""
    baseline = _baseline_for_plan(db, organization_id, plan_id)
    item = db.scalar(
        select(OpsPlanItem)
        .where(
            OpsPlanItem.id == item_id,
            OpsPlanItem.organization_id == organization_id,
            OpsPlanItem.plan_version_id == baseline.id,
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(404, "That activity is not a line of this timeline.")
    if getattr(item, "closed_at", None) is None:
        raise HTTPException(409, "This activity is not closed.")
    reason = (note or "").strip()
    if len(reason) < 3:
        raise HTTPException(422, "Say why the close is withdrawn (at least 3 characters). It is kept.")
    item.closed_at = None
    item.closed_by = ""
    item.close_source = ""
    item.close_note = ""
    item.closed_actual_hours = None
    item.updated_at = datetime.now(UTC)
    ledger = reports_svc._recompute_baseline(
        db, baseline, f"programme {baseline.label or f'v{baseline.version_no}'}"
    )
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="reopen",
        entity_type="ops_plan",
        entity_id=baseline.id,
        entity_label=baseline.label,
        summary=f"Reopened sequence {item.sequence_no} ({item.description[:80]}): {reason[:200]}",
        request=request,
    )
    db.commit()
    return {
        "item_id": item.id,
        "sequence_no": item.sequence_no,
        "state": next((r.state for r in ledger.codes if r.item_id == item.id), ""),
        "summary": f"Sequence {item.sequence_no} reopened; it has no verdict until it is closed again",
    }


def timeline_rollup(db: Session, organization_id: str, plan_id: str, user: User) -> dict:
    """Per-code planned vs actual hours, states and honest totals for one baseline."""
    baseline = _baseline_for_plan(db, organization_id, plan_id)
    blocks = reports_svc._scope_blocks(db, baseline)
    reports_svc._attach_report_context(db, blocks)
    ledger = reports_svc._ledger(db, baseline)
    policy = ledger.policy
    totals = ledger.totals

    # The schedule position is a different question from the sequence variance: it
    # asks where the well is against the programme today, using elapsed days. It is
    # computed here from the same effective curve so the two can never disagree
    # about which activities were skipped.
    position, position_basis = _schedule_position(db, baseline)

    return {
        "plan_version_id": baseline.id,
        "plan_label": baseline.label or f"v{baseline.version_no}",
        "actual_hours": totals.actual_total,
        "planned_hours": totals.planned_in_scope,
        "variance_hours": totals.realised_variance,
        "comparison": totals.comparison,
        "codes": [
            {
                "sequence_no": row.sequence_no,
                "description": (row.description or "")[:500],
                "planned_hours": row.planned_hours,
                "target_depth_m": row.target_depth_m,
                "actual_hours": row.actual_hours,
                "variance_hours": row.variance_hours,
                "variance_days": row.variance_days,
                "comparison": row.comparison,
                "line_count": row.line_count,
                "report_count": row.report_count,
                "item_id": row.item_id,
                "state": row.state,
                "progress_pct": row.progress_pct,
                "remaining_hours": row.remaining_hours,
                "close_suggested": row.close_suggested,
                "closed_at": row.closed_at,
                "close_source": row.close_source,
                "close_note": row.close_note,
                "saved_planned_hours": row.saved_planned_hours,
                "skip_reason": row.skip_reason,
                "skipped_by": row.skipped_by,
                "skipped_at": row.skipped_at,
                "effective_cum_days": row.effective_cum_days,
                "cum_shift_days": row.cum_shift_days,
                "saved_cum_days": row.saved_cum_days,
                "provisional_actual_hours": row.provisional_actual_hours,
            }
            for row in ledger.codes
        ],
        "uncoded_lines": ledger.unplanned.line_count,
        "unplanned": {
            "code": ledger.unplanned.code,
            "actual_hours": ledger.unplanned.actual_hours,
            "upa_hours": ledger.unplanned.upa_hours,
            "npt_hours": ledger.unplanned.npt_hours,
            "other_hours": ledger.unplanned.other_hours,
            "variance_hours": ledger.unplanned.variance_hours,
            "variance_days": ledger.unplanned.variance_days,
            "comparison": ledger.unplanned.comparison,
            "line_count": ledger.unplanned.line_count,
            "provisional_hours": ledger.unplanned.provisional_hours,
            "unmatched_hours": ledger.unplanned.unmatched_hours,
        },
        "totals": {
            "planned_in_scope": totals.planned_in_scope,
            "planned_in_scope_days": totals.planned_in_scope_days,
            "planned_saved": totals.planned_saved,
            "actual_coded": totals.actual_coded,
            "actual_unplanned": totals.actual_unplanned,
            "actual_total": totals.actual_total,
            "realised_variance": totals.realised_variance,
            "realised_variance_days": totals.realised_variance_days,
            "comparison": totals.comparison,
            "closed_coverage_pct": totals.closed_coverage_pct,
            "plan_coverage_pct": totals.plan_coverage_pct,
            "plan_coverage_days": totals.plan_coverage_days,
            "provisional_actual_hours": totals.provisional_actual_hours,
            "closed_code_count": totals.closed_code_count,
            "open_code_count": totals.open_code_count,
            "not_started_count": totals.not_started_count,
            "skipped_count": totals.skipped_count,
            "missing_planned_hours": totals.missing_planned_hours,
            "unattributed_hours": totals.unattributed_hours,
        },
        "findings": [
            {
                "kind": f.kind,
                "message": f.message,
                "item_id": f.item_id,
                "block_id": f.block_id,
                "severity": f.severity,
            }
            for f in ledger.findings
        ],
        "policy": _policy_out(policy),
        "confirmed_report_count": len(
            {b.report_id for b in blocks if getattr(b, "report_status", "") in reports_svc.CONFIRMED_STATUSES}
        ),
        "provisional_report_count": len(
            {b.report_id for b in blocks if getattr(b, "report_status", "") not in reports_svc.CONFIRMED_STATUSES}
        ),
        "schedule_position_days": position,
        "schedule_position_basis": position_basis,
    }


def _schedule_position(db: Session, baseline: OpsPlanVersion) -> tuple[Decimal | None, str]:
    """Where the well is against the programme today, in days.

    Measured from the programme start (or the latest report's own elapsed-days
    basis) to the confirmed checkpoint, on the curve with skipped activities
    removed. Distinct from the sequence variance above, and labelled as such: this
    one answers "are we ahead today", which is a different question from "did the
    work we finished take the hours allowed".
    """
    from app.services.operations import analytics

    report = db.scalar(
        select(OpsDailyReport)
        .where(
            OpsDailyReport.organization_id == baseline.organization_id,
            OpsDailyReport.well_id == baseline.well_id,
            OpsDailyReport.scope == baseline.scope,
            OpsDailyReport.is_deleted.is_(False),
            OpsDailyReport.is_current.is_(True),
            OpsDailyReport.status.in_(analytics.VERIFIED),
        )
        .order_by(OpsDailyReport.report_date.desc())
        .limit(1)
    )
    if report is None:
        return None, "no approved report yet"
    rows = reports_svc._plan_rows(db, baseline)
    elapsed = None
    basis = ""
    origin = baseline.planned_start_at
    if origin is not None and report.period_end_at is not None:
        elapsed = Decimal(
            str((utc(report.period_end_at) - utc(origin)).total_seconds() / 86400)
        )
        basis = "programme start"
    elif report.scope == "drilling" and report.dfs_days is not None:
        elapsed = reports_svc._as_decimal(report.dfs_days)
        basis = "reported DFS"
    if elapsed is None:
        return None, "no elapsed-days basis (set a programme start or report DFS)"
    checkpoint = report.completed_plan_item_id
    if checkpoint is None:
        # No confirmed checkpoint: fall back to the deepest accepted code by
        # sequence order, and say so rather than inventing a position.
        return None, "no confirmed programme checkpoint"
    position = sequence.schedule_position(rows, checkpoint, elapsed)
    return position, f"{basis} · confirmed checkpoint"
