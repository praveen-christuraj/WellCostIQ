"""Plan versions service."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.precision import rounded
from app.domain.operations.durations import utc
from app.models import User
from app.models.operations import OpsDailyReport, OpsPlanItem, OpsPlanSurveyStation, OpsPlanVersion
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


def get_plan(db: Session, organization_id: str, plan_id: str, *, lock=False, include_deleted=False):
    q = select(OpsPlanVersion).where(
        OpsPlanVersion.id == plan_id,
        OpsPlanVersion.organization_id == organization_id,
    )
    if not include_deleted:
        q = q.where(OpsPlanVersion.is_deleted.is_(False))
    row = db.scalar(q.with_for_update() if lock else q)
    if not row:
        raise HTTPException(404, "Plan not found")
    items = db.scalars(
        select(OpsPlanItem)
        .where(OpsPlanItem.organization_id == organization_id, OpsPlanItem.plan_version_id == row.id)
        .order_by(OpsPlanItem.sequence_no)
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
    from app.models.operations import OpsOperation

    resolve(db, org, plan.well_id, plan.scope)
    for data in items:
        for model, ident in [
            (HoleSection, data.hole_section_id),
            (Phase, data.phase_id),
            (OpsOperation, data.operation_id),
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
        it.cum_planned_days = rounded(hours / 24)
    plan.planned_days = rounded(hours / 24)
    plan.updated_at = datetime.now(UTC)
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


def update_plan(db: Session, organization_id: str, plan_id: str, data, user: User, request=None):
    plan = get_plan(db, organization_id, plan_id, lock=True)
    if plan.status != "draft":
        raise HTTPException(409, "Only a draft timeline can be edited. Reopen it to draft first.")
    resolve(db, organization_id, plan.well_id, plan.scope)
    fields = data.model_fields_set
    if "label" in fields and data.label is not None:
        plan.label = data.label
    if "basis" in fields and data.basis is not None:
        plan.basis = data.basis
    if "planned_start_at" in fields:
        plan.planned_start_at = utc(data.planned_start_at) if data.planned_start_at else None
    if "notes" in fields and data.notes is not None:
        plan.notes = data.notes
    plan.updated_by = user.email or ""
    plan.updated_at = datetime.now(UTC)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="update",
        entity_type="ops_plan",
        entity_id=plan.id,
        entity_label=plan.label,
        summary="Updated draft timeline metadata",
        request=request,
    )
    db.commit()
    return get_plan(db, organization_id, plan.id)


def reopen_plan(db: Session, organization_id: str, plan_id: str, remarks: str, user: User, request=None):
    reason = (remarks or "").strip()
    if len(reason) < 3:
        raise HTTPException(422, "Provide remarks (at least 3 characters) explaining why the timeline is reopened.")
    plan = get_plan(db, organization_id, plan_id, lock=True)
    if plan.status not in ("active", "superseded"):
        raise HTTPException(409, "Only active or superseded timelines can be reopened to draft.")
    resolve(db, organization_id, plan.well_id, plan.scope)
    prior_status = plan.status
    now = datetime.now(UTC)
    actor = user.full_name or user.email or ""
    plan.status = "draft"
    plan.reopened_at = now
    plan.reopened_by = actor[:255]
    plan.reopen_reason = reason[:500]
    plan.updated_by = user.email or ""
    plan.updated_at = now
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="reopen",
        entity_type="ops_plan",
        entity_id=plan.id,
        entity_label=plan.label,
        summary=f"Reopened {prior_status} timeline as draft: {reason[:200]}",
        request=request,
    )
    db.commit()
    return get_plan(db, organization_id, plan.id)


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
    plan.approved_by = (user.full_name or user.email or "")[:255]
    plan.updated_by = user.email or ""
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


def purge_plans(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    """Permanently remove deleted draft timelines.

    A permanent delete is the only operation in the module that destroys data, so
    it refuses rather than cascades:

    * only a soft-deleted version may be purged (a live version is never one click
      away from disappearing);
    * a version a daily report names as its baseline is refused, because purging
      it would silently strip the plan reference from an approved report;
    * items are removed with the version, which is what "delete this timeline"
      means once the version itself is gone.
    """
    rows = db.scalars(
        select(OpsPlanVersion)
        .where(OpsPlanVersion.organization_id == organization_id, OpsPlanVersion.id.in_(ids))
        .with_for_update()
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more plans not found")
    referenced = {
        row.baseline_plan_id
        for row in db.scalars(
            select(OpsDailyReport).where(
                OpsDailyReport.organization_id == organization_id,
                OpsDailyReport.baseline_plan_id.in_([row.id for row in rows]),
            )
        ).all()
        if row.baseline_plan_id
    }
    blocked = [row for row in rows if not row.is_deleted]
    if blocked:
        raise HTTPException(409, "Only deleted timelines can be permanently removed.")
    blocked = [row for row in rows if row.id in referenced]
    if blocked:
        raise HTTPException(
            409,
            "A daily report still uses this timeline as its baseline. Keep it, or remove the reference first: "
            + ", ".join(sorted(row.label or row.id for row in blocked)),
        )
    for row in rows:
        db.execute(delete(OpsPlanItem).where(OpsPlanItem.plan_version_id == row.id))
        db.execute(delete(OpsPlanSurveyStation).where(
            OpsPlanSurveyStation.organization_id == organization_id, OpsPlanSurveyStation.plan_version_id == row.id,
        ))
        db.delete(row)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="permanent-delete",
        entity_type="ops_plan",
        entity_id=None,
        entity_label=f"{len(rows)} timeline(s)",
        summary=f"Permanently removed {len(rows)} deleted timeline(s) and their programme rows",
        request=request,
    )
    db.commit()
    return {"affected_count": len(rows)}


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
