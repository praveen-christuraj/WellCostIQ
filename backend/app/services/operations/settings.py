"""Ops settings service."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models.operations import OpsSettings
from app.services.audit import record as audit_record


def get_or_create(db: Session, organization_id: str) -> OpsSettings:
    row = db.scalar(select(OpsSettings).where(OpsSettings.organization_id == organization_id))
    if row:
        return row
    row = OpsSettings(organization_id=organization_id)
    db.add(row)
    db.flush()
    # Do not commit — caller may commit
    return row


def get_settings(db: Session, organization_id: str) -> OpsSettings:
    return get_or_create(db, organization_id)


def update_settings(db: Session, organization_id: str, data, user: User, request=None) -> OpsSettings:
    row = get_or_create(db, organization_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    row.updated_by = user.email or ""
    audit_record(db, organization_id=organization_id, actor=user, action="update", entity_type="ops_settings", entity_id=row.id, entity_label="Operations settings", summary="Updated operations settings", request=request)
    db.commit()
    db.refresh(row)
    return row
