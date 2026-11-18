"""The shared identity boundary. No costing figures or costing permissions here."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operations import OpsDocumentType
from app.models.rig_well import Rig, Well

DEFAULT_TYPES = ("DDR", "DCR", "DMR", "RMR", "Other")


def document_types(db, org):
    return list(
        db.scalars(
            select(OpsDocumentType.code)
            .where(OpsDocumentType.organization_id == org)
            .order_by(OpsDocumentType.sort_order)
        )
    ) or list(DEFAULT_TYPES)


def available(well, scope):
    return not well.scope_is_deleted(scope) and well.scope_value(scope, "config_status") in (
        "configured",
        "completed",
    )


def resolve(db: Session, org: str, well_id: str, scope: str, rig_id: str | None = None):
    well = db.scalar(
        select(Well).where(Well.organization_id == org, Well.id == well_id, Well.is_deleted.is_(False))
    )
    if not well:
        raise HTTPException(404, "Well not found")
    if scope not in ("drilling", "completion") or not available(well, scope):
        raise HTTPException(422, "Configure this well scope in Rig & Well before starting operations.")
    if rig_id and rig_id != well.rig_id:
        raise HTTPException(422, "The selected rig does not own this well.")
    rig = db.scalar(select(Rig).where(Rig.organization_id == org, Rig.id == well.rig_id, Rig.is_deleted.is_(False)))
    if not rig:
        raise HTTPException(404, "Rig not found")
    return well, rig


def reference(db, org):
    rigs = db.scalars(
        select(Rig).where(Rig.organization_id == org, Rig.is_deleted.is_(False)).order_by(Rig.rig_code)
    ).all()
    wells = db.scalars(
        select(Well)
        .where(Well.organization_id == org, Well.is_deleted.is_(False), Well.rig_id.in_([r.id for r in rigs]))
        .order_by(Well.well_code)
    ).all()
    return {
        "rigs": [
            {
                "id": r.id,
                "rig_code": r.rig_code,
                "rig_name": r.rig_name,
                "display_name": f"{r.rig_code} — {r.rig_name}",
            }
            for r in rigs
        ],
        "wells": [
            {
                "id": w.id,
                "rig_id": w.rig_id,
                "block_id": w.block_id,
                "well_code": w.well_code,
                "well_name": w.well_name,
                "display_name": f"{w.well_code} — {w.well_name}",
                "drilling_available": available(w, "drilling"),
                "completion_available": available(w, "completion"),
            }
            for w in wells
            if any(available(w, s) for s in ("drilling", "completion"))
        ],
        "document_types": document_types(db, org),
    }
