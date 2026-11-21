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


#: Settings that change what a lead or a lag *means* for this workspace. A change to
#: one is named in the audit trail, because a reader comparing two months needs to
#: know the rule underneath the numbers changed between them.
SEQUENCE_SETTINGS = (
    "sequence_uncoded_policy",
    "sequence_npt_policy",
    "sequence_skipped_credit",
    "sequence_auto_close_tolerance_pct",
    "sequence_auto_close",
    "sequence_require_code_on_submit",
    "sequence_current_run_only",
)


def update_settings(db: Session, organization_id: str, data, user: User, request=None) -> OpsSettings:
    row = get_or_create(db, organization_id)
    values = data.model_dump(exclude_unset=True, exclude={"document_types"})
    changed_sequence = [
        f"{key.replace('sequence_', '')}: {getattr(row, key, None)!r} → {value!r}"
        for key, value in values.items()
        if key in SEQUENCE_SETTINGS and getattr(row, key, None) != value
    ]
    for key, value in values.items():
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
        summary=(
            "Updated operations settings"
            + (" — sequence policy changed: " + "; ".join(changed_sequence) if changed_sequence else "")
        ),
        request=request,
    )
    db.commit()
    db.refresh(row)
    return get_settings(db, organization_id)
