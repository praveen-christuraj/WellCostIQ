"""Operations Code Library correlations and multi-criteria code links.

Two complementary, auditable rule sets live in ``Well Operations -> Code library``:

1. **Printed-to-workspace correlations (``OpsCodeCorrelation``)** map an exact
   printed token from the reference dictionary (or a printed source agency token)
   to a primary workspace record — the Code Library Operations list, a cause, a
   sub-phase, a responsible agency label or an agency/service vendor — plus any
   optional companion criteria (hole section, phase, activity, allocation, scope).
2. **Multi-criteria workspace code links (``OpsCodeLink``)** connect two or more
   workspace records across Hole Section, Phase, Sub-phase, Activity, Operations,
   Cause, Responsible agency label, Agency / service vendor and Source mark in
   typed relational columns (no JSON). One rule carries as many criteria as the
   user needs: ``DRLSUR`` can say "this section, phase, sub-phase, activity,
   operation, cause and vendor" in a single row.

Hole Section, Phase and Activity are **Master Data** registers; Operations,
Sub-phase, Cause and the Responsible agency label are configured in the Code
Library; the vendor list is also Master Data. Correlations read all of them
without creating a dependency on any costing table.

Extraction applies exact printed correlations first, then fills any remaining
empty fields only when active workspace code links agree on one unambiguous
value. Every mapped block keeps ``review_state = "suggested"`` until an engineer
confirms it. Correlated or linked records cannot be deleted until their rules
are removed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.operations.default_codes import catalogue_rows
from app.models.master_data import Activity, HoleSection, Phase
from app.models.operations import (
    OpsActivityBlock,
    OpsAgency,
    OpsCause,
    OpsCodeCorrelation,
    OpsCodeLink,
    OpsMarkRule,
    OpsOperation,
    OpsSubPhase,
)
from app.models.vendor_master import Vendor
from app.models import User
from app.schemas.operations import (
    OpsCodeLinkBatchIn,
    OpsCodeLinkIn,
    OpsCorrelationBatchIn,
    OpsCorrelationIn,
    OpsCorrelationUpdate,
)
from app.services.audit import record as audit_record


def code_key(code: str) -> str:
    return (code or "").strip().lower()


def _format_code_label(row, code_col: str, name_col: str) -> str:
    code = (getattr(row, code_col, "") or "").strip()
    name = (getattr(row, name_col, "") or "").strip()
    if name and name != code:
        return f"{code} — {name}"
    return code


# Criterion spec: (library key, model, code column, name column, correlation
# column, link column, human label, signature prefix).
#
# The library key is what the Code Library page addresses the list by; Master
# Data criteria use their Master Data module name so the page can deep-link.
CRITERIA_SPECS: dict[str, tuple[str, type, str, str, str, str, str, str]] = {
    "hole_section": (
        "hole-sections",
        HoleSection,
        "section_code",
        "section_name",
        "target_hole_section_id",
        "hole_section_id",
        "Hole section",
        "hs",
    ),
    "phase": (
        "phases",
        Phase,
        "phase_code",
        "phase_name",
        "target_phase_id",
        "phase_id",
        "Phase",
        "ph",
    ),
    "sub_phase": (
        "sub-phases",
        OpsSubPhase,
        "sub_phase_code",
        "sub_phase_name",
        "target_sub_phase_id",
        "sub_phase_id",
        "Sub-phase",
        "sp",
    ),
    "activity": (
        "activities",
        Activity,
        "activity_code",
        "activity_name",
        "target_activity_id",
        "activity_id",
        "Activity",
        "ac",
    ),
    "operation": (
        "operations",
        OpsOperation,
        "operation_code",
        "operation_name",
        "target_operation_id",
        "operation_id",
        "Operations",
        "op",
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
    "responsible_agency": (
        "agencies",
        OpsAgency,
        "agency_code",
        "agency_name",
        "target_responsible_agency_id",
        "responsible_agency_id",
        "Responsible agency label",
        "ra",
    ),
    "vendor": (
        "vendors",
        Vendor,
        "vendor_code",
        "vendor_name",
        "target_vendor_id",
        "vendor_id",
        "Agency / service vendor",
        "vn",
    ),
    "mark": (
        "source-marks",
        OpsMarkRule,
        "mark_code",
        "mark_name",
        "target_mark_rule_id",
        "mark_rule_id",
        "Source mark",
        "mk",
    ),
}

MASTER_TO_CRITERION = {spec[0]: key for key, spec in CRITERIA_SPECS.items()}

#: The criterion a correlation's printed token belongs to, and the printed
#: reference families it may be read from. Hole Section, Phase and Activity are
#: deliberately absent: they are Master Data, so a printed token is correlated
#: *to* them rather than configured *as* them.
KINDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "operation": ("operation", ("Trouble / NPT", "Operation", "OpenWells operation code")),
    "cause": ("cause", ("Cause", "Trouble / NPT")),
    "sub-phase": ("sub_phase", ("OpenWells phase", "Programme phase")),
    "responsible-party": ("responsible_agency", ()),
    "agency": ("vendor", ()),
}

#: Correlation kind -> criterion key, for callers that only know the kind.
KIND_CRITERION = {kind: spec[0] for kind, spec in KINDS.items()}


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
        raise HTTPException(404, f"{short_label} not found in this workspace.")
    if require_active and hasattr(row, "is_active") and not row.is_active:
        raise HTTPException(
            422, f"{short_label} '{getattr(row, code_col)}' is inactive; activate it before linking."
        )
    if criterion == "vendor" and getattr(row, "status", "") not in ("", "active"):
        raise HTTPException(422, "Select an active vendor as the agency / service vendor.")
    return row, _format_code_label(row, code_col, name_col)


def _check_allocation_matrix(allocation: str, *, prefix: str = "") -> None:
    if allocation and allocation not in ("PT", "UPA", "NPT", "SP"):
        raise HTTPException(422, f"{prefix}Allocation must be PT, UPA, NPT or SP.")


def _check_cause_matrix(db: Session, organization_id: str, activity_id: str | None, cause_id: str | None,
                       *, prefix: str = "") -> None:
    """Refuse a rule that would force a cause onto Planned work.

    Cause is mandatory only when the Activity type is NPT or UPA. A link or
    correlation that pairs a cause with a Planned Activity would contradict that
    rule on every extracted block, so it is refused when the rule is saved rather
    than quietly ignored later. Without an Activity the rule is allowed: the
    cause then only ever fills a block the engineer typed NPT or UPA.
    """
    if not cause_id or not activity_id:
        return
    activity = db.scalar(
        select(Activity).where(Activity.organization_id == organization_id, Activity.id == activity_id)
    )
    if activity is None:
        return
    if (activity.activity_type or "Planned") == "Planned":
        raise HTTPException(
            422,
            f"{prefix}Activity '{activity.activity_code}' is {activity.activity_type}, so it never carries a "
            "cause. Select the cause on an NPT or UPA activity, or leave the cause out of this rule.",
        )


def _validate_printed(kind: str, source_code: str, source_family: str, *, prefix: str = "") -> tuple[str, str, str]:
    """Verify the printed code belongs to the built-in catalogue for ``kind``.

    Responsible agency and vendor rules are the explicit exception:
    ``default_codes.py`` intentionally holds no operator or contractor names, so
    those kinds accept any non-empty printed source token found on a report.
    """
    spec = KINDS.get(kind)
    if not spec:
        raise HTTPException(422, f"{prefix}Unsupported correlation kind '{kind}'.")
    _criterion, families = spec
    raw_code = (source_code or "").strip()
    if not raw_code:
        raise HTTPException(422, f"{prefix}Printed source code cannot be empty.")
    if not families:
        fam = (source_family or "").strip() or (
            "Source agency" if kind == "agency" else "Source responsible party"
        )
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
        f"{prefix}'{source_code}' is not in the printed reference catalogue for {kind} correlations.",
    )


def _companion_criteria(primary_kind: str) -> dict[str, tuple]:
    """Every criterion except the one the printed token itself is correlated as."""
    return {
        criterion: spec
        for criterion, spec in CRITERIA_SPECS.items()
        if criterion != KIND_CRITERION[primary_kind]
    }


def _build_companion_targets(
    db: Session,
    organization_id: str,
    primary_kind: str,
    primary_id: str,
    data: OpsCorrelationIn | OpsCorrelationUpdate,
    *,
    prefix: str = "",
) -> tuple[dict[str, str | None], str, str]:
    """Resolve the primary target plus every companion multi-criteria column."""
    values: dict[str, str | None] = {}
    extra_parts: list[str] = []
    allocation = (getattr(data, "target_allocation", "") or "").strip()

    if data.scope:
        extra_parts.append(f"Scope: {data.scope.title()}")
    if allocation:
        extra_parts.append(f"Alloc: {allocation}")

    _primary_row, primary_label = _resolve_target(db, organization_id, KIND_CRITERION[primary_kind], primary_id)
    primary_corr_col = CRITERIA_SPECS[KIND_CRITERION[primary_kind]][4]

    for criterion, spec in CRITERIA_SPECS.items():
        corr_col = spec[4]
        short_label = spec[6]
        if corr_col == primary_corr_col:
            values[corr_col] = primary_id
            continue
        raw_id = (getattr(data, corr_col, None) or "").strip() or None
        if raw_id:
            row, _label = _resolve_target(db, organization_id, criterion, raw_id)
            values[corr_col] = raw_id
            extra_parts.append(f"{short_label}: {getattr(row, spec[2])}")
        else:
            values[corr_col] = None

    _check_allocation_matrix(allocation, prefix=prefix)
    _check_cause_matrix(
        db,
        organization_id,
        values.get("target_activity_id"),
        values.get("target_cause_id"),
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
        try:
            row = _prepare_correlation_row(db, organization_id, item, actor, prefix=prefix)
        except HTTPException:
            db.rollback()
            raise
        # The stored code is canonicalised (trimmed, and upper-cased for catalogue
        # families), and the unique constraint is on that stored value. Keying the
        # in-batch check on the raw request text would let "tp02" and "TP02" both
        # pass and then fail at the flush, so compare what will actually be written.
        dup_key = (row.kind, row.source_code)
        if dup_key in seen:
            db.rollback()
            raise HTTPException(
                409, f"{prefix}Printed code '{row.source_code}' appears more than once in this batch."
            )
        seen.add(dup_key)
        db.add(row)
        created.append(row)

    try:
        # One transaction: a uniqueness race with another session rolls every row
        # back and reads as a conflict rather than a server error.
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            "A printed code in this batch was correlated by another session at the same time. "
            "Reload the correlations tab and retry the rows that are missing.",
        ) from exc
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
            f"{prefix}Select at least two criteria (for example Hole section + Phase, or "
            "Activity + Cause + Operations) to form a multi-criteria code link.",
        )

    _check_allocation_matrix(data.default_allocation, prefix=prefix)
    _check_cause_matrix(
        db, organization_id, link_cols.get("activity_id"), link_cols.get("cause_id"), prefix=prefix
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

    def label(criterion: str, record_id: str | None) -> str:
        if not record_id:
            return ""
        row = lookups[criterion].get(record_id)
        if row is None:
            return ""
        _mk, _m, code_col, name_col, _cc, _lc, _sl, _sig = CRITERIA_SPECS[criterion]
        return _format_code_label(row, code_col, name_col)

    def code_of(criterion: str, record_id: str | None) -> str:
        if not record_id:
            return ""
        row = lookups[criterion].get(record_id)
        return (getattr(row, CRITERIA_SPECS[criterion][2], "") or "") if row is not None else ""

    out: list[dict] = []
    for row in rows:
        activity = lookups["activity"].get(row.activity_id or "")
        out.append(
            {
                "id": row.id,
                "rule_name": row.rule_name or "",
                "scope": row.scope or "",
                "default_allocation": row.default_allocation or "",
                "hole_section_id": row.hole_section_id,
                "hole_section_label": label("hole_section", row.hole_section_id),
                "phase_id": row.phase_id,
                "phase_code": code_of("phase", row.phase_id),
                "phase_label": label("phase", row.phase_id),
                "sub_phase_id": row.sub_phase_id,
                "sub_phase_label": label("sub_phase", row.sub_phase_id),
                "activity_id": row.activity_id,
                "activity_label": label("activity", row.activity_id),
                "activity_type": getattr(activity, "activity_type", "") if activity else "",
                "operation_id": row.operation_id,
                "operation_label": label("operation", row.operation_id),
                "cause_id": row.cause_id,
                "cause_code": code_of("cause", row.cause_id),
                "cause_label": label("cause", row.cause_id),
                "responsible_agency_id": row.responsible_agency_id,
                "responsible_agency_label": label("responsible_agency", row.responsible_agency_id),
                "vendor_id": row.vendor_id,
                "vendor_label": label("vendor", row.vendor_id),
                "mark_rule_id": row.mark_rule_id,
                "mark_label": label("mark", row.mark_rule_id),
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

    try:
        # The batch is one transaction: a uniqueness race with another session must
        # roll every row back and read as a conflict, not as a server error.
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            409,
            "An identical multi-criteria code link was saved at the same moment. "
            "Reload the correlations tab and retry the rows that are missing.",
        ) from exc
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


def _apply_sub_phase(db: Session | None, block: OpsActivityBlock, sub_phase_id: str, fallback_code: str = "") -> bool:
    """Pre-select a Code Library sub-phase without ever writing its id into ``phases.id``."""
    if block.sub_phase_id:
        return False
    row = db.get(OpsSubPhase, sub_phase_id) if db is not None else None
    if db is not None and (row is None or row.is_deleted):
        return False
    block.sub_phase_id = sub_phase_id
    return True


def _apply_operation(db: Session | None, block: OpsActivityBlock, operation_id: str, *, fallback_code: str = "") -> bool:
    if block.operation_id:
        return False
    row = db.get(OpsOperation, operation_id) if db is not None else None
    if db is not None and (row is None or row.is_deleted):
        return False
    block.operation_id = operation_id
    if not (block.operation_snapshot or "").strip():
        code_txt = row.operation_code if row is not None else fallback_code
        if code_txt:
            block.operation_snapshot = code_txt[:50]
    return True


def _apply_responsible_agency(
    db: Session | None, block: OpsActivityBlock, agency_id: str, *, fallback_name: str = ""
) -> bool:
    """Set the responsible agency label, keeping its text beside the link."""
    if block.responsible_agency_id:
        return False
    agency = db.get(OpsAgency, agency_id) if db is not None else None
    if db is not None and (agency is None or agency.is_deleted):
        return False
    block.responsible_agency_id = agency_id
    if not (block.responsible_party or "").strip():
        name_txt = agency.agency_name if agency is not None else fallback_name
        if name_txt:
            block.responsible_party = name_txt[:200]
    return True


def _apply_vendor(db: Session | None, block: OpsActivityBlock, vendor_id: str, *, fallback_name: str = "") -> bool:
    """Set the agency / service vendor, keeping its name in ``responsible_party``."""
    if block.vendor_id:
        return False
    vendor = db.get(Vendor, vendor_id) if db is not None else None
    if db is not None and (vendor is None or vendor.is_deleted):
        return False
    block.vendor_id = vendor_id
    if not (block.responsible_party or "").strip():
        name_txt = vendor.vendor_name if vendor is not None else fallback_name
        if name_txt:
            block.responsible_party = name_txt[:200]
    return True


def _apply_activity(db: Session | None, block: OpsActivityBlock, activity_id: str) -> bool:
    """Pre-select the Master Data Activity and take its type as the block's Activity."""
    row = db.get(Activity, activity_id) if db is not None else None
    if db is not None and (row is None or row.is_deleted):
        return False
    changed = False
    if block.activity_id != activity_id:
        block.activity_id = activity_id
        changed = True
    activity_type = getattr(row, "activity_type", "") if row is not None else ""
    if activity_type and block.classification_source != "source_mark" and block.classification != activity_type:
        block.classification = activity_type
        block.is_productive = activity_type != "NPT"
        if activity_type != "NPT" and block.allocation == "NPT":
            block.allocation = activity_type
        changed = True
    return changed


def _apply_single_rule(
    db: Session | None,
    block: OpsActivityBlock,
    rule: OpsCodeCorrelation,
    *,
    kind: str,
) -> bool:
    """Apply a matched ``OpsCodeCorrelation`` and any empty companion criteria."""
    changed = False

    if rule.target_allocation and block.classification_source != "source_mark":
        if block.allocation != rule.target_allocation:
            block.allocation = rule.target_allocation
            if rule.target_allocation == "NPT":
                block.is_productive = False
            if block.classification == "Planned" and rule.target_allocation in ("UPA", "NPT"):
                block.classification = rule.target_allocation
            changed = True

    if rule.target_hole_section_id and not block.hole_section_id:
        block.hole_section_id = rule.target_hole_section_id
        changed = True
    if rule.target_phase_id and not block.phase_id:
        block.phase_id = rule.target_phase_id
        changed = True
    if rule.target_sub_phase_id and not block.sub_phase_id:
        if _apply_sub_phase(db, block, rule.target_sub_phase_id, fallback_code=_code_from_label(rule.target_label)):
            changed = True
    if rule.target_activity_id and _apply_activity(db, block, rule.target_activity_id):
        changed = True
    if rule.target_operation_id and _apply_operation(db, block, rule.target_operation_id):
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
        # Replace the raw printed cause token with the correlated workspace cause code.
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
    if rule.target_responsible_agency_id and _apply_responsible_agency(db, block, rule.target_responsible_agency_id):
        changed = True
    if rule.target_vendor_id and _apply_vendor(db, block, rule.target_vendor_id):
        changed = True
    if rule.target_mark_rule_id and not (block.source_mark or "").strip():
        mark = db.get(OpsMarkRule, rule.target_mark_rule_id) if db is not None else None
        if mark is not None and not mark.is_deleted:
            block.source_mark = mark.mark_code[:30]
            changed = True

    if changed:
        block.review_state = "suggested"
    return changed


#: Correlation kind -> the printed-token groups a block offers that kind.
TOKEN_KINDS = (
    "operation",
    "cause",
    "sub-phase",
    "responsible-party",
    "agency",
)


def apply_to_block(
    block: OpsActivityBlock,
    rules: dict[tuple[str, str], OpsCodeCorrelation],
    *,
    db: Session | None = None,
    report_scope: str = "",
    operation_tokens: tuple[str, ...] = (),
    cause_tokens: tuple[str, ...] = (),
    sub_phase_tokens: tuple[str, ...] = (),
    responsible_party_tokens: tuple[str, ...] = (),
    agency_tokens: tuple[str, ...] = (),
    tokens_by_kind: dict[str, tuple[str, ...]] | None = None,
) -> list[str]:
    """Apply matching printed-code correlations (plus companion criteria) to ``block``.

    Fills only what the source left empty (or translates a raw printed token),
    never overrides a direct library hit, keeps ``review_state == 'suggested'``,
    and returns auditable evidence lines for ``block.classification_evidence``.
    """
    if not rules:
        return []
    evidence: list[str] = []
    if tokens_by_kind is not None:
        token_groups = tuple(
            (kind, tuple(tokens_by_kind.get(kind, ())))
            for kind in TOKEN_KINDS
        )
    else:
        token_groups = (
            ("operation", operation_tokens),
            ("cause", cause_tokens),
            ("sub-phase", sub_phase_tokens),
            ("responsible-party", responsible_party_tokens),
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
    (b) at least one criterion on the link matches a value already set on the
    block, and (c) no criterion set on the link conflicts with a non-empty
    criterion on the block. An empty field is filled ONLY when every matching
    link that specifies that field supplies the exact same single value — never
    guessed.
    """
    if not links:
        return []

    block_cause = code_key(block.cause_code)
    block_mark = code_key(block.source_mark)
    block_phase_raw = code_key(block.phase_raw)

    compatible: list[dict] = []
    for link in links:
        if link.get("scope") and report_scope and link["scope"] != report_scope:
            continue
        matched = 0
        conflict = False

        def compare(link_id: str | None, block_value: str | None) -> None:
            nonlocal matched, conflict
            if conflict or not link_id:
                return
            if block_value:
                if block_value == link_id:
                    matched += 1
                else:
                    conflict = True

        compare(link.get("hole_section_id"), block.hole_section_id)
        compare(link.get("phase_id"), block.phase_id)
        compare(link.get("sub_phase_id"), block.sub_phase_id)
        compare(link.get("activity_id"), block.activity_id)
        compare(link.get("operation_id"), block.operation_id)
        compare(link.get("responsible_agency_id"), block.responsible_agency_id)
        compare(link.get("vendor_id"), block.vendor_id)
        compare(link.get("mark_rule_id"), block.source_mark or None)
        if not conflict and link.get("cause_code"):
            if block_cause:
                if block_cause == code_key(link["cause_code"]):
                    matched += 1
                else:
                    conflict = True
        if not conflict and link.get("phase_code"):
            # A printed phase token on the source may stand in for the phase link.
            if block_phase_raw and code_key(link["phase_code"]) == block_phase_raw:
                matched += 1

        if matched >= 1 and not conflict:
            compatible.append(link)

    if not compatible:
        return []

    def _unique(key: str) -> str | None:
        vals = {item[key] for item in compatible if item.get(key)}
        return next(iter(vals)) if len(vals) == 1 else None

    applied_fields: list[str] = []

    if not block.hole_section_id and (section_id := _unique("hole_section_id")):
        block.hole_section_id = section_id
        applied_fields.append("hole section")
    if not block.phase_id and (phase_id := _unique("phase_id")):
        block.phase_id = phase_id
        applied_fields.append("phase")
    if not block.sub_phase_id and (sub_phase_id := _unique("sub_phase_id")):
        if _apply_sub_phase(db, block, sub_phase_id):
            applied_fields.append("sub-phase")
    if activity_id := _unique("activity_id"):
        if block.activity_id != activity_id and _apply_activity(db, block, activity_id):
            applied_fields.append("activity")
    alloc_val = _unique("default_allocation")
    if alloc_val and block.classification_source != "source_mark" and block.allocation != alloc_val:
        block.allocation = alloc_val
        if alloc_val == "NPT":
            block.is_productive = False
        applied_fields.append(f"allocation={alloc_val}")
    if (
        not block_cause
        and block.classification in ("NPT", "UPA")
        and (cause_code := _unique("cause_code"))
    ):
        block.cause_code = cause_code[:50]
        applied_fields.append(f"cause={cause_code}")
    if not block.operation_id and (operation_id := _unique("operation_id")):
        if _apply_operation(db, block, operation_id):
            applied_fields.append("operations")
    if not block.responsible_agency_id and (agency_id := _unique("responsible_agency_id")):
        if _apply_responsible_agency(db, block, agency_id):
            applied_fields.append("responsible agency")
    if not block.vendor_id and (vendor_id := _unique("vendor_id")):
        if _apply_vendor(db, block, vendor_id):
            applied_fields.append("agency / service vendor")

    if not applied_fields:
        return []

    block.review_state = "suggested"
    return [f"code link pre-selected {', '.join(applied_fields)}"]
