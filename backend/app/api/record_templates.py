"""Reusable record templates: AFE estimate, well plan and daily sheet.

The point of this module is speed without retyping: a costing engineer picks the
standard drilling AFE, the standard well plan or the standard daily sheet, fills
only the values that changed, and saves an ordinary record. Nothing downstream
needs to know a template was used — the saved AFE, well plan or daily sheet is
the same record it would have been.
"""

import csv
import io

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import Current, Db, require
from app.schemas.record_template import (
    TemplateApplyIn,
    TemplateApplyPreviewOut,
    TemplateCreate,
    TemplateExportAuditIn,
    TemplateOut,
    TemplateSummaryOut,
    TemplateUpdate,
)
from app.services import audit, record_template as svc

router = APIRouter(prefix="/record-templates", tags=["Reusable Templates"])


@router.get("", response_model=list[TemplateSummaryOut], dependencies=[Depends(require("template:read"))])
def list_templates(db: Db, user: Current, kind: str = Query(default="", max_length=20)) -> list[TemplateSummaryOut]:
    """Every template this user can use: their own plus what the workspace shares."""
    return svc.list_templates(db, user, kind)


@router.get("/export", dependencies=[Depends(require("template:export"))])
def export_templates(db: Db, user: Current, kind: str = Query(default="", max_length=20)) -> Response:
    """The template library as a CSV, one row per line, for review outside the app."""
    rows = svc.export_rows(db, user, kind)
    # One header list for every kind, so the three exports open in the same way.
    headers = [
        "template", "kind", "scope", "line_type", "section_code", "from_depth", "to_depth", "phase_code",
        "days", "item_code", "item_name", "quantity", "currency", "amount", "remarks",
    ]
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.DictWriter(buffer, fieldnames=headers, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    filename = f"record-templates{'-' + kind if kind else ''}-{svc._now().date().isoformat()}.csv"
    return Response(
        content=buffer.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("template:export"))])
def export_audit(data: TemplateExportAuditIn, request: Request, db: Db, user: Current) -> Response:
    audit.record(
        db, organization_id=user.organization_id, actor=user, action="export",
        entity_type="record_template", entity_label="Template library",
        summary=f"Exported the template library as {data.format.upper()} ({data.record_count} rows)",
        request=request,
    )
    db.commit()
    return Response(status_code=204)


@router.get("/{template_id}", response_model=TemplateOut, dependencies=[Depends(require("template:read"))])
def get_template(template_id: str, db: Db, user: Current) -> TemplateOut:
    return svc.get_template(db, user, template_id)


@router.post("", response_model=TemplateOut, status_code=201, dependencies=[Depends(require("template:create"))])
def create_template(data: TemplateCreate, request: Request, db: Db, user: Current) -> TemplateOut:
    return svc.create_template(db, user, data, request)


@router.put("/{template_id}", response_model=TemplateOut, dependencies=[Depends(require("template:update"))])
def update_template(template_id: str, data: TemplateUpdate, request: Request, db: Db, user: Current) -> TemplateOut:
    return svc.update_template(db, user, template_id, data, request)


@router.post("/{template_id}/duplicate", response_model=TemplateOut, status_code=201, dependencies=[Depends(require("template:create"))])
def duplicate_template(template_id: str, request: Request, db: Db, user: Current) -> TemplateOut:
    """Copy a shared template into your own list so you can change it."""
    return svc.duplicate_template(db, user, template_id, request)


@router.delete("/{template_id}", status_code=204, dependencies=[Depends(require("template:delete"))])
def delete_template(template_id: str, request: Request, db: Db, user: Current) -> Response:
    svc.delete_template(db, user, template_id, request)
    return Response(status_code=204)


@router.post("/{template_id}/preview", response_model=TemplateApplyPreviewOut, dependencies=[Depends(require("template:read"))])
def preview_template(template_id: str, data: TemplateApplyIn, db: Db, user: Current) -> TemplateApplyPreviewOut:
    """What applying this template adds, and what is missing — before anything is written."""
    return svc.preview_template(db, user, template_id, data.well_id)


@router.post("/{template_id}/apply", response_model=TemplateSummaryOut, dependencies=[Depends(require("template:read"))])
def record_apply(template_id: str, request: Request, db: Db, user: Current) -> TemplateSummaryOut:
    """Count one use of the template.

    Applying does not write the AFE, well plan or daily sheet: the page does that
    with its ordinary save, so all the existing validation still applies. This
    call only keeps the audit trail and the usage count honest.
    """
    return svc.record_use(db, user, template_id, request)
