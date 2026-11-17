"""Well Operations API — documents, reports, analytics, masters, plans."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from app.api.deps import Current, Db, require
from app.schemas.operations import (
    OpsAgencyIn,
    OpsAgencyOut,
    OpsBulkActionOut,
    OpsCauseIn,
    OpsCauseOut,
    OpsDocumentOut,
    OpsExtractionJobOut,
    OpsImportOut,
    OpsImportRequest,
    OpsNptCodeIn,
    OpsNptCodeOut,
    OpsOperationCodeIn,
    OpsOperationCodeOut,
    OpsPlanVersionIn,
    OpsPlanVersionOut,
    OpsPlanItemIn,
    OpsReferenceOut,
    OpsReportCreate,
    OpsReportOut,
    OpsReportSaveIn,
    OpsSettingsIn,
    OpsSettingsOut,
    OpsIDs,
    OpsRejectIn,
    OpsActivityCodeIn,
    OpsActivityCodeOut,
)
from app.services.operations import analytics as analytics_svc
from app.services.operations import documents as docs_svc
from app.services.operations import extraction as extract_svc
from app.services.operations import masters as masters_svc
from app.services.operations import plans as plans_svc
from app.services.operations import reports as reports_svc
from app.services.operations import settings as settings_svc

router = APIRouter(prefix="/operations", tags=["Well Operations"])


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
    scope: str = "",
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


@router.get("/documents/deleted", response_model=list[OpsDocumentOut], dependencies=[Depends(require("ops-doc:read"))])
def list_deleted_documents(db: Db, user: Current):
    from sqlalchemy import select
    from app.models.operations import OpsDocument

    rows = db.scalars(select(OpsDocument).where(OpsDocument.organization_id == user.organization_id, OpsDocument.is_deleted.is_(True)).order_by(OpsDocument.deleted_at.desc())).all()
    return rows


@router.get("/documents/{document_id}", response_model=OpsDocumentOut, dependencies=[Depends(require("ops-doc:read"))])
def get_document(document_id: str, db: Db, user: Current):
    return docs_svc.get_document(db, user.organization_id, document_id)


@router.get("/documents/{document_id}/download", dependencies=[Depends(require("ops-doc:read"))])
def download_document(document_id: str, db: Db, user: Current):
    from fastapi.responses import Response

    doc = docs_svc.download_document(db, user.organization_id, document_id)
    return Response(content=doc.content or b"", media_type=doc.content_type, headers={"Content-Disposition": f'attachment; filename="{doc.file_name}"'})


@router.post("/documents/upload", response_model=OpsDocumentOut, dependencies=[Depends(require("ops-doc:upload"))])
async def upload_document(
    request: Request,
    db: Db,
    user: Current,
    file: UploadFile = File(...),
    well_id: str = Form(""),
    rig_id: str = Form(""),
    scope: str = Form("drilling"),
    document_type: str = Form("DDR"),
    document_date: str = Form(""),
    report_no_text: str = Form(""),
    notes: str = Form(""),
):
    content = await file.read()
    doc_date = None
    if document_date:
        try:
            doc_date = date.fromisoformat(document_date)
        except Exception:
            pass
    doc, deduped, _ = docs_svc.upload_document(
        db,
        user.organization_id,
        file_bytes=content,
        file_name=file.filename or "upload.pdf",
        content_type=file.content_type or "application/pdf",
        well_id=well_id or None,
        rig_id=rig_id or None,
        scope=scope or "drilling",
        document_type=document_type or "DDR",
        document_date=doc_date,
        report_no_text=report_no_text or "",
        notes=notes or "",
        user=user,
        request=request,
    )
    # Auto-extract if enabled
    from app.models.operations import OpsSettings
    from sqlalchemy import select

    settings = db.scalar(select(OpsSettings).where(OpsSettings.organization_id == user.organization_id))
    auto = settings.auto_extract_on_upload if settings else True
    if auto and not deduped:
        try:
            extract_svc.run_extraction(db, user.organization_id, doc, user, request)
        except Exception:
            pass
        db.refresh(doc)
    return doc


@router.post("/documents/{document_id}/extract", response_model=OpsExtractionJobOut, dependencies=[Depends(require("ops-doc:extract"))])
def extract_document(document_id: str, request: Request, db: Db, user: Current):
    doc = docs_svc.get_document(db, user.organization_id, document_id)
    job = extract_svc.run_extraction(db, user.organization_id, doc, user, request)
    return job


@router.get("/documents/{document_id}/extractions", response_model=list[OpsExtractionJobOut], dependencies=[Depends(require("ops-doc:read"))])
def list_extractions(document_id: str, db: Db, user: Current):
    from sqlalchemy import select
    from app.models.operations import OpsExtractionJob

    docs_svc.get_document(db, user.organization_id, document_id)  # ensure exists
    jobs = db.scalars(select(OpsExtractionJob).where(OpsExtractionJob.organization_id == user.organization_id, OpsExtractionJob.document_id == document_id).order_by(OpsExtractionJob.created_at.desc())).all()
    return jobs


@router.post("/documents/bulk-delete", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-doc:delete"))])
def bulk_delete_documents(data: OpsIDs, request: Request, db: Db, user: Current):
    result = docs_svc.delete_documents(db, user.organization_id, data.ids, user, request)
    return result


@router.post("/documents/bulk-restore", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-doc:restore"))])
def bulk_restore_documents(data: OpsIDs, request: Request, db: Db, user: Current):
    result = docs_svc.restore_documents(db, user.organization_id, data.ids, user, request)
    return result


@router.post("/documents/bulk-permanent-delete", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-doc:permanent-delete"))])
def bulk_purge_documents(data: OpsIDs, request: Request, db: Db, user: Current):
    result = docs_svc.purge_documents(db, user.organization_id, data.ids, user, request)
    return result


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def _to_report_out(report):
    blocks = getattr(report, "_blocks", []) or []
    # Enrich block with op/npt names if needed
    # Already handled via service enrichment lazy
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
        "tvd_m": report.tvd_m,
        "progress_m": report.progress_m,
        "rotating_hours": report.rotating_hours,
        "dfs_days": report.dfs_days,
        "est_days": report.est_days,
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
        "blocks": [
            {
                "id": b.id,
                "organization_id": b.organization_id,
                "report_id": b.report_id,
                "sequence_no": b.sequence_no,
                "started_at": b.started_at,
                "ended_at": b.ended_at,
                "duration_minutes": b.duration_minutes,
                "phase_raw": b.phase_raw or "",
                "operation_code_id": b.operation_code_id,
                "activity_code_id": b.activity_code_id,
                "activity_id": b.activity_id,
                "classification": b.classification,
                "allocation": b.allocation,
                "is_productive": b.is_productive,
                "classification_source": b.classification_source or "keyword",
                "npt_code_id": b.npt_code_id,
                "npt_code_snapshot": b.npt_code_snapshot or "",
                "agency_id": b.agency_id,
                "cause_code": b.cause_code or "",
                "hole_section_id": b.hole_section_id,
                "phase_id": b.phase_id,
                "depth_from_m": b.depth_from_m,
                "depth_to_m": b.depth_to_m,
                "depth_unit": b.depth_unit or "m",
                "footage_m": b.footage_m,
                "bit_depth_m": b.bit_depth_m,
                "rotating_hours": b.rotating_hours,
                "rop_m_per_hr": b.rop_m_per_hr,
                "rop_basis": b.rop_basis or "rotating",
                "responsible_party": b.responsible_party or "",
                "vendor_id": b.vendor_id,
                "reason": b.reason or "",
                "narrative": b.narrative or "",
                "source_page": b.source_page or 0,
                "source_bbox": b.source_bbox or "",
                "confidence": b.confidence,
                "review_state": b.review_state or "suggested",
                "reviewer_user_id": b.reviewer_user_id,
                "reviewed_at": b.reviewed_at,
                "is_deleted": b.is_deleted,
                "created_at": b.created_at,
                "updated_at": b.updated_at,
            }
            for b in blocks
        ],
        "unaccounted_minutes": unacc,
        "total_block_minutes": total,
    }


@router.get("/reports", response_model=list[OpsReportOut], dependencies=[Depends(require("ops-report:read"))])
def list_reports(
    db: Db,
    user: Current,
    well_id: str = "",
    rig_id: str = "",
    scope: str = "",
    status: str = "",
    report_type: str = "",
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
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
    return [_to_report_out(r) for r in rows]


@router.get("/reports/deleted", response_model=list[OpsReportOut], dependencies=[Depends(require("ops-report:read"))])
def list_deleted_reports(db: Db, user: Current):
    rows = reports_svc.list_reports(db, user.organization_id, include_deleted=True)
    deleted = [r for r in rows if r.is_deleted]
    return [_to_report_out(r) for r in deleted]


@router.get("/reports/{report_id}", response_model=OpsReportOut, dependencies=[Depends(require("ops-report:read"))])
def get_report(report_id: str, db: Db, user: Current):
    r = reports_svc.get_report(db, user.organization_id, report_id)
    return _to_report_out(r)


@router.post("/reports", response_model=OpsReportOut, dependencies=[Depends(require("ops-report:create"))])
def create_report(data: OpsReportCreate, request: Request, db: Db, user: Current):
    r = reports_svc.create_report(db, user.organization_id, data, user, request)
    # Return enriched
    full = reports_svc.get_report(db, user.organization_id, r.id)
    return _to_report_out(full)


@router.put("/reports/{report_id}", response_model=OpsReportOut, dependencies=[Depends(require("ops-report:update"))])
def save_report(report_id: str, data: OpsReportSaveIn, request: Request, db: Db, user: Current):
    r = reports_svc.save_report(db, user.organization_id, report_id, data, user, request)
    return _to_report_out(r)


@router.post("/reports/{report_id}/submit", response_model=OpsReportOut, dependencies=[Depends(require("ops-report:submit"))])
def submit_report(report_id: str, request: Request, db: Db, user: Current):
    r = reports_svc.submit_report(db, user.organization_id, report_id, user, request)
    full = reports_svc.get_report(db, user.organization_id, r.id)
    return _to_report_out(full)


@router.post("/reports/{report_id}/approve", response_model=OpsReportOut, dependencies=[Depends(require("ops-report:approve"))])
def approve_report(report_id: str, request: Request, db: Db, user: Current):
    r = reports_svc.approve_report(db, user.organization_id, report_id, user, request)
    full = reports_svc.get_report(db, user.organization_id, r.id)
    return _to_report_out(full)


@router.post("/reports/{report_id}/reject", response_model=OpsReportOut, dependencies=[Depends(require("ops-report:approve"))])
def reject_report(report_id: str, data: OpsRejectIn, request: Request, db: Db, user: Current):
    r = reports_svc.reject_report(db, user.organization_id, report_id, data.reason, user, request)
    full = reports_svc.get_report(db, user.organization_id, r.id)
    return _to_report_out(full)


@router.get("/reports/{report_id}/brief", dependencies=[Depends(require("ops-report:read"))])
def get_brief(report_id: str, db: Db, user: Current):
    return reports_svc.brief_for_report(db, user.organization_id, report_id)


@router.post("/reports/bulk-delete", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-report:delete"))])
def bulk_delete(data: OpsIDs, request: Request, db: Db, user: Current):
    return reports_svc.delete_reports(db, user.organization_id, data.ids, user, request)


@router.post("/reports/bulk-restore", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-report:restore"))])
def bulk_restore(data: OpsIDs, request: Request, db: Db, user: Current):
    return reports_svc.restore_reports(db, user.organization_id, data.ids, user, request)


@router.post("/reports/bulk-permanent-delete", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-report:permanent-delete"))])
def bulk_purge(data: OpsIDs, request: Request, db: Db, user: Current):
    return reports_svc.purge_reports(db, user.organization_id, data.ids, user, request)


@router.post("/reports/import", response_model=OpsImportOut, dependencies=[Depends(require("ops-report:import"))])
def import_reports(data: OpsImportRequest, request: Request, db: Db, user: Current):
    from sqlalchemy import select
    from app.models.rig_well import Rig, Well

    errors: list[str] = []
    created = 0
    rigs = {r.rig_code.lower(): r for r in db.scalars(select(Rig).where(Rig.organization_id == user.organization_id, Rig.is_deleted.is_(False))).all()}
    wells = {w.well_code.lower(): w for w in db.scalars(select(Well).where(Well.organization_id == user.organization_id, Well.is_deleted.is_(False))).all()}
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

            exists = db.scalar(sel(OpsDailyReport).where(OpsDailyReport.organization_id == user.organization_id, OpsDailyReport.well_id == well.id, OpsDailyReport.scope == row.scope, OpsDailyReport.report_date == row.report_date, OpsDailyReport.is_deleted.is_(False)))
            if exists:
                raise ValueError("Report for this well/scope/date already exists")
            payload = OpsReportCreate(
                well_id=well.id,
                rig_id=rig.id if rig else None,
                scope=row.scope,  # type: ignore
                report_date=row.report_date,
                report_no_text=row.report_no_text or "",
                depth_start_m=row.depth_start_m,
                depth_end_m=row.depth_end_m,
                operation_summary=row.operation_summary or "",
            )
            reports_svc.create_report(db, user.organization_id, payload, user, request)
            created += 1
        except Exception as ex:
            detail = getattr(ex, "detail", str(ex))
            errors.append(f"Row {idx}: {detail}")
    if errors and created == 0:
        # partial failure handled — still return
        pass
    # Need to commit already done per create_report; ensure flush
    return {"created_count": created, "errors": errors}


@router.get("/reference", response_model=OpsReferenceOut, dependencies=[Depends(require("ops-report:read"))])
def reference(db: Db, user: Current):
    from sqlalchemy import select
    from app.models.operations import OpsOperationCode, OpsNptCode, OpsAgency, OpsCause
    from app.models.master_data import HoleSection, Phase, Activity
    from app.models.rig_well import Rig, Well

    rigs = db.scalars(select(Rig).where(Rig.organization_id == user.organization_id, Rig.is_deleted.is_(False)).order_by(Rig.rig_code)).all()
    wells = db.scalars(select(Well).where(Well.organization_id == user.organization_id, Well.is_deleted.is_(False)).order_by(Well.well_code)).all()
    hole_sections = db.scalars(select(HoleSection).where(HoleSection.organization_id == user.organization_id, HoleSection.is_deleted.is_(False)).order_by(HoleSection.section_code)).all()
    phases = db.scalars(select(Phase).where(Phase.organization_id == user.organization_id, Phase.is_deleted.is_(False)).order_by(Phase.phase_code)).all()
    activities = db.scalars(select(Activity).where(Activity.organization_id == user.organization_id, Activity.is_deleted.is_(False)).order_by(Activity.activity_code)).all()
    op_codes = db.scalars(select(OpsOperationCode).where(OpsOperationCode.organization_id == user.organization_id, OpsOperationCode.is_deleted.is_(False)).order_by(OpsOperationCode.sort_order)).all()
    npt_codes = db.scalars(select(OpsNptCode).where(OpsNptCode.organization_id == user.organization_id, OpsNptCode.is_deleted.is_(False)).order_by(OpsNptCode.sort_order)).all()
    agencies = db.scalars(select(OpsAgency).where(OpsAgency.organization_id == user.organization_id, OpsAgency.is_deleted.is_(False)).order_by(OpsAgency.sort_order)).all()
    causes = db.scalars(select(OpsCause).where(OpsCause.organization_id == user.organization_id, OpsCause.is_deleted.is_(False)).order_by(OpsCause.sort_order)).all()

    return {
        "rigs": [{"id": r.id, "rig_code": r.rig_code, "rig_name": r.rig_name, "display_name": f"{r.rig_code} — {r.rig_name}"} for r in rigs],
        "wells": [{"id": w.id, "rig_id": w.rig_id, "block_id": w.block_id, "well_code": w.well_code, "well_name": w.well_name, "display_name": f"{w.well_code} — {w.well_name}", "drilling_available": not w.drilling_is_deleted, "completion_available": not w.completion_is_deleted} for w in wells],
        "hole_sections": [{"id": h.id, "section_code": h.section_code, "section_name": h.section_name} for h in hole_sections],
        "phases": [{"id": p.id, "phase_code": p.phase_code, "phase_name": p.phase_name} for p in phases],
        "operation_codes": op_codes,
        "npt_codes": npt_codes,
        "agencies": agencies,
        "causes": causes,
        "activities": [{"id": a.id, "activity_code": a.activity_code, "activity_name": a.activity_name} for a in activities],
    }


# ---------------------------------------------------------------------------
# Dashboard / analytics
# ---------------------------------------------------------------------------
@router.get("/dashboard", dependencies=[Depends(require("ops-report:read"))])
def dashboard(
    db: Db,
    user: Current,
    well_id: str = "",
    rig_id: str = "",
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
):
    return analytics_svc.dashboard(db, user.organization_id, well_id=well_id or None, rig_id=rig_id or None, date_from=date_from, date_to=date_to)


@router.get("/analytics/time-depth", dependencies=[Depends(require("ops-analytics:read"))])
def time_depth(db: Db, user: Current, well_id: str = Query(..., min_length=1), scope: str = Query("drilling")):
    return analytics_svc.time_depth(db, user.organization_id, well_id, scope)


# ---------------------------------------------------------------------------
# Masters
# ---------------------------------------------------------------------------
def _master_kind(kind: str) -> str:
    allowed = {"operation-codes", "activity-codes", "npt-codes", "agencies", "causes"}
    if kind not in allowed:
        from fastapi import HTTPException

        raise HTTPException(404, f"Unknown master kind '{kind}'")
    return kind


@router.get("/masters/{kind}", dependencies=[Depends(require("ops-master:read"))])
def list_masters(kind: str, db: Db, user: Current, include_deleted: bool = False):
    kind = _master_kind(kind)
    rows = masters_svc.list_masters(db, user.organization_id, kind, include_deleted=include_deleted)
    return rows


@router.post("/masters/{kind}", dependencies=[Depends(require("ops-master:create"))])
def create_master(kind: str, request: Request, db: Db, user: Current, payload: dict):
    kind = _master_kind(kind)
    # Build typed model
    mapping = {
        "operation-codes": OpsOperationCodeIn,
        "activity-codes": OpsActivityCodeIn,
        "npt-codes": OpsNptCodeIn,
        "agencies": OpsAgencyIn,
        "causes": OpsCauseIn,
    }
    model_cls = mapping[kind]
    data = model_cls.model_validate(payload)
    return masters_svc.create_master(db, user.organization_id, kind, data, user, request)


@router.put("/masters/{kind}/{record_id}", dependencies=[Depends(require("ops-master:update"))])
def update_master(kind: str, record_id: str, request: Request, db: Db, user: Current, payload: dict):
    kind = _master_kind(kind)
    mapping = {
        "operation-codes": OpsOperationCodeIn,
        "activity-codes": OpsActivityCodeIn,
        "npt-codes": OpsNptCodeIn,
        "agencies": OpsAgencyIn,
        "causes": OpsCauseIn,
    }
    model_cls = mapping[kind]
    data = model_cls.model_validate(payload)
    return masters_svc.update_master(db, user.organization_id, kind, record_id, data, user, request)


@router.post("/masters/{kind}/bulk-delete", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-master:delete"))])
def bulk_delete_masters(kind: str, data: OpsIDs, request: Request, db: Db, user: Current):
    kind = _master_kind(kind)
    return masters_svc.delete_masters(db, user.organization_id, kind, data.ids, user, request)


@router.post("/masters/{kind}/bulk-restore", response_model=OpsBulkActionOut, dependencies=[Depends(require("ops-master:delete"))])
def bulk_restore_masters(kind: str, data: OpsIDs, request: Request, db: Db, user: Current):
    kind = _master_kind(kind)
    return masters_svc.restore_masters(db, user.organization_id, kind, data.ids, user, request)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------
@router.get("/plans", response_model=list[OpsPlanVersionOut], dependencies=[Depends(require("ops-plan:read"))])
def list_plans(db: Db, user: Current, well_id: str = "", scope: str = ""):
    rows = plans_svc.list_plans(db, user.organization_id, well_id=well_id or None, scope=scope or None)
    out = []
    for r in rows:
        items = getattr(r, "_items", []) or []
        out.append(
            {
                "id": r.id,
                "organization_id": r.organization_id,
                "well_id": r.well_id,
                "scope": r.scope,
                "version_no": r.version_no,
                "label": r.label,
                "basis": r.basis,
                "status": r.status,
                "planned_start_at": r.planned_start_at,
                "planned_days": r.planned_days,
                "notes": r.notes or "",
                "is_deleted": r.is_deleted,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
                "well_code": getattr(r, "_well_code", ""),
                "well_name": getattr(r, "_well_name", ""),
                "items": [
                    {
                        "id": it.id,
                        "sequence_no": it.sequence_no,
                        "description": it.description,
                        "hole_section_id": it.hole_section_id,
                        "phase_id": it.phase_id,
                        "target_depth_m": str(it.target_depth_m) if it.target_depth_m else None,
                        "delta_depth_m": str(it.delta_depth_m) if it.delta_depth_m else None,
                        "planned_hours": str(it.planned_hours) if it.planned_hours else "0",
                        "cum_planned_days": str(it.cum_planned_days) if it.cum_planned_days else None,
                        "rop_assumption_m_per_hr": str(it.rop_assumption_m_per_hr) if it.rop_assumption_m_per_hr else None,
                    }
                    for it in items
                ],
            }
        )
    return out  # type: ignore


@router.post("/plans", response_model=OpsPlanVersionOut, dependencies=[Depends(require("ops-plan:create"))])
def create_plan(data: OpsPlanVersionIn, request: Request, db: Db, user: Current):
    r = plans_svc.create_plan(db, user.organization_id, data, user, request)
    items = getattr(r, "_items", []) or []
    return {
        "id": r.id,
        "organization_id": r.organization_id,
        "well_id": r.well_id,
        "scope": r.scope,
        "version_no": r.version_no,
        "label": r.label,
        "basis": r.basis,
        "status": r.status,
        "planned_start_at": r.planned_start_at,
        "planned_days": r.planned_days,
        "notes": r.notes or "",
        "is_deleted": r.is_deleted,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
        "well_code": getattr(r, "_well_code", ""),
        "well_name": getattr(r, "_well_name", ""),
        "items": [
            {
                "id": it.id,
                "sequence_no": it.sequence_no,
                "description": it.description,
                "target_depth_m": str(it.target_depth_m) if it.target_depth_m else None,
                "planned_hours": str(it.planned_hours),
                "cum_planned_days": str(it.cum_planned_days) if it.cum_planned_days else None,
            }
            for it in items
        ],
    }  # type: ignore


@router.post("/plans/{plan_id}/items", dependencies=[Depends(require("ops-plan:update"))])
def add_plan_item(plan_id: str, data: OpsPlanItemIn, request: Request, db: Db, user: Current):
    r = plans_svc.add_plan_item(db, user.organization_id, plan_id, data, user, request)
    return {"ok": True}


@router.post("/plans/{plan_id}/activate", response_model=OpsPlanVersionOut, dependencies=[Depends(require("ops-plan:activate"))])
def activate_plan(plan_id: str, request: Request, db: Db, user: Current):
    r = plans_svc.activate_plan(db, user.organization_id, plan_id, user, request)
    full = plans_svc.get_plan(db, user.organization_id, r.id)
    items = getattr(full, "_items", []) or []
    return {
        "id": full.id,
        "organization_id": full.organization_id,
        "well_id": full.well_id,
        "scope": full.scope,
        "version_no": full.version_no,
        "label": full.label,
        "basis": full.basis,
        "status": full.status,
        "planned_start_at": full.planned_start_at,
        "planned_days": full.planned_days,
        "notes": full.notes or "",
        "is_deleted": full.is_deleted,
        "created_at": full.created_at,
        "updated_at": full.updated_at,
        "well_code": getattr(full, "_well_code", ""),
        "well_name": getattr(full, "_well_name", ""),
        "items": [],
    }  # type: ignore


@router.delete("/plans/{plan_id}", dependencies=[Depends(require("ops-plan:delete"))])
def delete_plan(plan_id: str, request: Request, db: Db, user: Current):
    return plans_svc.delete_plan(db, user.organization_id, plan_id, user, request)
