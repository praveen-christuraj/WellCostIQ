"""Version-scoped planned surveys; never writes to the daily-report register."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.domain.operations.durations import utc
from app.domain.operations.trajectory import Station, dogleg_interval
from app.models.operations import OpsPlanSurveyStation
from app.services.audit import record as audit_record
from app.services.operations import plans
from app.services.operations.scope import resolve


def rows_for_plan(db, plan):
    return list(db.scalars(select(OpsPlanSurveyStation).where(
        OpsPlanSurveyStation.organization_id == plan.organization_id,
        OpsPlanSurveyStation.plan_version_id == plan.id,
    ).order_by(OpsPlanSurveyStation.md_m)).all())


def survey_detail(db, plan):
    return {
        "updated_at": utc(plan.updated_at),
        "shared_reference": plan.survey_shared_reference,
        "stations": rows_for_plan(db, plan),
    }


def draft_plan(db, org, plan_id, *, lock=False):
    plan = plans.get_plan(db, org, plan_id, lock=lock)
    if plan.status != "draft":
        raise HTTPException(409, "Only a draft plan’s survey can be edited. Reopen the plan first.")
    resolve(db, org, plan.well_id, plan.scope)
    return plan


def geometry_station(row):
    return Station(
        md_m=float(row.md_m), inc_deg=float(row.inc_deg), azi_deg=float(row.azi_deg or 0),
        tvd_m=float(row.tvd_m) if row.tvd_m is not None else None,
        ns_m=float(row.ns_m) if row.ns_m is not None else None,
        ew_m=float(row.ew_m) if row.ew_m is not None else None,
    )


def replace(db, org, plan_id, data, user, request):
    plan = draft_plan(db, org, plan_id, lock=True)
    if utc(plan.updated_at) != utc(data.expected_updated_at):
        raise HTTPException(409, "This plan changed after you opened it. Reopen Planned survey to load the latest saved version.")
    ordered = sorted(enumerate(data.stations, 1), key=lambda pair: pair[1].md_m)
    previous = None
    for idx, station in ordered:
        if station.azi_deg is None and station.inc_deg >= 1:
            raise HTTPException(422, f"Station {idx}: a deviated station needs an azimuth.")
        point = geometry_station(station)
        if previous:
            interval = dogleg_interval(previous.md_m, previous.inc_deg, previous.azi_deg, point.md_m, point.inc_deg, point.azi_deg)
            if not interval.valid:
                raise HTTPException(422, f"Station {idx} ({station.md_m} m MD): {interval.issue}")
        previous = point
    old_count = db.scalar(select(func.count()).select_from(OpsPlanSurveyStation).where(
        OpsPlanSurveyStation.organization_id == org, OpsPlanSurveyStation.plan_version_id == plan.id,
    )) or 0
    db.execute(delete(OpsPlanSurveyStation).where(
        OpsPlanSurveyStation.organization_id == org,
        OpsPlanSurveyStation.plan_version_id == plan.id,
    ))
    db.add_all(
        OpsPlanSurveyStation(organization_id=org, plan_version_id=plan.id, **station.model_dump())
        for _, station in ordered
    )
    plan.survey_shared_reference = bool(ordered) and data.shared_reference
    plan.updated_at = datetime.now(UTC)
    plan.updated_by = user.email or ""
    audit_record(
        db, organization_id=org, actor=user, action="import" if any(s.source_file for _, s in ordered) else "update",
        entity_type="ops_plan", entity_id=plan.id, entity_label=plan.label,
        summary=f"Saved planned directional survey: {old_count} → {len(ordered)} stations; "
                f"shared reference {'confirmed' if plan.survey_shared_reference else 'not confirmed'}",
        request=request,
    )
    db.commit()
    return survey_detail(db, plan)
