"""Ops settings service."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import User
from app.models.operations import OpsDocumentType, OpsSettings
from app.services.audit import record as audit_record
from app.services.operations.scope import document_types


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
    row = get_or_create(db, organization_id)
    row.document_types = document_types(db, organization_id)
    return row


def update_settings(db: Session, organization_id: str, data, user: User, request=None) -> OpsSettings:
    row = get_or_create(db, organization_id)
    for key, value in data.model_dump(exclude_unset=True, exclude={"document_types"}).items():
        setattr(row, key, value)
    if data.document_types is not None:
        db.execute(delete(OpsDocumentType).where(OpsDocumentType.organization_id == organization_id))
        db.add_all(
            [
                OpsDocumentType(organization_id=organization_id, code=code, sort_order=i)
                for i, code in enumerate(data.document_types)
            ]
        )
    row.updated_by = user.email or ""
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="update",
        entity_type="ops_settings",
        entity_id=row.id,
        entity_label="Operations settings",
        summary="Updated operations settings",
        request=request,
    )
    db.commit()
    db.refresh(row)
    return get_settings(db, organization_id)
