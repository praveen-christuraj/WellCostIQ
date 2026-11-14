"""Cost Intelligence endpoints: automated cost analysis, findings and suggestions.

Read-only. `cost-intelligence:read` opens the module; the figures themselves
still follow the source modules (`afe:read`, `daily-cost:read`, `rig-well:read`)
exactly as on the Operations dashboard, so this capability never widens what a
caller can see. `cost-intelligence:export` allows the audited report export.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import Current, Db, require
from app.schemas.cost_intelligence import IntelligenceExportAudit, IntelligenceOverview, IntelligenceWellDetail
from app.services import cost_intelligence as service

router = APIRouter(
    prefix="/cost-intelligence", tags=["Cost Intelligence"],
    dependencies=[Depends(require(service.READ_KEY))],
)


@router.get("/overview", response_model=IntelligenceOverview)
def overview(
    db: Db,
    user: Current,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    rig_id: str = Query(default="", max_length=36),
    well_id: str = Query(default="", max_length=36),
    well_status: str = Query(default="", max_length=20),
    currency: str = Query(default="", max_length=10),
    include_draft: bool = Query(default=True),
) -> IntelligenceOverview:
    """Workspace health, ranked findings and suggested next actions."""
    return service.overview(
        db, user, date_from=date_from, date_to=date_to, rig_id=rig_id, well_id=well_id,
        well_status=well_status, currency=currency, include_draft=include_draft,
    )


@router.get("/wells/{well_id}", response_model=IntelligenceWellDetail)
def well_detail(
    well_id: str,
    db: Db,
    user: Current,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    currency: str = Query(default="", max_length=10),
    include_draft: bool = Query(default=True),
) -> IntelligenceWellDetail:
    """One well: daily cost against its baseline, the trend statistic and the forecast path."""
    return service.well_detail(
        db, user, well_id, date_from=date_from, date_to=date_to, currency=currency, include_draft=include_draft,
    )


@router.post("/exports", status_code=204)
def export_audit(data: IntelligenceExportAudit, request: Request, db: Db, user: Current) -> None:
    """Record that the report left the application (the file is built in the browser)."""
    service.record_export(db, user, fmt=data.format, record_count=data.record_count, sections=data.sections, request=request)
