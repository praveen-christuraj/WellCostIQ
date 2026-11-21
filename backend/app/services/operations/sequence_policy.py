"""Sequence-code policy: how this workspace reads the awkward cases.

The arithmetic lives in ``app.domain.operations.sequence``; this is the one place
that reads the workspace's choice of policy out of ``ops_settings`` and hands it to
that module. Every figure the ledger prints carries the policy it was produced
under, so a reader can tell that a number is small because nothing has finished
rather than because a setting was switched.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.operations.sequence import Policy
from app.models.operations import OpsSettings


def policy_for(db: Session, organization_id: str) -> Policy:
    """The stored policy, or the documented defaults when no row exists yet."""
    row = db.scalar(select(OpsSettings).where(OpsSettings.organization_id == organization_id))
    if row is None:
        return Policy()
    return Policy(
        uncoded=getattr(row, "sequence_uncoded_policy", "lag") or "lag",
        npt=getattr(row, "sequence_npt_policy", "include") or "include",
        skipped_credit=getattr(row, "sequence_skipped_credit", "separate") or "separate",
        auto_close_tolerance_pct=Decimal(str(getattr(row, "sequence_auto_close_tolerance_pct", 0) or 0)),
        auto_close=bool(getattr(row, "sequence_auto_close", False)),
    ).normalised()


def require_code_on_submit(db: Session, organization_id: str) -> bool:
    row = db.scalar(
        select(OpsSettings.sequence_require_code_on_submit).where(
            OpsSettings.organization_id == organization_id
        )
    )
    return bool(row)


def current_run_only(db: Session, organization_id: str) -> bool:
    """Whether only current report revisions vote on the confirmed figure."""
    row = db.scalar(
        select(OpsSettings.sequence_current_run_only).where(
            OpsSettings.organization_id == organization_id
        )
    )
    # Absent settings row: default true, matching the model's server default.
    return True if row is None else bool(row)
