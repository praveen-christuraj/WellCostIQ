"""Document vault service."""

import hashlib
from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.models import User
from app.models.operations import (
    OpsDailyReport,
    OpsDocument,
    OpsExtractionJob,
    OpsSettings,
)
from app.services.audit import record as audit_record
from app.services.operations.scope import document_types, resolve


def list_documents(
    db: Session,
    organization_id: str,
    well_id: str | None = None,
    scope: str | None = None,
    document_type: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_deleted: bool = False,
):
    q = (
        select(OpsDocument)
        .options(defer(OpsDocument.content))
        .where(OpsDocument.organization_id == organization_id)
    )
    if not include_deleted:
        q = q.where(OpsDocument.is_deleted.is_(False))
    if well_id:
        q = q.where(OpsDocument.well_id == well_id)
    if scope:
        q = q.where(OpsDocument.scope == scope)
    if document_type:
        q = q.where(OpsDocument.document_type == document_type)
    if status:
        q = q.where(OpsDocument.status == status)
    if date_from:
        q = q.where(OpsDocument.document_date >= date_from)
    if date_to:
        q = q.where(OpsDocument.document_date <= date_to)
    rows = db.scalars(q.order_by(OpsDocument.created_at.desc())).all()
    return rows


def upload_limit(db, org):
    mb = db.scalar(select(OpsSettings.document_max_mb).where(OpsSettings.organization_id == org))
    return (mb or 25) * 1024**2


def upload_document(
    db: Session,
    organization_id: str,
    file_bytes: bytes,
    file_name: str,
    content_type: str,
    well_id: str | None,
    rig_id: str | None,
    scope: str,
    document_type: str,
    document_date: date | None,
    report_no_text: str,
    notes: str,
    user: User,
    request=None,
) -> tuple[OpsDocument, bool, str | None]:
    limit = upload_limit(db, organization_id)
    if len(file_bytes) > limit:
        raise HTTPException(413, f"File too large. Max {limit // (1024 * 1024)} MB.")
    if len(file_bytes) == 0:
        raise HTTPException(422, "Empty file.")

    if len(file_name) > 255 or any(ord(c) < 32 for c in file_name):
        raise HTTPException(422, "Choose a filename of 255 characters or less without control characters.")
    content_type = content_type[:100]
    # Basic extension check
    lower_name = file_name.lower()
    if not any(lower_name.endswith(ext) for ext in (".pdf", ".xlsx", ".xls", ".xlsm", ".csv", ".docx")):
        raise HTTPException(422, "Unsupported file type. Allowed: pdf, xlsx, xlsm, xls, csv, docx.")

    well, rig = resolve(db, organization_id, well_id, scope, rig_id)
    if document_type not in document_types(db, organization_id):
        raise HTTPException(422, "Select a document type configured in Operations settings.")
    checksum = hashlib.sha256(file_bytes).hexdigest()
    existing = db.scalar(
        select(OpsDocument).where(
            OpsDocument.organization_id == organization_id,
            OpsDocument.well_id == well.id,
            OpsDocument.scope == scope,
            OpsDocument.document_type == document_type,
            OpsDocument.checksum_sha256 == checksum,
            OpsDocument.is_deleted.is_(False),
        )
    )
    if existing:
        return existing, True, existing.id

    doc = OpsDocument(
        organization_id=organization_id,
        well_id=well.id if well else None,
        rig_id=rig.id if rig else None,
        scope=scope or "drilling",
        document_type=document_type,
        file_name=file_name,
        content_type=content_type or "application/octet-stream",
        size_bytes=len(file_bytes),
        checksum_sha256=checksum,
        content=file_bytes,
        document_date=document_date,
        report_no_text=report_no_text or "",
        status="uploaded",
        notes=notes or "",
        well_code_snapshot=well.well_code if well else "",
        well_name_snapshot=well.well_name if well else "",
        rig_code_snapshot=rig.rig_code if rig else "",
        rig_name_snapshot=rig.rig_name if rig else "",
        uploaded_by=str(user.id),
        uploaded_by_name=user.full_name or user.email,
    )
    db.add(doc)
    db.flush()
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="create",
        entity_type="ops_document",
        entity_id=doc.id,
        entity_label=file_name,
        summary=f"Uploaded document {file_name}",
        request=request,
    )
    db.commit()
    db.refresh(doc)
    return doc, False, None


def get_document(db: Session, organization_id: str, doc_id: str) -> OpsDocument:
    row = db.scalar(
        select(OpsDocument).where(
            OpsDocument.id == doc_id,
            OpsDocument.organization_id == organization_id,
            OpsDocument.is_deleted.is_(False),
        )
    )
    if not row:
        raise HTTPException(404, "Document not found")
    return row


def delete_documents(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(
        select(OpsDocument).where(OpsDocument.organization_id == organization_id, OpsDocument.id.in_(ids))
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more documents not found")
    now = datetime.now(UTC)
    affected = 0
    for r in rows:
        if not r.is_deleted:
            r.is_deleted = True
            r.deleted_at = now
            affected += 1
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="delete",
        entity_type="ops_document",
        entity_id=None,
        entity_label=f"{affected} document(s)",
        summary=f"Deleted {affected} document(s)",
        request=request,
    )
    db.commit()
    return {"affected_count": affected}


def restore_documents(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(
        select(OpsDocument).where(OpsDocument.organization_id == organization_id, OpsDocument.id.in_(ids))
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more documents not found")
    affected = 0
    for r in rows:
        if r.is_deleted:
            r.is_deleted = False
            r.deleted_at = None
            affected += 1
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="restore",
        entity_type="ops_document",
        entity_id=None,
        entity_label=f"{affected} document(s)",
        summary=f"Restored {affected} document(s)",
        request=request,
    )
    db.commit()
    return {"affected_count": affected}


def purge_documents(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(
        select(OpsDocument).where(OpsDocument.organization_id == organization_id, OpsDocument.id.in_(ids))
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more documents not found")
    affected = 0
    for r in rows:
        if not r.is_deleted:
            raise HTTPException(409, "Only deleted documents can be permanently removed")
        if r.legal_hold:
            raise HTTPException(409, "Document is on legal hold")
        if db.scalar(
            select(OpsDailyReport.id)
            .where(
                OpsDailyReport.organization_id == organization_id,
                (OpsDailyReport.source_document_id == r.id)
                | OpsDailyReport.id.in_(
                    select(OpsExtractionJob.report_id).where(OpsExtractionJob.document_id == r.id)
                ),
            )
            .limit(1)
        ):
            raise HTTPException(
                409, "A report still references this original. Restore it rather than removing its evidence."
            )
        db.delete(r)
        affected += 1
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="permanent-delete",
        entity_type="ops_document",
        entity_id=None,
        entity_label=f"{affected} document(s)",
        summary=f"Purged {affected} document(s)",
        request=request,
    )
    db.commit()
    return {"affected_count": affected}


def download_document(db: Session, organization_id: str, doc_id: str):
    doc = get_document(db, organization_id, doc_id)
    if not doc.content:
        raise HTTPException(404, "Document has no stored content")
    return doc
