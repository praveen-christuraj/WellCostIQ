"""Plan versions service."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models.operations import OpsPlanItem, OpsPlanVersion
from app.models.rig_well import Well
from app.services.audit import record as audit_record


def list_plans(db: Session, organization_id: str, well_id: str | None = None, scope: str | None = None):
    q = select(OpsPlanVersion).where(OpsPlanVersion.organization_id == organization_id, OpsPlanVersion.is_deleted.is_(False))
    if well_id:
        q = q.where(OpsPlanVersion.well_id == well_id)
    if scope:
        q = q.where(OpsPlanVersion.scope == scope)
    rows = db.scalars(q.order_by(OpsPlanVersion.version_no.desc())).all()
    for r in rows:
        items = db.scalars(select(OpsPlanItem).where(OpsPlanItem.plan_version_id == r.id).order_by(OpsPlanItem.sequence_no)).all()
        r._items = items  # type: ignore
        well = db.get(Well, r.well_id)
        r._well_code = well.well_code if well else ""  # type: ignore
        r._well_name = well.well_name if well else ""  # type: ignore
    return rows


def get_plan(db: Session, organization_id: str, plan_id: str):
    row = db.scalar(select(OpsPlanVersion).where(OpsPlanVersion.id == plan_id, OpsPlanVersion.organization_id == organization_id, OpsPlanVersion.is_deleted.is_(False)))
    if not row:
        raise HTTPException(404, "Plan not found")
    items = db.scalars(select(OpsPlanItem).where(OpsPlanItem.plan_version_id == row.id).order_by(OpsPlanItem.sequence_no)).all()
    row._items = items  # type: ignore
    well = db.get(Well, row.well_id)
    row._well_code = well.well_code if well else ""  # type: ignore
    row._well_name = well.well_name if well else ""  # type: ignore
    return row


def create_plan(db: Session, organization_id: str, data, user: User, request=None):
    well = db.scalar(select(Well).where(Well.id == data.well_id, Well.organization_id == organization_id, Well.is_deleted.is_(False)))
    if not well:
        raise HTTPException(404, "Well not found")
    # Version increment
    max_ver = db.scalar(select(OpsPlanVersion.version_no).where(OpsPlanVersion.organization_id == organization_id, OpsPlanVersion.well_id == data.well_id, OpsPlanVersion.scope == data.scope).order_by(OpsPlanVersion.version_no.desc()).limit(1))
    next_ver = (max_ver + 1) if max_ver else 1
    row = OpsPlanVersion(
        organization_id=organization_id,
        well_id=data.well_id,
        scope=data.scope,
        version_no=next_ver,
        label=data.label,
        basis=data.basis,
        status="draft",
        planned_start_at=data.planned_start_at,
        planned_days=data.planned_days,
        notes=data.notes or "",
        created_by=user.email or "",
        updated_by=user.email or "",
    )
    db.add(row)
    db.flush()
    audit_record(db, organization_id=organization_id, actor=user, action="create", entity_type="ops_plan", entity_id=row.id, entity_label=data.label, summary="Created plan version", request=request)
    db.commit()
    db.refresh(row)
    return get_plan(db, organization_id, row.id)


def add_plan_item(db: Session, organization_id: str, plan_id: str, data, user: User, request=None):
    plan = get_plan(db, organization_id, plan_id)
    if plan.status == "active":
        raise HTTPException(409, "Cannot edit an active plan — create a new version")
    item = OpsPlanItem(
        organization_id=organization_id,
        plan_version_id=plan.id,
        sequence_no=data.sequence_no,
        hole_section_id=data.hole_section_id,
        phase_id=data.phase_id,
        operation_code_id=data.operation_code_id,
        description=data.description,
        target_depth_m=data.target_depth_m,
        delta_depth_m=data.delta_depth_m,
        planned_hours=data.planned_hours,
        cum_planned_days=data.cum_planned_days,
        rop_assumption_m_per_hr=data.rop_assumption_m_per_hr,
        trip_speed_m_per_hr=data.trip_speed_m_per_hr,
        contingency_hours=data.contingency_hours,
        is_critical_path=data.is_critical_path,
        notes=data.notes,
    )
    db.add(item)
    db.flush()
    # Update plan planned_days as sum
    items = db.scalars(select(OpsPlanItem).where(OpsPlanItem.plan_version_id == plan.id)).all()
    total_hours = sum(float(i.planned_hours) for i in items) if items else 0
    plan.planned_days = Decimal(str(round(total_hours / 24, 2))) if total_hours else None
    # Recompute cum_planned_days sequentially if not provided
    cum = 0.0
    for it in sorted(items, key=lambda x: x.sequence_no):
        hrs = float(it.planned_hours) if it.planned_hours else 0
        cum += hrs / 24
        if it.cum_planned_days is None:
            it.cum_planned_days = Decimal(str(round(cum, 2)))
    db.commit()
    return get_plan(db, organization_id, plan_id)


def activate_plan(db: Session, organization_id: str, plan_id: str, user: User, request=None):
    plan = get_plan(db, organization_id, plan_id)
    # Deactivate other active plans for same well/scope
    others = db.scalars(select(OpsPlanVersion).where(OpsPlanVersion.organization_id == organization_id, OpsPlanVersion.well_id == plan.well_id, OpsPlanVersion.scope == plan.scope, OpsPlanVersion.status == "active", OpsPlanVersion.id != plan.id)).all()
    for o in others:
        o.status = "superseded"
    plan.status = "active"
    audit_record(db, organization_id=organization_id, actor=user, action="activate", entity_type="ops_plan", entity_id=plan.id, entity_label=plan.label, summary="Activated plan", request=request)
    db.commit()
    return plan


def delete_plan(db: Session, organization_id: str, plan_id: str, user: User, request=None):
    plan = get_plan(db, organization_id, plan_id)
    if plan.status == "active":
        raise HTTPException(409, "Cannot delete an active plan")
    plan.is_deleted = True
    plan.deleted_at = datetime.now(timezone.utc)
    audit_record(db, organization_id=organization_id, actor=user, action="delete", entity_type="ops_plan", entity_id=plan.id, entity_label=plan.label, summary="Deleted plan", request=request)
    db.commit()
    return {"affected_count": 1}
