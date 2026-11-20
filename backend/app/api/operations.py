"""Well Operations API — documents, reports, analytics, masters, plans."""

import re
from datetime import date
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import defer

from app.api.deps import Current, Db, granted, owner, require, require_any
from app.domain.operations.default_codes import catalogue_rows, describe_code
from app.domain.operations.requirements import MANDATORY as MANDATORY_FIELDS
from app.domain.operations.study import timeline_study
from app.schemas.ai import AiConnectionStatus
from app.services import ollama
from app.models.vendor_master import Vendor
from app.schemas.operations import (
    CORRELATION_KINDS,
    OpsAgencyIn,
    OpsAiPrefillOut,
    OpsAiReviewOut,
    OpsAiReviewRequest,
    OpsBriefRequest,
    OpsBulkActionOut,
    OpsBulkAssign,
    OpsBulkAssignOut,
    OpsBulkAssignPreviewOut,
    OpsBulkEdit,
    OpsCauseIn,
    OpsCodeLinkBatchIn,
    OpsCodeLinkBatchOut,
    OpsCodeLinkIn,
    OpsCodeLinkOut,
    OpsCorrelationBatchIn,
    OpsCorrelationBatchOut,
    OpsCorrelationIn,
    OpsCorrelationOut,
    OpsCorrelationUpdate,
    OpsDashboardOut,
    OpsDefaultCodeOut,
    OpsDocumentEdit,
    OpsDocumentOut,
    OpsExportAudit,
    OpsExtractIn,
    OpsExtractionJobOut,
    OpsIDs,
    OpsImportOut,
    OpsImportRequest,
    OpsMarkRuleIn,
    OpsNarrativeOut,
    OpsNarrativeRequest,
    OpsOperationIn,
    OpsSubPhaseIn,
    OpsPlanItemIn,
    OpsPlanStudyRequest,
    OpsPlanUpdateIn,
    OpsPlanVersionIn,
    OpsPlanVersionOut,
    OpsReferenceOut,
    OpsRegisterFolderOut,
    OpsRejectIn,
    OpsReopenIn,
    OpsReportCreate,
    OpsReportOut,
    OpsReportSaveIn,
    OpsSettingsIn,
    OpsSettingsOut,
    OpsStudyOut,
    OpsTimeDepthOut,
    OpsTimelineReviewIn,
    OpsTimelineReviewOut,
    OpsWellDiagramOut,
    OpsWellPathOut,
    OpsWellSummaryOut,
)
from app.services.audit import record as audit_record
from app.services.operations.report_labels import report_labels
from app.services.operations import analytics as analytics_svc
from app.services.operations import bulk_assign as bulk_svc
from app.services.operations import correlations as correlation_svc
from app.services.operations import documents as docs_svc
from app.services.operations import extraction as extract_svc
from app.services.operations import guide as guide_svc
from app.services.operations import masters as masters_svc
from app.services.operations import ops_ai as ops_ai_svc
from app.services.operations import plans as plans_svc
from app.services.operations import register as register_svc
from app.services.operations import reports as reports_svc
from app.services.operations import scope as scope_svc
from app.services.operations import settings as settings_svc
from app.services.operations import summary as summary_svc
from app.services.operations import well_path as well_path_svc
from app.services.operations.study_ai import with_ai
from app.services.operations.workbooks import timeline_preview

router = APIRouter(prefix="/operations", tags=["Well Operations"])


OpsRegister = Literal['plans', 'reports', 'documents']


@router.get('/directory/{resource}', response_model=list[OpsRegisterFolderOut])
def register_folders(resource: OpsRegister, db: Db, user: Current, deleted: bool = False):
    require(register_svc.READ_PERMISSIONS[resource])(user)
    return register_svc.folders(db, user.organization_id, resource, deleted)


@router.get('/directory/{resource}/records', response_model=list[OpsPlanVersionOut | OpsReportOut | OpsDocumentOut])
def register_records(
    resource: OpsRegister, db: Db, user: Current,
    rig: Annotated[str, Query(min_length=4, max_length=256)],
    well: Annotated[str, Query(min_length=4, max_length=256)],
    scope: Literal['', 'drilling', 'completion'] = '', deleted: bool = False,
):
    require(register_svc.READ_PERMISSIONS[resource])(user)
    rows = register_svc.records(db, user.organization_id, resource, deleted, rig, well, scope)
    if resource == 'plans':
        return [_plan_out(row) for row in rows]
    if resource == 'reports':
        return [_to_report_out(row, db) for row in rows]
    return rows


@router.get('/guide', dependencies=[Depends(require_any('ops-report:read', 'ops-plan:read', 'ops-doc:read', 'ops-master:read'))])
def guide(user: Current):
    return guide_svc.manual({'*'} if owner(user) else granted(user))


@router.get('/guide/study', dependencies=[Depends(require_any('ops-report:read', 'ops-plan:read', 'ops-doc:read', 'ops-master:read'))])
def guide_study():
    """The drilling engineering study books, grouped by subject.

    The same entries the guide answers from and the AI prompt carries, exposed
    without a model so a reader can use the arithmetic and the page references
    directly. Read-only reference material: there is nothing here about a
    workspace's own records, so no record-level capability is required.
    """
    from app.domain.operations.study_knowledge import study_library, study_sources

    return {'sources': study_sources(), 'topics': study_library()}


@router.get(
    '/ai-status',
    response_model=AiConnectionStatus,
    dependencies=[Depends(require_any('ops-report:read', 'ops-plan:read', 'ops-analytics:read', 'ops-doc:read'))],
)
def ai_status(probe: bool = False):
    return ollama.check_status(probe=probe)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@router.get("/settings", response_model=OpsSettingsOut, dependencies=[Depends(require("ops-settings:read"))])
def get_settings(db: Db, user: Current):
    return settings_svc.get_settings(db, user.organization_id)


@router.put("/settings", response_model=OpsSettingsOut, dependencies=[Depends(require("ops-settings:update"))])
def update_settings(data: OpsSettingsIn, request: Request, db: Db, user: Current):
    return settings_svc.update_settings(db, user.organization_id, data, user, request)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@router.get("/documents", response_model=list[OpsDocumentOut], dependencies=[Depends(require("ops-doc:read"))])
def list_documents(
    db: Db,
    user: Current,
    well_id: str = "",
    scope: Literal["", "drilling", "completion"] = "",
    document_type: str = "",
    status: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
):
    date_from_q = date_from
    date_to_q = date_to
    return docs_svc.list_documents(
        db,
        user.organization_id,
        well_id=well_id or None,
        scope=scope or None,
        document_type=document_type or None,
        status=status or None,
        date_from=date_from_q,
        date_to=date_to_q,
    )


@router.get(
    "/documents/deleted", response_model=list[OpsDocumentOut], dependencies=[Depends(require("ops-doc:read"))]
)
def list_deleted_documents(db: Db, user: Current):
    from sqlalchemy import select

    from app.models.operations import OpsDocument

    rows = db.scalars(
        select(OpsDocument)
        .options(defer(OpsDocument.content))
        .where(OpsDocument.organization_id == user.organization_id, OpsDocument.is_deleted.is_(True))
        .order_by(OpsDocument.deleted_at.desc())
    ).all()
    return rows


@router.get(
    "/documents/{document_id}", response_model=OpsDocumentOut, dependencies=[Depends(require("ops-doc:read"))]
)
def get_document(document_id: str, db: Db, user: Current):
    return docs_svc.get_document(db, user.organization_id, document_id)


@router.put(
    "/documents/{document_id}", response_model=OpsDocumentOut, dependencies=[Depends(require("ops-doc:update"))]
)
def edit_document(document_id: str, data: OpsDocumentEdit, request: Request, db: Db, user: Current):
    doc = docs_svc.get_document(db, user.organization_id, document_id)
    if data.document_type != doc.document_type and data.document_type not in scope_svc.document_types(
        db, user.organization_id
    ):
        raise HTTPException(422, "Select a configured document type.")
    for field, val in data.model_dump().items():
        setattr(doc, field, val)
    audit_record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="update",
        entity_type="ops_document",
        entity_id=doc.id,
        entity_label=doc.file_name,
        summary="Updated document metadata; original file unchanged",
        request=request,
    )
    db.commit()
    return doc


@router.get("/documents/{document_id}/download", dependencies=[Depends(require("ops-doc:download"))])
def download_document(document_id: str, request: Request, db: Db, user: Current):
    from fastapi.responses import Response

    doc = docs_svc.download_document(db, user.organization_id, document_id)
    audit_record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="download",
        entity_type="ops_document",
        entity_id=doc.id,
        entity_label=doc.file_name,
        summary="Downloaded source document",
        request=request,
    )
    db.commit()
    return Response(
        content=doc.content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(doc.file_name, safe="")},
    )


@router.post("/documents/upload", response_model=OpsDocumentOut, dependencies=[Depends(require("ops-doc:upload"))])
async def upload_document(
    request: Request,
    db: Db,
    user: Current,
    file: Annotated[UploadFile, File()],
    well_id: str = Form(""),
    rig_id: str = Form(""),
    scope: str = Form("drilling"),
    document_type: str = Form(..., min_length=1, max_length=20),
    document_date: str = Form(""),
    report_no_text: str = Form("", max_length=50),
    notes: str = Form("", max_length=1000),
):
    content = await file.read(docs_svc.upload_limit(db, user.organization_id) + 1)
    doc_date = None
    if document_date:
        try:
            doc_date = date.fromisoformat(document_date)
        except ValueError as exc:
            raise HTTPException(422, "Invalid document date") from exc
    doc, _, _ = docs_svc.upload_document(
        db,
        user.organization_id,
        file_bytes=content,
        file_name=file.filename or "upload.pdf",
        content_type=file.content_type or "application/pdf",
        well_id=well_id or None,
        rig_id=rig_id or None,
        scope=scope or "drilling",
        document_type=document_type,
        document_date=doc_date,
        report_no_text=report_no_text or "",
        notes=notes or "",
        user=user,
        request=request,
    )
    return doc


@router.get(
    "/documents/{document_id}/extractions",
    response_model=list[OpsExtractionJobOut],
    dependencies=[Depends(require("ops-doc:read"))],
)
def list_extractions(document_id: str, db: Db, user: Current):
    from sqlalchemy import select

    from app.models.operations import OpsExtractionJob

    docs_svc.get_document(db, user.organization_id, document_id)  # ensure exists
    jobs = db.scalars(
        select(OpsExtractionJob)
        .where(
            OpsExtractionJob.organization_id == user.organization_id, OpsExtractionJob.document_id == document_id
        )
        .order_by(OpsExtractionJob.created_at.desc())
    ).all()
    return jobs


@router.post(
    "/documents/bulk-delete", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-doc:delete"))]
)
def bulk_delete_documents(data: OpsIDs, request: Request, db: Db, user: Current):
    result = docs_svc.delete_documents(db, user.organization_id, data.ids, user, request)
    return result


@router.post(
    "/documents/bulk-restore", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-doc:restore"))]
)
def bulk_restore_documents(data: OpsIDs, request: Request, db: Db, user: Current):
    result = docs_svc.restore_documents(db, user.organization_id, data.ids, user, request)
    return result


@router.post(
    "/documents/bulk-permanent-delete",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-doc:permanent-delete"))],
)
def bulk_purge_documents(data: OpsIDs, request: Request, db: Db, user: Current):
    result = docs_svc.purge_documents(db, user.organization_id, data.ids, user, request)
    return result


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def _block_source_codes(block):
    # Older drafts only recorded the printed activity token in the evidence.
    # Interpret it on read rather than re-extracting or rewriting reviewed logs.
    activity = block.source_activity_code
    if not activity and (match := re.search(r"(?:^| · )Code ([^·]+?)(?= · |$)", block.classification_evidence or '')):
        activity = match[1].strip()
    return {
        'source_activity_code': activity,
        'source_activity_label': describe_code(activity, 'OpenWells code token' if block.source_page else 'Activity'),
        'source_operation_label': describe_code(block.source_operation_code, 'Operation'),
        'source_phase_label': describe_code(block.phase_raw, 'OpenWells phase', 'Programme phase'),
        'source_mark_label': describe_code(block.source_mark, 'Source mark', 'Allocation', 'Trouble / NPT'),
        'source_cause_label': describe_code(block.source_cause_code, 'Cause', 'Trouble / NPT'),
    }


def _block_out(b, db=None, organization_id: str | None = None) -> dict:
    labels = report_labels(db, organization_id) if db is not None and organization_id else None

    def lookup(kind: str, ident: str | None) -> str:
        return (labels or {}).get(kind, {}).get(ident or "", "") if ident else ""

    cause_label = lookup("cause", (b.cause_code or "").strip().upper())
    return {
        "id": b.id,
        "organization_id": b.organization_id,
        "report_id": b.report_id,
        "sequence_no": b.sequence_no,
        "started_at": b.started_at,
        "ended_at": b.ended_at,
        "duration_minutes": b.duration_minutes,
        "phase_raw": b.phase_raw or "",
        **_block_source_codes(b),
        # Criteria in review order.
        "hole_section_id": b.hole_section_id,
        "phase_id": b.phase_id,
        "sub_phase_id": b.sub_phase_id,
        "activity_id": b.activity_id,
        "classification": b.classification,
        "allocation": b.allocation,
        "is_productive": b.is_productive,
        "cause_code": b.cause_code or "",
        "operation_id": b.operation_id,
        "operation_snapshot": b.operation_snapshot or "",
        "responsible_agency_id": b.responsible_agency_id,
        "responsible_party": b.responsible_party or "",
        "vendor_id": b.vendor_id,
        # Resolved labels so a page never guesses how a code is displayed.
        "hole_section_label": lookup("hole_section", b.hole_section_id),
        "phase_label": lookup("phase", b.phase_id),
        "sub_phase_label": lookup("sub_phase", b.sub_phase_id),
        "activity_label": lookup("activity", b.activity_id),
        "activity_type": lookup("activity_type", b.activity_id),
        "operation_code": lookup("operation_code", b.operation_id) or None,
        "operation_name": lookup("operation", b.operation_id) if b.operation_id else None,
        "cause_label": cause_label,
        "responsible_agency_label": lookup("agency", b.responsible_agency_id),
        "classification_evidence": b.classification_evidence or "",
        "classification_source": b.classification_source or "keyword",
        "depth_from_m": b.depth_from_m,
        "depth_to_m": b.depth_to_m,
        "tvd_from_m": getattr(b, "tvd_from_m", None),
        "tvd_to_m": getattr(b, "tvd_to_m", None),
        "depth_unit": b.depth_unit or "m",
        "footage_m": b.footage_m,
        "bit_depth_m": b.bit_depth_m,
        "mud_weight_ppg": getattr(b, "mud_weight_ppg", None),
        "rotating_hours": b.rotating_hours,
        "rop_m_per_hr": b.rop_m_per_hr,
        "rop_basis": b.rop_basis or "rotating",
        "reason": b.reason or "",
        "narrative": b.narrative or "",
        "source_page": b.source_page or 0,
        "source_bbox": b.source_bbox or "",
        "confidence": b.confidence,
        "review_state": b.review_state or "suggested",
        # The generated comparison is part of the block the user reviews.
        "timeline_comparison": getattr(b, "timeline_comparison", "on") or "on",
        "timeline_review_state": getattr(b, "timeline_review_state", "suggested") or "suggested",
        "timeline_note": getattr(b, "timeline_note", "") or "",
        "timeline_variance_days": getattr(b, "timeline_variance_days", None),
        "timeline_planned_days": getattr(b, "timeline_planned_days", None),
        "timeline_actual_days": getattr(b, "timeline_actual_days", None),
        "timeline_basis": getattr(b, "timeline_basis", "") or "",
        "timeline_reviewed_by": getattr(b, "timeline_reviewed_by", "") or "",
        "timeline_reviewed_at": getattr(b, "timeline_reviewed_at", None),
        # Plan-vs-actual hours: the figures the engineer compares and edits.
        "timeline_plan_item_id": getattr(b, "timeline_plan_item_id", None),
        "timeline_plan_step_no": getattr(b, "timeline_plan_step_no", None),
        "timeline_plan_label": getattr(b, "timeline_plan_label", "") or "",
        "timeline_planned_hours": getattr(b, "timeline_planned_hours", None),
        "timeline_actual_hours": getattr(b, "timeline_actual_hours", None),
        "timeline_system_actual_hours": getattr(b, "timeline_system_actual_hours", None),
        "timeline_variance_hours": getattr(b, "timeline_variance_hours", None),
        "timeline_cum_planned_days": getattr(b, "timeline_cum_planned_days", None),
        "timeline_actual_edited": bool(getattr(b, "timeline_actual_edited", False)),
        "timeline_edited_by": getattr(b, "timeline_edited_by", "") or "",
        "timeline_edited_at": getattr(b, "timeline_edited_at", None),
        "reviewer_user_id": b.reviewer_user_id,
        "reviewed_at": b.reviewed_at,
        "is_deleted": b.is_deleted,
        "created_at": b.created_at,
        "updated_at": b.updated_at,
    }


def _to_report_out(report, db=None):
    blocks = getattr(report, "_blocks", []) or []
    # A register list passes no session: labels are then blank rather than a
    # per-row query, and the detail view (which has the session) fills them.
    organization_id = getattr(report, "organization_id", None)
    unacc = getattr(report, "_unaccounted_minutes", 0) or 0
    total = getattr(report, "_total_block_minutes", 0) or sum(getattr(b, "duration_minutes", 0) for b in blocks)
    return {
        "id": report.id,
        "organization_id": report.organization_id,
        "well_id": report.well_id,
        "rig_id": report.rig_id,
        "rig_code_snapshot": report.rig_code_snapshot or "",
        "rig_name_snapshot": report.rig_name_snapshot or "",
        "well_code_snapshot": report.well_code_snapshot or "",
        "well_name_snapshot": report.well_name_snapshot or "",
        "rejection_reason": report.rejection_reason or "",
        "reopened_at": getattr(report, "reopened_at", None),
        "reopened_by": getattr(report, "reopened_by", "") or "",
        "reopen_reason": getattr(report, "reopen_reason", "") or "",
        "submitted_at": report.submitted_at,
        "submitted_by": report.submitted_by or "",
        "approved_at": report.approved_at,
        "approved_by": report.approved_by or "",
        "baseline_plan_id": report.baseline_plan_id,
        "completed_plan_item_id": report.completed_plan_item_id,
        "plan_checkpoints": getattr(report, "_plan_checkpoints", []),
        "customer": report.customer or "",
        "project": report.project or "",
        "site": report.site or "",
        "datum": report.datum or "",
        "supervisor": report.supervisor or "",
        "engineer": report.engineer or "",
        "uwi": report.uwi or "",
        "block_text": report.block_text or "",
        "surveys": getattr(report, "_surveys", []),
        "extraction_notes": getattr(report, "_extraction_notes", ""),
        "sources": getattr(report, "_sources", []),
        "scope": report.scope,
        "report_type": report.report_type or "DDR",
        "report_date": report.report_date,
        "report_no_text": report.report_no_text or "",
        "report_no_seq": report.report_no_seq,
        "day_number": report.day_number,
        "event_code": report.event_code or "",
        "period_start_at": report.period_start_at,
        "period_end_at": report.period_end_at,
        "period_minutes": report.period_minutes or 1440,
        "hole_section_id": report.hole_section_id,
        "phase_id": report.phase_id,
        "depth_start_m": report.depth_start_m,
        "depth_end_m": report.depth_end_m,
        "depth_unit": report.depth_unit or "m",
        "tvd_start_m": getattr(report, "tvd_start_m", None),
        "tvd_m": report.tvd_m,
        "tvd_source": getattr(report, "tvd_source", "") or "",
        "bit_depth_m": getattr(report, "bit_depth_m", None),
        "progress_m": report.progress_m,
        "rotating_hours": report.rotating_hours,
        "cum_rotating_hours": getattr(report, "cum_rotating_hours", None),
        "spud_date": getattr(report, "spud_date", None),
        "dfs_days": report.dfs_days,
        "est_days": report.est_days,
        "md_auth_m": report.md_auth_m,
        "last_casing_size_in": report.last_casing_size_in,
        "last_casing_depth_m": report.last_casing_depth_m,
        "hole_section_text": getattr(report, "hole_section_text", "") or "",
        "hole_size_in": getattr(report, "hole_size_in", None),
        "current_status": getattr(report, "current_status", "") or "",
        "mud_type": getattr(report, "mud_type", "") or "",
        "mud_weight_ppg": getattr(report, "mud_weight_ppg", None),
        "mud_viscosity_sec": getattr(report, "mud_viscosity_sec", None),
        "mud_pv_cp": getattr(report, "mud_pv_cp", None),
        "mud_yp_lbf": getattr(report, "mud_yp_lbf", None),
        "bha_summary": getattr(report, "bha_summary", "") or "",
        "pob_count": getattr(report, "pob_count", None),
        "operation_summary": report.operation_summary or "",
        "forward_plan": report.forward_plan or "",
        "hse_summary": report.hse_summary or "",
        "remarks": report.remarks or "",
        "status": report.status,
        "extraction_status": report.extraction_status or "none",
        "current_extraction_id": report.current_extraction_id,
        "source_document_id": report.source_document_id,
        "supersedes_id": report.supersedes_id,
        "superseded_by_id": report.superseded_by_id,
        "is_current": report.is_current,
        "revision_no": report.revision_no or 1,
        "is_deleted": report.is_deleted,
        "deleted_at": report.deleted_at,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
        "created_by": report.created_by or "",
        "updated_by": report.updated_by or "",
        "blocks": [_block_out(b, db, organization_id) for b in blocks],
        "unaccounted_minutes": unacc,
        "total_block_minutes": total,
    }


@router.get("/reports", response_model=list[OpsReportOut], dependencies=[Depends(require("ops-report:read"))])
def list_reports(
    db: Db,
    user: Current,
    well_id: str = "",
    rig_id: str = "",
    scope: Literal["", "drilling", "completion"] = "",
    status: str = "",
    report_type: str = "",
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
):
    rows = reports_svc.list_reports(
        db,
        user.organization_id,
        well_id=well_id or None,
        rig_id=rig_id or None,
        scope=scope or None,
        status=status or None,
        report_type=report_type or None,
        date_from=date_from,
        date_to=date_to,
    )
    return [_to_report_out(r, db) for r in rows]


@router.get(
    "/reports/deleted", response_model=list[OpsReportOut], dependencies=[Depends(require("ops-report:read"))]
)
def list_deleted_reports(db: Db, user: Current):
    rows = reports_svc.list_reports(db, user.organization_id, include_deleted=True)
    deleted = [r for r in rows if r.is_deleted]
    return [_to_report_out(r, db) for r in deleted]


@router.post(
    "/reports/from-document",
    response_model=OpsReportOut,
    dependencies=[
        Depends(require("ops-report:read")),
        Depends(require("ops-doc:read")),
        Depends(require("ops-doc:extract")),
        Depends(require("ops-report:create")),
    ],
)
def report_from_document(data: OpsExtractIn, request: Request, db: Db, user: Current):
    report = extract_svc.extract(
        db, user.organization_id, data.document_id, data.report_date, user, request, use_ai=data.use_ai
    )
    return _to_report_out(reports_svc.get_report(db, user.organization_id, report.id), db)


@router.post(
    "/reports/{report_id}/extract",
    response_model=OpsReportOut,
    dependencies=[
        Depends(require("ops-report:read")),
        Depends(require("ops-doc:read")),
        Depends(require("ops-doc:extract")),
        Depends(require("ops-report:update")),
    ],
)
def add_report_source(report_id: str, data: OpsExtractIn, request: Request, db: Db, user: Current):
    report = extract_svc.extract(
        db,
        user.organization_id,
        data.document_id,
        data.report_date,
        user,
        request,
        target_id=report_id,
        use_ai=data.use_ai,
    )
    return _to_report_out(reports_svc.get_report(db, user.organization_id, report.id), db)


@router.post(
    "/reports/bulk-edit", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-report:update"))]
)
def bulk_edit(data: OpsBulkEdit, request: Request, db: Db, user: Current):
    from app.models.operations import OpsDailyReport

    rows = db.scalars(
        select(OpsDailyReport)
        .where(
            OpsDailyReport.organization_id == user.organization_id,
            OpsDailyReport.id.in_(data.ids),
            OpsDailyReport.is_deleted.is_(False),
        )
        .with_for_update()
    ).all()
    if len(rows) != len(set(data.ids)):
        raise HTTPException(404, "One or more reports not found.")
    if any(r.status not in ("draft", "in_review", "rejected") for r in rows):
        raise HTTPException(409, "Only editable reports can receive a register note.")
    for row in rows:
        row.remarks = (row.remarks + "\n" + data.remarks.strip()).strip()
        row.updated_by = user.email
        audit_record(
            db,
            organization_id=user.organization_id,
            actor=user,
            action="update",
            entity_type="ops_report",
            entity_id=row.id,
            entity_label=row.report_no_text,
            summary="Appended register note",
            request=request,
        )
    db.commit()
    return {"affected_count": len(rows)}


@router.get("/reports/{report_id}", response_model=OpsReportOut, dependencies=[Depends(require("ops-report:read"))])
def get_report(report_id: str, db: Db, user: Current, include_deleted: bool = False):
    r = reports_svc.get_report(db, user.organization_id, report_id, include_deleted=include_deleted)
    return _to_report_out(r, db)


@router.post("/reports", response_model=OpsReportOut, dependencies=[Depends(require("ops-report:create"))])
def create_report(data: OpsReportCreate, request: Request, db: Db, user: Current):
    r = reports_svc.create_report(db, user.organization_id, data, user, request)
    # Return enriched
    full = reports_svc.get_report(db, user.organization_id, r.id)
    return _to_report_out(full, db)


@router.put(
    "/reports/{report_id}", response_model=OpsReportOut, dependencies=[Depends(require("ops-report:update"))]
)
def save_report(report_id: str, data: OpsReportSaveIn, request: Request, db: Db, user: Current):
    r = reports_svc.save_report(
        db,
        user.organization_id,
        report_id,
        data,
        user,
        request,
        may_review=owner(user) or "ops-report:review" in granted(user),
    )
    return _to_report_out(r, db)


@router.post(
    "/reports/{report_id}/submit", response_model=OpsReportOut, dependencies=[Depends(require("ops-report:submit"))]
)
def submit_report(report_id: str, request: Request, db: Db, user: Current):
    r = reports_svc.submit_report(db, user.organization_id, report_id, user, request)
    full = reports_svc.get_report(db, user.organization_id, r.id)
    return _to_report_out(full, db)


@router.post(
    "/reports/{report_id}/approve",
    response_model=OpsReportOut,
    dependencies=[Depends(require("ops-report:approve"))],
)
def approve_report(report_id: str, request: Request, db: Db, user: Current):
    r = reports_svc.approve_report(db, user.organization_id, report_id, user, request)
    full = reports_svc.get_report(db, user.organization_id, r.id)
    return _to_report_out(full, db)


@router.post(
    "/reports/{report_id}/reject",
    response_model=OpsReportOut,
    dependencies=[Depends(require("ops-report:approve"))],
)
def reject_report(report_id: str, data: OpsRejectIn, request: Request, db: Db, user: Current):
    r = reports_svc.reject_report(db, user.organization_id, report_id, data.reason, user, request)
    full = reports_svc.get_report(db, user.organization_id, r.id)
    return _to_report_out(full, db)


@router.post(
    "/reports/{report_id}/reopen",
    response_model=OpsReportOut,
    dependencies=[Depends(require("ops-report:reopen"))],
)
def reopen_report(report_id: str, data: OpsReopenIn, request: Request, db: Db, user: Current):
    can_amend = owner(user) or "ops-report:amend" in granted(user)
    r = reports_svc.reopen_report(
        db,
        user.organization_id,
        report_id,
        data.remarks,
        user,
        request,
        can_amend=can_amend,
    )
    full = reports_svc.get_report(db, user.organization_id, r.id)
    return _to_report_out(full, db)


@router.post(
    "/reports/{report_id}/narratives",
    response_model=OpsNarrativeOut,
    dependencies=[Depends(require("ops-report:read"))],
)
def generate_narratives(report_id: str, data: OpsNarrativeRequest, request: Request, db: Db, user: Current):
    return ops_ai_svc.generate_report_narratives(
        db,
        user.organization_id,
        report_id,
        user,
        use_ai=data.use_ai,
        focus=data.focus,
        request=request,
    )


@router.post(
    "/reports/{report_id}/ai-prefill",
    response_model=OpsAiPrefillOut,
    dependencies=[Depends(require("ops-report:read")), Depends(require("ops-report:update"))],
)
def ai_prefill_report(report_id: str, request: Request, db: Db, user: Current):
    result = ops_ai_svc.refine_report_prefill(
        db,
        user.organization_id,
        report_id,
        user,
        request=request,
        from_extract=False,
    )
    report_obj = reports_svc.get_report(db, user.organization_id, report_id)
    result["report"] = _to_report_out(report_obj, db)
    return result


@router.get("/reports/{report_id}/brief", dependencies=[Depends(require("ops-report:read"))])
def get_brief(report_id: str, db: Db, user: Current, include_deleted: bool = False):
    return reports_svc.brief_for_report(db, user.organization_id, report_id, include_deleted=include_deleted)


@router.post('/reports/{report_id}/brief', response_model=OpsStudyOut, dependencies=[Depends(require('ops-report:read'))])
def review_brief(report_id: str, data: OpsBriefRequest, request: Request, db: Db, user: Current,
                 include_deleted: bool = False):
    result = reports_svc.brief_for_report(db, user.organization_id, report_id, include_deleted=include_deleted)
    return with_ai({'summary': result['summary']}, db, user, request, entity_type='ops_report',
                   entity_id=report_id, use_ai=data.use_ai)


@router.post(
    "/reports/{report_id}/timeline-review",
    response_model=OpsTimelineReviewOut,
    dependencies=[Depends(require("ops-report:update"))],
)
def review_timeline(report_id: str, data: OpsTimelineReviewIn, request: Request, db: Db, user: Current):
    """Accept, edit or reject the system's suggested lead/lag comparison."""
    if data.review_state in ("accepted", "edited") and not owner(user) and "ops-report:review" not in granted(user):
        raise HTTPException(403, "Permission denied. Confirming the comparison needs ops-report:review.")
    return reports_svc.review_timeline(db, user.organization_id, report_id, data, user, request)


@router.post(
    "/reports/bulk-assign/preview",
    response_model=OpsBulkAssignPreviewOut,
    dependencies=[Depends(require("ops-report:update"))],
)
def bulk_assign_preview(data: OpsBulkAssign, db: Db, user: Current):
    """Show what a bulk assignment would change, without writing anything."""
    return bulk_svc.preview(db, user.organization_id, data)


@router.post(
    "/reports/bulk-assign",
    response_model=OpsBulkAssignOut,
    dependencies=[Depends(require("ops-report:update"))],
)
def bulk_assign(data: OpsBulkAssign, request: Request, db: Db, user: Current):
    return bulk_svc.apply(db, user.organization_id, data, user, request)


@router.post(
    "/reports/bulk-delete", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-report:delete"))]
)
def bulk_delete(data: OpsIDs, request: Request, db: Db, user: Current):
    return reports_svc.delete_reports(db, user.organization_id, data.ids, user, request)


@router.post(
    "/reports/bulk-restore", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-report:restore"))]
)
def bulk_restore(data: OpsIDs, request: Request, db: Db, user: Current):
    return reports_svc.restore_reports(db, user.organization_id, data.ids, user, request)


@router.post(
    "/reports/bulk-permanent-delete",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-report:permanent-delete"))],
)
def bulk_purge(data: OpsIDs, request: Request, db: Db, user: Current):
    return reports_svc.purge_reports(db, user.organization_id, data.ids, user, request)


@router.post("/reports/import", response_model=OpsImportOut, dependencies=[Depends(require("ops-report:import"))])
def import_reports(data: OpsImportRequest, request: Request, db: Db, user: Current):
    from sqlalchemy import select

    from app.models.rig_well import Rig, Well

    errors: list[str] = []
    created = 0
    rigs = {
        r.rig_code.lower(): r
        for r in db.scalars(
            select(Rig).where(Rig.organization_id == user.organization_id, Rig.is_deleted.is_(False))
        ).all()
    }
    wells = {
        w.well_code.lower(): w
        for w in db.scalars(
            select(Well).where(Well.organization_id == user.organization_id, Well.is_deleted.is_(False))
        ).all()
    }
    for idx, row in enumerate(data.rows, 2):
        try:
            well = wells.get(row.well_code.lower())
            if not well:
                raise ValueError(f"Well code '{row.well_code}' not found")
            rig = rigs.get((row.rig_code or "").lower()) if row.rig_code else None
            if row.rig_code and not rig:
                raise ValueError(f"Rig code '{row.rig_code}' not found")
            # Check duplicate
            from sqlalchemy import select as sel

            from app.models.operations import OpsDailyReport

            exists = db.scalar(
                sel(OpsDailyReport).where(
                    OpsDailyReport.organization_id == user.organization_id,
                    OpsDailyReport.well_id == well.id,
                    OpsDailyReport.scope == row.scope,
                    OpsDailyReport.report_date == row.report_date,
                    OpsDailyReport.is_deleted.is_(False),
                )
            )
            if exists:
                raise ValueError("Report for this well/scope/date already exists")
            payload = OpsReportCreate(
                well_id=well.id,
                rig_id=rig.id if rig else None,
                report_type=row.report_type,
                scope=row.scope,  # type: ignore
                report_date=row.report_date,
                report_no_text=row.report_no_text or "",
                depth_start_m=row.depth_start_m,
                depth_end_m=row.depth_end_m,
                operation_summary=row.operation_summary or "",
            )
            reports_svc.create_report(db, user.organization_id, payload, user, request)
            created += 1
        except (HTTPException, ValueError) as ex:
            detail = ex.detail if isinstance(ex, HTTPException) else str(ex)
            errors.append(f"Row {idx}: {detail}")
    audit_record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="import",
        entity_type="ops_report",
        entity_id=None,
        entity_label="Daily reports",
        summary=f"Imported {created} report headers; {len(errors)} rejected",
        request=request,
    )
    db.commit()
    return {"created_count": created, "errors": errors}


@router.get(
    "/scope-reference",
    dependencies=[
        Depends(
            require_any(
                "ops-doc:read", "ops-report:read", "ops-plan:read", "ops-analytics:read", "ops-dashboard:read"
            )
        )
    ],
)
def scope_reference(db: Db, user: Current):
    return scope_svc.reference(db, user.organization_id)


@router.get("/reference", response_model=OpsReferenceOut, dependencies=[Depends(require("ops-report:read"))])
def reference(db: Db, user: Current):
    """Every daily-report dropdown in one payload.

    Hole Sections, Phases and Activities come from Master Data; sub-phases,
    Operations, causes and responsible agency labels come from the Code Library;
    vendors come from the vendor register. Nothing here touches a costing table.
    """
    from app.models.master_data import Activity, HoleSection, Phase
    from app.models.operations import OpsAgency, OpsCause, OpsOperation, OpsSubPhase

    org = user.organization_id

    def active(model):
        return db.scalars(
            select(model)
            .where(model.organization_id == org, model.is_active.is_(True), model.is_deleted.is_(False))
            .order_by(model.sort_order)
        ).all()

    def master(model, code_field: str, name_field: str):
        rows = db.scalars(
            select(model)
            .where(model.organization_id == org, model.is_deleted.is_(False))
            .order_by(getattr(model, code_field))
        ).all()
        return [
            {
                "id": row.id,
                "code": getattr(row, code_field),
                "name": getattr(row, name_field),
                "label": f"{getattr(row, code_field)} — {getattr(row, name_field)}",
                **({"activity_type": row.activity_type} if hasattr(row, "activity_type") else {}),
            }
            for row in rows
        ]

    return {
        **scope_svc.reference(db, org),
        "vendors": [
            {"id": v.id, "vendor_code": v.vendor_code, "vendor_name": v.vendor_name}
            for v in db.scalars(
                select(Vendor)
                .where(Vendor.organization_id == org, Vendor.is_deleted.is_(False), Vendor.status == "active")
                .order_by(Vendor.vendor_name)
            )
        ],
        "hole_sections": master(HoleSection, "section_code", "section_name"),
        "phases": master(Phase, "phase_code", "phase_name"),
        "activities": master(Activity, "activity_code", "activity_name"),
        "sub_phases": active(OpsSubPhase),
        "operations": active(OpsOperation),
        "causes": active(OpsCause),
        # The responsible agency label list configured in the Code Library.
        "agencies": active(OpsAgency),
        "code_links": correlation_svc.list_code_links(db, org, active_only=True),
        "classification_rules": {
            activity_type: list(fields) for activity_type, fields in MANDATORY_FIELDS.items()
        },
    }


# ---------------------------------------------------------------------------
# Code Library correlations: printed default codes -> workspace codes
# ---------------------------------------------------------------------------


@router.get(
    "/correlations",
    response_model=list[OpsCorrelationOut],
    dependencies=[Depends(require("ops-master:read"))],
)
def list_correlations(
    db: Db,
    user: Current,
    kind: str | None = None,
    deleted: bool = False,
):
    """Correlations that let extraction pre-select this workspace's own codes."""
    return correlation_svc.list_correlations(db, user.organization_id, kind=kind or "", include_deleted=deleted)


@router.get(
    "/correlations/reference",
    dependencies=[Depends(require("ops-master:read"))],
)
def correlation_reference(db: Db, user: Current):
    """The two sides of correlations and multi-criteria code links.

    The left side is the printed reference catalogue; the right side is this
    workspace's criteria — Master Data registers (Hole Section, Phase, Activity,
    vendor) and Code Library lists (Sub-phase, Operations, Cause, responsible
    agency label, source mark).
    """
    from app.models.master_data import Activity, HoleSection, Phase
    from app.models.operations import OpsAgency, OpsCause, OpsMarkRule, OpsOperation, OpsSubPhase

    usage = correlation_svc.code_usage_counts(db, user.organization_id)

    def library(model, code_field, name_field, master_kind: str):
        bucket = usage.get(master_kind, {})
        items = []
        for row in db.scalars(
            select(model)
            .where(
                model.organization_id == user.organization_id,
                model.is_deleted.is_(False),
            )
            .order_by(getattr(model, code_field))
        ):
            if not getattr(row, "is_active", True):
                continue
            item = {
                "id": row.id,
                "code": getattr(row, code_field),
                "name": getattr(row, name_field),
                "correlation_count": bucket.get(row.id, 0),
            }
            # The Activity carries its own type; a link or correlation dialog reads
            # it to refuse a cause on Planned work before the request is sent.
            if hasattr(row, "activity_type"):
                item["activity_type"] = getattr(row, "activity_type") or ""
            if hasattr(row, "default_allocation"):
                item["default_allocation"] = getattr(row, "default_allocation") or ""
            if hasattr(row, "default_cause_code"):
                item["default_cause_code"] = getattr(row, "default_cause_code") or ""
            items.append(item)
        return items

    return {
        "kinds": list(CORRELATION_KINDS),
        "printed": [
            {
                "family": row["family"],
                "code": row["code"],
                "name": row["name"],
                "description": row["name"] or row["description"],
                "detail": row["description"],
                "classification": row.get("classification", ""),
                "allocation": row.get("allocation", ""),
            }
            for row in catalogue_rows()
        ],
        "library": {
            # Master Data registers.
            "hole_section": library(HoleSection, "section_code", "section_name", "hole-sections"),
            "phase": library(Phase, "phase_code", "phase_name", "phases"),
            "activity": library(Activity, "activity_code", "activity_name", "activities"),
            "vendor": library(Vendor, "vendor_code", "vendor_name", "vendors"),
            # Code Library lists.
            "sub_phase": library(OpsSubPhase, "sub_phase_code", "sub_phase_name", "sub-phases"),
            "operation": library(OpsOperation, "operation_code", "operation_name", "operations"),
            "cause": library(OpsCause, "cause_code", "cause_name", "causes"),
            "responsible_agency": library(OpsAgency, "agency_code", "agency_name", "agencies"),
            "mark": library(OpsMarkRule, "mark_code", "mark_name", "source-marks"),
        },
    }


@router.post("/correlations", response_model=OpsCorrelationOut, dependencies=[Depends(require("ops-master:correlate"))])
def create_correlation(data: OpsCorrelationIn, request: Request, db: Db, user: Current):
    return correlation_svc.create_correlation(db, user.organization_id, data, user, request)


@router.post(
    "/correlations/batch",
    response_model=OpsCorrelationBatchOut,
    dependencies=[Depends(require("ops-master:correlate"))],
)
def create_correlations_batch(data: OpsCorrelationBatchIn, request: Request, db: Db, user: Current):
    return correlation_svc.create_correlations_batch(db, user.organization_id, data, user, request)


@router.put(
    "/correlations/{correlation_id}",
    response_model=OpsCorrelationOut,
    dependencies=[Depends(require("ops-master:correlate"))],
)
def update_correlation(correlation_id: str, data: OpsCorrelationUpdate, request: Request, db: Db, user: Current):
    return correlation_svc.update_correlation(db, user.organization_id, correlation_id, data, user, request)


@router.post(
    "/correlations/bulk-delete",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:correlate"))],
)
def delete_correlations(data: OpsIDs, request: Request, db: Db, user: Current):
    return correlation_svc.delete_correlations(db, user.organization_id, data.ids, user, request)


@router.post(
    "/correlations/bulk-restore",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:correlate"))],
)
def restore_correlations(data: OpsIDs, request: Request, db: Db, user: Current):
    return correlation_svc.restore_correlations(db, user.organization_id, data.ids, user, request)


@router.post(
    "/correlations/bulk-permanent-delete",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:permanent-delete"))],
)
def purge_correlations(data: OpsIDs, request: Request, db: Db, user: Current):
    """Permanently delete correlations already moved to Deleted entries."""
    return correlation_svc.purge_correlations(db, user.organization_id, data.ids, user, request)


@router.delete(
    "/correlations/{correlation_id}/permanent",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:permanent-delete"))],
)
def purge_single_correlation(correlation_id: str, request: Request, db: Db, user: Current):
    return correlation_svc.purge_correlations(db, user.organization_id, [correlation_id], user, request)


# ---------------------------------------------------------------------------
# Multi-criteria Workspace Code Links (Phase / Operation / Activity / NPT / Cause / Agency / Mark)
# ---------------------------------------------------------------------------


@router.get(
    "/code-links",
    response_model=list[OpsCodeLinkOut],
    dependencies=[Depends(require("ops-master:read"))],
)
def list_code_links(
    db: Db,
    user: Current,
    scope: Literal["", "drilling", "completion"] = "",
    deleted: bool = False,
):
    return correlation_svc.list_code_links(db, user.organization_id, scope=scope, include_deleted=deleted)


@router.post(
    "/code-links",
    response_model=OpsCodeLinkOut,
    dependencies=[Depends(require("ops-master:correlate"))],
)
def create_code_link(data: OpsCodeLinkIn, request: Request, db: Db, user: Current):
    return correlation_svc.create_code_link(db, user.organization_id, data, user, request)


@router.post(
    "/code-links/batch",
    response_model=OpsCodeLinkBatchOut,
    dependencies=[Depends(require("ops-master:correlate"))],
)
def create_code_links_batch(data: OpsCodeLinkBatchIn, request: Request, db: Db, user: Current):
    return correlation_svc.create_code_links_batch(db, user.organization_id, data, user, request)


@router.put(
    "/code-links/{link_id}",
    response_model=OpsCodeLinkOut,
    dependencies=[Depends(require("ops-master:correlate"))],
)
def update_code_link(link_id: str, data: OpsCodeLinkIn, request: Request, db: Db, user: Current):
    return correlation_svc.update_code_link(db, user.organization_id, link_id, data, user, request)


@router.post(
    "/code-links/bulk-delete",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:correlate"))],
)
def delete_code_links(data: OpsIDs, request: Request, db: Db, user: Current):
    return correlation_svc.delete_code_links(db, user.organization_id, data.ids, user, request)


@router.post(
    "/code-links/bulk-restore",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:correlate"))],
)
def restore_code_links(data: OpsIDs, request: Request, db: Db, user: Current):
    return correlation_svc.restore_code_links(db, user.organization_id, data.ids, user, request)


@router.post(
    "/code-links/bulk-permanent-delete",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:permanent-delete"))],
)
def purge_code_links(data: OpsIDs, request: Request, db: Db, user: Current):
    return correlation_svc.purge_code_links(db, user.organization_id, data.ids, user, request)


@router.delete(
    "/code-links/{link_id}/permanent",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:permanent-delete"))],
)
def purge_single_code_link(link_id: str, request: Request, db: Db, user: Current):
    return correlation_svc.purge_code_links(db, user.organization_id, [link_id], user, request)


# ---------------------------------------------------------------------------
# Multi-day Well Operation Summary & Offline AI Review
# ---------------------------------------------------------------------------
@router.get(
    "/summary",
    response_model=OpsWellSummaryOut,
    dependencies=[Depends(require("ops-report:read"))],
)
def well_summary(
    db: Db,
    user: Current,
    well_id: Annotated[str, Query(min_length=1, max_length=36)],
    scope: Literal["", "drilling", "completion"] = "",
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    include_drafts: bool = True,
):
    return summary_svc.well_operation_summary(
        db,
        user.organization_id,
        well_id=well_id,
        scope=scope or None,
        date_from=date_from,
        date_to=date_to,
        include_drafts=include_drafts,
    )


@router.post(
    "/summary/export-audit",
    status_code=204,
    dependencies=[Depends(require_any("ops-report:export", "ops-analytics:export"))],
)
def summary_export_audit(data: OpsExportAudit, request: Request, db: Db, user: Current):
    audit_record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="export",
        entity_type="ops_summary",
        entity_id=None,
        entity_label=data.format,
        summary=f"Exported Well Operation Summary ({data.record_count} rows) as {data.format.upper()}",
        request=request,
    )
    db.commit()


@router.post(
    "/ai-review",
    response_model=OpsAiReviewOut,
    dependencies=[Depends(require_any("ops-report:read", "ops-analytics:read"))],
)
def operations_ai_review(data: OpsAiReviewRequest, request: Request, db: Db, user: Current):
    return ops_ai_svc.run_ai_review(
        db,
        user.organization_id,
        user,
        data,
        request=request,
    )


# ---------------------------------------------------------------------------
# Dashboard / analytics
# ---------------------------------------------------------------------------
@router.get("/dashboard", response_model=OpsDashboardOut, dependencies=[Depends(require("ops-dashboard:read"))])
def dashboard(
    db: Db,
    user: Current,
    well_id: str = "",
    rig_id: str = "",
    scope: Literal["", "drilling", "completion"] = "",
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
):
    result = analytics_svc.dashboard(
        db,
        user.organization_id,
        well_id=well_id or None,
        rig_id=rig_id or None,
        date_from=date_from,
        date_to=date_to,
        scope=scope or None,
    )
    result["recent_reports"] = (
        [_to_report_out(report, db) for report in result["recent_reports"]]
        if owner(user) or "ops-report:read" in granted(user)
        else []
    )
    return result


@router.get(
    "/analytics/time-depth",
    response_model=OpsTimeDepthOut,
    dependencies=[Depends(require("ops-analytics:read"))],
)
def time_depth(
    db: Db,
    user: Current,
    well_id: str = Query(..., min_length=1),
    scope: Literal["drilling", "completion"] = Query("drilling"),
):
    return analytics_svc.time_depth(db, user.organization_id, well_id, scope)


# ---------------------------------------------------------------------------
# Well path and well diagram
# ---------------------------------------------------------------------------
@router.get(
    "/well-path",
    response_model=OpsWellPathOut,
    dependencies=[Depends(require_any("ops-dashboard:read", "ops-report:read", "ops-analytics:read"))],
)
def well_path(
    db: Db,
    user: Current,
    well_id: str = Query(..., min_length=1),
    scope: Literal["drilling", "completion"] = Query("drilling"),
    vs_azimuth: float | None = Query(default=None, ge=0, le=360),
):
    """Trajectory, casing diagram, current depth and planned curve for one well.

    Read-only geometry: surveys are integrated with minimum curvature and every
    number names its source. The same service feeds the Operations Dashboard
    cards, so the drawing and the KPI cannot disagree.
    """
    return well_path_svc.well_path(
        db, user.organization_id, well_id, scope, vertical_section_azimuth=vs_azimuth
    )


@router.get(
    "/well-diagram",
    response_model=OpsWellDiagramOut,
    dependencies=[Depends(require_any("ops-dashboard:read", "ops-report:read", "ops-analytics:read"))],
)
def well_diagram(
    db: Db,
    user: Current,
    scope: Literal["drilling", "completion"] = Query("drilling"),
    rig_id: str = "",
    well_id: str = "",
):
    """Every well in the current filter, drawn from its own surveys and casing seats."""
    from app.models.rig_well import Well

    stmt = select(Well).where(
        Well.organization_id == user.organization_id,
        Well.is_deleted.is_(False),
    )
    if rig_id:
        stmt = stmt.where(Well.rig_id == rig_id)
    if well_id:
        stmt = stmt.where(Well.id == well_id)
    wells = db.scalars(stmt.order_by(Well.well_code.asc())).all()
    drawn = [
        well_path_svc.well_path(db, user.organization_id, well.id, scope)
        for well in wells
        if scope_svc.available(well, scope)
    ]
    return {"scope": scope, "wells": drawn}


# ---------------------------------------------------------------------------
# Masters
# ---------------------------------------------------------------------------
MASTER_SCHEMAS = {
    "operations": OpsOperationIn,
    "sub-phases": OpsSubPhaseIn,
    "agencies": OpsAgencyIn,
    "causes": OpsCauseIn,
    "source-marks": OpsMarkRuleIn,
}


def _master_kind(kind: str) -> str:
    allowed = MASTER_SCHEMAS
    if kind not in allowed:
        from fastapi import HTTPException

        raise HTTPException(404, f"Unknown master kind '{kind}'")
    return kind


@router.get(
    '/default-codes', response_model=list[OpsDefaultCodeOut],
    dependencies=[Depends(require('ops-master:read'))],
)
def default_codes():
    return catalogue_rows()


@router.get("/masters/{kind}", dependencies=[Depends(require("ops-master:read"))])
def list_masters(kind: str, db: Db, user: Current, include_deleted: bool = False):
    kind = _master_kind(kind)
    if kind == "operations":
        # A workspace starts with the printed downtime vocabulary, once.
        masters_svc.ensure_default_operations(db, user.organization_id)
    rows = masters_svc.list_masters(db, user.organization_id, kind, include_deleted=include_deleted)
    return [masters_svc.serialize_master(row) for row in rows]


@router.post("/masters/{kind}", dependencies=[Depends(require("ops-master:create"))])
def create_master(kind: str, request: Request, db: Db, user: Current, payload: dict):
    kind = _master_kind(kind)
    model_cls = MASTER_SCHEMAS[kind]
    try:
        data = model_cls.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False)) from exc
    row = masters_svc.create_master(db, user.organization_id, kind, data, user, request)
    return masters_svc.serialize_master(row)


@router.put("/masters/{kind}/{record_id}", dependencies=[Depends(require("ops-master:update"))])
def update_master(kind: str, record_id: str, request: Request, db: Db, user: Current, payload: dict):
    kind = _master_kind(kind)
    model_cls = MASTER_SCHEMAS[kind]
    try:
        data = model_cls.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False)) from exc
    row = masters_svc.update_master(db, user.organization_id, kind, record_id, data, user, request)
    return masters_svc.serialize_master(row)


@router.post(
    "/masters/{kind}/import", response_model=OpsImportOut, dependencies=[Depends(require("ops-master:import"))]
)
def import_codes(
    kind: str,
    rows: Annotated[list[dict], Field(min_length=1, max_length=2000)],
    request: Request,
    db: Db,
    user: Current,
):
    """Import a Code Library list from a spreadsheet.

    Every published column is accepted: a blank optional cell keeps the schema
    default instead of clearing the field, ``Phase`` resolves to a Master Data
    phase for sub-phases (the page shows it beside every row), and booleans read
    yes/no. A row that cannot be read is reported with its own number and the
    rest of the file is still imported, so one bad line does not cost a 500-row
    list.
    """
    kind = _master_kind(kind)
    schema = MASTER_SCHEMAS[kind]
    errors: list[str] = []
    created = 0
    for idx, row in enumerate(rows, 2):
        try:
            payload = masters_svc.normalise_import_row(kind, row)
            if kind == "sub-phases":
                payload["phase_id"] = masters_svc.resolve_import_phase(db, user.organization_id, payload)
            data = schema.model_validate(payload)
            masters_svc.create_master(db, user.organization_id, kind, data, user, request)
            created += 1
        except (HTTPException, ValidationError, ValueError) as exc:
            if isinstance(exc, HTTPException):
                detail = exc.detail
            elif isinstance(exc, ValidationError):
                first = exc.errors()[0]
                location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
                detail = f"{location}: {first['msg']}" if location else str(first["msg"])
            else:
                detail = str(exc)
            errors.append(f"Row {idx}: {detail}")
    audit_record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="import",
        entity_type="ops_master",
        entity_id=None,
        entity_label=kind,
        summary=f"Imported {created} codes; {len(errors)} rejected",
        request=request,
    )
    db.commit()
    return {"created_count": created, "errors": errors}


@router.get("/masters/{kind}/import-template", dependencies=[Depends(require("ops-master:import"))])
def code_import_template(kind: str):
    """The exact columns this list's import accepts, in the order the page prints them.

    Serving the template from the same map the importer reads means the file a
    user downloads can never drift from the file the server accepts.
    """
    kind = _master_kind(kind)
    spec = masters_svc.IMPORT_COLUMNS[kind]
    required = list(spec["required"])
    optional = list(spec["optional"])
    if kind == "sub-phases":
        # ``phase_name`` is an accepted alternative to ``phase_code``; the template
        # prints the code, because it is the identifier that cannot be ambiguous.
        optional = [column for column in optional if column != "phase_name"]
    return {
        "kind": kind,
        "required": required,
        "optional": optional,
        "columns": required + optional,
        "aliases": spec["aliases"],
    }


@router.post(
    "/masters/{kind}/bulk-delete",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:delete"))],
)
def bulk_delete_masters(kind: str, data: OpsIDs, request: Request, db: Db, user: Current):
    kind = _master_kind(kind)
    return masters_svc.delete_masters(db, user.organization_id, kind, data.ids, user, request)


@router.post(
    "/masters/{kind}/bulk-restore",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:restore"))],
)
def bulk_restore_masters(kind: str, data: OpsIDs, request: Request, db: Db, user: Current):
    kind = _master_kind(kind)
    return masters_svc.restore_masters(db, user.organization_id, kind, data.ids, user, request)


@router.post(
    "/masters/{kind}/bulk-permanent-delete",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:permanent-delete"))],
)
def bulk_purge_masters(kind: str, data: OpsIDs, request: Request, db: Db, user: Current):
    """Permanently delete soft-deleted workspace codes that have no active or historical references."""
    kind = _master_kind(kind)
    return masters_svc.purge_masters(db, user.organization_id, kind, data.ids, user, request)


@router.delete(
    "/masters/{kind}/{record_id}/permanent",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-master:permanent-delete"))],
)
def purge_single_master(kind: str, record_id: str, request: Request, db: Db, user: Current):
    kind = _master_kind(kind)
    return masters_svc.purge_masters(db, user.organization_id, kind, [record_id], user, request)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------
@router.get("/plans", response_model=list[OpsPlanVersionOut], dependencies=[Depends(require("ops-plan:read"))])
def list_plans(db: Db, user: Current, well_id: str = "", scope: str = "", deleted: bool = False):
    rows = plans_svc.list_plans(
        db, user.organization_id, well_id=well_id or None, scope=scope or None, deleted=deleted
    )
    return [_plan_out(row) for row in rows]


def _plan_out(r):
    return {
        **{
            k: getattr(r, k) for k in OpsPlanVersionOut.model_fields if k not in ("items", "well_code", "well_name")
        },
        "well_code": r._well_code,
        "well_name": r._well_name,
        "items": [{"id": i.id, **{k: getattr(i, k) for k in OpsPlanItemIn.model_fields}} for i in r._items],
    }


@router.get('/plans/{plan_id}', response_model=OpsPlanVersionOut, dependencies=[Depends(require('ops-plan:read'))])
def get_plan(plan_id: str, db: Db, user: Current):
    return _plan_out(plans_svc.get_plan(db, user.organization_id, plan_id, include_deleted=True))


@router.post("/plans", response_model=OpsPlanVersionOut, dependencies=[Depends(require("ops-plan:create"))])
def create_plan(data: OpsPlanVersionIn, request: Request, db: Db, user: Current):
    return _plan_out(plans_svc.create_plan(db, user.organization_id, data, user, request))


@router.put("/plans/{plan_id}", response_model=OpsPlanVersionOut, dependencies=[Depends(require("ops-plan:update"))])
def update_plan(plan_id: str, data: OpsPlanUpdateIn, request: Request, db: Db, user: Current):
    updated = plans_svc.update_plan(db, user.organization_id, plan_id, data, user, request)
    return _plan_out(plans_svc.get_plan(db, user.organization_id, updated.id))


@router.post(
    "/plans/{plan_id}/reopen",
    response_model=OpsPlanVersionOut,
    dependencies=[Depends(require("ops-plan:reopen"))],
)
def reopen_plan(plan_id: str, data: OpsReopenIn, request: Request, db: Db, user: Current):
    reopened = plans_svc.reopen_plan(db, user.organization_id, plan_id, data.remarks, user, request)
    return _plan_out(plans_svc.get_plan(db, user.organization_id, reopened.id))


@router.post('/plans/{plan_id}/study', response_model=OpsStudyOut, dependencies=[Depends(require('ops-plan:read'))])
def study_plan(plan_id: str, data: OpsPlanStudyRequest, request: Request, db: Db, user: Current):
    plan = plans_svc.get_plan(db, user.organization_id, plan_id, include_deleted=True)
    if data.items is not None:
        require('ops-plan:update')(user)
        if plan.is_deleted or plan.status != 'draft':
            raise HTTPException(409, 'Preview rows can only be studied on a draft timeline.')
    items = data.items if data.items is not None else plan._items
    result = timeline_study(items, has_start=plan.planned_start_at is not None, scope=plan.scope)
    return with_ai(result, db, user, request, entity_type='ops_plan', entity_id=plan_id, use_ai=data.use_ai)


@router.post("/plans/{plan_id}/import-preview", dependencies=[Depends(require("ops-plan:import"))])
def preview_timeline(
    plan_id: str, db: Db, user: Current, file: Annotated[UploadFile, File()], sheet: str = Form("")
):
    plan = plans_svc.get_plan(db, user.organization_id, plan_id)
    if plan.status != "draft":
        raise HTTPException(409, "Import into a draft timeline.")
    content = file.file.read(10 * 1024**2 + 1)
    if len(content) > 10 * 1024**2:
        raise HTTPException(413, "Timeline file must be at most 10 MB.")
    try:
        return timeline_preview(file.filename or "", content, sheet)
    except Exception as exc:
        raise HTTPException(
            422,
            str(exc)
            if isinstance(exc, ValueError)
            else "Cannot read workbook. Provide an unencrypted .xlsx or .csv file.",
        ) from exc


@router.put("/plans/{plan_id}/items", dependencies=[Depends(require("ops-plan:update"))])
def save_timeline(
    plan_id: str,
    items: Annotated[list[OpsPlanItemIn], Field(min_length=1, max_length=2000)],
    request: Request,
    db: Db,
    user: Current,
):
    plans_svc.replace_items(db, user.organization_id, plan_id, items, user, request)
    return {"saved": len(items)}


@router.post("/plans/{plan_id}/items", dependencies=[Depends(require("ops-plan:update"))])
def add_plan_item(plan_id: str, data: OpsPlanItemIn, request: Request, db: Db, user: Current):
    plans_svc.add_plan_item(db, user.organization_id, plan_id, data, user, request)
    return {"ok": True}


@router.post(
    "/plans/{plan_id}/activate",
    response_model=OpsPlanVersionOut,
    dependencies=[Depends(require("ops-plan:activate"))],
)
def activate_plan(plan_id: str, request: Request, db: Db, user: Current):
    r = plans_svc.activate_plan(db, user.organization_id, plan_id, user, request)
    full = plans_svc.get_plan(db, user.organization_id, r.id)
    return _plan_out(full)


@router.delete("/plans/{plan_id}", dependencies=[Depends(require("ops-plan:delete"))])
def delete_plan(plan_id: str, request: Request, db: Db, user: Current):
    return plans_svc.delete_plan(db, user.organization_id, plan_id, user, request)


@router.post(
    "/plans/{plan_id}/restore", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-plan:restore"))]
)
def restore_plan(plan_id: str, db: Db, user: Current, request: Request):
    return plans_svc.restore_plan(db, user.organization_id, plan_id, user, request)


@router.post(
    "/plans/bulk-permanent-delete",
    response_model=OpsBulkActionOut,
    dependencies=[Depends(require("ops-plan:permanent-delete"))],
)
def purge_plans(data: OpsIDs, request: Request, db: Db, user: Current):
    """Permanently remove timelines already in Deleted entries."""
    return plans_svc.purge_plans(db, user.organization_id, data.ids, user, request)


@router.post(
    "/reports/{report_id}/print-audit",
    status_code=204,
    dependencies=[Depends(require("ops-report:read")), Depends(require("ops-report:print"))],
)
def print_report(report_id: str, db: Db, user: Current, request: Request, include_deleted: bool = False):
    report = reports_svc.get_report(db, user.organization_id, report_id, include_deleted=include_deleted)
    audit_record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="print",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=report.report_no_text,
        summary="Exported printable daily operations report",
        request=request,
    )
    db.commit()


def export_audit(resource):
    def audit(data: OpsExportAudit, request: Request, db: Db, user: Current):
        audit_record(
            db,
            organization_id=user.organization_id,
            actor=user,
            action="export",
            entity_type=resource,
            entity_id=None,
            entity_label=data.format,
            summary=f"Exported {data.record_count} rows as {data.format}",
            request=request,
        )
        db.commit()

    return audit


for path, resource in [
    ("reports", "ops-report"),
    ("documents", "ops-doc"),
    ("plans", "ops-plan"),
    ("library", "ops-master"),
    ("analytics", "ops-analytics"),
]:
    router.add_api_route(
        f"/{path}/export-audit",
        export_audit(resource),
        methods=["POST"],
        status_code=204,
        dependencies=[Depends(require(f"{resource}:export"))],
        name=f"{resource}_export_audit",
    )
