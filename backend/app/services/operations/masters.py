"""Operations code library management with correlation and historical dependency guards.

Covers the four Code Library lists, all configured here:

- ``operations`` (``OpsOperation``) — the downtime / non-productive work list
- ``sub-phases`` (``OpsSubPhase``) — sub-phases of a Master Data phase
- ``causes`` (``OpsCause``) — the reason list used when an Activity is NPT or UPA
- ``agencies`` (``OpsAgency``) — the responsible agency label list
- ``source-marks`` (``OpsMarkRule``) — printed mark interpretation rules

Hole Sections, Phases, Activities and vendors are **Master Data**, not Code
Library lists: correlations read them where they live, so a workspace has one
definition of a hole section or an activity for costing and operations alike.

Deletion follows the platform two-step safeguard:
1. Soft delete is blocked (409) while a code is referenced by any active printed-code
   correlation or multi-criteria workspace code link; users must unlink first.
2. Permanent delete requires the code to be soft-deleted first AND free of all
   correlations, code links, daily report activity blocks, and timeline plan items.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.master_data import Phase
from app.models.operations import (
    OpsActivityBlock,
    OpsAgency,
    OpsCause,
    OpsMarkRule,
    OpsOperation,
    OpsSubPhase,
)
from app.models import User
from app.services.audit import record as audit_record
from app.services.dependencies import dependency_counts
from app.services.operations import correlations as correlation_svc

MASTERS: dict[str, tuple[type[Any], str, str]] = {
    "operations": (OpsOperation, "operation_code", "ops_operation"),
    "sub-phases": (OpsSubPhase, "sub_phase_code", "ops_sub_phase"),
    "agencies": (OpsAgency, "agency_code", "ops_agency"),
    "causes": (OpsCause, "cause_code", "ops_cause"),
    "source-marks": (OpsMarkRule, "mark_code", "ops_mark_rule"),
}


def _sync_sub_phase_phase(db: Session, organization_id: str, row: OpsSubPhase) -> None:
    """Keep the phase code/name snapshot beside the sub-phase's Master Data phase."""
    phase = db.scalar(
        select(Phase).where(
            Phase.organization_id == organization_id,
            Phase.id == row.phase_id,
            Phase.is_deleted.is_(False),
        )
    )
    if phase is None:
        raise HTTPException(422, "The selected phase is not available in this workspace's Master Data.")
    row.phase_code_snapshot = (phase.phase_code or "")[:50]
    row.phase_name_snapshot = (phase.phase_name or "")[:150]


#: Import columns per Code Library list, with the alternate headings a user's
#: spreadsheet may carry. The template, the preview and the server all read this
#: one map, so a column the page offers is never rejected on the way in.
IMPORT_COLUMNS: dict[str, dict[str, Any]] = {
    "operations": {
        "required": ("operation_code", "operation_name"),
        "optional": (
            "family",
            "category",
            "default_responsible_party",
            "is_chargeable",
            "is_company_caused",
            "is_contractor_caused",
            "description",
            "sort_order",
            "is_active",
        ),
        "aliases": {
            "code": "operation_code",
            "operation": "operation_name",
            "name": "operation_name",
            "description": "description",
            "responsible party": "default_responsible_party",
            "chargeable": "is_chargeable",
            "company caused": "is_company_caused",
            "contractor caused": "is_contractor_caused",
            "order": "sort_order",
            "active": "is_active",
        },
    },
    "sub-phases": {
        # A sub-phase is a child of a Master Data phase, so the phase is part of
        # the identity of the row and must be importable — by code or by name.
        "required": ("sub_phase_code", "sub_phase_name", "phase_code"),
        "optional": ("description", "sort_order", "is_active"),
        "aliases": {
            "code": "sub_phase_code",
            "name": "sub_phase_name",
            "phase": "phase_code",
            "phase name": "phase_name",
            "phase code": "phase_code",
            "order": "sort_order",
            "active": "is_active",
        },
    },
    "causes": {
        "required": ("cause_code", "cause_name"),
        "optional": ("description", "sort_order", "is_active"),
        "aliases": {
            "code": "cause_code",
            "name": "cause_name",
            "order": "sort_order",
            "active": "is_active",
        },
    },
    "agencies": {
        "required": ("agency_code", "agency_name"),
        "optional": ("category", "description", "sort_order", "is_active"),
        "aliases": {
            "code": "agency_code",
            "name": "agency_name",
            "order": "sort_order",
            "active": "is_active",
        },
    },
    "source-marks": {
        "required": ("mark_code", "mark_name"),
        "optional": ("default_classification", "default_allocation", "description", "is_active"),
        "aliases": {
            "code": "mark_code",
            "name": "mark_name",
            "activity type": "default_classification",
            "classification": "default_classification",
            "allocation": "default_allocation",
            "active": "is_active",
        },
    },
}

_BOOL_TRUE = {"true", "yes", "y", "1", "active", "x"}
_BOOL_FALSE = {"false", "no", "n", "0", "inactive"}


def normalise_import_row(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    """Map a spreadsheet row onto the create schema for this list.

    Two rules keep an import predictable:

    * a heading the page prints is accepted under its own name, its spaced
      variant and the friendly alias (``Code`` → ``operation_code``);
    * a value is converted, not guessed — a boolean column reads yes/no, and a
      blank optional cell is dropped so the schema default applies rather than
      being overwritten with an empty string.
    """
    spec = IMPORT_COLUMNS[kind]
    aliases = spec["aliases"]
    allowed = set(spec["required"]) | set(spec["optional"]) | {"phase_name"}
    out: dict[str, Any] = {}
    for raw_key, raw_value in row.items():
        key = "_".join(str(raw_key).strip().lower().replace("-", " ").split())
        if key not in allowed:
            key = aliases.get(" ".join(str(raw_key).strip().lower().replace("_", " ").split()), key)
        if key not in allowed:
            continue
        value = raw_value
        if isinstance(value, str):
            value = value.strip()
        if value in ("", None):
            continue
        if key in ("is_chargeable", "is_company_caused", "is_contractor_caused", "is_active"):
            folded = str(value).strip().lower()
            if folded in _BOOL_TRUE:
                value = True
            elif folded in _BOOL_FALSE:
                value = False
            else:
                raise ValueError(f"'{raw_key}' must be yes or no, not '{value}'.")
        elif key == "sort_order":
            try:
                value = int(float(str(value)))
            except ValueError as exc:
                raise ValueError(f"'{raw_key}' must be a whole number, not '{value}'.") from exc
        out[key] = value
    return out


def resolve_import_phase(db: Session, organization_id: str, row: dict[str, Any]) -> str | None:
    """Find the Master Data phase a sub-phase row names, by code and then by name.

    The Code Library page shows the phase beside every sub-phase, so the import
    has to accept that column. A phase code is the identifier; a name is accepted
    only when it matches exactly one phase, because two phases may share a name
    and picking one would silently file the sub-phase under the wrong parent.
    """
    from app.models.master_data import Phase

    code = str(row.pop("phase_code", "") or "").strip()
    name = str(row.pop("phase_name", "") or "").strip()
    if not code and not name:
        raise ValueError("Add the Phase (its Master Data code) this sub-phase belongs to.")
    if code:
        phase = db.scalar(
            select(Phase).where(
                Phase.organization_id == organization_id,
                Phase.is_deleted.is_(False),
                func.upper(Phase.phase_code) == code.upper(),
            )
        )
        if phase is not None:
            return phase.id
        matches = list(
            db.scalars(
                select(Phase).where(
                    Phase.organization_id == organization_id,
                    Phase.is_deleted.is_(False),
                    func.upper(Phase.phase_name) == (name or code).upper(),
                )
            ).all()
        )
    else:
        matches = list(
            db.scalars(
                select(Phase).where(
                    Phase.organization_id == organization_id,
                    Phase.is_deleted.is_(False),
                    func.upper(Phase.phase_name) == name.upper(),
                )
            ).all()
        )
    if len(matches) == 1:
        return matches[0].id
    if len(matches) > 1:
        raise ValueError(f"Phase '{name or code}' matches more than one Master Data phase; use its phase code.")
    known = db.scalars(
        select(Phase.phase_code)
        .where(Phase.organization_id == organization_id, Phase.is_deleted.is_(False))
        .order_by(Phase.phase_code)
        .limit(12)
    ).all()
    hint = ", ".join(str(value) for value in known) if known else "none configured"
    raise ValueError(f"Phase '{name or code}' is not in Master Data (available: {hint}).")


def ensure_default_operations(db: Session, organization_id: str) -> int:
    """Seed the built-in downtime operations list for a workspace that has none.

    The tokens come from ``default_codes.py`` (the organisation's own printed
    trouble/NPT vocabulary), so a new workspace starts with the codes its reports
    actually print. Seeding never overwrites or re-creates a code a user deleted:
    it runs only while the workspace has no Operations row at all.
    """
    from app.domain.operations.default_codes import catalogue_rows

    existing = db.scalar(
        select(func.count(OpsOperation.id)).where(OpsOperation.organization_id == organization_id)
    )
    if existing:
        return 0
    rows = [row for row in catalogue_rows() if row["family"] == "Trouble / NPT"]
    for sort_order, row in enumerate(rows):
        db.add(
            OpsOperation(
                organization_id=organization_id,
                operation_code=row["code"],
                operation_name=(row["name"] or row["code"])[:150],
                family="trouble",
                category="other",
                description=(row.get("description") or "")[:500],
                sort_order=sort_order,
            )
        )
    db.commit()
    return len(rows)


def list_masters(db: Session, organization_id: str, kind: str, *, include_deleted: bool = False) -> list[Any]:
    model, code_field, _ = MASTERS[kind]
    stmt = (
        select(model)
        .where(model.organization_id == organization_id, model.is_deleted.is_(include_deleted))
        .order_by(model.sort_order.asc(), getattr(model, code_field).asc())
    )
    rows = list(db.scalars(stmt).all())
    counts = correlation_svc.code_usage_counts(db, organization_id).get(kind, {})
    for row in rows:
        row.correlation_count = counts.get(row.id, 0)
    if kind == "sub-phases":
        # A sub-phase belongs to a Master Data phase, so the list prints that
        # phase beside it and the page can filter without a second request.
        from app.models.master_data import Phase

        phase_ids = {row.phase_id for row in rows if row.phase_id}
        phases = {
            phase.id: phase
            for phase in db.scalars(
                select(Phase).where(Phase.organization_id == organization_id, Phase.id.in_(phase_ids))
            ).all()
        } if phase_ids else {}
        for row in rows:
            phase = phases.get(row.phase_id)
            row.phase_code_snapshot = getattr(phase, "phase_code", "") or ""
            row.phase_name_snapshot = getattr(phase, "phase_name", "") or ""
    return rows


def serialize_master(row: Any, *, correlation_count: int | None = None) -> dict[str, Any]:
    """Return a clean dict for a code library row including live ``correlation_count``."""
    payload = {col.name: getattr(row, col.name) for col in row.__table__.columns}
    payload["correlation_count"] = (
        correlation_count if correlation_count is not None else int(getattr(row, "correlation_count", 0))
    )
    return payload


def create_master(
    db: Session, organization_id: str, kind: str, data: Any, user: User, request: Request | None = None
) -> Any:
    model, code_field, entity_type = MASTERS[kind]
    payload = data.model_dump()
    code_val = payload[code_field]
    exists = db.scalar(
        select(model).where(model.organization_id == organization_id, getattr(model, code_field) == code_val)
    )
    if exists is not None:
        if exists.is_deleted:
            raise HTTPException(
                409,
                f"Code '{code_val}' is in Deleted entries; restore or permanently delete it before reusing it.",
            )
        raise HTTPException(409, f"{code_field} '{code_val}' already exists")
    row = model(organization_id=organization_id, **payload)
    if kind == "sub-phases":
        _sync_sub_phase_phase(db, organization_id, row)
    db.add(row)
    db.flush()
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="create",
        entity_type=entity_type,
        entity_id=row.id,
        entity_label=code_val,
        summary=f"Added {kind.replace('-', ' ')} {code_val}",
        request=request,
    )
    db.commit()
    db.refresh(row)
    row.correlation_count = 0
    return row


def update_master(
    db: Session,
    organization_id: str,
    kind: str,
    record_id: str,
    data: Any,
    user: User,
    request: Request | None = None,
) -> Any:
    model, code_field, entity_type = MASTERS[kind]
    row = db.scalar(
        select(model).where(
            model.organization_id == organization_id,
            model.id == record_id,
            model.is_deleted.is_(False),
        )
    )
    if not row:
        raise HTTPException(404, "Master record not found")
    payload = data.model_dump()
    new_code = payload[code_field]
    if new_code != getattr(row, code_field):
        clash = db.scalar(
            select(model).where(
                model.organization_id == organization_id,
                getattr(model, code_field) == new_code,
                model.id != record_id,
            )
        )
        if clash is not None:
            if clash.is_deleted:
                raise HTTPException(
                    409,
                    f"Code '{new_code}' is in Deleted entries; restore or permanently delete it first.",
                )
            raise HTTPException(409, f"{code_field} '{new_code}' already exists")
    for k, v in payload.items():
        setattr(row, k, v)
    if kind == "sub-phases":
        _sync_sub_phase_phase(db, organization_id, row)
    row.updated_at = datetime.now(UTC)
    correlation_svc.refresh_labels_for_code(db, organization_id, kind, row)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="update",
        entity_type=entity_type,
        entity_id=row.id,
        entity_label=new_code,
        summary=f"Updated {kind.replace('-', ' ')} {new_code}",
        request=request,
    )
    db.commit()
    db.refresh(row)
    row.correlation_count = correlation_svc.code_usage_counts(db, organization_id).get(kind, {}).get(row.id, 0)
    return row


def delete_masters(
    db: Session, organization_id: str, kind: str, ids: list[str], user: User, request: Request | None = None
) -> dict:
    """Soft-delete codes only after verifying no active correlation or code link references them."""
    model, code_field, entity_type = MASTERS[kind]
    rows = list(
        db.scalars(
            select(model).where(
                model.organization_id == organization_id,
                model.id.in_(ids),
                model.is_deleted.is_(False),
            )
        ).all()
    )
    for row in rows:
        code_val = getattr(row, code_field)
        active_refs = correlation_svc.active_code_references(db, organization_id, kind, row.id)
        if active_refs:
            preview = "; ".join(active_refs[:3])
            more = f" (+{len(active_refs) - 3} more)" if len(active_refs) > 3 else ""
            raise HTTPException(
                409,
                f"Cannot delete code '{code_val}': linked in {len(active_refs)} active rule(s) "
                f"({preview}{more}). Unlink or delete that correlation or code link in "
                "Code library -> Correlations first.",
            )

    stamp = datetime.now(UTC)
    for row in rows:
        code_val = getattr(row, code_field)
        row.is_deleted = True
        row.deleted_at = stamp
        row.updated_at = stamp
        audit_record(
            db,
            organization_id=organization_id,
            actor=user,
            action="delete",
            entity_type=entity_type,
            entity_id=row.id,
            entity_label=code_val,
            summary=f"Deleted {kind.replace('-', ' ')} {code_val}",
            request=request,
        )
    db.commit()
    return {"affected_count": len(rows)}


def restore_masters(
    db: Session, organization_id: str, kind: str, ids: list[str], user: User, request: Request | None = None
) -> dict:
    model, code_field, entity_type = MASTERS[kind]
    rows = list(
        db.scalars(
            select(model).where(
                model.organization_id == organization_id,
                model.id.in_(ids),
                model.is_deleted.is_(True),
            )
        ).all()
    )
    stamp = datetime.now(UTC)
    for row in rows:
        code_val = getattr(row, code_field)
        row.is_deleted = False
        row.deleted_at = None
        row.updated_at = stamp
        audit_record(
            db,
            organization_id=organization_id,
            actor=user,
            action="restore",
            entity_type=entity_type,
            entity_id=row.id,
            entity_label=code_val,
            summary=f"Restored {kind.replace('-', ' ')} {code_val}",
            request=request,
        )
    db.commit()
    return {"affected_count": len(rows)}


# A daily block keeps three codes as printed text instead of a foreign key, so the
# purge guard has to read them by name. Each name is only matched while the code is
# the one that name belongs to: the same text can be printed by a code from another
# library (a cause "06" beside an activity "06"), and a code that was deleted and
# re-created starts a new id whose history must not inherit the old one.
STRING_REFERENCE_COLUMNS = {
    "causes": (OpsActivityBlock.cause_code, ("cause_code",)),
    "source-marks": (OpsActivityBlock.source_mark, ("mark_code", "mark_name")),
}


def _string_block_reference_count(db: Session, organization_id: str, kind: str, row: Any) -> int:
    """Count daily report blocks that store this code by string rather than foreign key."""
    spec = STRING_REFERENCE_COLUMNS.get(kind)
    if spec is None:
        return 0
    column, fields = spec
    values = {
        str(getattr(row, name)).strip().upper()
        for name in fields
        if getattr(row, name, None)
    }
    if not values:
        return 0
    return int(
        db.scalar(
            select(func.count())
            .select_from(OpsActivityBlock)
            .where(
                OpsActivityBlock.organization_id == organization_id,
                func.upper(column).in_(values),
            )
        )
        or 0
    )


def purge_masters(
    db: Session, organization_id: str, kind: str, ids: list[str], user: User, request: Request | None = None
) -> dict:
    """Permanently delete soft-deleted codes that have zero correlation or report references."""
    model, code_field, entity_type = MASTERS[kind]
    rows = list(
        db.scalars(
            select(model).where(
                model.organization_id == organization_id,
                model.id.in_(ids),
            )
        ).all()
    )
    if not rows:
        return {"affected_count": 0}
    if any(not row.is_deleted for row in rows):
        raise HTTPException(409, "Delete a code before removing it permanently.")

    for row in rows:
        code_val = getattr(row, code_field)
        active_corr, deleted_corr, active_links, deleted_links = correlation_svc.all_code_references(
            db, organization_id, kind, row.id
        )
        corr_parts: list[str] = []
        if active_corr:
            corr_parts.append(f"{active_corr} active correlation(s)")
        if deleted_corr:
            corr_parts.append(f"{deleted_corr} deleted correlation(s)")
        if active_links:
            corr_parts.append(f"{active_links} active multi-criteria code link(s)")
        if deleted_links:
            corr_parts.append(f"{deleted_links} deleted multi-criteria code link(s)")
        if corr_parts:
            raise HTTPException(
                409,
                f"Cannot permanently delete code '{code_val}': referenced by {', '.join(corr_parts)}. "
                "Remove those rules from Code library -> Correlations (including Deleted entries) first.",
            )

        deps = dependency_counts(db, row, organization_id)
        str_blocks = _string_block_reference_count(db, organization_id, kind, row)
        if str_blocks:
            block_label = "daily operations report block(s)"
            deps[block_label] = deps.get(block_label, 0) + str_blocks
        if deps:
            summary = ", ".join(f"{count} {label}" for label, count in deps.items())
            raise HTTPException(
                409,
                f"Cannot permanently delete code '{code_val}': still referenced by {summary}. "
                "Keep it in Deleted entries or deactivate it so historical records remain intact.",
            )

    for row in rows:
        code_val = getattr(row, code_field)
        audit_record(
            db,
            organization_id=organization_id,
            actor=user,
            action="permanent_delete",
            entity_type=entity_type,
            entity_id=row.id,
            entity_label=code_val,
            summary=f"Permanently deleted {kind.replace('-', ' ')} {code_val}",
            request=request,
        )
        db.delete(row)
        try:
            # Flush per code so a database that still holds a reference names the
            # exact code that could not go, instead of failing the whole batch blind.
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                409,
                f"Cannot permanently delete code '{code_val}': operational records still reference it. "
                "Keep it in Deleted entries so history stays intact.",
            ) from exc
    db.commit()
    return {"affected_count": len(rows)}
