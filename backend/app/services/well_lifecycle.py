"""The single state machine behind a well scope's status and its plan status.

Every configuration scope of a well (Drilling, Completion) carries two linear
ladders:

    Well status   upcoming -> active -> final_review -> completed
    Plan status   draft -> configured -> completed

They are coupled at exactly one point: a scope that left operations (final
review or completed) carries a *completed* plan, and a scope that is upcoming or
active never does. The table below is therefore the whole lifecycle::

    stage  well status    plan status   what it means
    1      upcoming       draft         on the programme, plan being written
    2      upcoming       configured    plan signed off, budgetable (AFE)
    3      active         configured    operations running, daily costs booked
           active         draft         plan reopened for a correction
    4      final_review   completed     operations ended, costs closed for review
    5      completed      completed     signed off

Each step forward has exactly one step back, and a step back always lands on the
previous status — never two steps, never a different branch:

    forward                         rollback
    configure     draft->configured draft        configured->draft
    start         upcoming->active  defer        active->upcoming
    final_review  active->final rev reactivate   final review->active
    complete      final rev->compl. reopen       completed->final review

Forward moves need ``rig-well:update``. Rollbacks need ``rig-well:rollback``, so
the authority to undo a sign-off can be granted separately from day-to-day
editing. Both always need a reason, and both are written to the audit trail with
the status before and after.

Nothing outside this module decides whether a move is legal. The API asks
``available_transitions`` what to offer and ``apply_transition`` to perform it,
and the modules that start a scope as a side effect (the first daily cost sheet,
a recorded spud) call ``auto_start``.
"""

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Afe, DailyCostEntry, Well
from app.models.rig_well import (
    WELL_CLOSED_STATUSES,
    WELL_OPEN_STATUSES,
    WELL_PLAN_STATUSES,
    WELL_TRACKING_STATUSES,
)

UPDATE_PERMISSION = "rig-well:update"
ROLLBACK_PERMISSION = "rig-well:rollback"

STATUS_LABELS: dict[str, str] = {
    "upcoming": "Upcoming",
    "active": "Active",
    "final_review": "Final review",
    "completed": "Completed",
}
PLAN_LABELS: dict[str, str] = {
    "draft": "Draft",
    "configured": "Configured",
    "completed": "Completed",
}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status.replace("_", " ").title())


def plan_label(status: str) -> str:
    return PLAN_LABELS.get(status, status.replace("_", " ").title())


@dataclass(frozen=True)
class Transition:
    """One legal move of one ladder."""

    action: str
    #: What the button says. ``{scope}`` is replaced with Drilling / Completion.
    label: str
    #: What the confirmation dialog explains before the move is made.
    description: str
    ladder: str  # "well" | "plan"
    direction: str  # "forward" | "rollback"
    from_statuses: tuple[str, ...]
    from_plans: tuple[str, ...]
    to_status: str | None = None
    to_plan: str | None = None
    #: The saved section / phase plan must exist before this move.
    needs_sections: bool = False

    @property
    def permission(self) -> str:
        return ROLLBACK_PERMISSION if self.direction == "rollback" else UPDATE_PERMISSION


TRANSITIONS: tuple[Transition, ...] = (
    Transition(
        action="configure",
        label="Mark {scope} plan configured",
        description=(
            "The saved plan becomes the signed-off baseline that AFEs, SOW adjustments and daily "
            "costs are built on. It is read-only until it is reopened as Draft."
        ),
        ladder="plan", direction="forward",
        from_statuses=WELL_OPEN_STATUSES, from_plans=("draft",),
        to_plan="configured", needs_sections=True,
    ),
    Transition(
        action="draft",
        label="Reopen {scope} plan as Draft",
        description=(
            "Rolls the plan back from Configured to Draft so it can be edited. New AFEs, SOW "
            "adjustments and daily cost sheets wait until the plan is configured again."
        ),
        ladder="plan", direction="rollback",
        from_statuses=WELL_OPEN_STATUSES, from_plans=("configured",),
        to_plan="draft",
    ),
    Transition(
        action="start",
        label="Start {scope} scope (mark Active)",
        description=(
            "Operations have begun, so the scope leaves Upcoming and becomes Active. Budget and "
            "MIS reports start counting it against the programme."
        ),
        ladder="well", direction="forward",
        from_statuses=("upcoming",), from_plans=("configured",),
        to_status="active", needs_sections=True,
    ),
    Transition(
        action="defer",
        label="Move {scope} back to Upcoming",
        description=(
            "Rolls the scope back from Active to Upcoming — for a start that was recorded too "
            "early. Refused while the scope has daily cost sheets or a spud date & time, because "
            "those prove it ran."
        ),
        ladder="well", direction="rollback",
        from_statuses=("active",), from_plans=("draft", "configured"),
        to_status="upcoming",
    ),
    Transition(
        action="final_review",
        label="Send {scope} to Final review",
        description=(
            "Operations have ended. The scope moves to Final review and its plan is closed as "
            "Completed: no new daily cost sheets, AFEs or plan adjustments are accepted while the "
            "costs are reviewed."
        ),
        ladder="well", direction="forward",
        from_statuses=("active",), from_plans=("configured",),
        to_status="final_review", to_plan="completed", needs_sections=True,
    ),
    Transition(
        action="reactivate",
        label="Return {scope} to Active",
        description=(
            "Rolls the scope back from Final review to Active and reopens its plan as Configured, "
            "so daily costs and adjustments can be recorded again."
        ),
        ladder="well", direction="rollback",
        from_statuses=("final_review",), from_plans=WELL_PLAN_STATUSES,
        to_status="active", to_plan="configured",
    ),
    Transition(
        action="complete",
        label="Mark {scope} Completed",
        description=(
            "The final review is finished and the scope is signed off as Completed. Its plan and "
            "costs stay read-only; a completed scope can be rolled back to Final review."
        ),
        ladder="well", direction="forward",
        from_statuses=("final_review",), from_plans=WELL_PLAN_STATUSES,
        to_status="completed", to_plan="completed",
    ),
    Transition(
        action="reopen",
        label="Return {scope} to Final review",
        description=(
            "Rolls the scope back from Completed to Final review. The plan stays closed; return "
            "the scope to Active from there if operations or costs must be reopened."
        ),
        ladder="well", direction="rollback",
        from_statuses=("completed",), from_plans=WELL_PLAN_STATUSES,
        to_status="final_review", to_plan="completed",
    ),
)
TRANSITIONS_BY_ACTION: dict[str, Transition] = {item.action: item for item in TRANSITIONS}
ACTIONS: tuple[str, ...] = tuple(TRANSITIONS_BY_ACTION)


def _scope_name(scope: str) -> str:
    return "Completion" if scope == "completion" else "Drilling"


def _spud_at(well: Well, scope: str) -> Any:
    # The milestone columns are named per scope (``drilling_spud_at`` /
    # ``completion_spud_at``), unlike the status columns ``scope_value`` reads.
    return getattr(well, f"{scope}_spud_at", None)


def consistent_plan(status: str, plan: str) -> str:
    """The plan status a scope must carry at ``status``.

    Used wherever a row is written without walking the ladder (imports, repairs
    and the migration), so the coupling rule holds for every row in the table.
    """
    if status in WELL_CLOSED_STATUSES:
        return "completed"
    return "configured" if plan == "completed" else plan


def _state_reason(transition: Transition, well: Well, scope: str) -> str:
    """Why this move is not possible from the scope's current state ('' when it is)."""
    name = _scope_name(scope).lower()
    status = well.scope_value(scope, "status")
    plan = well.scope_value(scope, "config_status")
    if status not in transition.from_statuses:
        expected = " or ".join(status_label(item) for item in transition.from_statuses)
        return (
            f"The {name} scope of {well.well_code} is {status_label(status)}; "
            f"this move is only possible while it is {expected}."
        )
    # The saved plan is the more basic requirement, so it is named first: a scope
    # with nothing saved is told to save a plan, not to sign off an empty one.
    if transition.needs_sections and not well.sections_for_scope(scope):
        return f"Save the {name} section and phase plan of {well.well_code} first."
    if plan not in transition.from_plans:
        if transition.ladder == "plan":
            return (
                f"The {name} plan of {well.well_code} is already {plan_label(plan)}."
                if plan == transition.to_plan
                else f"The {name} plan of {well.well_code} is {plan_label(plan)}; "
                     f"this move needs a {' or '.join(plan_label(item) for item in transition.from_plans)} plan."
            )
        return f"Mark the {name} plan of {well.well_code} as Configured first."
    return ""


def _live_sheets(db: Session, well: Well, scope: str, *, status: str | None = None) -> int:
    """Daily cost sheets of this scope that are not in Deleted Entries."""
    statement = (
        select(func.count(DailyCostEntry.id))
        .join(Afe, DailyCostEntry.afe_id == Afe.id)
        .where(
            DailyCostEntry.organization_id == well.organization_id,
            DailyCostEntry.well_id == well.id,
            DailyCostEntry.is_deleted.is_(False),
            Afe.organization_id == well.organization_id,
            Afe.configuration_scope == scope,
        )
    )
    if status:
        statement = statement.where(DailyCostEntry.status == status)
    return int(db.scalar(statement) or 0)


def _defer_blockers(db: Session, well: Well, scope: str) -> list[str]:
    """Evidence that the scope really ran, which makes 'never started' untrue.

    An AFE is not such evidence: a configured upcoming scope is budgeted before
    it starts, so its AFEs simply stay with it.
    """
    blockers: list[str] = []
    sheets = _live_sheets(db, well, scope)
    if sheets:
        blockers.append(f"{sheets} daily cost sheet{'s' if sheets != 1 else ''}")
    if _spud_at(well, scope) is not None:
        blockers.append("a recorded spud date & time")
    return blockers


def available_transitions(
    well: Well, scope: str, can: Callable[[str], bool] | None = None
) -> list[dict[str, Any]]:
    """Every move that starts at the scope's current status, with why it may be disabled.

    Only state is read here (no queries), so a register of many wells stays one
    query. A move that also has a data precondition (``defer``) is offered and
    then explained by ``apply_transition`` if the data refuses it.
    """
    if well.scope_is_deleted(scope):
        return []
    status = well.scope_value(scope, "status")
    plan = well.scope_value(scope, "config_status")
    name = _scope_name(scope)
    offered: list[dict[str, Any]] = []
    for transition in TRANSITIONS:
        if status not in transition.from_statuses:
            continue
        # A plan move is offered only from the plan status it leaves; a well move
        # is offered whenever the well status matches, with the reason attached.
        if transition.ladder == "plan" and plan not in transition.from_plans:
            continue
        reason = _state_reason(transition, well, scope)
        permitted = True if can is None else bool(can(transition.permission))
        if not reason and not permitted:
            reason = f"This move needs the {transition.permission} permission."
        offered.append({
            "action": transition.action,
            "label": transition.label.format(scope=name),
            "description": transition.description,
            "ladder": transition.ladder,
            "direction": transition.direction,
            "to_status": transition.to_status or status,
            "to_plan": transition.to_plan or plan,
            "permission": transition.permission,
            "permitted": permitted,
            "allowed": not reason and permitted,
            "reason": reason,
        })
    return offered


@dataclass(frozen=True)
class AppliedTransition:
    transition: Transition
    status_before: str
    status_after: str
    plan_before: str
    plan_after: str

    def summary(self, well: Well, scope: str, remarks: str) -> str:
        """The audit sentence: what moved, from where to where, and why."""
        name = _scope_name(scope)
        verb = "Rolled back" if self.transition.direction == "rollback" else "Moved"
        parts: list[str] = []
        if self.status_before != self.status_after:
            parts.append(
                f"well status {status_label(self.status_before)} → {status_label(self.status_after)}"
            )
        if self.plan_before != self.plan_after:
            parts.append(f"plan status {plan_label(self.plan_before)} → {plan_label(self.plan_after)}")
        change = "; ".join(parts) or "no status change"
        reason = f" Reason: {remarks.strip()}" if remarks.strip() else ""
        return f"{verb} well {well.well_code} {name} scope: {change}.{reason}"


def apply_transition(
    db: Session,
    well: Well,
    scope: str,
    action: str,
    can: Callable[[str], bool],
) -> AppliedTransition:
    """Validate and perform one move. The caller audits and commits."""
    transition = TRANSITIONS_BY_ACTION.get(action)
    if transition is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown status move '{action}'. Use one of: {', '.join(ACTIONS)}.",
        )
    if not can(transition.permission):
        # Naming the capability turns a dead end into a request the user can make
        # of their administrator, exactly like ``require`` does for a whole route.
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied. This action needs {transition.permission}.",
        )
    name = _scope_name(scope).lower()
    if well.scope_is_deleted(scope):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Restore or add the {_scope_name(scope)} scope on well {well.well_code} "
                "before changing its status"
            ),
        )
    reason = _state_reason(transition, well, scope)
    if reason:
        raise HTTPException(status_code=409, detail=reason)
    if transition.action == "defer":
        blockers = _defer_blockers(db, well, scope)
        if blockers:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"The {name} scope of {well.well_code} cannot return to Upcoming while it has "
                    + " and ".join(blockers)
                    + ". Move those records to Deleted Entries (or clear the spud date) first."
                ),
            )
    if transition.action == "complete":
        # Completed means the cost is final. A sheet still in Draft has not been
        # submitted, so signing the scope off would freeze an unfinished record.
        drafts = _live_sheets(db, well, scope, status="draft")
        if drafts:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"The {name} scope of {well.well_code} still has {drafts} daily cost "
                    f"sheet{'s' if drafts != 1 else ''} in Draft. Submit or delete "
                    f"{'them' if drafts != 1 else 'it'} before marking the scope Completed."
                ),
            )
    status_before = well.scope_value(scope, "status")
    plan_before = well.scope_value(scope, "config_status")
    status_after = transition.to_status or status_before
    plan_after = consistent_plan(status_after, transition.to_plan or plan_before)
    well.set_scope_value(scope, "status", status_after)
    well.set_scope_value(scope, "config_status", plan_after)
    return AppliedTransition(transition, status_before, status_after, plan_before, plan_after)


def auto_start(well: Well, scope: str) -> bool:
    """Promote an upcoming scope to active because operations demonstrably began.

    The first daily cost sheet and a recorded spud both prove the scope is
    running, so the register follows without the operator pressing Start. A scope
    that is already active — or already closed — is left exactly as it is.
    """
    if well.scope_value(scope, "status") != "upcoming":
        return False
    well.set_scope_value(scope, "status", "active")
    return True


def reset_scope(well: Well, scope: str) -> None:
    """Return a purged or re-added scope to the first rung of both ladders."""
    well.set_scope_value(scope, "status", WELL_TRACKING_STATUSES[0])
    well.set_scope_value(scope, "config_status", WELL_PLAN_STATUSES[0])


def accepts_planning(well: Well, scope: str) -> bool:
    """True while the scope still takes AFEs, SOW adjustments and daily costs."""
    return (
        not well.scope_is_deleted(scope)
        and well.scope_value(scope, "status") in WELL_OPEN_STATUSES
        and well.scope_value(scope, "config_status") == "configured"
        and bool(well.sections_for_scope(scope))
    )


def planning_blocker(well: Well, scope: str, purpose: str) -> str:
    """Why the scope cannot take new planning or costing work ('' when it can).

    ``purpose`` finishes the sentence, e.g. ``"creating an AFE"``. One wording is
    shared by AFEs, SOW adjustments and daily costs so the same state reads the
    same in every module.
    """
    name = _scope_name(scope).lower()
    status = well.scope_value(scope, "status")
    plan = well.scope_value(scope, "config_status")
    if well.scope_is_deleted(scope):
        return (
            f"The {name} scope on well {well.well_code} is deleted. "
            f"Restore or add it in Rig & Well Management before {purpose}."
        )
    if status in WELL_CLOSED_STATUSES:
        step = (
            "Return it to Active in Rig & Well Management"
            if status == "final_review"
            else "Return it to Final review and then to Active in Rig & Well Management"
        )
        return (
            f"The {name} scope of {well.well_code} is in {status_label(status)} and its plan is closed. "
            f"{step} before {purpose}."
        )
    if not well.sections_for_scope(scope):
        return (
            f"Configure the {name} sections and phases of {well.well_code} in "
            f"Rig & Well Management before {purpose}."
        )
    if plan != "configured":
        return (
            f"The {name} plan of {well.well_code} is {plan_label(plan)}. "
            f"Mark it as Configured in Rig & Well Management before {purpose}."
        )
    return ""
