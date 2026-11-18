"""Reports service — CRUD, workflow, metrics."""

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.precision import rounded
from app.domain.operations.durations import duration_minutes as calc_duration
from app.domain.operations.durations import resolve_period, utc
from app.domain.operations.metrics import compute_rop, penetration, period_balance
from app.domain.operations.study import daily_brief
from app.models import User
from app.models.master_data import Activity
from app.models.operations import (
    OpsActivityBlock,
    OpsActivityCode,
    OpsAgency,
    OpsDailyMetric,
    OpsDailyReport,
    OpsDocument,
    OpsExtractionJob,
    OpsNptCode,
    OpsOperationCode,
    OpsPlanItem,
    OpsPlanVersion,
    OpsSettings,
    OpsSurvey,
    OpsUnaccountedTime,
)
from app.models.rig_well import HoleSection, Phase
from app.models.vendor_master import Vendor
from app.services.audit import record as audit_record
from app.services.operations import scope
from app.services.operations.plans import active_plan


def _actor(user: User) -> str:
    return user.email or user.full_name or str(user.id)


def _ref(db, org, model, ident):
    if not ident:
        return None
    row = db.scalar(
        select(model).where(model.id == ident, model.organization_id == org, model.is_deleted.is_(False))
    )
    if not row:
        raise HTTPException(422, "Selected reference is not available in this workspace.")
    return row


def _resolve_period(report_date: date, organization_id: str, db: Session):
    from app.models.operations import OpsSettings

    settings = db.scalar(select(OpsSettings).where(OpsSettings.organization_id == organization_id))
    boundary = settings.day_boundary_hour if settings else 0
    return resolve_period(report_date, boundary, settings.operating_timezone if settings else "Africa/Lagos")


def _validate_blocks(blocks: list[dict], period_start: datetime | None, period_end: datetime | None):
    if not blocks:
        return
    ordered = sorted(blocks, key=lambda b: utc(b["started_at"]))
    for i, block in enumerate(ordered):
        a, z = utc(block["started_at"]), utc(block["ended_at"])
        if z <= a or (period_start and a < utc(period_start)) or (period_end and z > utc(period_end)):
            raise HTTPException(
                422, f"Block {block['sequence_no']} must have positive duration inside the report period."
            )
        if i and a < utc(ordered[i - 1]["ended_at"]):
            raise HTTPException(409, f"Block {block['sequence_no']} overlaps another block.")


def _compute_metrics(db: Session, report: OpsDailyReport, blocks: list[OpsActivityBlock]):
    total = sum(b.duration_minutes for b in blocks)
    planned = sum(b.duration_minutes for b in blocks if b.classification == "Planned")
    upa = sum(b.duration_minutes for b in blocks if b.classification == "UPA")
    npt = sum(b.duration_minutes for b in blocks if b.classification == "NPT")
    productive = sum(b.duration_minutes for b in blocks if b.is_productive)
    avg_conf = float(sum(b.confidence for b in blocks) / len(blocks)) if blocks else 0
    unaccounted = period_balance(report.report_type, report.period_minutes, total)
    db.execute(
        delete(OpsUnaccountedTime).where(
            OpsUnaccountedTime.organization_id == report.organization_id, OpsUnaccountedTime.report_id == report.id
        )
    )
    if unaccounted and report.period_start_at and report.period_end_at:
        cursor = utc(report.period_start_at)
        for start, end in [
            (utc(b.started_at), utc(b.ended_at)) for b in sorted(blocks, key=lambda b: utc(b.started_at))
        ] + [(utc(report.period_end_at), utc(report.period_end_at))]:
            minutes = calc_duration(cursor, start)
            if minutes > 0:
                db.add(
                    OpsUnaccountedTime(
                        organization_id=report.organization_id,
                        report_id=report.id,
                        from_at=cursor,
                        to_at=start,
                        minutes=minutes,
                        reason="Gap in time log",
                        source="computed",
                    )
                )
            cursor = max(cursor, end)
    footage, rotating_hours = penetration(report, blocks)
    metric = db.scalar(
        select(OpsDailyMetric).where(
            OpsDailyMetric.organization_id == report.organization_id,
            OpsDailyMetric.well_id == report.well_id,
            OpsDailyMetric.scope == report.scope,
            OpsDailyMetric.report_date == report.report_date,
        )
    )
    if not metric:
        metric = OpsDailyMetric(
            organization_id=report.organization_id,
            well_id=report.well_id,
            rig_id=report.rig_id,
            scope=report.scope,
            report_date=report.report_date,
        )
        db.add(metric)
    metric.day_number = report.day_number
    metric.logged_minutes = total
    metric.planned_minutes = planned
    metric.upa_minutes = upa
    metric.npt_minutes = npt
    metric.productive_minutes = productive
    metric.unaccounted_minutes = max(0, unaccounted)
    metric.depth_end_m = report.depth_end_m
    metric.footage_m = footage
    metric.rop_m_per_hr = compute_rop(footage, rotating_hours)
    metric.npt_block_count = sum(1 for b in blocks if b.classification == "NPT")
    metric.avg_confidence = rounded(Decimal(str(avg_conf)))
    metric.review_state = report.status
    metric.computed_at = datetime.now(UTC)


def create_report(db: Session, organization_id: str, data, user: User, request=None):
    well, rig = scope.resolve(db, organization_id, data.well_id, data.scope, data.rig_id)
    # Check duplicate well/scope/date
    exists = db.scalar(
        select(OpsDailyReport).where(
            OpsDailyReport.organization_id == organization_id,
            OpsDailyReport.well_id == data.well_id,
            OpsDailyReport.scope == data.scope,
            OpsDailyReport.report_date == data.report_date,
        )
    )
    if exists:
        raise HTTPException(
            409,
            "A report for this period is in Deleted entries. Restore it."
            if exists.is_deleted
            else "A report for this well, scope and date already exists",
        )
    period_start, period_end = _resolve_period(data.report_date, organization_id, db)
    if data.period_start_at:
        period_start = data.period_start_at
    if data.period_end_at:
        period_end = data.period_end_at
    period_start, period_end = utc(period_start), utc(period_end)
    period_minutes = int((period_end - period_start).total_seconds() / 60)
    if not 0 < period_minutes <= 2880:
        raise HTTPException(422, "Invalid report period.")
    if data.source_document_id:
        doc = _ref(db, organization_id, OpsDocument, data.source_document_id)
        if doc.well_id != well.id or doc.scope != data.scope:
            raise HTTPException(422, "Source document belongs to another folder.")
    _ref(db, organization_id, HoleSection, data.hole_section_id)
    _ref(db, organization_id, Phase, data.phase_id)

    baseline = active_plan(db, organization_id, data.well_id, data.scope)
    report = OpsDailyReport(
        baseline_plan_id=baseline.id if baseline else None,
        organization_id=organization_id,
        well_id=well.id,
        rig_id=rig.id if rig else None,
        well_code_snapshot=well.well_code,
        well_name_snapshot=well.well_name,
        rig_code_snapshot=rig.rig_code if rig else "",
        rig_name_snapshot=rig.rig_name if rig else "",
        scope=data.scope,
        report_type=data.report_type,
        report_date=data.report_date,
        report_no_text=data.report_no_text or "",
        day_number=data.day_number,
        event_code=data.event_code or "",
        period_start_at=period_start,
        period_end_at=period_end,
        period_minutes=period_minutes,
        hole_section_id=data.hole_section_id,
        phase_id=data.phase_id,
        depth_start_m=data.depth_start_m,
        depth_end_m=data.depth_end_m,
        depth_unit=data.depth_unit or "m",
        tvd_m=data.tvd_m,
        progress_m=data.progress_m,
        rotating_hours=data.rotating_hours,
        dfs_days=data.dfs_days,
        customer=data.customer or "",
        supervisor=data.supervisor or "",
        engineer=data.engineer or "",
        operation_summary=data.operation_summary or "",
        forward_plan=data.forward_plan or "",
        hse_summary=data.hse_summary or "",
        remarks=data.remarks or "",
        source_document_id=data.source_document_id,
        status="draft",
        extraction_status="none",
        created_by=_actor(user),
        updated_by=_actor(user),
    )
    db.add(report)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A report for this period already exists") from exc
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="create",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=f"{well.well_code} {data.report_date}",
        summary="Created daily report",
        request=request,
    )
    db.commit()
    db.refresh(report)
    return report


def get_report(db: Session, organization_id: str, report_id: str, include_deleted: bool = False, *, lock=False):
    q = select(OpsDailyReport).where(
        OpsDailyReport.id == report_id, OpsDailyReport.organization_id == organization_id
    )
    if not include_deleted:
        q = q.where(OpsDailyReport.is_deleted.is_(False))
    report = db.scalar(q.with_for_update() if lock else q)
    if not report:
        raise HTTPException(404, "Report not found")
    blocks = db.scalars(
        select(OpsActivityBlock)
        .where(OpsActivityBlock.report_id == report.id, OpsActivityBlock.is_deleted.is_(False))
        .order_by(OpsActivityBlock.sequence_no)
    ).all()
    report._blocks = blocks
    report._total_block_minutes = sum(b.duration_minutes for b in blocks)
    report._unaccounted_minutes = period_balance(
        report.report_type, report.period_minutes, report._total_block_minutes
    )
    report._surveys = db.scalars(
        select(OpsSurvey)
        .where(
            OpsSurvey.organization_id == organization_id,
            OpsSurvey.report_id == report.id,
            OpsSurvey.is_deleted.is_(False),
        )
        .order_by(OpsSurvey.station_no)
    ).all()
    jobs = db.execute(
        select(OpsExtractionJob.findings, OpsDocument.id, OpsDocument.file_name)
        .join(OpsDocument, OpsDocument.id == OpsExtractionJob.document_id)
        .where(
            OpsExtractionJob.organization_id == organization_id,
            OpsExtractionJob.report_id == report.id,
            OpsDocument.is_deleted.is_(False),
        )
        .order_by(OpsExtractionJob.created_at)
    ).all()
    report._extraction_notes = "\n".join(j.findings for j in jobs if j.findings)
    report._plan_checkpoints = [
        {
            "id": i.id,
            "description": f"{version.label} · {i.sequence_no}. {i.description}",
            "days": str(i.cum_planned_days),
        }
        for i, version in db.execute(
            select(OpsPlanItem, OpsPlanVersion)
            .join(OpsPlanVersion, OpsPlanVersion.id == OpsPlanItem.plan_version_id)
            .where(
                OpsPlanVersion.organization_id == organization_id,
                OpsPlanVersion.well_id == report.well_id,
                OpsPlanVersion.scope == report.scope,
                OpsPlanVersion.is_deleted.is_(False),
                OpsPlanVersion.id == report.baseline_plan_id
                if report.baseline_plan_id
                else OpsPlanVersion.status == "active",
            )
            .order_by(OpsPlanItem.sequence_no)
        )
    ]
    report._sources = [{"id": j.id, "file_name": j.file_name} for j in jobs]
    return report


def list_reports(
    db: Session,
    organization_id: str,
    well_id: str | None = None,
    rig_id: str | None = None,
    scope: str | None = None,
    status: str | None = None,
    report_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_deleted: bool = False,
):
    q = select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id)
    if not include_deleted:
        q = q.where(OpsDailyReport.is_deleted.is_(False))
    if well_id:
        q = q.where(OpsDailyReport.well_id == well_id)
    if rig_id:
        q = q.where(OpsDailyReport.rig_id == rig_id)
    if scope:
        q = q.where(OpsDailyReport.scope == scope)
    if status:
        q = q.where(OpsDailyReport.status == status)
    if report_type:
        q = q.where(OpsDailyReport.report_type == report_type)
    if date_from:
        q = q.where(OpsDailyReport.report_date >= date_from)
    if date_to:
        q = q.where(OpsDailyReport.report_date <= date_to)
    rows = db.scalars(q.order_by(OpsDailyReport.report_date.desc(), OpsDailyReport.created_at.desc())).all()
    by_report = {}
    for block in db.scalars(
        select(OpsActivityBlock)
        .where(
            OpsActivityBlock.organization_id == organization_id,
            OpsActivityBlock.report_id.in_(q.with_only_columns(OpsDailyReport.id)),
            OpsActivityBlock.is_deleted.is_(False),
        )
        .order_by(OpsActivityBlock.sequence_no)
    ):
        by_report.setdefault(block.report_id, []).append(block)
    for r in rows:
        r._blocks = by_report.get(r.id, [])
        r._total_block_minutes = sum(b.duration_minutes for b in r._blocks)
        r._unaccounted_minutes = period_balance(r.report_type, r.period_minutes, r._total_block_minutes)
    return rows


def save_report(
    db: Session, organization_id: str, report_id: str, data, user: User, request=None, *, may_review=False
):
    report = get_report(db, organization_id, report_id, lock=True)
    if report.status not in ("draft", "in_review", "rejected"):
        raise HTTPException(409, "Submitted and approved reports are read-only.")
    scope.resolve(db, organization_id, report.well_id, report.scope)
    if data.expected_updated_at and utc(report.updated_at) != utc(data.expected_updated_at):
        raise HTTPException(409, "This draft changed since it was opened. Reload before applying corrections.")
    if data.confirm_review and not may_review:
        raise HTTPException(403, "Confirming source review needs ops-report:review.")
    # Update header fields
    upd = data.report
    if not report.baseline_plan_id:
        baseline = active_plan(db, organization_id, report.well_id, report.scope)
        report.baseline_plan_id = baseline.id if baseline else None
    if "completed_plan_item_id" in upd.model_fields_set:
        if upd.completed_plan_item_id and not any(
            c["id"] == upd.completed_plan_item_id for c in report._plan_checkpoints
        ):
            raise HTTPException(422, "Choose a checkpoint in this well and scope’s active timeline.")
        report.completed_plan_item_id = upd.completed_plan_item_id
    if upd.rig_id is not None and upd.rig_id != report.rig_id:
        raise HTTPException(422, "The rig is assigned by the well configuration.")
    _ref(db, organization_id, HoleSection, upd.hole_section_id)
    _ref(db, organization_id, Phase, upd.phase_id)
    for field in [
        "site",
        "report_no_text",
        "day_number",
        "event_code",
        "hole_section_id",
        "phase_id",
        "depth_start_m",
        "depth_end_m",
        "depth_unit",
        "tvd_m",
        "progress_m",
        "rotating_hours",
        "dfs_days",
        "operation_summary",
        "forward_plan",
        "hse_summary",
        "remarks",
    ]:
        val = getattr(upd, field, None)
        if field in upd.model_fields_set and (
            val is not None
            or field
            in ("depth_start_m", "depth_end_m", "tvd_m", "progress_m", "rotating_hours", "dfs_days", "day_number")
        ):
            setattr(report, field, val)
    if upd.period_start_at:
        report.period_start_at = utc(upd.period_start_at)
    if upd.period_end_at:
        report.period_end_at = utc(upd.period_end_at)
    if report.period_start_at and report.period_end_at:
        report.period_minutes = int((utc(report.period_end_at) - utc(report.period_start_at)).total_seconds() / 60)
    report.updated_by = _actor(user)
    report.updated_at = datetime.now(UTC)
    if report.period_minutes <= 0 or report.period_minutes > 2880:
        raise HTTPException(422, "Invalid report period")

    # Replace blocks
    if data.blocks is not None:
        # Validate
        block_dicts = [b.model_dump() if hasattr(b, "model_dump") else b for b in data.blocks]
        _validate_blocks(block_dicts, report.period_start_at, report.period_end_at)
        for i, bd in enumerate(block_dicts, 1):
            bd["sequence_no"] = i
            bd["started_at"], bd["ended_at"] = utc(bd["started_at"]), utc(bd["ended_at"])
            bd["duration_minutes"] = calc_duration(bd["started_at"], bd["ended_at"])
            if bd["duration_minutes"] <= 0:
                raise HTTPException(422, f"Block {i}: duration must be at least one minute.")
            for field, model in [
                ("npt_code_id", OpsNptCode),
                ("agency_id", OpsAgency),
                ("operation_code_id", OpsOperationCode),
                ("activity_code_id", OpsActivityCode),
                ("activity_id", Activity),
                ("phase_id", Phase),
                ("hole_section_id", HoleSection),
            ]:
                _ref(db, organization_id, model, bd[field])
            vendor = _ref(db, organization_id, Vendor, bd["vendor_id"])
            if vendor:
                if vendor.status != "active":
                    raise HTTPException(422, "Select an active vendor.")
                bd["responsible_party"] = vendor.vendor_name
            else:
                bd["responsible_party"] = ""
            if (bd["classification"] == "NPT" or bd["allocation"] == "NPT") and bd["is_productive"]:
                raise HTTPException(422, f"Block {i}: NPT cannot be productive.")

        # Update matching blocks in place. Reviewed records keep their IDs and machine
        # evidence; a removed row is retired, not relabelled as a different activity.
        existing = {b.id: b for b in report._blocks}
        retained = set()
        for bd in block_dicts:
            block_id = bd.pop("block_id", None)
            if block_id and (block_id not in existing or block_id in retained):
                raise HTTPException(422, "The selected activity block is not in this draft.")
            block = existing.get(block_id)
            if not block:
                block = OpsActivityBlock(
                    organization_id=organization_id,
                    report_id=report.id,
                    classification_source="reviewer",
                    classification_evidence="",
                    source_page=0,
                    source_bbox="",
                    confidence=Decimal(1),
                )
                db.add(block)
            else:
                retained.add(block.id)
                if block.classification != bd["classification"] or block.allocation != bd["allocation"]:
                    block.classification_source = "reviewer"
            # Provenance and calculated values are server-owned. Original source files
            # remain immutable even if the engineer changes the interpretation.
            for field in (
                "sequence_no",
                "started_at",
                "ended_at",
                "duration_minutes",
                "phase_raw",
                "operation_code_id",
                "activity_code_id",
                "activity_id",
                "classification",
                "allocation",
                "is_productive",
                "npt_code_id",
                "agency_id",
                "cause_code",
                "hole_section_id",
                "phase_id",
                "depth_from_m",
                "depth_to_m",
                "bit_depth_m",
                "rotating_hours",
                "vendor_id",
                "responsible_party",
                "reason",
                "narrative",
                "review_state",
            ):
                setattr(block, field, bd[field])
            block.depth_unit = "m"
            block.rop_basis = "rotating"
            start, end = block.depth_from_m, block.depth_to_m
            block.footage_m = end - start if start is not None and end is not None and end >= start else None
            block.rop_m_per_hr = compute_rop(block.footage_m, block.rotating_hours)
            code = db.get(OpsNptCode, block.npt_code_id) if block.npt_code_id else None
            block.npt_code_snapshot = code.npt_code if code else ""
            if data.confirm_review and block.review_state in ("accepted", "edited"):
                block.reviewer_user_id = user.id
                block.reviewed_at = datetime.now(UTC)
        for removed in existing.keys() - retained:
            existing[removed].is_deleted = True
            existing[removed].deleted_at = datetime.now(UTC)
        # Update extraction status to reviewed if all suggested now accepted/edited
        if report.current_extraction_id or report.extraction_status == "needs_review":
            if data.confirm_review and any(b["review_state"] not in ("edited", "accepted") for b in block_dicts):
                raise HTTPException(422, "Review every suggested block before confirming.")
            report.extraction_status = "reviewed" if data.confirm_review else "needs_review"

    if data.blocks is None and report.current_extraction_id and (upd.model_fields_set or data.surveys is not None):
        report.extraction_status = "needs_review"
    if data.surveys is not None:
        db.execute(
            delete(OpsSurvey).where(OpsSurvey.organization_id == organization_id, OpsSurvey.report_id == report.id)
        )
        db.add_all(
            [
                OpsSurvey(
                    report_id=report.id,
                    organization_id=organization_id,
                    well_id=report.well_id,
                    scope=report.scope,
                    station_no=i,
                    **station.model_dump(),
                )
                for i, station in enumerate(data.surveys, 1)
            ]
        )
    # Recompute metrics
    # Need to fetch blocks after flush
    db.flush()
    blocks_now = db.scalars(
        select(OpsActivityBlock).where(
            OpsActivityBlock.report_id == report.id, OpsActivityBlock.is_deleted.is_(False)
        )
    ).all()
    _compute_metrics(db, report, blocks_now)

    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="update",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=f"{report.well_code_snapshot} {report.report_date}",
        summary="Confirmed source review" if data.confirm_review else "Updated daily report",
        request=request,
    )
    db.commit()
    db.refresh(report)
    return get_report(db, organization_id, report.id)


def _metric_state(db, report):
    metric = db.scalar(
        select(OpsDailyMetric).where(
            OpsDailyMetric.organization_id == report.organization_id,
            OpsDailyMetric.well_id == report.well_id,
            OpsDailyMetric.scope == report.scope,
            OpsDailyMetric.report_date == report.report_date,
        )
    )
    if metric:
        metric.review_state = report.status


def submit_report(db: Session, organization_id: str, report_id: str, user: User, request=None):
    report = get_report(db, organization_id, report_id, lock=True)
    if report.status not in ("draft", "in_review", "rejected"):
        raise HTTPException(409, "Only draft or in-review reports can be submitted")
    blocks = db.scalars(
        select(OpsActivityBlock).where(
            OpsActivityBlock.report_id == report.id, OpsActivityBlock.is_deleted.is_(False)
        )
    ).all()
    scope.resolve(db, organization_id, report.well_id, report.scope)
    measurement_only = report.report_type == "DMR" and not blocks and bool(report.operation_summary.strip())
    if not blocks and not measurement_only:
        raise HTTPException(422, "Cannot submit a report with no time blocks")
    if report.extraction_status == "needs_review" or any(
        b.review_state not in ("accepted", "edited") for b in blocks
    ):
        raise HTTPException(422, "Review the suggested blocks and save the draft before submitting.")
    settings = db.scalar(select(OpsSettings).where(OpsSettings.organization_id == organization_id))
    total = sum(b.duration_minutes for b in blocks)
    if not measurement_only and total > (settings.max_daily_hours if settings else 24) * 60:
        raise HTTPException(422, "Logged hours exceed the workspace maximum daily hours.")
    if not measurement_only and abs(total - report.period_minutes) > (
        settings.completeness_tolerance_minutes if settings else 2
    ):
        raise HTTPException(
            422, f"Logged {total} minutes; expected {report.period_minutes}. Correct the log or the report period."
        )
    _validate_blocks(
        [{"sequence_no": b.sequence_no, "started_at": b.started_at, "ended_at": b.ended_at} for b in blocks],
        report.period_start_at,
        report.period_end_at,
    )
    for b in blocks:
        if (
            (b.classification == "NPT" or b.allocation == "NPT")
            and not b.npt_code_id
            and (not settings or settings.require_npt_code)
        ):
            raise HTTPException(422, f"Block {b.sequence_no}: select an NPT code.")
        if b.classification in ("NPT", "UPA") or b.allocation in ("NPT", "UPA"):
            if settings and settings.require_npt_agency and not b.vendor_id:
                raise HTTPException(422, f"Block {b.sequence_no}: select the responsible vendor.")
            if (not settings or settings.require_npt_reason) and not b.reason.strip():
                raise HTTPException(422, f"Block {b.sequence_no}: enter the reason.")
    report.status = "submitted"
    _metric_state(db, report)
    report.submitted_at = datetime.now(UTC)
    report.submitted_by = _actor(user)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="submit",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=str(report.report_date),
        summary="Submitted report",
        request=request,
    )
    db.commit()
    return report


def approve_report(db: Session, organization_id: str, report_id: str, user: User, request=None):
    report = get_report(db, organization_id, report_id, lock=True)
    if report.status != "submitted":
        raise HTTPException(409, "Only submitted reports can be approved")
    report.status = "approved"
    _metric_state(db, report)
    report.approved_at = datetime.now(UTC)
    report.approved_by = _actor(user)
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="approve",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=str(report.report_date),
        summary="Approved report",
        request=request,
    )
    db.commit()
    return report


def reject_report(db: Session, organization_id: str, report_id: str, reason: str, user: User, request=None):
    report = get_report(db, organization_id, report_id, lock=True)
    if report.status != "submitted":
        raise HTTPException(409, "Only submitted reports can be rejected")
    report.status = "rejected"
    _metric_state(db, report)
    report.rejection_reason = reason[:500]
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="reject",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=str(report.report_date),
        summary=f"Rejected: {reason[:100]}",
        request=request,
    )
    db.commit()
    return report


def delete_reports(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(
        select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.id.in_(ids))
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more reports not found")
    if any(r.status in ("approved", "submitted") for r in rows):
        raise HTTPException(409, "Submitted and approved reports cannot be deleted.")
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
        entity_type="ops_report",
        entity_id=None,
        entity_label=f"{affected} report(s)",
        summary=f"Deleted {affected} report(s)",
        request=request,
    )
    db.commit()
    return {"affected_count": affected}


def restore_reports(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(
        select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.id.in_(ids))
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more reports not found")
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
        entity_type="ops_report",
        entity_id=None,
        entity_label=f"{affected} report(s)",
        summary=f"Restored {affected} report(s)",
        request=request,
    )
    db.commit()
    return {"affected_count": affected}


def purge_reports(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(
        select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.id.in_(ids))
    ).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more reports not found")
    affected = 0
    for r in rows:
        if not r.is_deleted:
            raise HTTPException(409, "Only deleted reports can be permanently removed")
        # delete blocks first
        blocks = db.scalars(select(OpsActivityBlock).where(OpsActivityBlock.report_id == r.id)).all()
        for b in blocks:
            db.delete(b)
        db.execute(
            delete(OpsDailyMetric).where(
                OpsDailyMetric.organization_id == organization_id,
                OpsDailyMetric.well_id == r.well_id,
                OpsDailyMetric.scope == r.scope,
                OpsDailyMetric.report_date == r.report_date,
            )
        )
        db.execute(
            delete(OpsSurvey).where(OpsSurvey.organization_id == organization_id, OpsSurvey.report_id == r.id)
        )
        db.delete(r)
        affected += 1
    audit_record(
        db,
        organization_id=organization_id,
        actor=user,
        action="permanent-delete",
        entity_type="ops_report",
        entity_id=None,
        entity_label=f"{affected} report(s)",
        summary=f"Purged {affected} report(s)",
        request=request,
    )
    db.commit()
    return {"affected_count": affected}


def brief_for_report(db: Session, organization_id: str, report_id: str, *, include_deleted=False):
    report = get_report(db, organization_id, report_id, include_deleted=include_deleted)
    blocks = getattr(report, "_blocks", [])
    total = sum(b.duration_minutes for b in blocks)
    planned = sum(b.duration_minutes for b in blocks if b.classification == "Planned")
    upa = sum(b.duration_minutes for b in blocks if b.classification == "UPA")
    npt = sum(b.duration_minutes for b in blocks if b.classification == "NPT")
    npt_items = [
        {
            "npt_code": b.npt_code_snapshot or "",
            "reason": b.reason or b.narrative[:100],
            "duration_minutes": b.duration_minutes,
            "responsible_party": b.responsible_party,
        }
        for b in blocks
        if b.classification == "NPT" or b.allocation == "NPT"
    ]
    time_split = {
        "planned_minutes": planned,
        "upa_minutes": upa,
        "npt_minutes": npt,
        "unaccounted_minutes": getattr(report, "_unaccounted_minutes", 0),
        "total_minutes": total,
        "avg_confidence": str(rounded(sum((b.confidence for b in blocks), Decimal(0)) / len(blocks))) if blocks else "0.000",
    }
    footage, rotating_hours = penetration(report, blocks)
    rop = compute_rop(footage, rotating_hours)

    text = daily_brief(report, blocks, footage, rotating_hours, rop)
    return {
        "report_id": report.id,
        "well_code": report.well_code_snapshot,
        "well_name": report.well_name_snapshot,
        "report_date": report.report_date,
        "day_number": report.day_number,
        "summary": text,
        "time_split": time_split,
        "npt_items": npt_items,
        "depth_progress": {
            "depth_start_m": str(report.depth_start_m) if report.depth_start_m is not None else None,
            "depth_end_m": str(report.depth_end_m) if report.depth_end_m is not None else None,
            "footage_m": str(footage) if footage is not None else None,
            "rotating_hours": str(rounded(rotating_hours)) if rotating_hours is not None else None,
            "rop_m_per_hr": str(rop) if rop is not None else None,
        },
        "data_quality": {
            "blocks": len(blocks),
            "avg_confidence": time_split["avg_confidence"],
            "unaccounted_minutes": time_split["unaccounted_minutes"],
        },
    }
