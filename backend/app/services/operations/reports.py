"""Reports service — CRUD, workflow, metrics."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, cast, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.precision import rounded
from app.domain.operations.durations import duration_minutes as calc_duration
from app.domain.operations.durations import resolve_period, utc
from app.domain.operations.metrics import compute_rop, penetration, period_balance
from app.domain.operations.requirements import describe_missing
from app.domain.operations.study import daily_brief
from app.models import User
from app.models.master_data import Activity
from app.models.operations import (
    OpsActivityBlock,
    OpsActivityBlockCode,
    OpsAgency,
    OpsDailyMetric,
    OpsDailyReport,
    OpsDocument,
    OpsExtractionJob,
    OpsOperation,
    OpsPlanItem,
    OpsPlanVersion,
    OpsSettings,
    OpsSubPhase,
    OpsSurvey,
    OpsUnaccountedTime,
)
from app.models.rig_well import HoleSection, Phase
from app.models.vendor_master import Vendor
from app.services.audit import record as audit_record
from app.domain.operations import sequence
from app.services.operations import scope
from app.services.operations import sequence_policy
from app.services.operations.report_labels import report_labels
from app.services.operations.plans import active_plan


def _actor(user: User) -> str:
    return user.email or user.full_name or str(user.id)


def _ref(db, org, model, ident):
    if not ident:
        return None
    row = db.scalar(
        select(model).where(model.id == ident, model.organization_id == org, model.is_deleted.is_(False))
    )
    if not row:
        raise HTTPException(422, "Selected reference is not available in this workspace.")
    return row


def _resolve_period(report_date: date, organization_id: str, db: Session):
    from app.models.operations import OpsSettings

    settings = db.scalar(select(OpsSettings).where(OpsSettings.organization_id == organization_id))
    boundary = settings.day_boundary_hour if settings else 0
    return resolve_period(report_date, boundary, settings.operating_timezone if settings else "Africa/Lagos")


def _validate_blocks(blocks: list[dict], period_start: datetime | None, period_end: datetime | None):
    if not blocks:
        return
    ordered = sorted(blocks, key=lambda b: utc(b["started_at"]))
    for i, block in enumerate(ordered):
        a, z = utc(block["started_at"]), utc(block["ended_at"])
        if z <= a or (period_start and a < utc(period_start)) or (period_end and z > utc(period_end)):
            raise HTTPException(
                422, f"Block {block['sequence_no']} must have positive duration inside the report period."
            )
        if i and a < utc(ordered[i - 1]["ended_at"]):
            raise HTTPException(409, f"Block {block['sequence_no']} overlaps another block.")


def _norm_text(value: str | None) -> str:
    """Normalise a description for activity matching (case, punctuation, spacing)."""
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))


def _similarity(a: str, b: str) -> float:
    """Token overlap ratio (Jaccard) between two normalised descriptions."""
    left, right = set(a.split()), set(b.split())
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _item_key(item) -> str:
    """The identity of a programme row, whether it is an ORM item or a PlanRow."""
    return getattr(item, "item_id", None) or item.id


def _match_plan_item(
    description: str, items: dict[str, "OpsPlanItem"], used: set[str]
) -> "OpsPlanItem | None":
    """Pick the programme activity this block is logging.

    Matching is deliberately conservative and explainable: a block is only tied
    to a programme row when the words agree strongly. A weak match would be worse
    than none, because it would put the whole lead/lag on the wrong activity.
    """
    target = _norm_text(description)
    if not target:
        return None
    best: tuple[float, OpsPlanItem] | None = None
    for item in items.values():
        candidate = _norm_text(item.description)
        if not candidate:
            continue
        score = _similarity(target, candidate)
        if target == candidate:
            score = 1.0
        elif target.startswith(candidate) or candidate.startswith(target):
            # "Drill 12-1/4\" hole to 2800 m" against the programme's "Drill
            # 12-1/4\" hole as per Directional Plan to ±2800m" — the shorter is
            # genuinely part of the longer.
            score = max(score, 0.72)
        if _item_key(item) in used:
            score -= 0.15  # a second block can still log the same activity, but later
        if best is None or score > best[0]:
            best = (score, item)
    if best is None or best[0] < 0.5:
        return None
    return best[1]


def _baseline_for(db: Session, report: OpsDailyReport) -> OpsPlanVersion | None:
    """The programme this report is compared against (pinned, else the active one)."""
    baseline = db.get(OpsPlanVersion, report.baseline_plan_id) if report.baseline_plan_id else None
    if baseline is None:
        baseline = _active_baseline_id(db, report)
    return baseline


def _scope_blocks(db: Session, baseline: OpsPlanVersion) -> list[OpsActivityBlock]:
    """Every time-log line tied to the baseline across the well/scope.

    The active programme sweeps in rows whose report never pinned a baseline
    (drafts and work in progress); a superseded programme only owns the reports
    explicitly pinned to it.

    Both confirmed and provisional reports are returned: the caller decides which
    of them votes. A draft must never change a submitted month, and only this
    function knows where the boundary is.
    """
    stmt = (
        select(OpsActivityBlock)
        .join(OpsDailyReport, OpsDailyReport.id == OpsActivityBlock.report_id)
        .where(
            OpsActivityBlock.organization_id == baseline.organization_id,
            OpsDailyReport.organization_id == baseline.organization_id,
            OpsDailyReport.well_id == baseline.well_id,
            OpsDailyReport.scope == baseline.scope,
            OpsDailyReport.is_deleted.is_(False),
            OpsActivityBlock.is_deleted.is_(False),
            # A rejected report is not evidence either way.
            OpsDailyReport.status != "rejected",
        )
    )
    if baseline.status == "active":
        stmt = stmt.where(
            or_(OpsDailyReport.baseline_plan_id == baseline.id, OpsDailyReport.baseline_plan_id.is_(None))
        )
    else:
        stmt = stmt.where(OpsDailyReport.baseline_plan_id == baseline.id)
    return list(db.scalars(stmt).all())


CONFIRMED_STATUSES = ("submitted", "approved")


def _line_contribution(block: OpsActivityBlock) -> Decimal:
    """The hours this line contributes to its code's total."""
    if block.timeline_actual_edited and block.timeline_actual_hours is not None:
        return _as_decimal(block.timeline_actual_hours) or Decimal(0)
    return _hours_from_minutes(block.duration_minutes) or Decimal(0)


def _set_if_changed(obj, field, value) -> bool:
    if getattr(obj, field) != value:
        setattr(obj, field, value)
        return True
    return False


def _plan_rows(db: Session, baseline: OpsPlanVersion) -> list[sequence.PlanRow]:
    """The programme as the pure ledger wants it: one immutable row per code."""
    items = db.scalars(
        select(OpsPlanItem)
        .where(
            OpsPlanItem.organization_id == baseline.organization_id,
            OpsPlanItem.plan_version_id == baseline.id,
        )
        .order_by(OpsPlanItem.sequence_no, OpsPlanItem.id)
    ).all()
    return [
        sequence.PlanRow(
            item_id=item.id,
            sequence_no=item.sequence_no,
            description=item.description or "",
            planned_hours=_as_decimal(item.planned_hours),
            target_depth_m=_as_decimal(item.target_depth_m),
            saved_cum_days=_as_decimal(item.cum_planned_days),
            hole_section_id=item.hole_section_id,
            phase_id=item.phase_id,
            skipped=(getattr(item, "state", "planned") == "skipped"),
            skip_reason=getattr(item, "skip_reason", "") or "",
            skipped_by=getattr(item, "skipped_by", "") or "",
            skipped_at=getattr(item, "skipped_at", None),
            closed_at=getattr(item, "closed_at", None),
            closed_by=getattr(item, "closed_by", "") or "",
            close_source=getattr(item, "close_source", "") or "",
            close_note=getattr(item, "close_note", "") or "",
            closed_actual_hours=_as_decimal(getattr(item, "closed_actual_hours", None)),
        )
        for item in items
    ]


def _split_rows(db: Session, block_ids: list[str]) -> dict[str, list]:
    """Split rows for these lines, grouped by line. One query, never N."""
    if not block_ids:
        return {}
    rows = db.scalars(
        select(OpsActivityBlockCode).where(OpsActivityBlockCode.block_id.in_(block_ids))
    ).all()
    out: dict[str, list] = {}
    for row in rows:
        out.setdefault(row.block_id, []).append(row)
    return out


def _report_statuses(db: Session, blocks: list[OpsActivityBlock]) -> dict[str, str]:
    """The report status of every line's report, in one query.

    Read here rather than through an attribute a caller may or may not have
    attached: getting this wrong would let a draft vote on a signed month, and a
    silent "assume confirmed" default is exactly the bug that caused.
    """
    report_ids = {b.report_id for b in blocks if b.report_id}
    if not report_ids:
        return {}
    rows = db.execute(
        select(OpsDailyReport.id, OpsDailyReport.status).where(OpsDailyReport.id.in_(report_ids))
    ).all()
    return {report_id: status for report_id, status in rows}


def _contributions(
    db: Session,
    baseline: OpsPlanVersion,
    blocks: list[OpsActivityBlock],
    *,
    item_ids_by_block: dict[str, str] | None = None,
) -> list[sequence.Contribution]:
    """Hours per code, reading splits where a line has them.

    A split changes **which** code a line's hours belong to. It never changes how
    many hours the line logged, and a remainder stays in the unplanned bucket so a
    split can never quietly lose an hour.
    """
    splits = _split_rows(db, [b.id for b in blocks])
    statuses = _report_statuses(db, blocks)
    out: list[sequence.Contribution] = []
    for block in blocks:
        # An unknown status is *not* confirmed: a line whose report cannot be read
        # must not be able to move a figure that was signed.
        confirmed = statuses.get(block.report_id) in CONFIRMED_STATUSES
        total = _line_contribution(block)
        report_date = str(getattr(block, "report_date", "") or "")
        rows = splits.get(block.id)
        if rows:
            allocated = Decimal(0)
            for row in rows:
                hours = _as_decimal(row.hours) or Decimal(0)
                allocated += hours
                out.append(
                    sequence.Contribution(
                        block_id=block.id,
                        report_id=block.report_id,
                        item_id=row.plan_item_id,
                        hours=hours,
                        confirmed=confirmed,
                        allocation=block.allocation or "PT",
                        report_date=report_date,
                    )
                )
            remainder = total - allocated
            if remainder > 0:
                out.append(
                    sequence.Contribution(
                        block_id=block.id,
                        report_id=block.report_id,
                        item_id=None,
                        hours=remainder,
                        confirmed=confirmed,
                        allocation=block.allocation or "PT",
                        report_date=report_date,
                    )
                )
            continue
        item_id = (item_ids_by_block or {}).get(block.id)
        if item_id is None:
            item_id = block.timeline_plan_item_id
        if item_id is None:
            item_id = _resolve_code_item(db, baseline, (block.timeline_code or "").strip())
        out.append(
            sequence.Contribution(
                block_id=block.id,
                report_id=block.report_id,
                item_id=item_id,
                hours=total,
                confirmed=confirmed,
                allocation=block.allocation or "PT",
                report_date=report_date,
            )
        )
    return out


_CODE_ITEM_CACHE: dict[tuple[str, str], str | None] = {}


def _resolve_code_item(db: Session, baseline: OpsPlanVersion, code: str) -> str | None:
    """The plan row a typed sequence code names, on *this* baseline only.

    ``timeline_code`` is a display snapshot. The identity is the plan item id, and
    this is the one place that translates between them. A code is never resolved
    across wells, scopes or versions.
    """
    if not code:
        return None
    key = (baseline.id, code)
    if key in _CODE_ITEM_CACHE:
        return _CODE_ITEM_CACHE[key]
    matches = db.scalars(
        select(OpsPlanItem.id).where(
            OpsPlanItem.organization_id == baseline.organization_id,
            OpsPlanItem.plan_version_id == baseline.id,
            cast(OpsPlanItem.sequence_no, String) == code,
        )
    ).all()
    value = matches[0] if len(matches) == 1 else None
    _CODE_ITEM_CACHE[key] = value
    return value


def _linkable_items(rows: list[sequence.PlanRow]) -> dict[str, sequence.PlanRow]:
    """The codes a new line may still be reported against.

    A closed code is finished work: hours found later belong to whatever activity
    actually happened, not to it. A skipped activity will never be done. Linking a
    fresh line to either would manufacture a lead or an overrun out of a guess, so
    only the open part of the programme is a candidate.
    """
    return {row.item_id: row for row in rows if not row.skipped and row.closed_at is None}


def _suggested_items(
    blocks: list[OpsActivityBlock], rows: list[sequence.PlanRow]
) -> dict[str, str]:
    """The open code each uncoded line most likely logs, from its own words.

    A **suggestion**, derived at read time from the narrative and the programme —
    never stored as an assignment. It is what lets the review screen pre-fill the
    likely code instead of leaving the engineer to retype it, and it can only ever
    point at an *open* code, so it can never rewrite a finished verdict.

    The match is deliberately conservative (``_match_plan_item``): exact wording,
    a containment relation, or a strong token overlap with the same drilling
    action. Two lines are never suggested to the same code, because the second
    one is usually the next job.
    """
    candidates = _linkable_items(rows)
    used: set[str] = set()
    out: dict[str, str] = {}
    for block in sorted(blocks, key=lambda b: (str(b.report_id), b.sequence_no)):
        if (block.timeline_code or "").strip() or block.timeline_plan_item_id:
            continue
        if getattr(block, "timeline_split_state", "") == "unplanned":
            # An engineer cleared the code on purpose. A suggestion must never undo
            # a decision a person recorded.
            continue
        text = block.narrative or getattr(block, "operation_snapshot", "") or ""
        match = _match_plan_item(text, candidates, used)
        if match is not None:
            out[block.id] = match.item_id
            used.add(match.item_id)
    return out


def _ledger(db: Session, baseline: OpsPlanVersion, *, confirmed_only: bool = True) -> sequence.Ledger:
    """The whole comparison for one baseline: rows, hours, policy, states."""
    blocks = _scope_blocks(db, baseline)
    _attach_report_context(db, blocks)
    rows = _plan_rows(db, baseline)
    contributions = _contributions(
        db, baseline, blocks, item_ids_by_block=_suggested_items(blocks, rows)
    )
    policy = sequence_policy.policy_for(db, baseline.organization_id)
    return sequence.build_ledger(rows, contributions, policy, confirmed_only=confirmed_only)


def _attach_report_context(db: Session, blocks: list[OpsActivityBlock]) -> None:
    """Give each line the report facts the ledger needs, without N queries."""
    if not blocks:
        return
    reports = {
        r.id: r
        for r in db.scalars(
            select(OpsDailyReport).where(
                OpsDailyReport.id.in_({b.report_id for b in blocks})
            )
        ).all()
    }
    for block in blocks:
        report = reports.get(block.report_id)
        # ``report_status`` decides confirmed vs provisional; ``report_date`` names
        # the day in a finding. Both are read-only context, never stored here.
        block.report_status = report.status if report is not None else ""
        block.report_date = report.report_date if report is not None else ""


def _recompute_baseline(db: Session, baseline: OpsPlanVersion, basis: str) -> sequence.Ledger:
    """Rewrite the plan-versus-actual fields on every line of the baseline's scope.

    The ledger decides; this function only writes its verdict onto the rows. Code
    derived fields are refreshed on every non-rejected row so a reviewed line can
    never display a stale plan, while an engineer's own corrected actual hours, the
    review mark, the note and the edited-by evidence are kept untouched. Rejected
    rows are left exactly as they are.

    What each state writes:

    * **complete** — ``variance = planned − actual`` and its days.
    * **in progress / overrun / not started** — no variance. Writing one would
      claim a job that has not finished is 88 hours early, which is the defect this
      replaces. The row carries its state so the register can say so.
    * **skipped** — no variance; the hours are reported as saved on the rollup.
    * **no code** — *Unplanned Activity*: actual with no planned, so it reads as a
      lag rather than disappearing from the arithmetic.
    """
    _CODE_ITEM_CACHE.clear()
    ledger = _ledger(db, baseline)
    blocks = _scope_blocks(db, baseline)
    _attach_report_context(db, blocks)
    # Two cohorts, one arithmetic. A **submitted or approved** line is written from
    # the confirmed ledger only, so a colleague's unsaved draft can never move a
    # number that was signed. A draft line is written from the inclusive ledger,
    # because the engineer reviewing it must see the arithmetic of the hours that
    # are actually recorded — including the ones on this screen.
    if any(b.report_status not in CONFIRMED_STATUSES for b in blocks):
        inclusive_states = {row.item_id: row for row in _ledger(db, baseline, confirmed_only=False).codes}
    else:
        inclusive_states = {row.item_id: row for row in ledger.codes}
    confirmed_states = {row.item_id: row for row in ledger.codes}
    splits = _split_rows(db, [b.id for b in blocks])
    # The same suggestion the ledger voted on, so the row a page displays and the
    # code the arithmetic used can never be two different activities.
    suggested = _suggested_items(blocks, _plan_rows(db, baseline))

    for block in blocks:
        code = (block.timeline_code or "").strip()
        item_id = (
            block.timeline_plan_item_id
            or suggested.get(block.id)
            or _resolve_code_item(db, baseline, code)
        )
        if block.timeline_review_state == "rejected":
            # "Not comparable" is a decision, not an error: the row is left
            # exactly as the engineer rejected it.
            continue
        reviewed = block.timeline_review_state in ("accepted", "edited")
        system_actual = _hours_from_minutes(block.duration_minutes)
        _set_if_changed(block, "timeline_system_actual_hours", system_actual)
        if not (block.timeline_actual_edited and block.timeline_actual_hours is not None):
            _set_if_changed(block, "timeline_actual_hours", system_actual)

        states = (
            confirmed_states
            if block.report_status in CONFIRMED_STATUSES
            else inclusive_states
        )
        state_row = states.get(item_id) if item_id else None
        split = bool(splits.get(block.id))
        # A deliberate "this work is unplanned" survives recompute; it is cleared only
        # when someone codes the line again.
        _set_if_changed(
            block,
            "timeline_split_state",
            "split" if split else ("unplanned" if block.timeline_split_state == "unplanned" else ""),
        )

        if state_row is None:
            # No comparable pair. Under this workspace's policy an unassigned line
            # is Unplanned Activity — it adds to actual hours and produces lag —
            # so the row states that instead of clearing to "on plan".
            _set_if_changed(block, "timeline_plan_item_id", item_id)
            _set_if_changed(block, "timeline_plan_step_no", None)
            _set_if_changed(block, "timeline_plan_label", "")
            _set_if_changed(block, "timeline_planned_hours", None)
            _set_if_changed(block, "timeline_cum_planned_days", None)
            _set_if_changed(block, "timeline_planned_days", None)
            _set_if_changed(block, "timeline_actual_days", None)
            _set_if_changed(block, "timeline_sequence_state", "")
            if ledger.policy.uncoded == "lag" and system_actual is not None:
                _set_if_changed(block, "timeline_variance_hours", _as_decimal(rounded(-system_actual)))
                _set_if_changed(
                    block, "timeline_variance_days",
                    _as_decimal(sequence.to_days(_as_decimal(rounded(-system_actual)))),
                )
                _set_if_changed(block, "timeline_comparison", "behind")
                _set_if_changed(
                    block, "timeline_basis",
                    ("unplanned activity" + (" (split remainder)" if split else ""))[:120],
                )
            else:
                _set_if_changed(block, "timeline_variance_hours", None)
                _set_if_changed(block, "timeline_variance_days", None)
                _set_if_changed(block, "timeline_comparison", "on")
                _set_if_changed(
                    block, "timeline_basis",
                    ("unplanned activity (shown, not subtracted)" if code or split else "unplanned activity")[:120],
                )
            if not reviewed:
                _set_if_changed(block, "timeline_review_state", "suggested")
            continue

        planned = state_row.planned_hours
        _set_if_changed(block, "timeline_plan_item_id", state_row.item_id)
        _set_if_changed(block, "timeline_plan_step_no", state_row.sequence_no)
        _set_if_changed(block, "timeline_plan_label", state_row.description[:500])
        _set_if_changed(block, "timeline_planned_hours", planned)
        _set_if_changed(block, "timeline_cum_planned_days", state_row.saved_cum_days)
        _set_if_changed(block, "timeline_planned_days", state_row.saved_cum_days)
        _set_if_changed(block, "timeline_actual_days", None)
        _set_if_changed(block, "timeline_sequence_state", state_row.state)

        if state_row.state == sequence.COMPLETE:
            _set_if_changed(block, "timeline_variance_hours", state_row.variance_hours)
            _set_if_changed(block, "timeline_variance_days", state_row.variance_days)
            _set_if_changed(block, "timeline_comparison", state_row.comparison)
        elif state_row.state == sequence.SKIPPED:
            _set_if_changed(block, "timeline_variance_hours", None)
            _set_if_changed(block, "timeline_variance_days", None)
            _set_if_changed(block, "timeline_comparison", "on")
        else:
            # Started and unfinished, or not started: progress and remaining hours,
            # never a lead. The register reads the state and says so in words.
            _set_if_changed(block, "timeline_variance_hours", None)
            _set_if_changed(block, "timeline_variance_days", None)
            _set_if_changed(block, "timeline_comparison", "on")

        if state_row.state == sequence.COMPLETE:
            _set_if_changed(
                block, "timeline_basis",
                f"{basis} · closed {state_row.close_source or 'confirmed'}".strip()[:120],
            )
        elif state_row.state == sequence.SKIPPED:
            _set_if_changed(block, "timeline_basis", f"{basis} · activity skipped"[:120])
        elif state_row.state == sequence.IN_PROGRESS:
            _set_if_changed(
                block, "timeline_basis",
                f"{basis} · in progress {state_row.progress_pct or 0}%"
                f" ({state_row.remaining_hours or 0} h remaining)"[:120],
            )
        elif state_row.state == sequence.OVERRUN_OPEN:
            _set_if_changed(
                block, "timeline_basis",
                f"{basis} · over plan, not closed ({state_row.progress_pct or 0}%)"[:120],
            )
        else:
            _set_if_changed(block, "timeline_basis", basis[:120])
        if not reviewed:
            _set_if_changed(block, "timeline_review_state", "suggested")
    return ledger


def _suggest_comparison(db: Session, report: OpsDailyReport) -> sequence.Ledger | None:
    """Propose plan-versus-actual hours for each line, from the sequence ledger.

    Lead and lag correlate **by sequence code, never by description**: each line of
    the baseline programme carries a code (its ``sequence_no``), and a daily-report
    line joins that code explicitly. The hours of all lines sharing a code are
    summed and compared with the programme's planned hours for it:

    * ``variance = planned − Σ actual`` → positive = lead, negative = lag — but
      **only for a code the engineer has closed**. A code that has started and not
      finished has progress and remaining hours, not a lead;
    * the sum spans the baseline's whole scope (the freshest record), while the
      printed verdict uses submitted and approved hours and shows draft hours
      beside it: a draft must not change a submitted month;
    * a rejected row is never overwritten, and an engineer's own correction of a
      line's hours counts in the group total;
    * lines without a code are *Unplanned Activity*: they raise actual hours and
      can only produce lag. Nothing is guessed from the wording of a narrative.
    """
    baseline = _baseline_for(db, report)
    if baseline is None:
        blocks = db.scalars(
            select(OpsActivityBlock).where(
                OpsActivityBlock.organization_id == report.organization_id,
                OpsActivityBlock.report_id == report.id,
                OpsActivityBlock.is_deleted.is_(False),
            )
        ).all()
        for block in blocks:
            if block.timeline_review_state in ("accepted", "edited", "rejected"):
                continue
            block.timeline_comparison = "on"
            block.timeline_basis = "no active programme"
            block.timeline_plan_item_id = None
            block.timeline_plan_step_no = None
            block.timeline_plan_label = ""
            block.timeline_planned_hours = None
            block.timeline_system_actual_hours = _hours_from_minutes(block.duration_minutes)
            block.timeline_actual_hours = None
            block.timeline_variance_hours = None
            block.timeline_variance_days = None
            block.timeline_cum_planned_days = None
            block.timeline_planned_days = None
            block.timeline_actual_days = None
            block.timeline_sequence_state = ""
            block.timeline_split_state = ""
            block.timeline_review_state = "suggested"
        return None
    basis = f"programme {baseline.label or f'v{baseline.version_no}'}"
    return _recompute_baseline(db, baseline, basis)


def _as_decimal(value: Any) -> Decimal | None:
    """Read a stored number as Decimal.

    A model default can hand back a plain Python number before the row is
    flushed, and ``Decimal(float)`` would carry the binary residue of a fraction
    into the result. ``str`` keeps the printed value exact.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _hours_from_minutes(minutes: int | None) -> Decimal | None:
    if minutes is None:
        return None
    return rounded(Decimal(minutes) / Decimal(60))


def _active_baseline_id(db: Session, report: OpsDailyReport) -> OpsPlanVersion | None:
    """Fall back to the well/scope's active programme when the report has no saved baseline."""
    return db.scalar(
        select(OpsPlanVersion).where(
            OpsPlanVersion.organization_id == report.organization_id,
            OpsPlanVersion.well_id == report.well_id,
            OpsPlanVersion.scope == report.scope,
            OpsPlanVersion.status == "active",
            OpsPlanVersion.is_deleted.is_(False),
        )
    )


def _compute_metrics(db: Session, report: OpsDailyReport, blocks: list[OpsActivityBlock]):
    total = sum(b.duration_minutes for b in blocks)
    planned = sum(b.duration_minutes for b in blocks if b.classification == "Planned")
    upa = sum(b.duration_minutes for b in blocks if b.classification == "UPA")
    npt = sum(b.duration_minutes for b in blocks if b.classification == "NPT")
    productive = sum(b.duration_minutes for b in blocks if b.is_productive)
    avg_conf = float(sum(b.confidence for b in blocks) / len(blocks)) if blocks else 0
    unaccounted = period_balance(report.report_type, report.period_minutes, total)
    db.execute(
        delete(OpsUnaccountedTime).where(
            OpsUnaccountedTime.organization_id == report.organization_id, OpsUnaccountedTime.report_id == report.id
        )
    )
    if unaccounted and report.period_start_at and report.period_end_at:
        cursor = utc(report.period_start_at)
        for start, end in [
            (utc(b.started_at), utc(b.ended_at)) for b in sorted(blocks, key=lambda b: utc(b.started_at))
        ] + [(utc(report.period_end_at), utc(report.period_end_at))]:
            minutes = calc_duration(cursor, start)
            if minutes > 0:
                db.add(
                    OpsUnaccountedTime(
                        organization_id=report.organization_id,
                        report_id=report.id,
                        from_at=cursor,
                        to_at=start,
                        minutes=minutes,
                        reason="Gap in time log",
                        source="computed",
                    )
                )
            cursor = max(cursor, end)
    footage, rotating_hours = penetration(report, blocks)
    metric = db.scalar(
        select(OpsDailyMetric).where(
            OpsDailyMetric.organization_id == report.organization_id,
            OpsDailyMetric.well_id == report.well_id,
            OpsDailyMetric.scope == report.scope,
            OpsDailyMetric.report_date == report.report_date,
        )
    )
    if not metric:
        metric = OpsDailyMetric(
            organization_id=report.organization_id,
            well_id=report.well_id,
            rig_id=report.rig_id,
            scope=report.scope,
            report_date=report.report_date,
        )
        db.add(metric)
    metric.day_number = report.day_number
    metric.logged_minutes = total
    metric.planned_minutes = planned
    metric.upa_minutes = upa
    metric.npt_minutes = npt
    metric.productive_minutes = productive
    metric.unaccounted_minutes = max(0, unaccounted)
    metric.depth_end_m = report.depth_end_m
    metric.footage_m = footage
    metric.rop_m_per_hr = compute_rop(footage, rotating_hours, scope=report.scope)
    metric.npt_block_count = sum(1 for b in blocks if b.classification == "NPT")
    metric.avg_confidence = rounded(Decimal(str(avg_conf)))
    metric.review_state = report.status
    metric.computed_at = datetime.now(UTC)


def create_report(db: Session, organization_id: str, data, user: User, request=None):
    well, rig = scope.resolve(db, organization_id, data.well_id, data.scope, data.rig_id)
    # Check duplicate well/scope/date
    exists = db.scalar(
        select(OpsDailyReport).where(
            OpsDailyReport.organization_id == organization_id,
            OpsDailyReport.well_id == data.well_id,
            OpsDailyReport.scope == data.scope,
            OpsDailyReport.report_date == data.report_date,
        )
    )
    if exists:
        raise HTTPException(
            409,
            "A report for this period is in Deleted entries. Restore it."
            if exists.is_deleted
            else "A report for this well, scope and date already exists",
        )
    period_start, period_end = _resolve_period(data.report_date, organization_id, db)
    if data.period_start_at:
        period_start = data.period_start_at
    if data.period_end_at:
        period_end = data.period_end_at
    period_start, period_end = utc(period_start), utc(period_end)
    period_minutes = int((period_end - period_start).total_seconds() / 60)
    if not 0 < period_minutes <= 2880:
        raise HTTPException(422, "Invalid report period.")
    if data.source_document_id:
        doc = _ref(db, organization_id, OpsDocument, data.source_document_id)
        if doc.well_id != well.id or doc.scope != data.scope:
            raise HTTPException(422, "Source document belongs to another folder.")
    _ref(db, organization_id, HoleSection, data.hole_section_id)
    _ref(db, organization_id, Phase, data.phase_id)

    baseline = active_plan(db, organization_id, data.well_id, data.scope)
    report = OpsDailyReport(
        baseline_plan_id=baseline.id if baseline else None,
        organization_id=organization_id,
        well_id=well.id,
        rig_id=rig.id if rig else None,
        well_code_snapshot=well.well_code,
        well_name_snapshot=well.well_name,
        rig_code_snapshot=rig.rig_code if rig else "",
        rig_name_snapshot=rig.rig_name if rig else "",
        scope=data.scope,
        report_type=data.report_type,
        report_date=data.report_date,
        report_no_text=data.report_no_text or "",
        day_number=data.day_number,
        event_code=data.event_code or "",
        period_start_at=period_start,
        period_end_at=period_end,
        period_minutes=period_minutes,
        hole_section_id=data.hole_section_id,
        phase_id=data.phase_id,
        depth_start_m=data.depth_start_m,
        depth_end_m=data.depth_end_m,
        depth_unit=data.depth_unit or "m",
        tvd_start_m=data.tvd_start_m,
        tvd_m=data.tvd_m,
        tvd_source=data.tvd_source or ("manual" if data.tvd_m is not None else ""),
        bit_depth_m=data.bit_depth_m,
        progress_m=data.progress_m,
        rotating_hours=data.rotating_hours,
        cum_rotating_hours=data.cum_rotating_hours,
        spud_date=data.spud_date,
        dfs_days=data.dfs_days,
        est_days=data.est_days,
        md_auth_m=data.md_auth_m,
        last_casing_size_in=data.last_casing_size_in,
        last_casing_depth_m=data.last_casing_depth_m,
        hole_section_text=data.hole_section_text or "",
        hole_size_in=data.hole_size_in,
        current_status=data.current_status or "",
        mud_type=data.mud_type or "",
        mud_weight_ppg=data.mud_weight_ppg,
        mud_viscosity_sec=data.mud_viscosity_sec,
        mud_pv_cp=data.mud_pv_cp,
        mud_yp_lbf=data.mud_yp_lbf,
        bha_summary=data.bha_summary or "",
        pob_count=data.pob_count,
        customer=data.customer or "",
        project=data.project or "",
        site=data.site or "",
        datum=data.datum or "",
        supervisor=data.supervisor or "",
        engineer=data.engineer or "",
        uwi=data.uwi or "",
        block_text=data.block_text or "",
        operation_summary=data.operation_summary or "",
        forward_plan=data.forward_plan or "",
        hse_summary=data.hse_summary or "",
        remarks=data.remarks or "",
        source_document_id=data.source_document_id,
        status="draft",
        extraction_status="none",
        created_by=_actor(user),
        updated_by=_actor(user),
    )
    db.add(report)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A report for this period already exists") from exc
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="create",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=f"{well.well_code} {data.report_date}",
        summary="Created daily report",
        request=request,
    )
    db.commit()
    db.refresh(report)
    return report


def get_report(db: Session, organization_id: str, report_id: str, include_deleted: bool = False, *, lock=False):
    q = select(OpsDailyReport).where(
        OpsDailyReport.id == report_id, OpsDailyReport.organization_id == organization_id
    )
    if not include_deleted:
        q = q.where(OpsDailyReport.is_deleted.is_(False))
    report = db.scalar(q.with_for_update() if lock else q)
    if not report:
        raise HTTPException(404, "Report not found")
    blocks = db.scalars(
        select(OpsActivityBlock)
        .where(OpsActivityBlock.report_id == report.id, OpsActivityBlock.is_deleted.is_(False))
        .order_by(OpsActivityBlock.sequence_no)
    ).all()
    report._blocks = blocks
    report._total_block_minutes = sum(b.duration_minutes for b in blocks)
    report._unaccounted_minutes = period_balance(
        report.report_type, report.period_minutes, report._total_block_minutes
    )
    report._surveys = db.scalars(
        select(OpsSurvey)
        .where(
            OpsSurvey.organization_id == organization_id,
            OpsSurvey.report_id == report.id,
            OpsSurvey.is_deleted.is_(False),
        )
        .order_by(OpsSurvey.station_no)
    ).all()
    jobs = db.execute(
        select(OpsExtractionJob.findings, OpsDocument.id, OpsDocument.file_name)
        .join(OpsDocument, OpsDocument.id == OpsExtractionJob.document_id)
        .where(
            OpsExtractionJob.organization_id == organization_id,
            OpsExtractionJob.report_id == report.id,
            OpsDocument.is_deleted.is_(False),
        )
        .order_by(OpsExtractionJob.created_at)
    ).all()
    report._extraction_notes = "\n".join(j.findings for j in jobs if j.findings)
    report._plan_checkpoints = [
        {
            "id": i.id,
            "description": f"{version.label} · {i.sequence_no}. {i.description}",
            "days": str(i.cum_planned_days),
        }
        for i, version in db.execute(
            select(OpsPlanItem, OpsPlanVersion)
            .join(OpsPlanVersion, OpsPlanVersion.id == OpsPlanItem.plan_version_id)
            .where(
                OpsPlanVersion.organization_id == organization_id,
                OpsPlanVersion.well_id == report.well_id,
                OpsPlanVersion.scope == report.scope,
                OpsPlanVersion.is_deleted.is_(False),
                OpsPlanVersion.id == report.baseline_plan_id
                if report.baseline_plan_id
                else OpsPlanVersion.status == "active",
            )
            .order_by(OpsPlanItem.sequence_no)
        )
    ]
    report._sources = [{"id": j.id, "file_name": j.file_name} for j in jobs]
    return report


def list_reports(
    db: Session,
    organization_id: str,
    well_id: str | None = None,
    rig_id: str | None = None,
    scope: str | None = None,
    status: str | None = None,
    report_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_deleted: bool = False,
):
    q = select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id)
    if not include_deleted:
        q = q.where(OpsDailyReport.is_deleted.is_(False))
    if well_id:
        q = q.where(OpsDailyReport.well_id == well_id)
    if rig_id:
        q = q.where(OpsDailyReport.rig_id == rig_id)
    if scope:
        q = q.where(OpsDailyReport.scope == scope)
    if status:
        q = q.where(OpsDailyReport.status == status)
    if report_type:
        q = q.where(OpsDailyReport.report_type == report_type)
    if date_from:
        q = q.where(OpsDailyReport.report_date >= date_from)
    if date_to:
        q = q.where(OpsDailyReport.report_date <= date_to)
    rows = db.scalars(q.order_by(OpsDailyReport.report_date.desc(), OpsDailyReport.created_at.desc())).all()
    by_report = {}
    for block in db.scalars(
        select(OpsActivityBlock)
        .where(
            OpsActivityBlock.organization_id == organization_id,
            OpsActivityBlock.report_id.in_(q.with_only_columns(OpsDailyReport.id)),
            OpsActivityBlock.is_deleted.is_(False),
        )
        .order_by(OpsActivityBlock.sequence_no)
    ):
        by_report.setdefault(block.report_id, []).append(block)
    for r in rows:
        r._blocks = by_report.get(r.id, [])
        r._total_block_minutes = sum(b.duration_minutes for b in r._blocks)
        r._unaccounted_minutes = period_balance(r.report_type, r.period_minutes, r._total_block_minutes)
    return rows


def save_report(
    db: Session, organization_id: str, report_id: str, data, user: User, request=None, *, may_review=False
):
    report = get_report(db, organization_id, report_id, lock=True)
    if report.status not in ("draft", "in_review", "rejected"):
        raise HTTPException(409, "Submitted and approved reports are read-only.")
    scope.resolve(db, organization_id, report.well_id, report.scope)
    if data.expected_updated_at and utc(report.updated_at) != utc(data.expected_updated_at):
        raise HTTPException(409, "This draft changed since it was opened. Reload before applying corrections.")
    if data.confirm_review and not may_review:
        raise HTTPException(403, "Confirming source review needs ops-report:review.")
    # Update header fields
    upd = data.report
    if not report.baseline_plan_id:
        baseline = active_plan(db, organization_id, report.well_id, report.scope)
        report.baseline_plan_id = baseline.id if baseline else None
    if "completed_plan_item_id" in upd.model_fields_set:
        if upd.completed_plan_item_id and not any(
            c["id"] == upd.completed_plan_item_id for c in report._plan_checkpoints
        ):
            raise HTTPException(422, "Choose a checkpoint in this well and scope’s active timeline.")
        report.completed_plan_item_id = upd.completed_plan_item_id
    if upd.rig_id is not None and upd.rig_id != report.rig_id:
        raise HTTPException(422, "The rig is assigned by the well configuration.")
    _ref(db, organization_id, HoleSection, upd.hole_section_id)
    _ref(db, organization_id, Phase, upd.phase_id)
    nullable_report_fields = {
        "depth_start_m",
        "depth_end_m",
        "tvd_start_m",
        "tvd_m",
        "bit_depth_m",
        "progress_m",
        "rotating_hours",
        "cum_rotating_hours",
        "spud_date",
        "dfs_days",
        "est_days",
        "md_auth_m",
        "last_casing_size_in",
        "last_casing_depth_m",
        "hole_size_in",
        "mud_weight_ppg",
        "mud_viscosity_sec",
        "mud_pv_cp",
        "mud_yp_lbf",
        "pob_count",
        "day_number",
    }
    for field in [
        "customer",
        "project",
        "site",
        "datum",
        "supervisor",
        "engineer",
        "uwi",
        "block_text",
        "report_no_text",
        "day_number",
        "event_code",
        "hole_section_id",
        "phase_id",
        "depth_start_m",
        "depth_end_m",
        "depth_unit",
        "tvd_start_m",
        "tvd_m",
        "tvd_source",
        "bit_depth_m",
        "progress_m",
        "rotating_hours",
        "cum_rotating_hours",
        "spud_date",
        "dfs_days",
        "est_days",
        "md_auth_m",
        "last_casing_size_in",
        "last_casing_depth_m",
        "hole_section_text",
        "hole_size_in",
        "current_status",
        "mud_type",
        "mud_weight_ppg",
        "mud_viscosity_sec",
        "mud_pv_cp",
        "mud_yp_lbf",
        "bha_summary",
        "pob_count",
        "operation_summary",
        "forward_plan",
        "hse_summary",
        "remarks",
    ]:
        val = getattr(upd, field, None)
        if field in upd.model_fields_set and (val is not None or field in nullable_report_fields):
            if field == "tvd_m" and val != report.tvd_m and "tvd_source" not in upd.model_fields_set:
                report.tvd_source = "manual" if val is not None else ""
            setattr(report, field, val)
    if upd.period_start_at:
        report.period_start_at = utc(upd.period_start_at)
    if upd.period_end_at:
        report.period_end_at = utc(upd.period_end_at)
    if report.period_start_at and report.period_end_at:
        report.period_minutes = int((utc(report.period_end_at) - utc(report.period_start_at)).total_seconds() / 60)
    report.updated_by = _actor(user)
    report.updated_at = datetime.now(UTC)
    if report.period_minutes <= 0 or report.period_minutes > 2880:
        raise HTTPException(422, "Invalid report period")

    # Replace blocks
    if data.blocks is not None:
        # Validate
        block_dicts = [b.model_dump() if hasattr(b, "model_dump") else b for b in data.blocks]
        _validate_blocks(block_dicts, report.period_start_at, report.period_end_at)
        for i, bd in enumerate(block_dicts, 1):
            bd["sequence_no"] = i
            if bd.get("timeline_code") is not None:
                bd["timeline_code"] = str(bd["timeline_code"]).strip()[:20] or None
            bd["started_at"], bd["ended_at"] = utc(bd["started_at"]), utc(bd["ended_at"])
            bd["duration_minutes"] = calc_duration(bd["started_at"], bd["ended_at"])
            if bd["duration_minutes"] <= 0:
                raise HTTPException(422, f"Block {i}: duration must be at least one minute.")
            for field, model in [
                ("hole_section_id", HoleSection),
                ("phase_id", Phase),
                ("sub_phase_id", OpsSubPhase),
                ("activity_id", Activity),
                ("operation_id", OpsOperation),
                ("responsible_agency_id", OpsAgency),
            ]:
                _ref(db, organization_id, model, bd[field])
            vendor = _ref(db, organization_id, Vendor, bd["vendor_id"])
            if vendor:
                if vendor.status != "active":
                    raise HTTPException(422, "Select an active vendor.")
            # The Master Data Activity decides the block's Activity type.
            activity = _ref(db, organization_id, Activity, bd["activity_id"])
            if activity is not None and activity.activity_type != bd["classification"]:
                bd["classification"] = activity.activity_type
                if activity.activity_type == "NPT":
                    bd["is_productive"] = False
            # The responsible agency label keeps its own text beside the link, and
            # an agency / service vendor keeps its name. A typed label survives.
            typed_party = str(bd.get("responsible_party") or "").strip()[:200]
            if vendor is not None:
                bd["responsible_party"] = vendor.vendor_name
            elif bd.get("responsible_agency_id"):
                agency = _ref(db, organization_id, OpsAgency, bd["responsible_agency_id"])
                bd["responsible_party"] = (agency.agency_name if agency is not None else typed_party)
            else:
                bd["responsible_party"] = typed_party
            if (bd["classification"] == "NPT" or bd["allocation"] == "NPT") and bd["is_productive"]:
                raise HTTPException(422, f"Block {i}: NPT cannot be productive.")
            # The comparison generated by the system stays visible and editable. A
            # manual mark must say why it differs from the computed one.
            if bd.get("timeline_review_state") in ("edited", "rejected") and not (
                bd.get("timeline_note") or ""
            ).strip():
                raise HTTPException(422, f"Block {i}: add a note explaining the changed lead/lag mark.")

        # A block the engineer accepted or edited must carry the codes its own
        # classification makes mandatory. Unfinished suggestions stay saveable so a
        # half-reviewed draft is never lost.
        for i, bd in enumerate(block_dicts, 1):
            if bd["review_state"] in ("accepted", "edited") or data.confirm_review:
                stub = OpsActivityBlock(
                    sequence_no=i,
                    classification=bd["classification"],
                    hole_section_id=bd["hole_section_id"],
                    phase_id=bd["phase_id"],
                    sub_phase_id=bd["sub_phase_id"],
                    activity_id=bd["activity_id"],
                    allocation=bd["allocation"],
                    cause_code=bd["cause_code"],
                    operation_id=bd["operation_id"],
                    responsible_agency_id=bd["responsible_agency_id"],
                    vendor_id=bd["vendor_id"],
                    responsible_party=bd["responsible_party"],
                )
                if message := describe_missing(stub):
                    raise HTTPException(422, message)

        # Update matching blocks in place. Reviewed records keep their IDs and machine
        # evidence; a removed row is retired, not relabelled as a different activity.
        existing = {b.id: b for b in report._blocks}
        retained = set()
        for bd in block_dicts:
            block_id = bd.pop("block_id", None)
            if block_id and (block_id not in existing or block_id in retained):
                raise HTTPException(422, "The selected activity block is not in this draft.")
            block = existing.get(block_id)
            if not block:
                block = OpsActivityBlock(
                    organization_id=organization_id,
                    report_id=report.id,
                    classification_source="reviewer",
                    classification_evidence="",
                    source_page=0,
                    source_bbox="",
                    confidence=Decimal(1),
                )
                db.add(block)
            else:
                retained.add(block.id)
                if block.classification != bd["classification"] or block.allocation != bd["allocation"]:
                    block.classification_source = "reviewer"
            # Provenance and calculated values are server-owned. Original source files
            # remain immutable even if the engineer changes the interpretation.
            for field in (
                "sequence_no",
                "started_at",
                "ended_at",
                "duration_minutes",
                "phase_raw",
                "hole_section_id",
                "phase_id",
                "sub_phase_id",
                "activity_id",
                "classification",
                "allocation",
                "is_productive",
                "cause_code",
                "operation_id",
                "responsible_agency_id",
                "depth_from_m",
                "depth_to_m",
                "tvd_from_m",
                "tvd_to_m",
                "bit_depth_m",
                "mud_weight_ppg",
                "rotating_hours",
                "vendor_id",
                "responsible_party",
                "reason",
                "narrative",
                "review_state",
                "timeline_code",
            ):
                setattr(block, field, bd[field])
            # The lead/lag arithmetic is not computed here; the baseline recompute
            # after the write owns it. An engineer's correction survives because
            # the recompute leaves reviewed rows untouched and their hours count
            # in the group total.
            if bd.get("timeline_review_state") in ("accepted", "edited", "rejected"):
                # Only a reviewer records who compared the plan with the actual.
                block.timeline_reviewed_by = _actor(user)
                block.timeline_reviewed_at = datetime.now(UTC)
            block.depth_unit = "m"
            block.rop_basis = "rotating"
            start, end = block.depth_from_m, block.depth_to_m
            block.footage_m = end - start if start is not None and end is not None and end >= start else None
            block.rop_m_per_hr = compute_rop(block.footage_m, block.rotating_hours, scope=report.scope)
            operation = db.get(OpsOperation, block.operation_id) if block.operation_id else None
            block.operation_snapshot = operation.operation_code if operation else ""
            if data.confirm_review and block.review_state in ("accepted", "edited"):
                block.reviewer_user_id = user.id
                block.reviewed_at = datetime.now(UTC)
        for removed in existing.keys() - retained:
            existing[removed].is_deleted = True
            existing[removed].deleted_at = datetime.now(UTC)
        # Update extraction status to reviewed if all suggested now accepted/edited
        if report.current_extraction_id or report.extraction_status == "needs_review":
            if data.confirm_review and any(b["review_state"] not in ("edited", "accepted") for b in block_dicts):
                raise HTTPException(422, "Review every suggested block before confirming.")
            report.extraction_status = "reviewed" if data.confirm_review else "needs_review"

    if data.blocks is None and report.current_extraction_id and (upd.model_fields_set or data.surveys is not None):
        report.extraction_status = "needs_review"
    if data.surveys is not None:
        db.execute(
            delete(OpsSurvey).where(OpsSurvey.organization_id == organization_id, OpsSurvey.report_id == report.id)
        )
        db.add_all(
            [
                OpsSurvey(
                    report_id=report.id,
                    organization_id=organization_id,
                    well_id=report.well_id,
                    scope=report.scope,
                    station_no=i,
                    **station.model_dump(),
                )
                for i, station in enumerate(data.surveys, 1)
            ]
        )
    # Recompute metrics
    # Need to fetch blocks after flush
    db.flush()
    blocks_now = db.scalars(
        select(OpsActivityBlock).where(
            OpsActivityBlock.report_id == report.id, OpsActivityBlock.is_deleted.is_(False)
        )
    ).all()
    _compute_metrics(db, report, blocks_now)
    _suggest_comparison(db, report)

    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="update",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=f"{report.well_code_snapshot} {report.report_date}",
        summary="Confirmed source review" if data.confirm_review else "Updated daily report",
        request=request,
    )
    db.commit()
    db.refresh(report)
    return get_report(db, organization_id, report.id)


def review_timeline(db: Session, organization_id: str, report_id: str, data, user: User, request=None):
    """Confirm, correct or reject the plan-vs-timeline comparison on a report.

    The engineer's real question is not "was this day ahead?" but "did this job
    take the hours the programme said?". So the review carries **actual hours per
    activity**: the system fills them from the block's logged duration, and the
    engineer changes any figure the log got wrong. The variance and the lead/lag
    mark then recompute from the corrected hours, and every later day, chart and
    summary reads the corrected value because it is stored on the block.

    Rules, each of which exists to stop a plausible-but-wrong number:

    * Planned hours are the programme's and are never altered here. A daily log
      cannot rewrite the baseline; it can only disagree with it.
    * An edited actual needs a reason, because the value now differs from the
      time log and a reader must be able to tell why.
    * Rejecting blanks the comparison rather than zeroing it: "not comparable"
      and "on plan" are different statements.
    * The pre-edit figures stay on the row (``timeline_system_actual_hours``) so
      an audit can see what the system proposed and what was applied.
    """
    report = get_report(db, organization_id, report_id, lock=True)
    if report.status not in ("draft", "in_review"):
        raise HTTPException(409, "The timeline comparison can be reviewed while the report is a draft.")
    blocks = getattr(report, "_blocks", [])
    if not blocks:
        raise HTTPException(422, "Add time blocks before reviewing the timeline comparison.")
    by_id = {b.id: b for b in blocks}
    targets = [by_id[b] for b in (data.block_ids or [])] if data.block_ids else list(blocks)
    missing = [b for b in (data.block_ids or []) if b not in by_id]
    if missing:
        raise HTTPException(422, "A selected block is not in this report.")
    if not targets:
        raise HTTPException(422, "The selected blocks are not in this report.")
    if data.review_state == "edited" and not data.note.strip() and not data.hours:
        raise HTTPException(422, "A manual comparison needs a note or corrected actual hours.")

    # A correction that names a block this report does not hold is a stale screen,
    # not a small mistake: applying the rest and reporting success would leave the
    # engineer believing a figure was saved when it was dropped.
    unknown = sorted({row.block_id for row in data.hours} - set(by_id))
    if unknown:
        raise HTTPException(
            422,
            "A corrected actual belongs to a block that is no longer in this report. "
            "Reload the report and enter the hours again.",
        )
    outside = sorted({row.block_id for row in data.hours} - {b.id for b in targets})
    if outside:
        raise HTTPException(
            422, "A corrected actual was sent for a block that is not part of this review."
        )
    corrections = {row.block_id: row for row in data.hours}
    stamp = datetime.now(UTC)
    actor = _actor(user)
    for block in targets:
        correction = corrections.get(block.id)
        if correction is not None:
            if correction.actual_hours is None:
                # Clearing an edit restores the logged duration as the proposal.
                block.timeline_actual_hours = block.timeline_system_actual_hours
                block.timeline_actual_edited = False
                block.timeline_edited_by = ""
                block.timeline_edited_at = None
            else:
                if correction.actual_hours < 0:
                    raise HTTPException(422, "Actual hours cannot be negative.")
                block.timeline_actual_hours = rounded(correction.actual_hours)
                block.timeline_actual_edited = rounded(correction.actual_hours) != (
                    block.timeline_system_actual_hours
                )
                block.timeline_edited_by = actor
                block.timeline_edited_at = stamp
        elif block.timeline_actual_edited and block.timeline_actual_hours is not None:
            # Keep an earlier correction; recompute its variance below.
            pass
        block.timeline_review_state = data.review_state
        block.timeline_note = data.note.strip()[:500]
        block.timeline_reviewed_by = actor
        block.timeline_reviewed_at = stamp
        if data.review_state == "rejected":
            block.timeline_comparison = "on"
            block.timeline_variance_hours = None
            block.timeline_variance_days = None
    # Recompute the whole baseline: the correction just stored counts in its
    # code's group total, so the comparison on every sibling line — and on this
    # line — is the group arithmetic, not a per-line guess. Reviewed rows are
    # kept exactly as the engineer left them, so their stored values are written
    # here from the same group figures.
    baseline = _baseline_for(db, report)
    ledger: sequence.Ledger | None = None
    if baseline is not None:
        basis = f"programme {baseline.label or f'v{baseline.version_no}'}"
        # Suggested rows take the full rewrite; the reviewed rows below are then
        # written from the same ledger, with their review mark untouched. A
        # correction stored a moment ago counts in its code's total.
        _recompute_baseline(db, baseline, basis)
        # Answer on the same evidence the row was written from: a draft report is
        # reviewed against the hours actually recorded, a submitted one against the
        # confirmed figures only.
        ledger = _ledger(
            db, baseline, confirmed_only=report.status in CONFIRMED_STATUSES
        )
    state_by_item = {row.item_id: row for row in ledger.codes} if ledger else {}
    for block in targets:
        if data.review_state == "rejected":
            continue
        if baseline is None:
            block.timeline_comparison = data.comparison or "on"
            block.timeline_variance_hours = None
            block.timeline_variance_days = None
            continue
        state_row = state_by_item.get(block.timeline_plan_item_id or "")
        if state_row is None:
            # No comparable pair: the comparison is whatever the engineer stated
            # and no more — no variance is invented.
            block.timeline_comparison = data.comparison or "on"
            block.timeline_variance_hours = None
            block.timeline_variance_days = None
            continue
        block.timeline_sequence_state = state_row.state
        if state_row.state == sequence.COMPLETE:
            # The only state that carries a verdict. The hours decide the mark by
            # default, because they are evidence. When the engineer states one
            # instead — "the rig moved late, this is behind regardless of the
            # printed days" — their mark is kept and the variance still shows
            # beside it, so a reader sees both the figure and the call.
            block.timeline_variance_hours = state_row.variance_hours
            block.timeline_variance_days = state_row.variance_days
            computed = state_row.comparison
            block.timeline_comparison = data.comparison or computed
        else:
            # In progress, skipped or not started: no variance exists to show, and
            # the engineer's stated mark is kept as the mark.
            block.timeline_variance_hours = None
            block.timeline_variance_days = None
            block.timeline_comparison = data.comparison or "on"
        block.timeline_basis = (block.timeline_basis or basis)[:120]
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="review",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=f"{report.well_code_snapshot} {report.report_date}",
        summary=(
            f"{data.review_state.capitalize()} the plan-vs-timeline comparison on {len(targets)} block(s)"
            + (f" with {len(corrections)} corrected actual hour(s)" if corrections else "")
            + (f": {data.note.strip()}" if data.note.strip() else "")
        ),
        request=request,
    )
    db.commit()
    first = targets[0]
    # One variance per code, not per line: lines sharing a code all carry the
    # same group figures, so the report's total is the sum over the distinct
    # closed codes reviewed. An open code contributes nothing, because it has no
    # verdict — that is the whole point of the state model.
    reviewed_items: dict[str, str] = {}
    for block in targets:
        if block.timeline_review_state == "rejected":
            continue
        item_id = block.timeline_plan_item_id or (block.timeline_code or "").strip()
        if item_id:
            reviewed_items[item_id] = block.id
    total = Decimal(0)
    covered = 0
    for item_id in reviewed_items:
        row = state_by_item.get(item_id)
        if row is None or row.state != sequence.COMPLETE or row.variance_hours is None:
            continue
        total += row.variance_hours
        covered += 1
    return {
        "review_state": data.review_state,
        "updated_count": len(targets),
        "comparison": first.timeline_comparison if data.review_state != "rejected" else "on",
        "summary": (
            f"{data.review_state} on {len(targets)} block(s)"
            + ("" if covered else " · no reviewed activity is closed, so no lead or lag is claimed")
        ),
        "variance_hours": first.timeline_variance_hours,
        "total_variance_hours": rounded(total) if covered else None,
        "corrected_blocks": len([c for c in corrections.values() if c.actual_hours is not None]),
    }


def _metric_state(db, report):
    metric = db.scalar(
        select(OpsDailyMetric).where(
            OpsDailyMetric.organization_id == report.organization_id,
            OpsDailyMetric.well_id == report.well_id,
            OpsDailyMetric.scope == report.scope,
            OpsDailyMetric.report_date == report.report_date,
        )
    )
    if metric:
        metric.review_state = report.status


@dataclass(frozen=True)
class SubmitRefusal:
    """One reason a report cannot be submitted, with the answer it would produce.

    The checklist and the refusal are one piece of arithmetic: ``submit_refusals``
    collects everything that still stops a submission and ``submit_report`` turns
    the first one into the HTTP response. Returning a value instead of raising an
    ``HTTPException`` lets the read-only readiness check run exactly the same code
    without pretending it is the write.
    """

    message: str
    status_code: int = 422


def _is_measurement_only(report: OpsDailyReport, blocks: list[OpsActivityBlock]) -> bool:
    """A mud report with no shift blocks is a measurement, not a missing 24 hours."""

    return report.report_type == "DMR" and not blocks and bool((report.operation_summary or "").strip())


def submit_refusals(db: Session, report: OpsDailyReport, blocks: list[OpsActivityBlock]) -> list[SubmitRefusal]:
    """Everything that still stops this report being submitted, in reading order.

    Both the readiness panel and the submit route read this list, so the reason a
    user sees before pressing Submit is the reason the server gives after, and the
    two cannot drift apart. The order is the order the engineer would fix things:
    the review state first, then the time arithmetic, then the codes on each line.
    """

    refusals: list[SubmitRefusal] = []
    settings = db.scalar(select(OpsSettings).where(OpsSettings.organization_id == report.organization_id))
    measurement_only = _is_measurement_only(report, blocks)
    if not blocks and not measurement_only:
        refusals.append(
            SubmitRefusal("This report has no time blocks. Log the day's activities before submitting.")
        )
    if report.extraction_status == "needs_review" or any(
        b.review_state not in ("accepted", "edited") for b in blocks
    ):
        suggested = sum(1 for b in blocks if b.review_state not in ("accepted", "edited"))
        detail = (
            f" {suggested} suggested block(s) still need accepting or editing."
            if suggested
            else ""
        )
        refusals.append(
            SubmitRefusal("Review the suggested blocks and save the draft before submitting." + detail)
        )
    total = sum(b.duration_minutes for b in blocks)
    if not measurement_only and total > (settings.max_daily_hours if settings else 24) * 60:
        refusals.append(SubmitRefusal("Logged hours exceed the workspace maximum daily hours."))
    tolerance = settings.completeness_tolerance_minutes if settings else 2
    # With no log at all the missing blocks are the answer; a period-balance
    # figure on top of that only repeats it in different words.
    if blocks and not measurement_only and abs(total - report.period_minutes) > tolerance:
        # Saying which way the gap runs is the difference between "your log is
        # wrong" and "you have three hours left to account for".
        direction = "under" if total < report.period_minutes else "over"
        refusals.append(
            SubmitRefusal(
                f"Logged {total} minutes; expected {report.period_minutes} "
                f"({direction} by {abs(total - report.period_minutes)} minutes). "
                "Correct the log or the report period."
            )
        )
    if blocks:
        try:
            _validate_blocks(
                [{"sequence_no": b.sequence_no, "started_at": b.started_at, "ended_at": b.ended_at} for b in blocks],
                report.period_start_at,
                report.period_end_at,
            )
        except HTTPException as exc:
            refusals.append(SubmitRefusal(str(exc.detail), exc.status_code))
    for b in blocks:
        if message := describe_missing(b):
            refusals.append(SubmitRefusal(message))
        if (
            b.classification in ("NPT", "UPA")
            and not b.operation_id
            and (settings.require_operations if settings else True)
        ):
            refusals.append(SubmitRefusal(f"Block {b.sequence_no}: select the Operations code."))
        if b.classification in ("NPT", "UPA") or b.allocation in ("NPT", "UPA"):
            if settings and settings.require_npt_agency and not b.responsible_agency_id and not (
                b.vendor_id or b.responsible_party or ""
            ).strip():
                refusals.append(SubmitRefusal(f"Block {b.sequence_no}: select the responsible agency."))
            if (not settings or settings.require_npt_reason) and not (b.reason or "").strip():
                refusals.append(SubmitRefusal(f"Block {b.sequence_no}: enter the reason."))
    # A line with no sequence code is Unplanned Activity — real work, but work the
    # programme cannot account for. Submitting it is allowed by default (the
    # arithmetic already shows it as lag); a workspace that wants the code chosen
    # before submission switches this on, and the refusal names the line.
    if blocks and not measurement_only and sequence_policy.require_code_on_submit(db, report.organization_id):
        split_blocks = {
            row.block_id
            for row in db.scalars(
                select(OpsActivityBlockCode).where(
                    OpsActivityBlockCode.block_id.in_([b.id for b in blocks])
                )
            ).all()
        }
        # A line is accounted for when it carries a code, carries a split, or was
        # deliberately classified as Unplanned Activity with a reason. Anything
        # else is work nobody has said where it belongs.
        uncoded = [
            b.sequence_no
            for b in blocks
            if not (b.timeline_code or "").strip()
            and b.id not in split_blocks
            and not (b.classification == "UPA" and (b.reason or "").strip())
        ]
        if uncoded:
            refusals.append(
                SubmitRefusal(
                    "These lines carry no sequence code: "
                    + ", ".join(str(n) for n in uncoded[:10])
                    + (f" (+{len(uncoded) - 10} more)" if len(uncoded) > 10 else "")
                    + ". Code them, or classify the work as Unplanned Activity with a reason, before submitting."
                )
            )
    return refusals


def submit_readiness(db: Session, organization_id: str, report_id: str) -> dict[str, Any]:
    """Everything still outstanding before this report can be submitted.

    Read-only and side-effect free: the editor calls it after every save so the
    engineer sees the same checklist the submit route would refuse with, instead
    of discovering it from a bare 422.
    """

    report = get_report(db, organization_id, report_id)
    if report.status not in ("draft", "in_review", "rejected"):
        return {
            "ready": False,
            "blockers": [f"This report is {report.status}; only a draft, in-review or rejected report can be submitted."],
            "blocker_count": 1,
        }
    try:
        # The submit route refuses an unconfigured well scope before it reads a
        # single gate. A checklist that raised instead of reporting would hide
        # exactly the one thing standing in the way, so it becomes a blocker.
        scope.resolve(db, organization_id, report.well_id, report.scope, report.rig_id)
    except HTTPException as exc:
        return {"ready": False, "blockers": [str(exc.detail)], "blocker_count": 1}
    blocks = db.scalars(
        select(OpsActivityBlock).where(
            OpsActivityBlock.report_id == report.id, OpsActivityBlock.is_deleted.is_(False)
        )
    ).all()
    refusals = submit_refusals(db, report, list(blocks))
    return {
        "ready": not refusals,
        "blockers": [refusal.message for refusal in refusals],
        "blocker_count": len(refusals),
    }


def submit_report(db: Session, organization_id: str, report_id: str, user: User, request=None):
    report = get_report(db, organization_id, report_id, lock=True)
    if report.status not in ("draft", "in_review", "rejected"):
        raise HTTPException(409, "Only draft or in-review reports can be submitted")
    blocks = db.scalars(
        select(OpsActivityBlock).where(
            OpsActivityBlock.report_id == report.id, OpsActivityBlock.is_deleted.is_(False)
        )
    ).all()
    scope.resolve(db, organization_id, report.well_id, report.scope)
    # The gates live in one place: the readiness panel shows this same list, so a
    # refusal here is never the first time the engineer hears about it.
    refusals = submit_refusals(db, report, list(blocks))
    if refusals:
        # An out-of-period or overlapping log is still a 409; every other gate is
        # a 422. The first refusal is what the response carries, and the rest are
        # listed in the message so a caller that only reads `detail` sees them.
        first = refusals[0]
        detail = first.message
        if len(refusals) > 1:
            detail = "\n".join(refusal.message for refusal in refusals)
        raise HTTPException(first.status_code, detail)
    report.status = "submitted"
    _metric_state(db, report)
    report.submitted_at = datetime.now(UTC)
    report.submitted_by = _actor(user)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="submit",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=str(report.report_date),
        summary="Submitted report",
        request=request,
    )
    db.commit()
    return report


def approve_report(db: Session, organization_id: str, report_id: str, user: User, request=None):
    report = get_report(db, organization_id, report_id, lock=True)
    if report.status != "submitted":
        raise HTTPException(409, "Only submitted reports can be approved")
    report.status = "approved"
    _metric_state(db, report)
    report.approved_at = datetime.now(UTC)
    report.approved_by = _actor(user)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="approve",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=str(report.report_date),
        summary="Approved report",
        request=request,
    )
    db.commit()
    return report


def reopen_report(
    db: Session,
    organization_id: str,
    report_id: str,
    remarks: str,
    user: User,
    request=None,
    *,
    can_amend: bool = False,
):
    from app.core.time import wat_today

    reason = (remarks or "").strip()
    if len(reason) < 3:
        raise HTTPException(422, "Provide remarks (at least 3 characters) explaining why the report is reopened.")
    report = get_report(db, organization_id, report_id, lock=True)
    if report.status not in ("submitted", "approved"):
        raise HTTPException(409, "Only submitted or approved reports can be reopened to draft.")
    scope.resolve(db, organization_id, report.well_id, report.scope)
    age_days = (wat_today() - report.report_date).days
    if age_days > 30 and not can_amend:
        raise HTTPException(
            403,
            "Reopening a report more than 30 days after its report date requires ops-report:amend.",
        )
    prior_status = report.status
    now = datetime.now(UTC)
    actor = _actor(user)
    report.status = "draft"
    report.approved_at = None
    report.approved_by = ""
    report.reopened_at = now
    report.reopened_by = actor
    report.reopen_reason = reason[:500]
    report.revision_no = int(report.revision_no or 1) + 1
    report.updated_by = actor
    report.updated_at = now
    _metric_state(db, report)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="reopen",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=f"{report.well_code_snapshot} {report.report_date}",
        summary=f"Reopened {prior_status} report as draft (rev {report.revision_no}): {reason[:200]}",
        request=request,
    )
    db.commit()
    db.refresh(report)
    return get_report(db, organization_id, report.id)


def reject_report(db: Session, organization_id: str, report_id: str, reason: str, user: User, request=None):
    report = get_report(db, organization_id, report_id, lock=True)
    if report.status != "submitted":
        raise HTTPException(409, "Only submitted reports can be rejected")
    report.status = "rejected"
    _metric_state(db, report)
    report.rejection_reason = reason[:500]
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="reject",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=str(report.report_date),
        summary=f"Rejected: {reason[:100]}",
        request=request,
    )
    db.commit()
    return report


def delete_reports(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(
        select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.id.in_(ids))
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more reports not found")
    if any(r.status in ("approved", "submitted") for r in rows):
        raise HTTPException(409, "Submitted and approved reports cannot be deleted.")
    now = datetime.now(UTC)
    affected = 0
    for r in rows:
        if not r.is_deleted:
            r.is_deleted = True
            r.deleted_at = now
            affected += 1
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="delete",
        entity_type="ops_report",
        entity_id=None,
        entity_label=f"{affected} report(s)",
        summary=f"Deleted {affected} report(s)",
        request=request,
    )
    db.commit()
    return {"affected_count": affected}


def restore_reports(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(
        select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.id.in_(ids))
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more reports not found")
    affected = 0
    for r in rows:
        if r.is_deleted:
            r.is_deleted = False
            r.deleted_at = None
            affected += 1
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="restore",
        entity_type="ops_report",
        entity_id=None,
        entity_label=f"{affected} report(s)",
        summary=f"Restored {affected} report(s)",
        request=request,
    )
    db.commit()
    return {"affected_count": affected}


def purge_reports(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(
        select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.id.in_(ids))
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more reports not found")
    affected = 0
    for r in rows:
        if not r.is_deleted:
            raise HTTPException(409, "Only deleted reports can be permanently removed")
        # delete blocks first
        blocks = db.scalars(select(OpsActivityBlock).where(OpsActivityBlock.report_id == r.id)).all()
        for b in blocks:
            db.delete(b)
        db.execute(
            delete(OpsDailyMetric).where(
                OpsDailyMetric.organization_id == organization_id,
                OpsDailyMetric.well_id == r.well_id,
                OpsDailyMetric.scope == r.scope,
                OpsDailyMetric.report_date == r.report_date,
            )
        )
        db.execute(
            delete(OpsSurvey).where(OpsSurvey.organization_id == organization_id, OpsSurvey.report_id == r.id)
        )
        db.delete(r)
        affected += 1
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="permanent-delete",
        entity_type="ops_report",
        entity_id=None,
        entity_label=f"{affected} report(s)",
        summary=f"Purged {affected} report(s)",
        request=request,
    )
    db.commit()
    return {"affected_count": affected}


def brief_for_report(db: Session, organization_id: str, report_id: str, *, include_deleted=False):
    report = get_report(db, organization_id, report_id, include_deleted=include_deleted)
    blocks = getattr(report, "_blocks", [])
    total = sum(b.duration_minutes for b in blocks)
    planned = sum(b.duration_minutes for b in blocks if b.classification == "Planned")
    upa = sum(b.duration_minutes for b in blocks if b.classification == "UPA")
    npt = sum(b.duration_minutes for b in blocks if b.classification == "NPT")
    labels = report_labels(db, organization_id)
    npt_items = [
        {
            "operation_code": labels["operation_code"].get(b.operation_id, ""),
            "npt_code": labels["npt"].get(b.operation_id, ""),
            "reason": b.reason or b.narrative[:100],
            "duration_minutes": b.duration_minutes,
            "responsible_party": b.responsible_party,
        }
        for b in blocks
        if b.classification == "NPT" or b.allocation == "NPT"
    ]
    time_split = {
        "planned_minutes": planned,
        "upa_minutes": upa,
        "npt_minutes": npt,
        "unaccounted_minutes": getattr(report, "_unaccounted_minutes", 0),
        "total_minutes": total,
        "avg_confidence": str(rounded(sum((b.confidence for b in blocks), Decimal(0)) / len(blocks))) if blocks else "0.000",
    }
    footage, rotating_hours = penetration(report, blocks)
    rop = compute_rop(footage, rotating_hours, scope=report.scope)

    text = daily_brief(report, blocks, footage, rotating_hours, rop, labels=labels)
    return {
        "report_id": report.id,
        "well_code": report.well_code_snapshot,
        "well_name": report.well_name_snapshot,
        "report_date": report.report_date,
        "day_number": report.day_number,
        "summary": text,
        "time_split": time_split,
        "npt_items": npt_items,
        "depth_progress": {
            "depth_start_m": str(report.depth_start_m) if report.depth_start_m is not None else None,
            "depth_end_m": str(report.depth_end_m) if report.depth_end_m is not None else None,
            "footage_m": str(footage) if footage is not None else None,
            "rotating_hours": str(rounded(rotating_hours)) if rotating_hours is not None else None,
            "rop_m_per_hr": str(rop) if rop is not None else None,
        },
        "data_quality": {
            "blocks": len(blocks),
            "avg_confidence": time_split["avg_confidence"],
            "unaccounted_minutes": time_split["unaccounted_minutes"],
        },
    }
