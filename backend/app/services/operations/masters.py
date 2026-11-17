"""Masters service for operations code library."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models.operations import OpsOperationCode, OpsActivityCode, OpsNptCode, OpsAgency, OpsCause
from app.services.audit import record as audit_record


def _actor(user: User) -> str:
    return user.email or user.full_name or str(user.id)


# Generic CRUD helpers
MAP = {
    "operation-codes": (OpsOperationCode, "operation_code", "ops_operation_code"),
    "activity-codes": (OpsActivityCode, "activity_code", "ops_activity_code"),
    "npt-codes": (OpsNptCode, "npt_code", "ops_npt_code"),
    "agencies": (OpsAgency, "agency_code", "ops_agency"),
    "causes": (OpsCause, "cause_code", "ops_cause"),
}


def list_masters(db: Session, organization_id: str, kind: str, include_deleted: bool = False):
    model, _, _ = MAP[kind]
    q = select(model).where(model.organization_id == organization_id)  # type: ignore
    if not include_deleted:
        q = q.where(model.is_deleted.is_(False))  # type: ignore
    rows = db.scalars(q.order_by(model.sort_order if hasattr(model, "sort_order") else model.id)).all()  # type: ignore
    return rows


def create_master(db: Session, organization_id: str, kind: str, data, user: User, request=None):
    model, code_field, entity_type = MAP[kind]
    code_val = getattr(data, code_field, "")
    # Check duplicate
    exists = db.scalar(select(model).where(model.organization_id == organization_id, getattr(model, code_field) == code_val, model.is_deleted.is_(False)))  # type: ignore
    if exists:
        raise HTTPException(409, f"{code_field} '{code_val}' already exists")
    row = model(organization_id=organization_id, **data.model_dump())  # type: ignore
    db.add(row)
    db.flush()
    audit_record(db, organization_id=organization_id, actor=user, action="create", entity_type=entity_type, entity_id=row.id, entity_label=code_val, summary=f"Created {kind} {code_val}", request=request)
    db.commit()
    db.refresh(row)
    return row


def update_master(db: Session, organization_id: str, kind: str, record_id: str, data, user: User, request=None):
    model, code_field, entity_type = MAP[kind]
    row = db.scalar(select(model).where(model.id == record_id, model.organization_id == organization_id, model.is_deleted.is_(False)))  # type: ignore
    if not row:
        raise HTTPException(404, f"{kind} not found")
    # If code changed, check duplicate
    new_code = getattr(data, code_field, None)
    if new_code and new_code != getattr(row, code_field):
        dup = db.scalar(select(model).where(model.organization_id == organization_id, getattr(model, code_field) == new_code, model.is_deleted.is_(False)))  # type: ignore
        if dup:
            raise HTTPException(409, f"{code_field} '{new_code}' already exists")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    audit_record(db, organization_id=organization_id, actor=user, action="update", entity_type=entity_type, entity_id=row.id, entity_label=getattr(row, code_field), summary=f"Updated {kind}", request=request)
    db.commit()
    db.refresh(row)
    return row


def delete_masters(db: Session, organization_id: str, kind: str, ids: list[str], user: User, request=None):
    model, code_field, entity_type = MAP[kind]
    rows = db.scalars(select(model).where(model.organization_id == organization_id, model.id.in_(ids))).all()  # type: ignore
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more records not found")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    affected = 0
    for r in rows:
        if not r.is_deleted:
            r.is_deleted = True
            r.deleted_at = now
            affected += 1
    audit_record(db, organization_id=organization_id, actor=user, action="delete", entity_type=entity_type, entity_id=None, entity_label=f"{affected} {kind}", summary=f"Deleted {affected} {kind}", request=request)
    db.commit()
    return {"affected_count": affected}


def restore_masters(db: Session, organization_id: str, kind: str, ids: list[str], user: User, request=None):
    model, _, entity_type = MAP[kind]
    rows = db.scalars(select(model).where(model.organization_id == organization_id, model.id.in_(ids))).all()  # type: ignore
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more records not found")
    affected = 0
    for r in rows:
        if r.is_deleted:
            r.is_deleted = False
            r.deleted_at = None
            affected += 1
    audit_record(db, organization_id=organization_id, actor=user, action="restore", entity_type=entity_type, entity_id=None, entity_label=f"{affected} {kind}", summary=f"Restored {affected} {kind}", request=request)
    db.commit()
    return {"affected_count": affected}
