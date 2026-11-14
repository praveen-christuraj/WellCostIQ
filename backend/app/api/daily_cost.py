"""Tenant-scoped Daily Cost Management endpoints."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response

from app.api.deps import Current, Db, require
from app.schemas.daily_cost import (
    DailyCostBaselineOut,
    DailyCostDateUpdate,
    DailyCostDayOut,
    DailyCostEntryCreate,
    DailyCostEntryOut,
    DailyCostExportAudit,
    DailyCostIDs,
    DailyCostImportRequest,
    DailyCostImportResponse,
    DailyCostOverview,
    DailyCostPreviewOut,
    DailyCostReference,
    DailyCostRigLatestOut,
    DailyCostReopenIn,
    DailyCostSaveIn,
    DailyCostStatusIn,
    DailyCostWellOption,
    DailyCostWellProgressReport,
    DailyCostWellProgressUpdate,
    DailyCostWellSummary,
)
from app.schemas.entry_check import (
    DailyCostCheckReopenIn,
    DailyCostCheckReviewIn,
    DailyCostEntryChecksOut,
    DailyCostWellChecksOut,
)
from app.services import daily_cost as service
from app.services import entry_checks

router = APIRouter(prefix="/daily-cost", tags=["Daily Cost Management"])


def _refresh_profiles_later(background: BackgroundTasks, organization_id: str) -> None:
    """Rebuild stale workspace item profiles once the response has been sent."""
    if entry_checks.has_pending_refresh(organization_id):
        background.add_task(entry_checks.run_pending_profile_refresh, organization_id)


@router.get("/reference", response_model=DailyCostReference, dependencies=[Depends(require("daily-cost:read"))])
def reference(db: Db, user: Current) -> DailyCostReference:
    return service.reference_data(db, user.organization_id)


@router.get("/overview", response_model=DailyCostOverview, dependencies=[Depends(require("daily-cost:read"))])
def overview(db: Db, user: Current) -> DailyCostOverview:
    return service.overview(db, user.organization_id, user)


@router.get("/wells", response_model=list[DailyCostWellOption], dependencies=[Depends(require("daily-cost:read"))])
def tracked_wells(db: Db, user: Current) -> list[DailyCostWellOption]:
    """Wells that carry daily costs, used by the module's well picker."""
    return service.daily_cost_wells(db, user.organization_id)


@router.get(
    "/wells/{well_id}/cost-summary", response_model=DailyCostWellSummary,
    dependencies=[Depends(require("daily-cost:read"))],
)
def well_cost_summary(
    well_id: str,
    db: Db,
    user: Current,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    include_draft: bool = Query(default=True),
) -> DailyCostWellSummary:
    """Whole-well cost detail: daily run sheet, AFE positions and every cost factor."""
    return service.well_cost_summary(
        db, user.organization_id, well_id, date_from=date_from, date_to=date_to, include_draft=include_draft,
    )


@router.get(
    "/wells/{well_id}/checks", response_model=DailyCostWellChecksOut,
    dependencies=[Depends(require("daily-cost:read"))],
)
def well_entry_checks(
    well_id: str,
    background: BackgroundTasks,
    db: Db,
    user: Current,
    afe_id: str | None = Query(default=None, max_length=36),
) -> DailyCostWellChecksOut:
    """Entry checks across a well's saved sheets, newest sheet first."""
    result = entry_checks.checks_for_well(db, user.organization_id, well_id, afe_id)
    _refresh_profiles_later(background, user.organization_id)
    return result


@router.get(
    "/progress-overview", response_model=list[DailyCostWellProgressReport],
    dependencies=[Depends(require("daily-cost:read"))],
)
def progress_overview(
    db: Db,
    user: Current,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    include_draft: bool = Query(default=True),
) -> list[DailyCostWellProgressReport]:
    """Exact spud-based actual days for every well with daily cost, in one call."""
    return service.progress_overview(
        db, user.organization_id, date_from=date_from, date_to=date_to, include_draft=include_draft,
    )


@router.get(
    "/wells/{well_id}/progress", response_model=DailyCostWellProgressReport,
    dependencies=[Depends(require("daily-cost:read"))],
)
def well_progress(
    well_id: str,
    db: Db,
    user: Current,
    as_of: date | None = Query(default=None),
) -> DailyCostWellProgressReport:
    """Well Spud Date & Time and Progress Completed Date & Time with the day counts they drive."""
    return service.well_progress_report(db, user.organization_id, well_id, as_of=as_of)


@router.put(
    "/wells/{well_id}/progress", response_model=DailyCostWellProgressReport,
    dependencies=[Depends(require("daily-cost:update"))],
)
def update_well_progress(
    well_id: str,
    data: DailyCostWellProgressUpdate,
    db: Db,
    user: Current,
    request: Request,
    as_of: date | None = Query(default=None),
) -> DailyCostWellProgressReport:
    """Enter or edit the spud / progress completion milestones; the spud date can never be cleared."""
    return service.update_well_progress(db, user.organization_id, well_id, data, user, request, as_of=as_of)


@router.get(
    "/wells/{well_id}/cost-report", response_model=list[DailyCostDayOut],
    dependencies=[Depends(require("daily-cost:read")), Depends(require("daily-cost:export"))],
)
def well_cost_report(
    well_id: str, db: Db, user: Current,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    include_draft: bool = Query(default=True),
) -> list[DailyCostDayOut]:
    """Complete saved sheets for one well; no cross-well or cross-currency totals."""
    return service.well_cost_report(
        db, user.organization_id, well_id, date_from=date_from, date_to=date_to, include_draft=include_draft,
    )


@router.get(
    "/entries/latest-per-rig", response_model=DailyCostRigLatestOut,
    dependencies=[Depends(require("daily-cost:read"))],
)
def latest_entries_per_rig(
    db: Db,
    user: Current,
    as_of: date | None = Query(default=None),
    inactivity_days: int = Query(default=5, ge=1, le=60),
) -> DailyCostRigLatestOut:
    """Exactly one saved sheet per rig — the latest — and the rigs that have gone quiet.

    The register's opening view is rig-scoped: each rig shows the single sheet
    the user continues from. ``inactive_rigs`` names the rigs whose newest sheet
    is too old to still be in progress, so the page can explain their absence.
    """
    return service.latest_entry_per_rig(
        db, user.organization_id, as_of=as_of, inactivity_days=inactivity_days,
    )


@router.get("/entries/deleted", response_model=list[DailyCostEntryOut], dependencies=[Depends(require("daily-cost:read"))])
def deleted_entries(db: Db, user: Current) -> list[DailyCostEntryOut]:
    return service.list_entries(db, user.organization_id, deleted=True)


@router.get("/entries", response_model=list[DailyCostEntryOut], dependencies=[Depends(require("daily-cost:read"))])
def list_entries(
    db: Db,
    user: Current,
    well_id: str = Query(default="", max_length=36),
    afe_id: str = Query(default="", max_length=36),
    status: Literal["", "draft", "submitted"] = Query(default=""),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> list[DailyCostEntryOut]:
    return service.list_entries(
        db, user.organization_id, well_id=well_id, afe_id=afe_id, status=status,
        date_from=date_from, date_to=date_to,
    )


@router.post("/entries", response_model=DailyCostDayOut, status_code=201, dependencies=[Depends(require("daily-cost:create"))])
def create_entry(data: DailyCostEntryCreate, request: Request, db: Db, user: Current) -> DailyCostDayOut:
    return service.create_entry(db, user.organization_id, data, user, request)


@router.post("/entries/bulk-delete", dependencies=[Depends(require("daily-cost:delete"))])
def bulk_delete(data: DailyCostIDs, request: Request, db: Db, user: Current) -> dict[str, int]:
    return {"affected_count": service.bulk_soft_delete(db, user.organization_id, data, user, request)}


@router.post("/entries/bulk-restore", dependencies=[Depends(require("daily-cost:restore"))])
def bulk_restore(data: DailyCostIDs, request: Request, db: Db, user: Current) -> dict[str, int]:
    return {"affected_count": service.bulk_restore(db, user.organization_id, data, user, request)}


@router.post("/entries/bulk-permanent-delete", dependencies=[Depends(require("daily-cost:permanent-delete"))])
def bulk_permanent_delete(data: DailyCostIDs, request: Request, db: Db, user: Current) -> dict[str, int]:
    return {"affected_count": service.permanently_delete(db, user.organization_id, data.ids, user, request)}


@router.get("/entries/{entry_id}/baseline", response_model=DailyCostBaselineOut, dependencies=[Depends(require("daily-cost:read"))])
def baseline(entry_id: str, db: Db, user: Current) -> DailyCostBaselineOut:
    return service.context_for_entry(db, user.organization_id, entry_id)


@router.get("/entries/{entry_id}", response_model=DailyCostDayOut, dependencies=[Depends(require("daily-cost:read"))])
def get_entry(entry_id: str, db: Db, user: Current) -> DailyCostDayOut:
    return service.get_day(db, user.organization_id, entry_id)


@router.put("/entries/{entry_id}/preview", response_model=DailyCostPreviewOut, dependencies=[Depends(require("daily-cost:read"))])
def preview_entry(
    entry_id: str, data: DailyCostSaveIn, background: BackgroundTasks, db: Db, user: Current,
) -> DailyCostPreviewOut:
    preview = service.preview_day(db, user.organization_id, entry_id, data)
    _refresh_profiles_later(background, user.organization_id)
    return preview


@router.get(
    "/entries/{entry_id}/checks", response_model=DailyCostEntryChecksOut,
    dependencies=[Depends(require("daily-cost:read"))],
)
def entry_checks_for_sheet(entry_id: str, background: BackgroundTasks, db: Db, user: Current) -> DailyCostEntryChecksOut:
    """Values on the saved sheet that look mistyped next to the other sheets of its AFE."""
    result = entry_checks.checks_for_entry(db, user.organization_id, entry_id)
    _refresh_profiles_later(background, user.organization_id)
    return result


@router.post(
    "/entries/{entry_id}/checks/review", response_model=DailyCostEntryChecksOut,
    dependencies=[Depends(require("daily-cost:update"))],
)
def review_entry_checks(
    entry_id: str, data: DailyCostCheckReviewIn, request: Request, db: Db, user: Current,
) -> DailyCostEntryChecksOut:
    """Keep the values behind these findings as entered (Draft sheets only, audited)."""
    return entry_checks.review_checks(db, user.organization_id, entry_id, data, user, request)


@router.post(
    "/entries/{entry_id}/checks/reopen", response_model=DailyCostEntryChecksOut,
    dependencies=[Depends(require("daily-cost:update"))],
)
def reopen_entry_checks(
    entry_id: str, data: DailyCostCheckReopenIn, request: Request, db: Db, user: Current,
) -> DailyCostEntryChecksOut:
    """Withdraw reviews so the findings are open again (Draft sheets only, audited)."""
    return entry_checks.reopen_checks(db, user.organization_id, entry_id, data, user, request)


@router.put("/entries/{entry_id}", response_model=DailyCostDayOut, dependencies=[Depends(require("daily-cost:update"))])
def save_entry(entry_id: str, data: DailyCostSaveIn, request: Request, db: Db, user: Current) -> DailyCostDayOut:
    return service.save_day(db, user.organization_id, entry_id, data, user, request)


@router.patch("/entries/{entry_id}/date", response_model=DailyCostDayOut, dependencies=[Depends(require("daily-cost:update"))])
def update_entry_date(entry_id: str, data: DailyCostDateUpdate, request: Request, db: Db, user: Current) -> DailyCostDayOut:
    """Correct the operating date of a Draft sheet without replacing its cost lines."""
    return service.update_entry_date(db, user.organization_id, entry_id, data, user, request)


@router.post("/entries/{entry_id}/import", response_model=DailyCostImportResponse, dependencies=[Depends(require("daily-cost:import"))])
def import_entry(entry_id: str, data: DailyCostImportRequest, request: Request, db: Db, user: Current) -> DailyCostImportResponse:
    return service.import_daily_cost(db, user.organization_id, entry_id, data, user, request)


@router.post("/entries/{entry_id}/submit", response_model=DailyCostDayOut, dependencies=[Depends(require("daily-cost:submit"))])
def submit_entry(entry_id: str, data: DailyCostStatusIn, request: Request, db: Db, user: Current) -> DailyCostDayOut:
    return service.submit_entry(db, user.organization_id, entry_id, data, user, request)


@router.post("/entries/{entry_id}/reopen", response_model=DailyCostDayOut, dependencies=[Depends(require("daily-cost:reopen"))])
def reopen_entry(entry_id: str, data: DailyCostReopenIn, request: Request, db: Db, user: Current) -> DailyCostDayOut:
    return service.reopen_entry(db, user.organization_id, entry_id, data, user, request)


@router.delete("/entries/{entry_id}", response_model=DailyCostEntryOut, dependencies=[Depends(require("daily-cost:delete"))])
def delete_entry(entry_id: str, request: Request, db: Db, user: Current) -> DailyCostEntryOut:
    return service.soft_delete_entry(db, user.organization_id, entry_id, user, request)


@router.post("/entries/{entry_id}/restore", response_model=DailyCostEntryOut, dependencies=[Depends(require("daily-cost:restore"))])
def restore_entry(entry_id: str, request: Request, db: Db, user: Current) -> DailyCostEntryOut:
    return service.restore_entry(db, user.organization_id, entry_id, user, request)


@router.delete("/entries/{entry_id}/permanent", status_code=204, dependencies=[Depends(require("daily-cost:permanent-delete"))])
def permanently_delete_entry(entry_id: str, request: Request, db: Db, user: Current) -> Response:
    service.permanently_delete(db, user.organization_id, [entry_id], user, request)
    return Response(status_code=204)


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("daily-cost:export"))])
def export_audit(data: DailyCostExportAudit, request: Request, db: Db, user: Current) -> Response:
    service.record_export(db, user, data, request)
    return Response(status_code=204)


@router.post("/entries/{entry_id}/refresh-service-rates", response_model=DailyCostBaselineOut,
             dependencies=[Depends(require("daily-cost:update"))])
def refresh_service_rates(entry_id: str, request: Request, db: Db, user: Current):
    return service.refresh_service_rates(db, user.organization_id, entry_id, user, request)
