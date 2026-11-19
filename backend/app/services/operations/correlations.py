"""Operations code correlations and multi-criteria workspace code links.

Two complementary, auditable rule sets live in ``Well Operations -> Code library``:

1. **Printed-to-workspace correlations (``OpsCodeCorrelation``)** map an exact printed
   token from the reference dictionary (or a printed source agency token) to a primary
   workspace code — plus any optional companion criteria (phase, operation, activity,
   NPT, cause, agency, source mark, scope, classification, allocation).
2. **Multi-criteria workspace code links (``OpsCodeLink``)** connect two or more
   workspace codes across Phase, Operation, Activity, NPT, Cause, Agency, Source Mark,
   Scope, Classification, and Allocation in typed relational columns (no JSON).

Extraction applies exact printed correlations first, then fills any remaining empty
fields only when active workspace code links agree on one unambiguous value. Every
mapped block keeps ``review_state = "suggested"`` until an engineer confirms it.
Correlated or linked codes cannot be deleted until their correlation rules are removed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.operations.default_codes import catalogue_rows
from app.models.master_data import Phase
from app.models.operations import (
    OpsActivityBlock,
    OpsActivityCode,
    OpsAgency,
    OpsCause,
    OpsCodeCorrelation,
    OpsCodeLink,
    OpsMarkRule,
    OpsNptCode,
    OpsOperationCode,
    OpsPhaseCode,
)
from app.models import User
from app.schemas.operations import (
    OpsCodeLinkBatchIn,
    OpsCodeLinkIn,
    OpsCorrelationBatchIn,
    OpsCorrelationIn,
    OpsCorrelationUpdate,
)
from app.services.audit import record as audit_record

# kind -> (model, code column, name column, correlation target column, allowed printed families)
KINDS: dict[str, tuple[type, str, str, str, tuple[str, ...]]] = {
    "operation": (
        OpsOperationCode,
        "operation_code",
        "operation_name",
        "target_operation_code_id",
        ("Operation", "OpenWells operation code"),
    ),
    "activity": (
        OpsActivityCode,
        "activity_code",
        "activity_name",
        "target_activity_code_id",
        ("Activity", "OpenWells code token"),
    ),
    "npt": (
        OpsNptCode,
        "npt_code",
        "npt_name",
        "target_npt_code_id",
        ("Trouble / NPT",),
    ),
    "cause": (
        OpsCause,
        "cause_code",
        "cause_name",
        "target_cause_id",
        ("Cause", "Trouble / NPT"),
    ),
    "phase": (
        OpsPhaseCode,
        "phase_code",
        "phase_name",
        "target_phase_code_id",
        ("OpenWells phase", "Programme phase"),
    ),
    "agency": (
        OpsAgency,
        "agency_code",
        "agency_name",
        "target_agency_id",
        (),
    ),
}

# All 7 workspace code criteria supported in multi-criteria links & companion fields.
# criterion_key -> (master_kind, model, code_col, name_col, corr_col, link_col, short_label, sig_prefix)
CRITERIA_SPECS: dict[str, tuple[str, type, str, str, str, str, str, str]] = {
    "phase": (
        "phase-codes",
        OpsPhaseCode,
        "phase_code",
        "phase_name",
        "target_phase_code_id",
        "phase_code_id",
        "Phase",
        "ph",
    ),
    "operation": (
        "operation-codes",
        OpsOperationCode,
        "operation_code",
        "operation_name",
        "target_operation_code_id",
        "operation_code_id",
        "Operation",
        "op",
    ),
    "activity": (
        "activity-codes",
        OpsActivityCode,
        "activity_code",
        "activity_name",
        "target_activity_code_id",
        "activity_code_id",
        "Activity",
        "ac",
    ),
    "npt": (
        "npt-codes",
        OpsNptCode,
        "npt_code",
        "npt_name",
        "target_npt_code_id",
        "npt_code_id",
        "NPT",
        "np",
    ),
    "cause": (
        "causes",
        OpsCause,
        "cause_code",
        "cause_name",
        "target_cause_id",
        "cause_id",
        "Cause",
        "ca",
    ),
    "agency": (
        "agencies",
        OpsAgency,
        "agency_code",
        "agency_name",
        "target_agency_id",
        "agency_id",
        "Agency",
        "ag",
    ),
    "mark": (
        "source-marks",
        OpsMarkRule,
        "mark_code",
        "mark_name",
        "target_mark_rule_id",
        "mark_rule_id",
        "Mark",
        "mk",
    ),
}

MASTER_TO_CRITERION = {spec[0]: key for key, spec in CRITERIA_SPECS.items()}


def code_key(code: str) -> str:
    return (code or "").strip().lower()


def _format_code_label(row, code_col: str, name_col: str) -> str:
    code = (getattr(row, code_col, "") or "").strip()
    name = (getattr(row, name_col, "") or "").strip()
    if name and name != code:
        return f"{code} — {name}"
    return code


def _printed_index() -> dict[tuple[str, str], dict]:
    return {(row["family"], code_key(row["code"])): row for row in catalogue_rows()}


def _resolve_target(
    db: Session,
    organization_id: str,
    criterion: str,
    target_id: str,
    *,
    require_active: bool = False,
) -> tuple[object, str]:
    spec = CRITERIA_SPECS.get(criterion)
    if not spec:
        raise HTTPException(422, f"Unsupported code criterion '{criterion}'.")
    _master_kind, model, code_col, name_col, _corr_col, _link_col, short_label, _sig = spec
    row = db.scalar(
        select(model).where(
            model.organization_id == organization_id,
            model.id == target_id,
            model.is_deleted.is_(False),
        )
    )
    if row is None:
        raise HTTPException(404, f"{short_label} code not found in this workspace.")
    if require_active and hasattr(row, "is_active") and not row.is_active:
        raise HTTPException(
            422, f"{short_label} code '{getattr(row, code_col)}' is inactive; activate it before linking."
        )
    return row, _format_code_label(row, code_col, name_col)


def _check_classification_matrix(
    classification: str,
    allocation: str,
    npt_code_id: str | None,
    *,
    prefix: str = "",
) -> None:
    if classification in ("Planned", "UPA") and npt_code_id:
        raise HTTPException(422, f"{prefix}NPT code applies only when classification is NPT (or unset).")
    if allocation == "NPT" and classification in ("Planned", "UPA"):
        raise HTTPException(422, f"{prefix}NPT allocation requires NPT classification.")
    if classification == "NPT" and allocation == "PT":
        raise HTTPException(422, f"{prefix}NPT classification cannot be paired with PT allocation.")


def _validate_printed(kind: str, source_code: str, source_family: str, *, prefix: str = "") -> tuple[str, str, str]:
    """Verify the printed code belongs to the built-in catalogue for ``kind``.

    Agency rules are the explicit exception: ``default_codes.py`` intentionally holds
    no operator or contractor names, so ``agency`` accepts any non-empty printed source
    agency token found on a daily report.
    """
    spec = KINDS.get(kind)
    if not spec:
        raise HTTPException(422, f"{prefix}Unsupported correlation kind '{kind}'.")
    _model, _c, _n, _col, families = spec
    raw_code = (source_code or "").strip()
    if not raw_code:
        raise HTTPException(422, f"{prefix}Printed source code cannot be empty.")
    if kind == "agency":
        fam = (source_family or "").strip() or "Source agency"
        return raw_code.upper(), fam, raw_code

    key = code_key(raw_code)
    index = _printed_index()
    if source_family:
        entry = index.get((source_family, key))
        if entry and source_family in families:
            return entry["code"], entry["family"], entry["name"]
    for family in families:
        entry = index.get((family, key))
        if entry:
            return entry["code"], entry["family"], entry["name"]
    raise HTTPException(
        422,
        f"{prefix}'{source_code}' is not in the printed reference catalogue for {kind} codes.",
    )


def _build_companion_targets(
    db: Session,
    organization_id: str,
    primary_kind: str,
    primary_id: str,
    data: OpsCorrelationIn | OpsCorrelationUpdate,
    *,
    prefix: str = "",
) -> tuple[dict[str, str | None], str, str]:
    """Resolve primary target plus any companion multi-criteria target columns."""
    values: dict[str, str | None] = {}
    extra_parts: list[str] = []

    if data.scope:
        extra_parts.append(f"Scope: {data.scope.title()}")
    if data.target_classification:
        extra_parts.append(f"Class: {data.target_classification}")
    if data.target_allocation:
        extra_parts.append(f"Alloc: {data.target_allocation}")

    _primary_row, primary_label = _resolve_target(db, organization_id, primary_kind, primary_id)
    primary_corr_col = CRITERIA_SPECS[primary_kind][4]

    for criterion, spec in CRITERIA_SPECS.items():
        corr_col = spec[4]
        short_label = spec[6]
        if corr_col == primary_corr_col:
            values[corr_col] = primary_id
            continue
        raw_id = (getattr(data, corr_col, None) or "").strip() or None
        if raw_id:
            row, _label = _resolve_target(db, organization_id, criterion, raw_id)
            code_val = getattr(row, spec[2])
            values[corr_col] = raw_id
            extra_parts.append(f"{short_label}: {code_val}")
        else:
            values[corr_col] = None

    _check_classification_matrix(
        data.target_classification,
        data.target_allocation,
        values.get("target_npt_code_id"),
        prefix=prefix,
    )
    summary = " · ".join(extra_parts)[:300]
    return values, primary_label, summary


def list_correlations(
    db: Session,
    organization_id: str,
    *,
    kind: str = "",
    include_deleted: bool = False,
) -> list[OpsCodeCorrelation]:
    q = select(OpsCodeCorrelation).where(
        OpsCodeCorrelation.organization_id == organization_id,
        OpsCodeCorrelation.is_deleted.is_(include_deleted),
    )
    if kind:
        q = q.where(OpsCodeCorrelation.kind == kind)
    return list(db.scalars(q.order_by(OpsCodeCorrelation.kind, OpsCodeCorrelation.source_code)))


def _prepare_correlation_row(
    db: Session,
    organization_id: str,
    data: OpsCorrelationIn,
    actor: User,
    *,
    prefix: str = "",
) -> OpsCodeCorrelation:
    canonical_code, family, catalogue_name = _validate_printed(
        data.kind, data.source_code, data.source_family, prefix=prefix
    )
    existing = db.scalar(
        select(OpsCodeCorrelation).where(
            OpsCodeCorrelation.organization_id == organization_id,
            OpsCodeCorrelation.kind == data.kind,
            OpsCodeCorrelation.source_code == canonical_code,
        )
    )
    if existing is not None:
        if existing.is_deleted:
            raise HTTPException(
                409,
                f"{prefix}Correlation for '{canonical_code}' is in Deleted entries; "
                "restore or permanently delete it before creating a new rule.",
            )
        raise HTTPException(
            409,
            f"{prefix}Correlation already exists for printed code '{canonical_code}'. "
            "Edit or delete the existing rule instead.",
        )

    target_cols, label, extra_summary = _build_companion_targets(
        db, organization_id, data.kind, data.target_id, data, prefix=prefix
    )
    source_label = (data.source_label or "").strip() or catalogue_name
    return OpsCodeCorrelation(
        organization_id=organization_id,
        kind=data.kind,
        source_family=family,
        source_code=canonical_code,
        source_label=source_label[:200],
        target_label=label[:200],
        scope=data.scope,
        target_classification=data.target_classification,
        target_allocation=data.target_allocation,
        extra_criteria_summary=extra_summary,
        note=(data.note or "").strip(),
        created_by=actor.email,
        updated_by=actor.email,
        **target_cols,
    )


def create_correlation(
    db: Session,
    organization_id: str,
    data: OpsCorrelationIn,
    actor: User,
    request: Request | None = None,
) -> OpsCodeCorrelation:
    row = _prepare_correlation_row(db, organization_id, data, actor)
    db.add(row)
    db.flush()
    summary = f"Correlated printed {row.source_code} ({row.source_family}) -> {row.target_label}"
    if row.extra_criteria_summary:
        summary += f" [{row.extra_criteria_summary}]"
    audit_record(
        db,
        organization_id=organization_id,
        actor=actor,
        action="create",
        entity_type="ops_code_correlation",
        entity_id=row.id,
        entity_label=f"{row.kind}:{row.source_code}",
        summary=summary[:500],
        request=request,
    )
    db.commit()
    db.refresh(row)
    return row


def create_correlations_batch(
    db: Session,
    organization_id: str,
    data: OpsCorrelationBatchIn,
    actor: User,
    request: Request | None = None,
) -> dict:
    """Validate and save multiple printed-to-workspace correlations atomically."""
    seen: set[tuple[str, str]] = set()
    created: list[OpsCodeCorrelation] = []
    for idx, item in enumerate(data.items, start=1):
        prefix = f"Row {idx} ({item.source_code.strip() or item.kind}): "
        dup_key = (item.kind, code_key(item.source_code))
        if dup_key in seen:
            db.rollback()
            raise HTTPException(
                409, f"{prefix}Printed code '{item.source_code.strip()}' appears more than once in this batch."
            )
        seen.add(dup_key)
        try:
            row = _prepare_correlation_row(db, organization_id, item, actor, prefix=prefix)
        except HTTPException:
            db.rollback()
            raise
        db.add(row)
        created.append(row)

    db.flush()
    audit_record(
        db,
        organization_id=organization_id,
        actor=actor,
        action="create",
        entity_type="ops_code_correlation",
        entity_id=created[0].id if len(created) == 1 else None,
        entity_label=f"Batch ({len(created)} correlations)",
        summary=f"Created {len(created)} code correlation(s) in batch",
        request=request,
    )
    db.commit()
    for row in created:
        db.refresh(row)
    return {"created_count": len(created), "items": created}


def update_correlation(
    db: Session,
    organization_id: str,
    correlation_id: str,
    data: OpsCorrelationUpdate,
    actor: User,
    request: Request | None = None,
) -> OpsCodeCorrelation:
    row = db.scalar(
        select(OpsCodeCorrelation).where(
            OpsCodeCorrelation.organization_id == organization_id,
            OpsCodeCorrelation.id == correlation_id,
            OpsCodeCorrelation.is_deleted.is_(False),
        )
    )
    if row is None:
        raise HTTPException(404, "Correlation not found.")
    target_cols, label, extra_summary = _build_companion_targets(db, organization_id, row.kind, data.target_id, data)
    for col, val in target_cols.items():
        setattr(row, col, val)
    row.target_label = label[:200]
    row.scope = data.scope
    row.target_classification = data.target_classification
    row.target_allocation = data.target_allocation
    row.extra_criteria_summary = extra_summary
    row.is_active = data.is_active
    row.note = (data.note or "").strip()
    row.updated_by = actor.email
    summary = f"Updated correlation {row.source_code} -> {label} (active={row.is_active})"
    if extra_summary:
        summary += f" [{extra_summary}]"
    audit_record(
        db,
        organization_id=organization_id,
        actor=actor,
        action="update",
        entity_type="ops_code_correlation",
        entity_id=row.id,
        entity_label=f"{row.kind}:{row.source_code}",
        summary=summary[:500],
        request=request,
    )
    db.commit()
    db.refresh(row)
    return row


def _ensure_correlation_targets_live(db: Session, organization_id: str, row: OpsCodeCorrelation) -> None:
    for _criterion, spec in CRITERIA_SPECS.items():
        _master_kind, model, code_col, _name_col, corr_col, _link_col, short_label, _sig = spec
        target_id = getattr(row, corr_col, None)
        if not target_id:
            continue
        target = db.scalar(
            select(model).where(model.organization_id == organization_id, model.id == target_id)
        )
        if target is None or target.is_deleted:
            code_txt = getattr(target, code_col, target_id) if target is not None else target_id
            raise HTTPException(
                409,
                f"Cannot restore correlation '{row.source_code}': workspace {short_label.lower()} code "
                f"'{code_txt}' is in Deleted entries. Restore the code first.",
            )


def delete_correlations(
    db: Session, organization_id: str, ids: list[str], actor: User, request: Request | None = None
) -> dict:
    rows = list(
        db.scalars(
            select(OpsCodeCorrelation).where(
                OpsCodeCorrelation.organization_id == organization_id,
                OpsCodeCorrelation.id.in_(ids),
                OpsCodeCorrelation.is_deleted.is_(False),
            )
        )
    )
    stamp = datetime.now(UTC)
    for row in rows:
        row.is_deleted = True
        row.deleted_at = stamp
        row.updated_by = actor.email
        audit_record(
            db,
            organization_id=organization_id,
            actor=actor,
            action="delete",
            entity_type="ops_code_correlation",
            entity_id=row.id,
            entity_label=f"{row.kind}:{row.source_code}",
            summary=f"Deleted correlation {row.source_code} -> {row.target_label}",
            request=request,
        )
    db.commit()
    return {"affected_count": len(rows)}


def restore_correlations(
    db: Session, organization_id: str, ids: list[str], actor: User, request: Request | None = None
) -> dict:
    rows = list(
        db.scalars(
            select(OpsCodeCorrelation).where(
                OpsCodeCorrelation.organization_id == organization_id,
                OpsCodeCorrelation.id.in_(ids),
                OpsCodeCorrelation.is_deleted.is_(True),
            )
        )
    )
    for row in rows:
        _ensure_correlation_targets_live(db, organization_id, row)
    for row in rows:
        row.is_deleted = False
        row.deleted_at = None
        row.updated_by = actor.email
        audit_record(
            db,
            organization_id=organization_id,
            actor=actor,
            action="restore",
            entity_type="ops_code_correlation",
            entity_id=row.id,
            entity_label=f"{row.kind}:{row.source_code}",
            summary=f"Restored correlation {row.source_code} -> {row.target_label}",
            request=request,
        )
    db.commit()
    return {"affected_count": len(rows)}


def purge_correlations(
    db: Session, organization_id: str, ids: list[str], actor: User, request: Request | None = None
) -> dict:
    """Permanently delete correlations that are already in Deleted entries."""
    rows = list(
        db.scalars(
            select(OpsCodeCorrelation).where(
                OpsCodeCorrelation.organization_id == organization_id,
                OpsCodeCorrelation.id.in_(ids),
            )
        )
    )
    if any(not row.is_deleted for row in rows):
        raise HTTPException(409, "Delete a correlation before removing it permanently.")
    for row in rows:
        audit_record(
            db,
            organization_id=organization_id,
            actor=actor,
            action="permanent_delete",
            entity_type="ops_code_correlation",
            entity_id=row.id,
            entity_label=f"{row.kind}:{row.source_code}",
            summary=f"Permanently deleted correlation {row.source_code} -> {row.target_label}",
            request=request,
        )
        db.delete(row)
    db.commit()
    return {"affected_count": len(rows)}


# ---------------------------------------------------------------------------
# Multi-criteria workspace code links (OpsCodeLink)
# ---------------------------------------------------------------------------


def _build_link_payload(
    db: Session,
    organization_id: str,
    data: OpsCodeLinkIn,
    *,
    prefix: str = "",
) -> tuple[dict[str, str | None], str, int, str]:
    """Validate and canonicalize a multi-criteria workspace code link."""
    link_cols: dict[str, str | None] = {}
    sig_parts: list[str] = []
    label_parts: list[str] = []
    code_count = 0

    if data.scope:
        sig_parts.append(f"sc={data.scope}")
        label_parts.append(f"Scope: {data.scope.title()}")
    if data.default_classification:
        sig_parts.append(f"cl={data.default_classification}")
        label_parts.append(f"Class: {data.default_classification}")
    if data.default_allocation:
        sig_parts.append(f"al={data.default_allocation}")
        label_parts.append(f"Alloc: {data.default_allocation}")

    for criterion, spec in CRITERIA_SPECS.items():
        _master_kind, _model, code_col, name_col, _corr_col, link_col, short_label, sig_prefix = spec
        raw_id = (getattr(data, link_col, None) or "").strip() or None
        if raw_id:
            row, _full_label = _resolve_target(db, organization_id, criterion, raw_id, require_active=True)
            link_cols[link_col] = raw_id
            code_count += 1
            sig_parts.append(f"{sig_prefix}={raw_id}")
            code_val = (getattr(row, code_col, "") or "").strip()
            name_val = (getattr(row, name_col, "") or "").strip()
            piece = f"{short_label}: {code_val}"
            if name_val and name_val != code_val and criterion != "mark":
                piece += f" ({name_val})"
            label_parts.append(piece)
        else:
            link_cols[link_col] = None

    if code_count < 2:
        raise HTTPException(
            422,
            f"{prefix}Select at least two workspace code criteria (for example Operation + Activity, "
            "or NPT + Cause + Agency) to form a multi-criteria code link.",
        )

    _check_classification_matrix(
        data.default_classification,
        data.default_allocation,
        link_cols.get("npt_code_id"),
        prefix=prefix,
    )

    criteria_count = len(sig_parts)
    signature = "|".join(sig_parts)
    summary_label = " -> ".join(label_parts)[:400]
    return link_cols, signature, criteria_count, summary_label


def _hydrate_links(db: Session, organization_id: str, rows: list[OpsCodeLink]) -> list[dict]:
    if not rows:
        return []
    lookups: dict[str, dict[str, object]] = {}
    for criterion, spec in CRITERIA_SPECS.items():
        _master_kind, model, _code_col, _name_col, _corr_col, link_col, _short_label, _sig = spec
        ids = {getattr(row, link_col) for row in rows if getattr(row, link_col)}
        if ids:
            fetched = db.scalars(
                select(model).where(model.organization_id == organization_id, model.id.in_(ids))
            ).all()
            lookups[criterion] = {item.id: item for item in fetched}
        else:
            lookups[criterion] = {}

    out: list[dict] = []
    for row in rows:
        phase = lookups["phase"].get(row.phase_code_id or "")
        op = lookups["operation"].get(row.operation_code_id or "")
        act = lookups["activity"].get(row.activity_code_id or "")
        npt = lookups["npt"].get(row.npt_code_id or "")
        cause = lookups["cause"].get(row.cause_id or "")
        agency = lookups["agency"].get(row.agency_id or "")
        mark = lookups["mark"].get(row.mark_rule_id or "")
        out.append(
            {
                "id": row.id,
                "rule_name": row.rule_name or "",
                "scope": row.scope or "",
                "default_classification": row.default_classification or "",
                "default_allocation": row.default_allocation or "",
                "phase_code_id": row.phase_code_id,
                "phase_label": _format_code_label(phase, "phase_code", "phase_name") if phase else "",
                "operation_code_id": row.operation_code_id,
                "operation_label": _format_code_label(op, "operation_code", "operation_name") if op else "",
                "activity_code_id": row.activity_code_id,
                "activity_label": _format_code_label(act, "activity_code", "activity_name") if act else "",
                "npt_code_id": row.npt_code_id,
                "npt_label": _format_code_label(npt, "npt_code", "npt_name") if npt else "",
                "cause_id": row.cause_id,
                "cause_code": getattr(cause, "cause_code", "") if cause else "",
                "cause_label": _format_code_label(cause, "cause_code", "cause_name") if cause else "",
                "agency_id": row.agency_id,
                "agency_name": getattr(agency, "agency_name", "") if agency else "",
                "agency_label": _format_code_label(agency, "agency_code", "agency_name") if agency else "",
                "mark_rule_id": row.mark_rule_id,
                "mark_label": _format_code_label(mark, "mark_code", "mark_name") if mark else "",
                "criteria_count": row.criteria_count,
                "summary_label": row.summary_label or "",
                "note": row.note or "",
                "is_active": row.is_active,
                "is_deleted": row.is_deleted,
                "created_by": row.created_by or "",
                "updated_by": row.updated_by or "",
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
    return out


def list_code_links(
    db: Session,
    organization_id: str,
    *,
    scope: str = "",
    include_deleted: bool = False,
    active_only: bool = False,
) -> list[dict]:
    q = select(OpsCodeLink).where(
        OpsCodeLink.organization_id == organization_id,
        OpsCodeLink.is_deleted.is_(include_deleted),
    )
    if scope:
        q = q.where(or_(OpsCodeLink.scope == "", OpsCodeLink.scope == scope))
    if active_only:
        q = q.where(OpsCodeLink.is_active.is_(True))
    rows = list(db.scalars(q.order_by(OpsCodeLink.summary_label, OpsCodeLink.created_at)))
    return _hydrate_links(db, organization_id, rows)


def _prepare_code_link(
    db: Session,
    organization_id: str,
    data: OpsCodeLinkIn,
    actor: User,
    *,
    prefix: str = "",
) -> OpsCodeLink:
    link_cols, signature, criteria_count, summary_label = _build_link_payload(
        db, organization_id, data, prefix=prefix
    )
    existing = db.scalar(
        select(OpsCodeLink).where(
            OpsCodeLink.organization_id == organization_id,
            OpsCodeLink.rule_signature == signature,
        )
    )
    if existing is not None:
        if existing.is_deleted:
            raise HTTPException(
                409,
                f"{prefix}This multi-criteria code link is in Deleted entries; "
                "restore or permanently delete it before recreating it.",
            )
        raise HTTPException(
            409,
            f"{prefix}An identical multi-criteria code link already exists ({existing.summary_label}).",
        )
    return OpsCodeLink(
        organization_id=organization_id,
        rule_name=data.rule_name,
        rule_signature=signature,
        scope=data.scope,
        default_classification=data.default_classification,
        default_allocation=data.default_allocation,
        criteria_count=criteria_count,
        summary_label=summary_label,
        note=data.note,
        is_active=data.is_active,
        created_by=actor.email,
        updated_by=actor.email,
        **link_cols,
    )


def create_code_link(
    db: Session,
    organization_id: str,
    data: OpsCodeLinkIn,
    actor: User,
    request: Request | None = None,
) -> dict:
    row = _prepare_code_link(db, organization_id, data, actor)
    db.add(row)
    db.flush()
    audit_record(
        db,
        organization_id=organization_id,
        actor=actor,
        action="create",
        entity_type="ops_code_link",
        entity_id=row.id,
        entity_label=(row.rule_name or row.summary_label)[:160],
        summary=f"Linked workspace codes ({row.criteria_count} criteria): {row.summary_label}"[:500],
        request=request,
    )
    db.commit()
    db.refresh(row)
    return _hydrate_links(db, organization_id, [row])[0]


def create_code_links_batch(
    db: Session,
    organization_id: str,
    data: OpsCodeLinkBatchIn,
    actor: User,
    request: Request | None = None,
) -> dict:
    """Validate and save multiple multi-criteria workspace code links atomically."""
    seen: set[str] = set()
    created: list[OpsCodeLink] = []
    for idx, item in enumerate(data.items, start=1):
        prefix = f"Link {idx}: "
        try:
            row = _prepare_code_link(db, organization_id, item, actor, prefix=prefix)
        except HTTPException:
            db.rollback()
            raise
        if row.rule_signature in seen:
            db.rollback()
            raise HTTPException(409, f"{prefix}Duplicate code link inside this batch ({row.summary_label}).")
        seen.add(row.rule_signature)
        db.add(row)
        created.append(row)

    db.flush()
    audit_record(
        db,
        organization_id=organization_id,
        actor=actor,
        action="create",
        entity_type="ops_code_link",
        entity_id=created[0].id if len(created) == 1 else None,
        entity_label=f"Batch ({len(created)} code links)",
        summary=f"Created {len(created)} multi-criteria code link(s) in batch",
        request=request,
    )
    db.commit()
    for row in created:
        db.refresh(row)
    return {"created_count": len(created), "items": _hydrate_links(db, organization_id, created)}


def update_code_link(
    db: Session,
    organization_id: str,
    link_id: str,
    data: OpsCodeLinkIn,
    actor: User,
    request: Request | None = None,
) -> dict:
    row = db.scalar(
        select(OpsCodeLink).where(
            OpsCodeLink.organization_id == organization_id,
            OpsCodeLink.id == link_id,
            OpsCodeLink.is_deleted.is_(False),
        )
    )
    if row is None:
        raise HTTPException(404, "Multi-criteria code link not found.")
    link_cols, signature, criteria_count, summary_label = _build_link_payload(db, organization_id, data)
    clash = db.scalar(
        select(OpsCodeLink).where(
            OpsCodeLink.organization_id == organization_id,
            OpsCodeLink.rule_signature == signature,
            OpsCodeLink.id != link_id,
        )
    )
    if clash is not None:
        if clash.is_deleted:
            raise HTTPException(
                409,
                "Another deleted code link already uses this exact criteria combination; "
                "restore or permanently delete it first.",
            )
        raise HTTPException(409, f"An identical multi-criteria code link already exists ({clash.summary_label}).")

    for col, val in link_cols.items():
        setattr(row, col, val)
    row.rule_name = data.rule_name
    row.rule_signature = signature
    row.scope = data.scope
    row.default_classification = data.default_classification
    row.default_allocation = data.default_allocation
    row.criteria_count = criteria_count
    row.summary_label = summary_label
    row.note = data.note
    row.is_active = data.is_active
    row.updated_by = actor.email
    audit_record(
        db,
        organization_id=organization_id,
        actor=actor,
        action="update",
        entity_type="ops_code_link",
        entity_id=row.id,
        entity_label=(row.rule_name or row.summary_label)[:160],
        summary=f"Updated code link ({criteria_count} criteria): {summary_label}"[:500],
        request=request,
    )
    db.commit()
    db.refresh(row)
    return _hydrate_links(db, organization_id, [row])[0]


def delete_code_links(
    db: Session, organization_id: str, ids: list[str], actor: User, request: Request | None = None
) -> dict:
    rows = list(
        db.scalars(
            select(OpsCodeLink).where(
                OpsCodeLink.organization_id == organization_id,
                OpsCodeLink.id.in_(ids),
                OpsCodeLink.is_deleted.is_(False),
            )
        )
    )
    stamp = datetime.now(UTC)
    for row in rows:
        row.is_deleted = True
        row.deleted_at = stamp
        row.updated_by = actor.email
        audit_record(
            db,
            organization_id=organization_id,
            actor=actor,
            action="delete",
            entity_type="ops_code_link",
            entity_id=row.id,
            entity_label=(row.rule_name or row.summary_label)[:160],
            summary=f"Deleted multi-criteria code link: {row.summary_label}"[:500],
            request=request,
        )
    db.commit()
    return {"affected_count": len(rows)}


def restore_code_links(
    db: Session, organization_id: str, ids: list[str], actor: User, request: Request | None = None
) -> dict:
    rows = list(
        db.scalars(
            select(OpsCodeLink).where(
                OpsCodeLink.organization_id == organization_id,
                OpsCodeLink.id.in_(ids),
                OpsCodeLink.is_deleted.is_(True),
            )
        )
    )
    for row in rows:
        for _criterion, spec in CRITERIA_SPECS.items():
            _master_kind, model, code_col, _name_col, _corr_col, link_col, short_label, _sig = spec
            target_id = getattr(row, link_col, None)
            if not target_id:
                continue
            target = db.scalar(
                select(model).where(model.organization_id == organization_id, model.id == target_id)
            )
            if target is None or target.is_deleted:
                code_txt = getattr(target, code_col, target_id) if target is not None else target_id
                raise HTTPException(
                    409,
                    f"Cannot restore code link: workspace {short_label.lower()} code "
                    f"'{code_txt}' is in Deleted entries. Restore the code first.",
                )
    for row in rows:
        row.is_deleted = False
        row.deleted_at = None
        row.updated_by = actor.email
        audit_record(
            db,
            organization_id=organization_id,
            actor=actor,
            action="restore",
            entity_type="ops_code_link",
            entity_id=row.id,
            entity_label=(row.rule_name or row.summary_label)[:160],
            summary=f"Restored multi-criteria code link: {row.summary_label}"[:500],
            request=request,
        )
    db.commit()
    return {"affected_count": len(rows)}


def purge_code_links(
    db: Session, organization_id: str, ids: list[str], actor: User, request: Request | None = None
) -> dict:
    """Permanently remove multi-criteria code links that are already in Deleted entries."""
    rows = list(
        db.scalars(
            select(OpsCodeLink).where(
                OpsCodeLink.organization_id == organization_id,
                OpsCodeLink.id.in_(ids),
            )
        )
    )
    if any(not row.is_deleted for row in rows):
        raise HTTPException(409, "Delete a code link before removing it permanently.")
    for row in rows:
        audit_record(
            db,
            organization_id=organization_id,
            actor=actor,
            action="permanent_delete",
            entity_type="ops_code_link",
            entity_id=row.id,
            entity_label=(row.rule_name or row.summary_label)[:160],
            summary=f"Permanently deleted multi-criteria code link: {row.summary_label}"[:500],
            request=request,
        )
        db.delete(row)
    db.commit()
    return {"affected_count": len(rows)}


# ---------------------------------------------------------------------------
# Code library dependency guards, label synchronisation & usage counts
# ---------------------------------------------------------------------------


def active_code_references(db: Session, organization_id: str, master_kind: str, record_id: str) -> list[str]:
    """Return human-readable active correlation and code-link rules that reference ``record_id``."""
    criterion = MASTER_TO_CRITERION.get(master_kind)
    if not criterion:
        return []
    _mk, _model, _cc, _nc, corr_col, link_col, _short, _sig = CRITERIA_SPECS[criterion]
    refs: list[str] = []
    for corr in db.scalars(
        select(OpsCodeCorrelation).where(
            OpsCodeCorrelation.organization_id == organization_id,
            OpsCodeCorrelation.is_deleted.is_(False),
            getattr(OpsCodeCorrelation, corr_col) == record_id,
        )
    ):
        refs.append(f"printed correlation '{corr.source_code} -> {corr.target_label}'")
    for link in db.scalars(
        select(OpsCodeLink).where(
            OpsCodeLink.organization_id == organization_id,
            OpsCodeLink.is_deleted.is_(False),
            getattr(OpsCodeLink, link_col) == record_id,
        )
    ):
        title = link.rule_name or link.summary_label
        refs.append(f"code link '{title}'")
    return refs


def all_code_references(
    db: Session, organization_id: str, master_kind: str, record_id: str
) -> tuple[int, int, int, int]:
    """Return ``(active_corr, deleted_corr, active_links, deleted_links)`` for a code."""
    criterion = MASTER_TO_CRITERION.get(master_kind)
    if not criterion:
        return (0, 0, 0, 0)
    _mk, _model, _cc, _nc, corr_col, link_col, _short, _sig = CRITERIA_SPECS[criterion]
    corrs = list(
        db.scalars(
            select(OpsCodeCorrelation).where(
                OpsCodeCorrelation.organization_id == organization_id,
                getattr(OpsCodeCorrelation, corr_col) == record_id,
            )
        )
    )
    links = list(
        db.scalars(
            select(OpsCodeLink).where(
                OpsCodeLink.organization_id == organization_id,
                getattr(OpsCodeLink, link_col) == record_id,
            )
        )
    )
    active_corr = sum(1 for row in corrs if not row.is_deleted)
    deleted_corr = sum(1 for row in corrs if row.is_deleted)
    active_links = sum(1 for row in links if not row.is_deleted)
    deleted_links = sum(1 for row in links if row.is_deleted)
    return (active_corr, deleted_corr, active_links, deleted_links)


def code_usage_counts(db: Session, organization_id: str) -> dict[str, dict[str, int]]:
    """Active correlation + code-link count per workspace code ID across all 7 libraries."""
    counts: dict[str, dict[str, int]] = {spec[0]: defaultdict(int) for spec in CRITERIA_SPECS.values()}
    for corr in db.scalars(
        select(OpsCodeCorrelation).where(
            OpsCodeCorrelation.organization_id == organization_id,
            OpsCodeCorrelation.is_deleted.is_(False),
        )
    ):
        for spec in CRITERIA_SPECS.values():
            val = getattr(corr, spec[4], None)
            if val:
                counts[spec[0]][val] += 1
    for link in db.scalars(
        select(OpsCodeLink).where(
            OpsCodeLink.organization_id == organization_id,
            OpsCodeLink.is_deleted.is_(False),
        )
    ):
        for spec in CRITERIA_SPECS.values():
            val = getattr(link, spec[5], None)
            if val:
                counts[spec[0]][val] += 1
    return {kind: dict(bucket) for kind, bucket in counts.items()}


def refresh_labels_for_code(db: Session, organization_id: str, master_kind: str, record: object) -> None:
    """Keep denormalised labels on correlations and code links in sync after code edits."""
    criterion = MASTER_TO_CRITERION.get(master_kind)
    if not criterion:
        return
    _mk, _model, code_col, name_col, corr_col, link_col, _short, _sig = CRITERIA_SPECS[criterion]
    record_id = getattr(record, "id")
    fresh_label = _format_code_label(record, code_col, name_col)[:200]

    for corr in db.scalars(
        select(OpsCodeCorrelation).where(
            OpsCodeCorrelation.organization_id == organization_id,
            getattr(OpsCodeCorrelation, corr_col) == record_id,
        )
    ):
        if corr.kind == criterion:
            corr.target_label = fresh_label
        # Rebuild companion summary if secondary criteria exist.
        parts: list[str] = []
        if corr.scope:
            parts.append(f"Scope: {corr.scope.title()}")
        if corr.target_classification:
            parts.append(f"Class: {corr.target_classification}")
        if corr.target_allocation:
            parts.append(f"Alloc: {corr.target_allocation}")
        primary_col = CRITERIA_SPECS.get(corr.kind, CRITERIA_SPECS[criterion])[4]
        for c_key, c_spec in CRITERIA_SPECS.items():
            if c_spec[4] == primary_col:
                continue
            cid = getattr(corr, c_spec[4], None)
            if not cid:
                continue
            target = record if cid == record_id else db.get(c_spec[1], cid)
            if target is not None:
                parts.append(f"{c_spec[6]}: {getattr(target, c_spec[2], '')}")
        corr.extra_criteria_summary = " · ".join(parts)[:300]

    for link in db.scalars(
        select(OpsCodeLink).where(
            OpsCodeLink.organization_id == organization_id,
            getattr(OpsCodeLink, link_col) == record_id,
        )
    ):
        parts = []
        if link.scope:
            parts.append(f"Scope: {link.scope.title()}")
        if link.default_classification:
            parts.append(f"Class: {link.default_classification}")
        if link.default_allocation:
            parts.append(f"Alloc: {link.default_allocation}")
        for c_key, c_spec in CRITERIA_SPECS.items():
            cid = getattr(link, c_spec[5], None)
            if not cid:
                continue
            target = record if cid == record_id else db.get(c_spec[1], cid)
            if target is not None:
                c_val = (getattr(target, c_spec[2], "") or "").strip()
                n_val = (getattr(target, c_spec[3], "") or "").strip()
                piece = f"{c_spec[6]}: {c_val}"
                if n_val and n_val != c_val and c_key != "mark":
                    piece += f" ({n_val})"
                parts.append(piece)
        link.summary_label = " -> ".join(parts)[:400]


# ---------------------------------------------------------------------------
# Extraction helpers — deterministic correlation + multi-criteria link pass
# ---------------------------------------------------------------------------


def correlation_map(db: Session, organization_id: str) -> dict[tuple[str, str], OpsCodeCorrelation]:
    """Lookup used during extraction: ``(kind, normalised_source_code) -> rule``."""
    rows = db.scalars(
        select(OpsCodeCorrelation).where(
            OpsCodeCorrelation.organization_id == organization_id,
            OpsCodeCorrelation.is_deleted.is_(False),
            OpsCodeCorrelation.is_active.is_(True),
        )
    )
    return {(row.kind, code_key(row.source_code)): row for row in rows}


def _code_from_label(label: str) -> str:
    return (label or "").split(" — ", 1)[0].strip()


def _apply_phase_code(db: Session | None, block: OpsActivityBlock, phase_code_id: str, fallback_code: str = "") -> bool:
    """Apply an ``OpsPhaseCode`` safely without writing its ID to ``phases.id``."""
    phase_code = db.get(OpsPhaseCode, phase_code_id) if db is not None else None
    code_txt = ""
    name_txt = ""
    if phase_code is not None and not phase_code.is_deleted:
        code_txt = phase_code.phase_code
        name_txt = phase_code.phase_name
    elif fallback_code:
        code_txt = fallback_code
    if not code_txt:
        return False
    block.phase_raw = code_txt[:20]
    if db is not None and not block.phase_id:
        conds = [Phase.phase_code == code_txt]
        if name_txt:
            conds.append(Phase.phase_name == name_txt)
        master_phase = db.scalar(
            select(Phase).where(
                Phase.organization_id == block.organization_id,
                Phase.is_deleted.is_(False),
                or_(*conds),
            )
        )
        if master_phase is not None:
            block.phase_id = master_phase.id
    return True


def _apply_agency_code(
    db: Session | None, block: OpsActivityBlock, agency_id: str, *, fallback_name: str = ""
) -> bool:
    if block.agency_id:
        return False
    agency = db.get(OpsAgency, agency_id) if db is not None else None
    if db is not None and (agency is None or agency.is_deleted):
        return False
    block.agency_id = agency_id
    if not (block.responsible_party or "").strip():
        name_txt = agency.agency_name if agency is not None else fallback_name
        if name_txt:
            block.responsible_party = name_txt[:200]
    return True


def _apply_single_rule(
    db: Session | None,
    block: OpsActivityBlock,
    rule: OpsCodeCorrelation,
    *,
    kind: str,
) -> bool:
    """Apply a matched ``OpsCodeCorrelation`` and any empty companion criteria."""
    changed = False

    # Explicit classification / allocation overrides apply when the block has no explicit source mark.
    if rule.target_classification and block.classification_source != "source_mark":
        if block.classification != rule.target_classification:
            block.classification = rule.target_classification
            block.is_productive = rule.target_classification != "NPT"
            if not rule.target_allocation:
                block.allocation = {
                    "Planned": "PT",
                    "UPA": "UPA",
                    "NPT": "NPT",
                }.get(rule.target_classification, block.allocation)
            changed = True
    if rule.target_allocation and block.classification_source != "source_mark":
        if not (rule.target_allocation == "NPT" and block.classification != "NPT"):
            if block.allocation != rule.target_allocation:
                block.allocation = rule.target_allocation
                if rule.target_allocation == "NPT":
                    block.is_productive = False
                changed = True

    if rule.target_operation_code_id and not block.operation_code_id:
        block.operation_code_id = rule.target_operation_code_id
        changed = True
    if rule.target_activity_code_id and not block.activity_code_id:
        block.activity_code_id = rule.target_activity_code_id
        changed = True
    if rule.target_npt_code_id and block.classification == "NPT" and not block.npt_code_id:
        block.npt_code_id = rule.target_npt_code_id
        if not block.npt_code_snapshot:
            if db is not None and (npt_row := db.get(OpsNptCode, rule.target_npt_code_id)) is not None:
                block.npt_code_snapshot = npt_row.npt_code
            elif kind == "npt":
                block.npt_code_snapshot = _code_from_label(rule.target_label)[:50]
        changed = True
    if rule.target_cause_id and not (block.cause_code or "").strip():
        cause_code = ""
        if db is not None:
            cause = db.get(OpsCause, rule.target_cause_id)
            if cause is not None and not cause.is_deleted:
                cause_code = cause.cause_code
        elif kind == "cause":
            cause_code = _code_from_label(rule.target_label)
        if cause_code:
            block.cause_code = cause_code[:50]
            changed = True
    elif rule.target_cause_id and kind == "cause" and code_key(block.cause_code) == code_key(rule.source_code):
        # Replace raw printed cause token with correlated workspace cause code.
        cause_code = ""
        if db is not None:
            cause = db.get(OpsCause, rule.target_cause_id)
            if cause is not None and not cause.is_deleted:
                cause_code = cause.cause_code
        else:
            cause_code = _code_from_label(rule.target_label)
        if cause_code and cause_code != block.cause_code:
            block.cause_code = cause_code[:50]
            changed = True
    if rule.target_phase_code_id and (
        not (block.phase_raw or "").strip()
        or (kind == "phase" and code_key(block.phase_raw) == code_key(rule.source_code))
    ):
        fallback_code = _code_from_label(rule.target_label) if kind == "phase" else ""
        if _apply_phase_code(db, block, rule.target_phase_code_id, fallback_code=fallback_code):
            changed = True
    if rule.target_agency_id and not block.vendor_id:
        fallback_name = ""
        if kind == "agency" and " — " in (rule.target_label or ""):
            fallback_name = rule.target_label.split(" — ", 1)[1].strip()
        if _apply_agency_code(db, block, rule.target_agency_id, fallback_name=fallback_name):
            changed = True

    if changed:
        block.review_state = "suggested"
    return changed


def apply_to_block(
    block: OpsActivityBlock,
    rules: dict[tuple[str, str], OpsCodeCorrelation],
    *,
    db: Session | None = None,
    report_scope: str = "",
    operation_tokens: tuple[str, ...] = (),
    activity_tokens: tuple[str, ...] = (),
    npt_tokens: tuple[str, ...] = (),
    cause_tokens: tuple[str, ...] = (),
    phase_tokens: tuple[str, ...] = (),
    agency_tokens: tuple[str, ...] = (),
) -> list[str]:
    """Apply matching printed-code correlations (plus companion criteria) to ``block``.

    Fills only what the source left empty (or translates raw printed cause/phase tokens),
    never overrides a direct library hit, keeps ``review_state == 'suggested'``, and
    returns auditable evidence lines for ``block.classification_evidence``.
    """
    if not rules:
        return []
    evidence: list[str] = []
    token_groups = (
        ("operation", operation_tokens),
        ("activity", activity_tokens),
        ("npt", npt_tokens),
        ("cause", cause_tokens),
        ("phase", phase_tokens),
        ("agency", agency_tokens),
    )
    for kind, tokens in token_groups:
        for raw in tokens:
            if not raw:
                continue
            rule = rules.get((kind, code_key(raw)))
            if rule is None:
                continue
            if rule.scope and report_scope and rule.scope != report_scope:
                continue
            if _apply_single_rule(db, block, rule, kind=kind):
                line = f"correlated {rule.source_code} -> {rule.target_label}"
                if rule.extra_criteria_summary:
                    line += f" [{rule.extra_criteria_summary}]"
                evidence.append(line)
            break
    return evidence


def apply_code_links_to_block(
    db: Session,
    block: OpsActivityBlock,
    links: list[dict],
    *,
    report_scope: str = "",
) -> list[str]:
    """Fill remaining empty block fields when active multi-criteria links agree unambiguously.

    A link matches a block when (a) its scope is empty or equals ``report_scope``,
    (b) at least one workspace code criterion on the link matches a code already set on
    the block, and (c) no criterion set on the link conflicts with a non-empty criterion
    on the block. An empty field is filled ONLY when every matching link that specifies
    that field supplies the exact same single value — never guessed.
    """
    if not links:
        return []

    phase_code_by_id = {
        link["phase_code_id"]: code_key(_code_from_label(link["phase_label"]))
        for link in links
        if link.get("phase_code_id") and link.get("phase_label")
    }
    mark_by_id = {
        link["mark_rule_id"]: code_key(_code_from_label(link["mark_label"]))
        for link in links
        if link.get("mark_rule_id") and link.get("mark_label")
    }

    block_phase = code_key(block.phase_raw)
    block_cause = code_key(block.cause_code)
    block_mark = code_key(block.source_mark)

    compatible: list[dict] = []
    for link in links:
        if link.get("scope") and report_scope and link["scope"] != report_scope:
            continue
        matched = 0
        conflict = False

        if link.get("operation_code_id"):
            if block.operation_code_id:
                if block.operation_code_id == link["operation_code_id"]:
                    matched += 1
                else:
                    conflict = True
        if not conflict and link.get("activity_code_id"):
            if block.activity_code_id:
                if block.activity_code_id == link["activity_code_id"]:
                    matched += 1
                else:
                    conflict = True
        if not conflict and link.get("npt_code_id"):
            if block.npt_code_id:
                if block.npt_code_id == link["npt_code_id"]:
                    matched += 1
                else:
                    conflict = True
        if not conflict and link.get("cause_code"):
            if block_cause:
                if block_cause == code_key(link["cause_code"]):
                    matched += 1
                else:
                    conflict = True
        if not conflict and link.get("agency_id"):
            if block.agency_id:
                if block.agency_id == link["agency_id"]:
                    matched += 1
                else:
                    conflict = True
        if not conflict and link.get("phase_code_id"):
            lp = phase_code_by_id.get(link["phase_code_id"], "")
            if block_phase and lp:
                if block_phase == lp:
                    matched += 1
                else:
                    conflict = True
        if not conflict and link.get("mark_rule_id"):
            lm = mark_by_id.get(link["mark_rule_id"], "")
            if block_mark and lm:
                if block_mark == lm:
                    matched += 1
                else:
                    conflict = True

        if matched >= 1 and not conflict:
            compatible.append(link)

    if not compatible:
        return []

    def _unique(key: str) -> str | None:
        vals = {item[key] for item in compatible if item.get(key)}
        return next(iter(vals)) if len(vals) == 1 else None

    applied_fields: list[str] = []

    cls_val = _unique("default_classification")
    alloc_val = _unique("default_allocation")
    if cls_val and block.classification_source != "source_mark" and block.classification == "Planned":
        if cls_val != block.classification:
            block.classification = cls_val
            block.is_productive = cls_val != "NPT"
            block.allocation = alloc_val or {"Planned": "PT", "UPA": "UPA", "NPT": "NPT"}.get(
                cls_val, block.allocation
            )
            applied_fields.append(f"classification={cls_val}")
    if alloc_val and block.classification_source != "source_mark":
        if not (alloc_val == "NPT" and block.classification != "NPT") and block.allocation != alloc_val:
            if not (block.classification == "NPT" and alloc_val == "PT"):
                block.allocation = alloc_val
                if alloc_val == "NPT":
                    block.is_productive = False
                applied_fields.append(f"allocation={alloc_val}")

    if not block.operation_code_id and (op_id := _unique("operation_code_id")):
        block.operation_code_id = op_id
        applied_fields.append("operation")
    if not block.activity_code_id and (act_id := _unique("activity_code_id")):
        block.activity_code_id = act_id
        applied_fields.append("activity")
    if block.classification == "NPT" and not block.npt_code_id and (npt_id := _unique("npt_code_id")):
        block.npt_code_id = npt_id
        if not block.npt_code_snapshot and (npt_row := db.get(OpsNptCode, npt_id)) is not None:
            block.npt_code_snapshot = npt_row.npt_code
        applied_fields.append("NPT")
    if not block_cause and block.classification in ("NPT", "UPA") and (cause_code := _unique("cause_code")):
        block.cause_code = cause_code[:50]
        applied_fields.append(f"cause={cause_code}")
    if not block.vendor_id and not block.agency_id and (agency_id := _unique("agency_id")):
        if _apply_agency_code(db, block, agency_id):
            applied_fields.append("agency")
    if not block_phase and (phase_id := _unique("phase_code_id")):
        if _apply_phase_code(db, block, phase_id):
            applied_fields.append("phase")

    if not applied_fields:
        return []

    block.review_state = "suggested"
    return [f"code link pre-selected {', '.join(applied_fields)}"]
