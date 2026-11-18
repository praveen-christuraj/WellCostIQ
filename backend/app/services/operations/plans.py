"""Plan versions service."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.operations.durations import utc
from app.models import User
from app.models.operations import OpsPlanItem, OpsPlanVersion
from app.models.rig_well import Well
from app.services.audit import record as audit_record
from app.services.operations.scope import resolve


def active_plan(db, org, well_id, scope):
    return db.scalar(
        select(OpsPlanVersion).where(
            OpsPlanVersion.organization_id == org,
            OpsPlanVersion.well_id == well_id,
            OpsPlanVersion.scope == scope,
            OpsPlanVersion.status == "active",
            OpsPlanVersion.is_deleted.is_(False),
        )
    )


def list_plans(
    db: Session, organization_id: str, well_id: str | None = None, scope: str | None = None, deleted=False
):
    q = select(OpsPlanVersion).where(
        OpsPlanVersion.organization_id == organization_id, OpsPlanVersion.is_deleted.is_(deleted)
    )
    if well_id:
        q = q.where(OpsPlanVersion.well_id == well_id)
    if scope:
        q = q.where(OpsPlanVersion.scope == scope)
    rows = db.scalars(q.order_by(OpsPlanVersion.version_no.desc())).all()
    for r in rows:
        items = db.scalars(
            select(OpsPlanItem).where(OpsPlanItem.plan_version_id == r.id).order_by(OpsPlanItem.sequence_no)
        ).all()
        r._items = items  # type: ignore
        well = db.get(Well, r.well_id)
        r._well_code = well.well_code if well else ""  # type: ignore
        r._well_name = well.well_name if well else ""  # type: ignore
    return rows


def get_plan(db: Session, organization_id: str, plan_id: str, *, lock=False):
    q = select(OpsPlanVersion).where(
        OpsPlanVersion.id == plan_id,
        OpsPlanVersion.organization_id == organization_id,
        OpsPlanVersion.is_deleted.is_(False),
    )
    row = db.scalar(q.with_for_update() if lock else q)
    if not row:
        raise HTTPException(404, "Plan not found")
    items = db.scalars(
        select(OpsPlanItem).where(OpsPlanItem.plan_version_id == row.id).order_by(OpsPlanItem.sequence_no)
    ).all()
    row._items = items  # type: ignore
    well = db.get(Well, row.well_id)
    row._well_code = well.well_code if well else ""  # type: ignore
    row._well_name = well.well_name if well else ""  # type: ignore
    return row


def create_plan(db: Session, organization_id: str, data, user: User, request=None):
    _well, _ = resolve(db, organization_id, data.well_id, data.scope)
    # Version increment
    max_ver = db.scalar(
        select(OpsPlanVersion.version_no)
        .where(
            OpsPlanVersion.organization_id == organization_id,
            OpsPlanVersion.well_id == data.well_id,
            OpsPlanVersion.scope == data.scope,
        )
        .order_by(OpsPlanVersion.version_no.desc())
        .limit(1)
    )
    next_ver = (max_ver + 1) if max_ver else 1
    row = OpsPlanVersion(
        organization_id=organization_id,
        well_id=data.well_id,
        scope=data.scope,
        version_no=next_ver,
        label=data.label,
        basis=data.basis,
        status="draft",
        planned_start_at=utc(data.planned_start_at) if data.planned_start_at else None,
        planned_days=None,
        notes=data.notes or "",
        created_by=user.email or "",
        updated_by=user.email or "",
    )
    db.add(row)
    db.flush()
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="create",
        entity_type="ops_plan",
        entity_id=row.id,
        entity_label=data.label,
        summary="Created plan version",
        request=request,
    )
    db.commit()
    db.refresh(row)
    return get_plan(db, organization_id, row.id)


def add_plan_item(db: Session, organization_id: str, plan_id: str, data, user: User, request=None):
    plan = get_plan(db, organization_id, plan_id, lock=True)
    if plan.status != "draft":
        raise HTTPException(409, "Only a draft timeline can be edited.")
    if any(i.sequence_no == data.sequence_no for i in plan._items):
        raise HTTPException(409, "Duplicate timeline sequence.")
    _write_items(db, organization_id, plan, [data], list(plan._items), user, request)
    return get_plan(db, organization_id, plan_id)


def replace_items(db, org, plan_id, items, user, request):
    plan = get_plan(db, org, plan_id, lock=True)
    if plan.status != "draft":
        raise HTTPException(409, "Only a draft timeline can be edited.")
    db.execute(
        delete(OpsPlanItem).where(OpsPlanItem.organization_id == org, OpsPlanItem.plan_version_id == plan.id)
    )
    for i, item in enumerate(items, 1):
        item.sequence_no = i
    _write_items(db, org, plan, items, [], user, request)


def _write_items(db, org, plan, items, existing, user, request):
    from app.models.master_data import HoleSection, Phase
    from app.models.operations import OpsOperationCode

    resolve(db, org, plan.well_id, plan.scope)
    for data in items:
        for model, ident in [
            (HoleSection, data.hole_section_id),
            (Phase, data.phase_id),
            (OpsOperationCode, data.operation_code_id),
        ]:
            if ident and not db.scalar(
                select(model.id).where(model.id == ident, model.organization_id == org, model.is_deleted.is_(False))
            ):
                raise HTTPException(422, "Plan item reference not found in this workspace.")
        item = OpsPlanItem(organization_id=org, plan_version_id=plan.id, **data.model_dump())
        db.add(item)
        existing.append(item)
    hours = Decimal(0)
    for it in sorted(existing, key=lambda i: i.sequence_no):
        hours += it.planned_hours
        it.cum_planned_days = hours / 24
    plan.planned_days = hours / 24
    plan.updated_by = user.email
    audit_record(
        db,
        organization_id=org,
        actor=user,
        action="update",
        entity_type="ops_plan",
        entity_id=plan.id,
        entity_label=plan.label,
        summary=f"Saved {len(existing)} timeline items ({hours} planned hours)",
        request=request,
    )
    db.commit()


def activate_plan(db: Session, organization_id: str, plan_id: str, user: User, request=None):
    candidate = get_plan(db, organization_id, plan_id)
    db.execute(
        select(OpsPlanVersion.id)
        .where(
            OpsPlanVersion.organization_id == organization_id,
            OpsPlanVersion.well_id == candidate.well_id,
            OpsPlanVersion.scope == candidate.scope,
        )
        .order_by(OpsPlanVersion.id)
        .with_for_update()
    ).all()
    db.refresh(candidate)
    plan = get_plan(db, organization_id, plan_id)
    if plan.status != "draft" or not plan._items or not plan.planned_days:
        raise HTTPException(409, "Activate a reviewed draft timeline with positive planned hours.")
    resolve(db, organization_id, plan.well_id, plan.scope)
    # Deactivate other active plans for same well/scope
    others = db.scalars(
        select(OpsPlanVersion).where(
            OpsPlanVersion.organization_id == organization_id,
            OpsPlanVersion.well_id == plan.well_id,
            OpsPlanVersion.scope == plan.scope,
            OpsPlanVersion.status == "active",
            OpsPlanVersion.id != plan.id,
        )
    ).all()
    for o in others:
        o.status = "superseded"
    plan.status = "active"
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="activate",
        entity_type="ops_plan",
        entity_id=plan.id,
        entity_label=plan.label,
        summary="Activated plan",
        request=request,
    )
    db.commit()
    return plan


def delete_plan(db: Session, organization_id: str, plan_id: str, user: User, request=None):
    plan = get_plan(db, organization_id, plan_id, lock=True)
    if plan.status != "draft":
        raise HTTPException(409, "Only draft versions can be removed. Reviewed baselines are retained.")
    plan.is_deleted = True
    plan.deleted_at = datetime.now(UTC)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="delete",
        entity_type="ops_plan",
        entity_id=plan.id,
        entity_label=plan.label,
        summary="Deleted plan",
        request=request,
    )
    db.commit()
    return {"affected_count": 1}


def restore_plan(db, org, plan_id, user, request):
    plan = db.scalar(
        select(OpsPlanVersion)
        .where(
            OpsPlanVersion.organization_id == org, OpsPlanVersion.id == plan_id, OpsPlanVersion.is_deleted.is_(True)
        )
        .with_for_update()
    )
    if not plan:
        raise HTTPException(404, "Deleted plan not found")
    plan.is_deleted = False
    plan.deleted_at = None
    plan.status = "draft"
    audit_record(
        db,
        organization_id=org,
        actor=user,
        action="restore",
        entity_type="ops_plan",
        entity_id=plan.id,
        entity_label=plan.label,
        summary="Restored draft timeline",
        request=request,
    )
    db.commit()
    return {"affected_count": 1}
