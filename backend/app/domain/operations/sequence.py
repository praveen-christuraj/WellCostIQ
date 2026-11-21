"""Sequence ledger: what a sequence code has earned, spent and still owes.

Lead and lag are hours, never opinions, and they are never read off a narrative.
Every line of a baseline programme carries a sequence code; a daily-report line
joins that code explicitly. The hours of every line sharing a code are summed and
compared with the programme's planned hours for it:

    variance (hours) = planned − actual        positive = lead, negative = lag
    variance (days)  = variance (hours) / 24

That is only half the question, and on its own it produces a number an engineer
cannot defend. This module adds the two facts the arithmetic needs to be honest:

* **A code has a state.** A plan of 100 h with 12 h logged has not finished
  88 hours early — it is 12 % through and owes 88 hours (``in_progress``). Only a
  *closed* code earns a lead or a lag. A code nobody has touched is
  ``not_started``, not "on plan". A code logged past its plan without a close is
  ``overrun_open``: over plan, still open.
* **Hours with no code are work, not noise.** They are *Unplanned Activity*: they
  raise actual hours while planned hours stay put, so they can only produce lag.
  They are a row in the ledger, never a footnote that says "excluded".

A skipped programmed activity releases its planned hours. They are reported once as
saved (``planned_saved``) and are **not** netted into the realised variance by
default; the saving reaches the schedule once, honestly, by moving every later
activity's *effective* cumulative position earlier. The saved programme curve is
never rewritten, so a submitted month keeps reading as it was signed.

Two measures, never mixed
-------------------------

``realised_variance``  — did the work we *finished* take the hours allowed?
                         Valid only over closed codes; says nothing about the open
                         ones, and prints the share of the plan it covers.
``plan_coverage``      — actual ÷ planned over the whole plan. This is burn, not a
                         verdict: it counts work not yet started. It is shown
                         because engineers use it, named so nobody reads it as a lead.

Layering
--------
Pure and deterministic: no session, no clock, no query, no randomness. The service
layer gathers rows and contributions; this module decides the arithmetic. Same split
as ``entry_statistics``/``entry_rules`` → ``entry_checks``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

#: One shift. The request states the conversion explicitly: hours ÷ 24, once, here.
HOURS_PER_DAY = Decimal(24)

#: Stored values are read at three places (``core.precision``); round at the boundary.
QUANTUM = Decimal("0.001")

# States a code can be in. Derived, never typed by a user.
NOT_STARTED = "not_started"
IN_PROGRESS = "in_progress"
OVERRUN_OPEN = "overrun_open"
COMPLETE = "complete"
SKIPPED = "skipped"

STATES = (NOT_STARTED, IN_PROGRESS, OVERRUN_OPEN, COMPLETE, SKIPPED)

#: ``allocation`` values that are not productive work against the programme.
NPT_ALLOCATIONS = ("NPT",)


def rounded(value: Decimal) -> Decimal:
    return value.quantize(QUANTUM, rounding=ROUND_HALF_UP)


def to_days(hours: Decimal | None) -> Decimal | None:
    """Convert a variance in hours to days. None stays None: unknown is not zero."""
    if hours is None:
        return None
    return rounded(Decimal(hours) / HOURS_PER_DAY)


def _dec(value) -> Decimal | None:
    """Read a stored number as Decimal without importing binary residue."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class Policy:
    """How this workspace reads the awkward cases. Every default is the ask."""

    #: ``lag`` — unassigned hours add to actual and produce lag (the request).
    #: ``exclude`` — the historical behaviour, kept so a workspace can opt out.
    uncoded: str = "lag"
    #: ``include`` — NPT hours inside the unplanned lag. ``exclude`` — shown, not subtracted.
    npt: str = "include"
    #: ``separate`` — skipped hours reported beside the variance (default).
    #: ``net`` — skipped hours added to the realised variance as a lead.
    skipped_credit: str = "separate"
    #: ``actual >= planned × (1 + pct/100)`` suggests closing the code.
    auto_close_tolerance_pct: Decimal = Decimal(0)
    #: Apply an auto-close without a reviewer. Off by default: 100 h finished in 90
    #: and 100 h burned without finishing the hole are not the same event.
    auto_close: bool = False

    def normalised(self) -> "Policy":
        return Policy(
            uncoded=self.uncoded if self.uncoded in ("lag", "exclude") else "lag",
            npt=self.npt if self.npt in ("include", "exclude") else "include",
            skipped_credit=self.skipped_credit if self.skipped_credit in ("separate", "net") else "separate",
            auto_close_tolerance_pct=_dec(self.auto_close_tolerance_pct) or Decimal(0),
            auto_close=bool(self.auto_close),
        )


@dataclass(frozen=True)
class PlanRow:
    """One line of the baseline programme, as the ledger needs it."""

    item_id: str
    sequence_no: int
    description: str = ""
    planned_hours: Decimal | None = None
    target_depth_m: Decimal | None = None
    #: The cumulative days the saved programme prints for this line (never rewritten).
    saved_cum_days: Decimal | None = None
    hole_section_id: str | None = None
    phase_id: str | None = None
    skipped: bool = False
    skip_reason: str = ""
    skipped_by: str = ""
    skipped_at: datetime | None = None
    closed_at: datetime | None = None
    closed_by: str = ""
    close_source: str = ""
    close_note: str = ""
    #: The actual the engineer confirmed at close, when they disagreed with the sum.
    closed_actual_hours: Decimal | None = None


@dataclass(frozen=True)
class Contribution:
    """Hours that belong to a code — one block, or one slice of a split block."""

    block_id: str
    report_id: str
    item_id: str | None
    hours: Decimal
    #: Submitted or approved. A draft is provisional and does not vote.
    confirmed: bool = True
    allocation: str = "PT"
    report_date: str = ""


@dataclass
class CodeRow:
    """One sequence code's position. A field is None when the fact is unknown."""

    item_id: str
    sequence_no: int
    description: str
    state: str
    planned_hours: Decimal | None
    actual_hours: Decimal | None
    progress_pct: Decimal | None
    remaining_hours: Decimal | None
    variance_hours: Decimal | None
    variance_days: Decimal | None
    comparison: str
    #: True when the code looks finished but no engineer has closed it.
    close_suggested: bool
    closed_at: datetime | None
    close_source: str
    close_note: str
    saved_planned_hours: Decimal | None
    skip_reason: str
    skipped_by: str
    skipped_at: datetime | None
    effective_cum_days: Decimal | None
    cum_shift_days: Decimal | None
    saved_cum_days: Decimal | None
    target_depth_m: Decimal | None
    line_count: int
    report_count: int
    #: Hours logged by drafts only; shown beside the confirmed figure, never in it.
    provisional_actual_hours: Decimal | None
    line_ids: list[str] = field(default_factory=list)
    report_ids: list[str] = field(default_factory=list)


@dataclass
class UnplannedRow:
    """Hours logged against no sequence code — the lag nobody planned for."""

    code: str
    actual_hours: Decimal | None
    upa_hours: Decimal | None
    npt_hours: Decimal | None
    other_hours: Decimal | None
    variance_hours: Decimal | None
    variance_days: Decimal | None
    comparison: str
    line_count: int
    provisional_hours: Decimal | None
    #: Hours whose code names a row that is not in this programme.
    unmatched_hours: Decimal | None = None


@dataclass
class Totals:
    planned_in_scope: Decimal | None
    planned_saved: Decimal | None
    actual_coded: Decimal | None
    actual_unplanned: Decimal | None
    actual_total: Decimal | None
    realised_variance: Decimal | None
    realised_variance_days: Decimal | None
    comparison: str
    closed_coverage_pct: Decimal | None
    plan_coverage_pct: Decimal | None
    plan_coverage_days: Decimal | None
    planned_in_scope_days: Decimal | None
    provisional_actual_hours: Decimal | None
    closed_code_count: int
    open_code_count: int
    not_started_count: int
    skipped_count: int
    missing_planned_hours: int
    #: Hours a code carries that are not attributable (orphan codes, remainders).
    unattributed_hours: Decimal | None


@dataclass
class Finding:
    kind: str
    message: str
    item_id: str | None = None
    block_id: str | None = None
    severity: str = "note"


@dataclass
class Ledger:
    codes: list[CodeRow]
    unplanned: UnplannedRow
    totals: Totals
    findings: list[Finding]
    policy: Policy
    confirmed_only: bool

    def effective_cum_days(self) -> dict[str, Decimal | None]:
        return {row.item_id: row.effective_cum_days for row in self.codes}


def _sum(values) -> Decimal | None:
    total = Decimal(0)
    seen = False
    for value in values:
        if value is None:
            continue
        total += value
        seen = True
    return rounded(total) if seen else None


def _state(
    row: PlanRow, actual: Decimal | None, policy: Policy
) -> tuple[str, bool, Decimal | None, Decimal | None]:
    """Return ``(state, close_suggested, progress_pct, remaining)``.

    The single most important line in the module: work that has started and not
    finished is **not** a lead. It has progress and it owes hours.
    """
    if row.skipped:
        return SKIPPED, False, None, None
    planned = row.planned_hours
    if row.closed_at is not None or row.close_source:
        progress = None
        if planned is not None and planned > 0 and actual is not None:
            progress = rounded(min(Decimal(100), actual / planned * 100))
        return COMPLETE, False, progress, Decimal(0)
    if actual is None or actual <= 0:
        return NOT_STARTED, False, None, planned
    if planned is None:
        # Hours exist against a row with no planned figure: open, nothing to compare.
        return IN_PROGRESS, False, None, None
    if planned <= 0:
        return OVERRUN_OPEN, True, None, Decimal(0)
    progress = rounded(min(Decimal(100), actual / planned * 100))
    remaining = rounded(max(Decimal(0), planned - actual))
    tolerance = planned * (Decimal(1) + (policy.auto_close_tolerance_pct / 100))
    if actual > planned:
        if policy.auto_close and actual >= tolerance:
            return COMPLETE, False, progress, Decimal(0)
        return OVERRUN_OPEN, True, progress, Decimal(0)
    if actual == planned:
        # Fully logged, nothing left, but nobody has said the job is finished.
        return IN_PROGRESS, True, progress, Decimal(0)
    return IN_PROGRESS, False, progress, remaining


def effective_cum_days(rows: list[PlanRow]) -> dict[str, Decimal | None]:
    """Cumulative planned days with skipped rows contributing nothing.

    The saved programme curve keeps its own numbers; this is the curve the plan is
    actually being run on once activities are skipped.
    """
    out: dict[str, Decimal | None] = {}
    hours = Decimal(0)
    for row in sorted(rows, key=lambda r: (r.sequence_no, r.item_id)):
        if not row.skipped and row.planned_hours is not None:
            hours += row.planned_hours
        out[row.item_id] = rounded(hours / HOURS_PER_DAY)
    return out


def _finding(kind: str, message: str, *, item_id=None, block_id=None, severity="note") -> Finding:
    return Finding(kind=kind, message=message, item_id=item_id, block_id=block_id, severity=severity)


def build_ledger(
    rows: list[PlanRow],
    contributions: list[Contribution],
    policy: Policy | None = None,
    *,
    confirmed_only: bool = True,
) -> Ledger:
    """The whole arithmetic for one baseline programme.

    ``confirmed_only`` excludes draft/in-review hours from every figure it prints;
    those hours are still returned per code (``provisional_actual_hours``) so a
    reader can see what is waiting to be submitted. A draft must never change a
    submitted month.
    """
    policy = (policy or Policy()).normalised()
    by_item = {row.item_id: row for row in rows}
    ordered = sorted(rows, key=lambda r: (r.sequence_no, r.item_id))

    confirmed: dict[str, list[Contribution]] = {}
    provisional: dict[str, list[Contribution]] = {}
    unplanned_confirmed: list[Contribution] = []
    unplanned_provisional: list[Contribution] = []
    unmatched_confirmed: list[Contribution] = []

    for contribution in contributions:
        hours = _dec(contribution.hours) or Decimal(0)
        if hours == 0:
            continue
        piece = Contribution(
            block_id=contribution.block_id,
            report_id=contribution.report_id,
            item_id=contribution.item_id,
            hours=hours,
            confirmed=contribution.confirmed,
            allocation=contribution.allocation or "PT",
            report_date=contribution.report_date,
        )
        bucket = confirmed if contribution.confirmed else provisional
        if contribution.item_id and contribution.item_id in by_item:
            bucket.setdefault(contribution.item_id, []).append(piece)
        elif contribution.item_id:
            # A code that is not a line of this programme is not attributable here.
            if contribution.confirmed:
                unmatched_confirmed.append(piece)
            else:
                bucket.setdefault("__unmatched__", []).append(piece)
        else:
            (unplanned_confirmed if contribution.confirmed else unplanned_provisional).append(piece)

    effective = effective_cum_days(ordered)
    findings: list[Finding] = []
    codes: list[CodeRow] = []

    for row in ordered:
        group = confirmed.get(row.item_id, [])
        draft = provisional.get(row.item_id, [])
        # ``confirmed_only`` is a *reporting* choice, not an arithmetic one: when a
        # reviewer asks for the inclusive ledger on a draft, the drafts are what has
        # actually been recorded so far, so they are the actual. The confirmed-only
        # ledger keeps them out, and returns them separately as what is waiting to
        # be submitted.
        if confirmed_only:
            actual = _sum(c.hours for c in group)
        else:
            actual = _sum([*(c.hours for c in group), *(c.hours for c in draft)])
        provisional_actual = _sum(c.hours for c in draft)
        # Hours typed at the close are used only for an activity that has no lines
        # of its own. Where lines exist, they *are* the record: a correction, or a
        # late submission, must move the verdict, and a frozen typed figure would
        # silently disagree with the reports it was drawn from.
        if row.closed_actual_hours is not None and actual is None:
            actual = rounded(_dec(row.closed_actual_hours) or Decimal(0))
        state, close_suggested, progress, remaining = _state(row, actual, policy)
        planned = _dec(row.planned_hours)

        variance = None
        variance_days = None
        comparison = "on"
        if state == COMPLETE:
            if planned is not None and actual is not None:
                variance = rounded(planned - actual)
                variance_days = to_days(variance)
                comparison = "ahead" if variance > 0 else ("behind" if variance < 0 else "on")
            elif actual is None and planned is not None:
                # Closed with nothing logged: the whole plan is a lead, and that is
                # a claim worth making explicit rather than hiding behind "on".
                variance = rounded(planned)
                variance_days = to_days(variance)
                comparison = "ahead"
        elif state == SKIPPED and actual:
            findings.append(
                _finding(
                    "hours_on_skipped_activity",
                    f"Sequence {row.sequence_no} is skipped but has {rounded(actual)} h coded to it. "
                    "Move those hours to the activity that did the work, or correct the log.",
                    item_id=row.item_id,
                    severity="warning",
                )
            )
        if close_suggested and state != COMPLETE:
            findings.append(
                _finding(
                    "close_suggested",
                    f"Sequence {row.sequence_no} has logged its planned hours ({planned}) but is not closed. "
                    "Close it to record the outcome, or correct the actual hours.",
                    item_id=row.item_id,
                )
            )

        # The lines whose hours the actual is made of — drafts included when the
        # inclusive ledger is asked for, because those are the lines being closed.
        voters = group if confirmed_only else [*group, *draft]
        line_ids = list(dict.fromkeys(c.block_id for c in voters))
        report_ids = list(dict.fromkeys(c.report_id for c in voters))
        saved_cum = _dec(row.saved_cum_days)
        eff = effective.get(row.item_id)
        shift = None
        if saved_cum is not None and eff is not None:
            shift = rounded(saved_cum - eff)

        codes.append(
            CodeRow(
                item_id=row.item_id,
                sequence_no=row.sequence_no,
                description=(row.description or "")[:500],
                state=state,
                planned_hours=planned,
                actual_hours=actual,
                progress_pct=progress,
                remaining_hours=remaining,
                variance_hours=variance,
                variance_days=variance_days,
                comparison=comparison,
                close_suggested=bool(close_suggested),
                closed_at=row.closed_at,
                close_source=row.close_source,
                close_note=row.close_note,
                saved_planned_hours=planned if state == SKIPPED else None,
                skip_reason=row.skip_reason,
                skipped_by=row.skipped_by,
                skipped_at=row.skipped_at,
                effective_cum_days=eff,
                cum_shift_days=shift,
                saved_cum_days=saved_cum,
                target_depth_m=_dec(row.target_depth_m),
                line_count=len(line_ids),
                report_count=len(report_ids),
                provisional_actual_hours=provisional_actual,
                line_ids=line_ids,
                report_ids=report_ids,
            )
        )

    # ------------------------------------------------------------------ unplanned
    def _allocation_hours(items, *allocations) -> Decimal | None:
        picked = [c.hours for c in items if (c.allocation or "PT") in allocations]
        return _sum(picked)

    npt_hours = _allocation_hours(unplanned_confirmed, *NPT_ALLOCATIONS)
    upa_hours = _allocation_hours(unplanned_confirmed, "UPA")
    other_hours = _sum(
        c.hours for c in unplanned_confirmed if (c.allocation or "PT") not in (*NPT_ALLOCATIONS, "UPA")
    )
    unmatched_hours = _sum(c.hours for c in unmatched_confirmed)
    unplanned_actual = _sum(c.hours for c in unplanned_confirmed)
    unplanned_provisional_hours = _sum(c.hours for c in unplanned_provisional)

    subtractable = unplanned_actual
    if policy.uncoded == "exclude":
        subtractable = None
    elif policy.npt == "exclude" and unplanned_actual is not None:
        subtractable = rounded(unplanned_actual - (npt_hours or Decimal(0)))

    unplanned_variance = None
    unplanned_days = None
    if unplanned_actual is not None and unplanned_actual > 0:
        unplanned_variance = rounded(-unplanned_actual)
        unplanned_days = to_days(unplanned_variance)

    unplanned = UnplannedRow(
        code="—",
        actual_hours=unplanned_actual,
        upa_hours=upa_hours,
        npt_hours=npt_hours,
        other_hours=other_hours,
        variance_hours=unplanned_variance,
        variance_days=unplanned_days,
        comparison="behind" if (unplanned_variance is not None and unplanned_variance < 0) else "on",
        line_count=len({c.block_id for c in unplanned_confirmed}),
        provisional_hours=unplanned_provisional_hours,
        unmatched_hours=unmatched_hours,
    )
    if unmatched_hours:
        findings.append(
            _finding(
                "code_not_in_programme",
                f"{unmatched_hours} h are coded to a sequence that is not a line of this programme "
                "and cannot be attributed. Re-code them, or activate the programme they belong to.",
                severity="warning",
            )
        )
    if unplanned_actual:
        findings.append(
            _finding(
                "unplanned_activity",
                f"{unplanned_actual} h are logged against no sequence code. They add to actual hours while "
                f"planned hours stay put, so they read as lag"
                + (" and are included in the sequence variance." if policy.uncoded == "lag"
                   else " and are shown but not subtracted, by this workspace's policy."),
                severity="warning" if policy.uncoded == "lag" else "note",
            )
        )

    # -------------------------------------------------------------------- totals
    planned_in_scope = _sum(row.planned_hours for row in ordered if not row.skipped)
    planned_saved = _sum(row.planned_hours for row in ordered if row.skipped)
    actual_coded = _sum(c.hours for group in confirmed.values() for c in group)
    closed_planned = _sum(
        _dec(row.planned_hours) for row in ordered if not row.skipped and _is_closed(row, confirmed.get(row.item_id, []), policy)
    )
    # The printed lead/lag. An empty sum of finished activities is zero, not
    # "nothing to say": 20 h of unplanned work against a programme where nothing has
    # finished yet is a 20 h lag, and returning None there would hide exactly the
    # hours the old code dropped. Only a programme with no hours at all has no
    # figure to print.
    finished = _sum(row.variance_hours for row in codes if row.state == COMPLETE)
    realised = None
    if finished is not None or subtractable is not None:
        realised = rounded((finished or Decimal(0)) - (subtractable or Decimal(0)))
    if realised is not None and policy.skipped_credit == "net" and planned_saved is not None:
        realised = rounded(realised + planned_saved)
    if realised is None and policy.skipped_credit == "net" and planned_saved is not None:
        realised = rounded(planned_saved)
    realised_days = to_days(realised)
    comparison = "on"
    if realised is not None:
        comparison = "ahead" if realised > 0 else ("behind" if realised < 0 else "on")

    actual_total = None
    coded = actual_coded or Decimal(0)
    unplanned_total = unplanned_actual or Decimal(0)
    if actual_coded is not None or unplanned_actual is not None:
        actual_total = rounded(coded + unplanned_total)
    # Draft hours are shown beside the confirmed figure, never added to it: a draft
    # must not move a submitted month, but the engineer still needs to see what is
    # waiting behind it.
    provisional_total = _sum(
        [*(c.hours for group in provisional.values() for c in group), unplanned_provisional_hours]
    )

    closed_coverage = None
    if planned_in_scope and planned_in_scope > 0 and closed_planned is not None:
        closed_coverage = rounded(min(Decimal(100), closed_planned / planned_in_scope * 100))
    plan_coverage = None
    if planned_in_scope and planned_in_scope > 0 and actual_total is not None:
        plan_coverage = rounded(actual_total / planned_in_scope * 100)

    open_states = (IN_PROGRESS, OVERRUN_OPEN)
    missing_planned = sum(1 for row in ordered if not row.skipped and row.planned_hours is None)
    if missing_planned:
        findings.append(
            _finding(
                "missing_planned_hours",
                f"{missing_planned} programme activit{'y has' if missing_planned == 1 else 'ies have'} no planned "
                "hours. They are counted in the plan as zero and cannot produce a variance.",
                severity="warning",
            )
        )
    if any(row.state == NOT_STARTED for row in codes):
        findings.append(
            _finding(
                "not_started",
                f"{sum(1 for row in codes if row.state == NOT_STARTED)} programme activit"
                f"{'y is' if sum(1 for row in codes if row.state == NOT_STARTED) == 1 else 'ies are'} not started. "
                "Their planned hours stay in the plan and are excluded from the sequence variance.",
            )
        )

    totals = Totals(
        planned_in_scope=planned_in_scope,
        planned_saved=planned_saved,
        actual_coded=actual_coded,
        actual_unplanned=unplanned_actual,
        actual_total=actual_total,
        realised_variance=realised,
        realised_variance_days=realised_days,
        comparison=comparison,
        closed_coverage_pct=closed_coverage,
        plan_coverage_pct=plan_coverage,
        plan_coverage_days=to_days(actual_total) if actual_total is not None else None,
        planned_in_scope_days=to_days(planned_in_scope) if planned_in_scope is not None else None,
        provisional_actual_hours=provisional_total,
        closed_code_count=sum(1 for row in codes if row.state == COMPLETE),
        open_code_count=sum(1 for row in codes if row.state in open_states),
        not_started_count=sum(1 for row in codes if row.state == NOT_STARTED),
        skipped_count=sum(1 for row in codes if row.state == SKIPPED),
        missing_planned_hours=missing_planned,
        unattributed_hours=unmatched_hours,
    )
    return Ledger(
        codes=codes,
        unplanned=unplanned,
        totals=totals,
        findings=findings,
        policy=policy,
        confirmed_only=confirmed_only,
    )


def _is_closed(row: PlanRow, group: list[Contribution], policy: Policy) -> bool:
    actual = _sum(c.hours for c in group)
    if row.closed_actual_hours is not None:
        actual = rounded(_dec(row.closed_actual_hours) or Decimal(0))
    state, _, _, _ = _state(row, actual, policy)
    return state == COMPLETE


def schedule_position(
    rows: list[PlanRow], checkpoint_item_id: str | None, elapsed_days: Decimal | None
) -> Decimal | None:
    """Days ahead (+) or behind (−) the programme, on the effective curve.

    ``elapsed_days`` is the caller's business: programme start, reported DFS or the
    first submitted period — ``analytics.time_depth`` already owns that basis. This
    function only chooses the planned position, and it uses the curve with skipped
    activities removed so a saving reaches the schedule once, without rewriting the
    saved baseline.
    """
    if checkpoint_item_id is None or elapsed_days is None:
        return None
    effective = effective_cum_days(rows)
    planned = effective.get(checkpoint_item_id)
    if planned is None:
        return None
    return rounded(planned - Decimal(elapsed_days))
