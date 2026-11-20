"""Workspace labels for saved daily-report criteria (never import tokens)."""
from sqlalchemy import select

from app.models.master_data import Activity, HoleSection, Phase
from app.models.operations import OpsAgency, OpsCause, OpsOperation, OpsSubPhase


def report_labels(db, organization_id: str) -> dict[str, dict[str, str]]:
    cache = db.info.setdefault("ops_report_labels", {})
    if organization_id not in cache:
        def rows(model):
            return db.scalars(select(model).where(model.organization_id == organization_id)).all()

        activities = rows(Activity)
        operations = rows(OpsOperation)
        phases = rows(Phase)
        cache[organization_id] = {
            "hole_section": {r.id: r.section_name for r in rows(HoleSection)},
            "phase": {r.id: r.phase_name for r in phases},
            "phase_code": {r.id: r.phase_code for r in phases},
            "sub_phase": {r.id: r.sub_phase_name for r in rows(OpsSubPhase)},
            "activity": {r.id: r.activity_name for r in activities},
            "activity_code": {r.id: r.activity_code for r in activities},
            "activity_type": {r.id: r.activity_type for r in activities},
            "operation": {r.id: r.operation_name for r in operations},
            "npt": {r.id: f"{r.operation_code} — {r.operation_name}" for r in operations},
            "operation_code": {r.id: r.operation_code for r in operations},
            "agency": {r.id: r.agency_name for r in rows(OpsAgency)},
            "cause": {r.cause_code.strip().upper(): f"{r.cause_code} — {r.cause_name}" for r in rows(OpsCause)},
        }
    return cache[organization_id]
