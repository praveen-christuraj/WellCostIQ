"""Document vault service."""

import hashlib
from datetime import date, datetime, timezone
from io import BytesIO

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models.operations import OpsDocument, OpsExtractionJob
from app.models.rig_well import Rig, Well
from app.services.audit import record as audit_record

ALLOWED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "text/csv": "csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}
MAX_FILE_BYTES = 25 * 1024 * 1024


def _actor(user: User) -> str:
    return user.email or user.full_name or str(user.id)


def _snapshot_rig_well(db: Session, organization_id: str, well_id: str | None, rig_id: str | None):
    well = None
    rig = None
    if well_id:
        well = db.scalar(select(Well).where(Well.id == well_id, Well.organization_id == organization_id))
    if rig_id:
        rig = db.scalar(select(Rig).where(Rig.id == rig_id, Rig.organization_id == organization_id))
    return well, rig


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
    q = select(OpsDocument).where(OpsDocument.organization_id == organization_id)
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
    if len(file_bytes) > MAX_FILE_BYTES:
        raise HTTPException(413, f"File too large. Max {MAX_FILE_BYTES // (1024*1024)} MB.")
    if len(file_bytes) == 0:
        raise HTTPException(422, "Empty file.")

    # Basic extension check
    lower_name = file_name.lower()
    if not any(lower_name.endswith(ext) for ext in (".pdf", ".xlsx", ".xls", ".xlsm", ".csv", ".docx")):
        raise HTTPException(422, "Unsupported file type. Allowed: pdf, xlsx, xls, csv, docx.")

    checksum = hashlib.sha256(file_bytes).hexdigest()

    # Dedupe by checksum per org
    existing = db.scalar(select(OpsDocument).where(OpsDocument.organization_id == organization_id, OpsDocument.checksum_sha256 == checksum, OpsDocument.is_deleted.is_(False)))
    if existing:
        return existing, True, existing.id

    well, rig = _snapshot_rig_well(db, organization_id, well_id, rig_id)
    if well_id and not well:
        raise HTTPException(404, "Well not found for this organization.")
    if rig_id and not rig:
        raise HTTPException(404, "Rig not found for this organization.")

    doc = OpsDocument(
        organization_id=organization_id,
        well_id=well.id if well else None,
        rig_id=rig.id if rig else None,
        scope=scope or "drilling",
        document_type=document_type or _infer_type(file_name),
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
    audit_record(db, organization_id=organization_id, actor=user, action="create", entity_type="ops_document", entity_id=doc.id, entity_label=file_name, summary=f"Uploaded document {file_name}", request=request)
    db.commit()
    db.refresh(doc)
    return doc, False, None


def _infer_type(file_name: str) -> str:
    low = file_name.lower()
    if "dcr" in low:
        return "DCR"
    if "dmr" in low or "mud" in low:
        return "DMR"
    if "rmr" in low:
        return "RMR"
    return "DDR"


def get_document(db: Session, organization_id: str, doc_id: str) -> OpsDocument:
    row = db.scalar(select(OpsDocument).where(OpsDocument.id == doc_id, OpsDocument.organization_id == organization_id, OpsDocument.is_deleted.is_(False)))
    if not row:
        raise HTTPException(404, "Document not found")
    return row


def delete_documents(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(select(OpsDocument).where(OpsDocument.organization_id == organization_id, OpsDocument.id.in_(ids))).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more documents not found")
    now = datetime.now(timezone.utc)
    affected = 0
    for r in rows:
        if not r.is_deleted:
            r.is_deleted = True
            r.deleted_at = now
            affected += 1
    audit_record(db, organization_id=organization_id, actor=user, action="delete", entity_type="ops_document", entity_id=None, entity_label=f"{affected} document(s)", summary=f"Deleted {affected} document(s)", request=request)
    db.commit()
    return {"affected_count": affected}


def restore_documents(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(select(OpsDocument).where(OpsDocument.organization_id == organization_id, OpsDocument.id.in_(ids))).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more documents not found")
    affected = 0
    for r in rows:
        if r.is_deleted:
            r.is_deleted = False
            r.deleted_at = None
            affected += 1
    audit_record(db, organization_id=organization_id, actor=user, action="restore", entity_type="ops_document", entity_id=None, entity_label=f"{affected} document(s)", summary=f"Restored {affected} document(s)", request=request)
    db.commit()
    return {"affected_count": affected}


def purge_documents(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(select(OpsDocument).where(OpsDocument.organization_id == organization_id, OpsDocument.id.in_(ids))).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more documents not found")
    affected = 0
    for r in rows:
        if not r.is_deleted:
            raise HTTPException(409, "Only deleted documents can be permanently removed")
        db.delete(r)
        affected += 1
    audit_record(db, organization_id=organization_id, actor=user, action="permanent-delete", entity_type="ops_document", entity_id=None, entity_label=f"{affected} document(s)", summary=f"Purged {affected} document(s)", request=request)
    db.commit()
    return {"affected_count": affected}


def download_document(db: Session, organization_id: str, doc_id: str):
    doc = get_document(db, organization_id, doc_id)
    if not doc.content:
        raise HTTPException(404, "Document has no stored content")
    return doc
