"""Correlate the printed default codes with this workspace's own code library.

The Code Library holds the codes the organisation actually uses. The built-in
default codes are a printed dictionary. A correlation says "printed token X is
our workspace code Y", and extraction then pre-selects Y on a suggested block.

Design rules:

* A correlation is a suggestion source, never an approval. Extraction still
  writes ``review_state='suggested'`` and the engineer still accepts the block.
* One token maps once per family. Ambiguity is refused, not guessed: a second
  correlation for the same printed token is a 409 until the first is removed.
* The target must live in the workspace, be active and not deleted, and be in
  the same family as the correlation. A template can never point across fields.
* Deleting a correlation leaves saved reports untouched; only future drafts
  change.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.operations.default_codes import catalogue_rows
from app.domain.operations.taxonomy import code_key
from app.models import User
from app.models.operations import (
    OpsActivityCode,
    OpsAgency,
    OpsCause,
    OpsCodeCorrelation,
    OpsNptCode,
    OpsOperationCode,
    OpsPhaseCode,
)
from app.services.audit import record as audit_record

# kind -> (workspace model, target column, printed families that belong to it)
KINDS: dict[str, tuple[type, str, tuple[str, ...]]] = {
    "operation": (OpsOperationCode, "target_operation_code_id", ("Operation", "OpenWells operation code")),
    "activity": (OpsActivityCode, "target_activity_code_id", ("Activity", "OpenWells code token")),
    "npt": (OpsNptCode, "target_npt_code_id", ("Trouble / NPT",)),
    "cause": (OpsCause, "target_cause_id", ("Cause", "Trouble / NPT")),
    "phase": (OpsPhaseCode, "target_phase_code_id", ("OpenWells phase", "Programme phase")),
    "agency": (OpsAgency, "target_agency_id", ()),
}
TARGET_COLUMNS = tuple(column for _, column, _ in KINDS.values())


def _actor(user: User) -> str:
    return user.email or user.full_name or str(user.id)


def _target_label(model, row) -> str:
    for code_field, name_field in (
        ("operation_code", "operation_name"),
        ("activity_code", "activity_name"),
        ("npt_code", "npt_name"),
        ("cause_code", "cause_name"),
        ("phase_code", "phase_name"),
        ("agency_code", "agency_name"),
    ):
        if hasattr(row, code_field):
            return f"{getattr(row, code_field)} — {getattr(row, name_field)}"
    return str(getattr(row, "id", ""))


def _clear_targets(row: OpsCodeCorrelation) -> None:
    for column in TARGET_COLUMNS:
        setattr(row, column, None)


def _resolve_target(db: Session, organization_id: str, kind: str, target_id: str):
    model, column, _families = KINDS[kind]
    row = db.scalar(
        select(model).where(
            model.id == target_id,
            model.organization_id == organization_id,
            model.is_deleted.is_(False),
        )
    )
    if not row:
        raise HTTPException(422, "Choose an active code from this workspace's library.")
    return row


def _check_source(kind: str, source_family: str, source_code: str) -> None:
    """The printed token must exist in the reference dictionary it claims."""
    if not source_code.strip():
        raise HTTPException(422, "A printed code is required.")
    rows = [
        entry
        for entry in catalogue_rows()
        if code_key(entry["code"]) == code_key(source_code)
        and (not source_family or entry["family"] == source_family)
    ]
    if not rows:
        raise HTTPException(
            422,
            "That code is not in the printed reference dictionary. Pick the printed code from the "
            "default list so the correlation keeps its meaning.",
        )
    allowed = KINDS[kind][2]
    if allowed and rows[0]["family"] not in allowed:
        raise HTTPException(
            422,
            f"A {rows[0]['family'].lower()} code cannot be correlated with a {kind} code. "
            f"Choose one of: {', '.join(allowed)}.",
        )


def list_correlations(db: Session, organization_id: str, *, kind: str = "", include_deleted: bool = False):
    q = select(OpsCodeCorrelation).where(OpsCodeCorrelation.organization_id == organization_id)
    if kind:
        if kind not in KINDS:
            raise HTTPException(404, f"Unknown correlation kind '{kind}'")
        q = q.where(OpsCodeCorrelation.kind == kind)
    if not include_deleted:
        q = q.where(OpsCodeCorrelation.is_deleted.is_(False))
    return db.scalars(q.order_by(OpsCodeCorrelation.kind, OpsCodeCorrelation.source_code)).all()


def correlation_map(db: Session, organization_id: str) -> dict[tuple[str, str], OpsCodeCorrelation]:
    """Active correlations keyed by (kind, normalised printed code)."""
    rows = db.scalars(
        select(OpsCodeCorrelation).where(
            OpsCodeCorrelation.organization_id == organization_id,
            OpsCodeCorrelation.is_deleted.is_(False),
            OpsCodeCorrelation.is_active.is_(True),
        )
    ).all()
    return {(row.kind, code_key(row.source_code)): row for row in rows}


def create_correlation(db: Session, organization_id: str, data, user: User, request=None):
    kind = data.kind
    if kind not in KINDS:
        raise HTTPException(404, f"Unknown correlation kind '{kind}'")
    source_code = data.source_code.strip()
    _check_source(kind, data.source_family, source_code)
    target = _resolve_target(db, organization_id, kind, data.target_id)
    existing = db.scalar(
        select(OpsCodeCorrelation).where(
            OpsCodeCorrelation.organization_id == organization_id,
            OpsCodeCorrelation.kind == kind,
            OpsCodeCorrelation.source_code == source_code,
        )
    )
    if existing:
        if existing.is_deleted:
            raise HTTPException(409, "This printed code was correlated before. Restore that correlation instead.")
        raise HTTPException(
            409, f"{source_code} is already correlated. Remove that correlation before adding another."
        )
    row = OpsCodeCorrelation(
        organization_id=organization_id,
        kind=kind,
        source_family=data.source_family or "",
        source_code=source_code,
        source_label=data.source_label or "",
        target_label=_target_label(KINDS[kind][0], target),
        note=data.note or "",
        is_active=True,
        created_by=_actor(user),
        updated_by=_actor(user),
        **{KINDS[kind][1]: target.id},
    )
    db.add(row)
    db.flush()
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="create",
        entity_type="ops_correlation",
        entity_id=row.id,
        entity_label=f"{source_code} → {row.target_label}",
        summary=f"Correlated printed {kind} code {source_code} with {row.target_label}",
        request=request,
    )
    db.commit()
    db.refresh(row)
    return row


def update_correlation(db: Session, organization_id: str, correlation_id: str, data, user: User, request=None):
    row = db.scalar(
        select(OpsCodeCorrelation).where(
            OpsCodeCorrelation.id == correlation_id,
            OpsCodeCorrelation.organization_id == organization_id,
            OpsCodeCorrelation.is_deleted.is_(False),
        )
    )
    if not row:
        raise HTTPException(404, "Correlation not found")
    target = _resolve_target(db, organization_id, row.kind, data.target_id)
    _clear_targets(row)
    setattr(row, KINDS[row.kind][1], target.id)
    row.target_label = _target_label(KINDS[row.kind][0], target)
    row.note = data.note or ""
    row.is_active = data.is_active
    row.updated_by = _actor(user)
    row.updated_at = datetime.now(UTC)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="update",
        entity_type="ops_correlation",
        entity_id=row.id,
        entity_label=f"{row.source_code} → {row.target_label}",
        summary="Updated a printed-code correlation",
        request=request,
    )
    db.commit()
    db.refresh(row)
    return row


def delete_correlations(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(
        select(OpsCodeCorrelation).where(
            OpsCodeCorrelation.organization_id == organization_id, OpsCodeCorrelation.id.in_(ids)
        )
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more correlations not found")
    now = datetime.now(UTC)
    affected = 0
    for row in rows:
        if not row.is_deleted:
            row.is_deleted = True
            row.deleted_at = now
            row.updated_by = _actor(user)
            affected += 1
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="delete",
        entity_type="ops_correlation",
        entity_id=None,
        entity_label=f"{affected} correlation(s)",
        summary=f"Moved {affected} correlation(s) to Deleted entries; saved reports are unchanged",
        request=request,
    )
    db.commit()
    return {"affected_count": affected}


def restore_correlations(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(
        select(OpsCodeCorrelation).where(
            OpsCodeCorrelation.organization_id == organization_id, OpsCodeCorrelation.id.in_(ids)
        )
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more correlations not found")
    affected = 0
    for row in rows:
        if row.is_deleted:
            clash = db.scalar(
                select(OpsCodeCorrelation.id).where(
                    OpsCodeCorrelation.organization_id == organization_id,
                    OpsCodeCorrelation.kind == row.kind,
                    OpsCodeCorrelation.source_code == row.source_code,
                    OpsCodeCorrelation.is_deleted.is_(False),
                )
            )
            if clash:
                raise HTTPException(
                    409, f"{row.source_code} is already correlated by an active row. Remove it first."
                )
            row.is_deleted = False
            row.deleted_at = None
            row.updated_by = _actor(user)
            affected += 1
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="restore",
        entity_type="ops_correlation",
        entity_id=None,
        entity_label=f"{affected} correlation(s)",
        summary=f"Restored {affected} correlation(s)",
        request=request,
    )
    db.commit()
    return {"affected_count": affected}


def apply_to_block(
    block,
    correlations: dict[tuple[str, str], OpsCodeCorrelation],
    *,
    activity_tokens=(),
    operation_tokens=(),
    cause_tokens=(),
    phase_tokens=(),
    npt_tokens=(),
    agency_tokens=(),
) -> list[str]:
    """Pre-select correlated workspace codes on an extracted (suggested) block.

    Each candidate token is tried in the order supplied; the first token with a
    correlation wins. Returns the evidence lines to append, so the engineer can
    see that a pre-selection came from a correlation rather than from the source
    printed code itself.
    """
    evidence: list[str] = []

    def pick(kind: str, tokens):
        for token in tokens:
            if not token:
                continue
            row = correlations.get((kind, code_key(token)))
            if row:
                return row
        return None

    if not block.operation_code_id and (row := pick("operation", operation_tokens)):
        block.operation_code_id = getattr(row, "target_operation_code_id", None)
        evidence.append(f"Operation correlation: {row.source_code} → {row.target_label}")
    if not block.activity_code_id and (row := pick("activity", activity_tokens)):
        block.activity_code_id = getattr(row, "target_activity_code_id", None)
        evidence.append(f"Activity correlation: {row.source_code} → {row.target_label}")
    if not block.phase_id and (row := pick("phase", phase_tokens)):
        block.phase_id = getattr(row, "target_phase_code_id", None)
        evidence.append(f"Phase correlation: {row.source_code} → {row.target_label}")
    if not block.npt_code_id and (row := pick("npt", npt_tokens)):
        block.npt_code_id = getattr(row, "target_npt_code_id", None)
        evidence.append(f"NPT correlation: {row.source_code} → {row.target_label}")
    if not block.cause_code and (row := pick("cause", cause_tokens)):
        cause_row = row
        block.cause_code = _cause_code(db_row=cause_row)
        evidence.append(f"Cause correlation: {row.source_code} → {row.target_label}")
    if not block.vendor_id and not block.responsible_party and (row := pick("agency", agency_tokens)):
        # Agencies are library records, not Master Data vendors: the block keeps the
        # agency name and leaves vendor_id for the engineer to link a real vendor.
        block.responsible_party = str(getattr(row, "target_label", "") or "").split(" — ", 1)[-1][:200]
        evidence.append(f"Agency correlation: {row.source_code} → {row.target_label}")
    return evidence


def _cause_code(*, db_row: OpsCodeCorrelation) -> str:
    """The stored cause column is the printed code, so keep its leading token."""
    label = (db_row.target_label or "").split(" — ", 1)[0].strip()
    return label[:50]
