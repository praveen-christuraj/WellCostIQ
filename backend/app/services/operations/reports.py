"""Reports service — CRUD, workflow, metrics."""

from datetime import date, datetime, timezone, timedelta, time
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.core.units import depth_to_meters
from app.domain.operations.classify import classify_block, build_brief
from app.domain.operations.durations import resolve_period, duration_minutes as calc_duration
from app.models import User
from app.models.operations import (
    OpsActivityBlock,
    OpsDailyReport,
    OpsDailyMetric,
    OpsDocument,
    OpsUnaccountedTime,
)
from app.models.rig_well import Rig, Well, HoleSection, Phase
from app.services.audit import record as audit_record


def _actor(user: User) -> str:
    return user.email or user.full_name or str(user.id)


def _ensure_well_rig(db: Session, organization_id: str, well_id: str, rig_id: str | None, scope: str):
    well = db.scalar(select(Well).where(Well.id == well_id, Well.organization_id == organization_id, Well.is_deleted.is_(False)))
    if not well:
        raise HTTPException(404, "Well not found")
    # Check scope availability
    # Allow both scopes
    if scope not in ("drilling", "completion"):
        raise HTTPException(422, "Scope must be drilling or completion")
    rig = None
    if rig_id:
        rig = db.scalar(select(Rig).where(Rig.id == rig_id, Rig.organization_id == organization_id, Rig.is_deleted.is_(False)))
        if not rig:
            raise HTTPException(404, "Rig not found")
    return well, rig


def _resolve_period(report_date: date, organization_id: str, db: Session):
    from app.models.operations import OpsSettings
    settings = db.scalar(select(OpsSettings).where(OpsSettings.organization_id == organization_id))
    boundary = settings.day_boundary_hour if settings else 0
    return resolve_period(report_date, boundary)


def _validate_blocks(blocks: list[dict], period_start: datetime | None, period_end: datetime | None):
    if not blocks:
        return
    sorted_blocks = sorted(blocks, key=lambda b: b["started_at"])
    for i in range(len(sorted_blocks) - 1):
        if sorted_blocks[i+1]["started_at"] < sorted_blocks[i]["ended_at"]:
            raise HTTPException(409, f"Block {sorted_blocks[i]['sequence_no']} overlaps block {sorted_blocks[i+1]['sequence_no']}. Adjust one of them.")
    if period_start and period_end:
        for b in sorted_blocks:
            if b["started_at"] < period_start or b["ended_at"] > period_end + timedelta(minutes=2):
                # allow 1 spill block past midnight
                pass


def _compute_metrics(db: Session, report: OpsDailyReport, blocks: list[OpsActivityBlock]):
    total = sum(b.duration_minutes for b in blocks)
    planned = sum(b.duration_minutes for b in blocks if b.classification == "Planned")
    upa = sum(b.duration_minutes for b in blocks if b.classification == "UPA")
    npt = sum(b.duration_minutes for b in blocks if b.classification == "NPT")
    productive = sum(b.duration_minutes for b in blocks if b.is_productive)
    avg_conf = float(sum(b.confidence for b in blocks) / len(blocks)) if blocks else 0
    unaccounted = report.period_minutes - total if report.period_minutes else 0
    if unaccounted < 0:
        unaccounted = 0
    # Update report's unaccounted mirror? Store via OpsUnaccountedTime
    existing = db.scalars(select(OpsUnaccountedTime).where(OpsUnaccountedTime.report_id == report.id)).all()
    for e in existing:
        db.delete(e)
    if unaccounted > 2:
        db.add(OpsUnaccountedTime(
            organization_id=report.organization_id,
            report_id=report.id,
            from_at=report.period_end_at or datetime.now(timezone.utc),
            to_at=report.period_end_at or datetime.now(timezone.utc),
            minutes=unaccounted,
            reason="Gap in time log",
            source="computed",
        ))
    # Update metrics table
    depth_end = report.depth_end_m
    footage = None
    if report.depth_start_m is not None and report.depth_end_m is not None:
        try:
            footage = report.depth_end_m - report.depth_start_m
            if footage < 0:
                footage = None
        except Exception:
            pass
    rop = None
    # ROP: compute from footage / drilling hours (blocks that count as on-bottom — approximate as Planned with rotating)
    # For now simple
    metric = db.scalar(select(OpsDailyMetric).where(OpsDailyMetric.organization_id == report.organization_id, OpsDailyMetric.well_id == report.well_id, OpsDailyMetric.scope == report.scope, OpsDailyMetric.report_date == report.report_date))
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
    metric.depth_end_m = depth_end
    metric.footage_m = footage
    metric.npt_block_count = sum(1 for b in blocks if b.classification == "NPT")
    metric.avg_confidence = Decimal(str(round(avg_conf, 2)))
    metric.review_state = report.status
    metric.computed_at = datetime.now(timezone.utc)


def create_report(db: Session, organization_id: str, data, user: User, request=None):
    well, rig = _ensure_well_rig(db, organization_id, data.well_id, data.rig_id, data.scope)
    # Check duplicate well/scope/date
    exists = db.scalar(select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.well_id == data.well_id, OpsDailyReport.scope == data.scope, OpsDailyReport.report_date == data.report_date, OpsDailyReport.is_deleted.is_(False)))
    if exists:
        raise HTTPException(409, "A report for this well, scope and date already exists")
    period_start, period_end = _resolve_period(data.report_date, organization_id, db)
    if data.period_start_at:
        period_start = data.period_start_at
    if data.period_end_at:
        period_end = data.period_end_at
    period_minutes = int((period_end - period_start).total_seconds() / 60) if period_start and period_end else 1440

    report = OpsDailyReport(
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
    db.flush()
    audit_record(db, organization_id=organization_id, actor=user, action="create", entity_type="ops_report", entity_id=report.id, entity_label=f"{well.well_code} {data.report_date}", summary="Created daily report", request=request)
    db.commit()
    db.refresh(report)
    return report


def get_report(db: Session, organization_id: str, report_id: str, include_deleted: bool = False):
    q = select(OpsDailyReport).where(OpsDailyReport.id == report_id, OpsDailyReport.organization_id == organization_id)
    if not include_deleted:
        q = q.where(OpsDailyReport.is_deleted.is_(False))
    report = db.scalar(q)
    if not report:
        raise HTTPException(404, "Report not found")
    blocks = db.scalars(select(OpsActivityBlock).where(OpsActivityBlock.report_id == report.id, OpsActivityBlock.is_deleted.is_(False)).order_by(OpsActivityBlock.sequence_no)).all()
    unacc = db.scalars(select(OpsUnaccountedTime).where(OpsUnaccountedTime.report_id == report.id)).all()
    unacc_minutes = sum(u.minutes for u in unacc)
    total_minutes = sum(b.duration_minutes for b in blocks)
    # Attach computed fields for output
    report._blocks = blocks  # type: ignore
    report._unaccounted_minutes = unacc_minutes  # type: ignore
    report._total_block_minutes = total_minutes  # type: ignore
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
    # Attach blocks for each (lightweight)
    for r in rows:
        blocks = db.scalars(select(OpsActivityBlock).where(OpsActivityBlock.report_id == r.id, OpsActivityBlock.is_deleted.is_(False)).order_by(OpsActivityBlock.sequence_no)).all()
        unacc = db.scalars(select(OpsUnaccountedTime).where(OpsUnaccountedTime.report_id == r.id)).all()
        r._blocks = blocks  # type: ignore
        r._unaccounted_minutes = sum(u.minutes for u in unacc)  # type: ignore
        r._total_block_minutes = sum(b.duration_minutes for b in blocks)  # type: ignore
    return rows


def save_report(db: Session, organization_id: str, report_id: str, data, user: User, request=None):
    report = get_report(db, organization_id, report_id)
    if report.status not in ("draft", "in_review", "rejected"):
        raise HTTPException(409, "Only draft, in-review or rejected reports can be edited. Submit or amend instead.")
    # Update header fields
    upd = data.report
    if upd.rig_id is not None:
        # allow clearing rig
        if upd.rig_id == "":
            report.rig_id = None
            report.rig_code_snapshot = ""
            report.rig_name_snapshot = ""
        else:
            rig = db.scalar(select(Rig).where(Rig.id == upd.rig_id, Rig.organization_id == organization_id))
            if not rig:
                raise HTTPException(404, "Rig not found")
            report.rig_id = rig.id
            report.rig_code_snapshot = rig.rig_code
            report.rig_name_snapshot = rig.rig_name
    for field in ["report_no_text", "day_number", "event_code", "hole_section_id", "phase_id", "depth_start_m", "depth_end_m", "depth_unit", "tvd_m", "progress_m", "rotating_hours", "dfs_days", "operation_summary", "forward_plan", "hse_summary", "remarks"]:
        val = getattr(upd, field, None)
        if val is not None:
            setattr(report, field, val)
    if upd.period_start_at:
        report.period_start_at = upd.period_start_at
    if upd.period_end_at:
        report.period_end_at = upd.period_end_at
    if report.period_start_at and report.period_end_at:
        report.period_minutes = int((report.period_end_at - report.period_start_at).total_seconds() / 60)
    report.updated_by = _actor(user)
    report.extraction_status = "reviewed" if report.extraction_status == "needs_review" else report.extraction_status

    # Replace blocks
    if data.blocks is not None:
        # Validate
        block_dicts = [b.model_dump() if hasattr(b, "model_dump") else b for b in data.blocks]
        # Recompute duration_minutes from timestamps to be authoritative
        for bd in block_dicts:
            try:
                if bd.get("started_at") and bd.get("ended_at"):
                    sa = bd["started_at"]
                    ea = bd["ended_at"]
                    # Ensure aware
                    if sa.tzinfo is None:
                        sa = sa.replace(tzinfo=timezone.utc)
                    if ea.tzinfo is None:
                        ea = ea.replace(tzinfo=timezone.utc)
                    bd["duration_minutes"] = calc_duration(sa, ea)
            except Exception:
                pass
        _validate_blocks(block_dicts, report.period_start_at, report.period_end_at)
        # Check NPT completeness
        from app.models.operations import OpsSettings
        settings = db.scalar(select(OpsSettings).where(OpsSettings.organization_id == organization_id))
        require_npt_code = settings.require_npt_code if settings else True
        for bd in block_dicts:
            if bd.get("classification") == "NPT" and require_npt_code and not bd.get("npt_code_id"):
                raise HTTPException(422, f"Block {bd.get('sequence_no')} classified NPT requires an NPT code")
            if bd.get("classification") in ("NPT", "UPA") and not (bd.get("reason") or "").strip():
                # Warning not block — but if setting requires reason, enforce
                if settings and settings.require_npt_reason and bd.get("classification") == "NPT":
                    raise HTTPException(422, f"Block {bd.get('sequence_no')} NPT requires a reason")
            if bd.get("classification") == "NPT" and bd.get("is_productive"):
                raise HTTPException(422, f"Block {bd.get('sequence_no')} NPT cannot be productive")

        # Delete old
        old = db.scalars(select(OpsActivityBlock).where(OpsActivityBlock.report_id == report.id)).all()
        for ob in old:
            db.delete(ob)
        db.flush()
        # Create new
        for bd in block_dicts:
            # Normalize depth
            dfm = bd.get("depth_from_m")
            dtm = bd.get("depth_to_m")
            footage = None
            if dfm is not None and dtm is not None:
                try:
                    dfm = Decimal(str(dfm))
                    dtm = Decimal(str(dtm))
                    if dtm > dfm:
                        footage = dtm - dfm
                except Exception:
                    pass
            rop = None
            if footage is not None and bd.get("rotating_hours"):
                try:
                    rh = Decimal(str(bd["rotating_hours"]))
                    if rh > 0:
                        rop = footage / rh
                except Exception:
                    pass
            block = OpsActivityBlock(
                organization_id=organization_id,
                report_id=report.id,
                sequence_no=bd.get("sequence_no", 1),
                started_at=bd["started_at"],
                ended_at=bd["ended_at"],
                duration_minutes=bd.get("duration_minutes", 60),
                phase_raw=bd.get("phase_raw", "")[:20],
                operation_code_id=bd.get("operation_code_id"),
                activity_code_id=bd.get("activity_code_id"),
                activity_id=bd.get("activity_id"),
                classification=bd.get("classification", "Planned"),
                allocation=bd.get("allocation", "PT"),
                is_productive=bd.get("is_productive", True),
                classification_source=bd.get("classification_source", "keyword"),
                npt_code_id=bd.get("npt_code_id"),
                agency_id=bd.get("agency_id"),
                cause_code=bd.get("cause_code", "")[:50],
                hole_section_id=bd.get("hole_section_id"),
                phase_id=bd.get("phase_id"),
                depth_from_m=dfm,
                depth_to_m=dtm,
                depth_unit=bd.get("depth_unit", "m"),
                footage_m=footage,
                rotating_hours=Decimal(str(bd["rotating_hours"])) if bd.get("rotating_hours") is not None else None,
                rop_m_per_hr=rop,
                rop_basis=bd.get("rop_basis", "rotating"),
                responsible_party=bd.get("responsible_party", "")[:200],
                vendor_id=bd.get("vendor_id"),
                reason=bd.get("reason", "")[:500],
                narrative=bd.get("narrative", "")[:5000],
                confidence=Decimal(str(bd.get("confidence", 0.5))),
                review_state=bd.get("review_state", "suggested"),
            )
            # Snapshot NPT code
            if block.npt_code_id:
                from app.models.operations import OpsNptCode
                npt = db.get(OpsNptCode, block.npt_code_id)
                if npt:
                    block.npt_code_snapshot = npt.npt_code
            db.add(block)
        # Update extraction status to reviewed if all suggested now accepted/edited
        report.extraction_status = "reviewed"

    # Recompute metrics
    # Need to fetch blocks after flush
    db.flush()
    blocks_now = db.scalars(select(OpsActivityBlock).where(OpsActivityBlock.report_id == report.id, OpsActivityBlock.is_deleted.is_(False))).all()
    _compute_metrics(db, report, blocks_now)

    audit_record(db, organization_id=organization_id, actor=user, action="update", entity_type="ops_report", entity_id=report.id, entity_label=f"{report.well_code_snapshot} {report.report_date}", summary="Updated daily report", request=request)
    db.commit()
    db.refresh(report)
    return get_report(db, organization_id, report.id)


def submit_report(db: Session, organization_id: str, report_id: str, user: User, request=None):
    report = get_report(db, organization_id, report_id)
    if report.status != "draft" and report.status != "in_review":
        raise HTTPException(409, "Only draft or in-review reports can be submitted")
    blocks = db.scalars(select(OpsActivityBlock).where(OpsActivityBlock.report_id == report.id, OpsActivityBlock.is_deleted.is_(False))).all()
    if not blocks:
        raise HTTPException(422, "Cannot submit a report with no time blocks")
    # Check blocking findings
    total = sum(b.duration_minutes for b in blocks)
    if abs(total - report.period_minutes) > 60:
        raise HTTPException(422, f"Logged time {total} min differs too much from period {report.period_minutes} min — check completeness")
    for b in blocks:
        if b.classification == "NPT" and not b.npt_code_id:
            raise HTTPException(422, f"Block {b.sequence_no} NPT needs a code — complete the review")
        if b.classification == "NPT" and b.is_productive:
            raise HTTPException(422, f"Block {b.sequence_no} NPT cannot be productive")
    report.status = "submitted"
    report.submitted_at = datetime.now(timezone.utc)
    report.submitted_by = _actor(user)
    audit_record(db, organization_id=organization_id, actor=user, action="submit", entity_type="ops_report", entity_id=report.id, entity_label=str(report.report_date), summary="Submitted report", request=request)
    db.commit()
    return report


def approve_report(db: Session, organization_id: str, report_id: str, user: User, request=None):
    report = get_report(db, organization_id, report_id)
    if report.status != "submitted":
        raise HTTPException(409, "Only submitted reports can be approved")
    report.status = "approved"
    report.approved_at = datetime.now(timezone.utc)
    report.approved_by = _actor(user)
    audit_record(db, organization_id=organization_id, actor=user, action="approve", entity_type="ops_report", entity_id=report.id, entity_label=str(report.report_date), summary="Approved report", request=request)
    db.commit()
    return report


def reject_report(db: Session, organization_id: str, report_id: str, reason: str, user: User, request=None):
    report = get_report(db, organization_id, report_id)
    if report.status != "submitted":
        raise HTTPException(409, "Only submitted reports can be rejected")
    report.status = "rejected"
    report.rejection_reason = reason[:500]
    audit_record(db, organization_id=organization_id, actor=user, action="reject", entity_type="ops_report", entity_id=report.id, entity_label=str(report.report_date), summary=f"Rejected: {reason[:100]}", request=request)
    db.commit()
    return report


def delete_reports(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.id.in_(ids))).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more reports not found")
    now = datetime.now(timezone.utc)
    affected = 0
    for r in rows:
        if not r.is_deleted:
            r.is_deleted = True
            r.deleted_at = now
            affected += 1
    audit_record(db, organization_id=organization_id, actor=user, action="delete", entity_type="ops_report", entity_id=None, entity_label=f"{affected} report(s)", summary=f"Deleted {affected} report(s)", request=request)
    db.commit()
    return {"affected_count": affected}


def restore_reports(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.id.in_(ids))).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more reports not found")
    affected = 0
    for r in rows:
        if r.is_deleted:
            r.is_deleted = False
            r.deleted_at = None
            affected += 1
    audit_record(db, organization_id=organization_id, actor=user, action="restore", entity_type="ops_report", entity_id=None, entity_label=f"{affected} report(s)", summary=f"Restored {affected} report(s)", request=request)
    db.commit()
    return {"affected_count": affected}


def purge_reports(db: Session, organization_id: str, ids: list[str], user: User, request=None):
    rows = db.scalars(select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.id.in_(ids))).all()
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
        db.delete(r)
        affected += 1
    audit_record(db, organization_id=organization_id, actor=user, action="permanent-delete", entity_type="ops_report", entity_id=None, entity_label=f"{affected} report(s)", summary=f"Purged {affected} report(s)", request=request)
    db.commit()
    return {"affected_count": affected}


def brief_for_report(db: Session, organization_id: str, report_id: str):
    report = get_report(db, organization_id, report_id)
    blocks = getattr(report, "_blocks", [])
    total = sum(b.duration_minutes for b in blocks)
    planned = sum(b.duration_minutes for b in blocks if b.classification == "Planned")
    upa = sum(b.duration_minutes for b in blocks if b.classification == "UPA")
    npt = sum(b.duration_minutes for b in blocks if b.classification == "NPT")
    npt_items = [{"npt_code": b.npt_code_snapshot or "", "reason": b.reason or b.narrative[:100], "duration_minutes": b.duration_minutes, "responsible_party": b.responsible_party} for b in blocks if b.classification == "NPT"]
    time_split = {"planned_minutes": planned, "upa_minutes": upa, "npt_minutes": npt, "unaccounted_minutes": getattr(report, "_unaccounted_minutes", 0), "total_minutes": total, "avg_confidence": str(round(float(sum(b.confidence for b in blocks)/len(blocks)) if blocks else 0, 2))}
    text = build_brief(report.well_code_snapshot, report.well_name_snapshot, str(report.report_date), report.day_number, str(report.depth_start_m or "—"), str(report.depth_end_m or "—"), str(report.depth_end_m - report.depth_start_m) if report.depth_end_m and report.depth_start_m else "—", str(report.rotating_hours or "—"), [{"classification": b.classification, "narrative": b.narrative, "duration_minutes": b.duration_minutes} for b in blocks], time_split, npt_items)
    return {
        "report_id": report.id,
        "well_code": report.well_code_snapshot,
        "well_name": report.well_name_snapshot,
        "report_date": report.report_date,
        "day_number": report.day_number,
        "summary": text,
        "time_split": time_split,
        "npt_items": npt_items,
        "depth_progress": {"depth_start_m": str(report.depth_start_m) if report.depth_start_m else None, "depth_end_m": str(report.depth_end_m) if report.depth_end_m else None, "footage_m": str(report.depth_end_m - report.depth_start_m) if report.depth_end_m and report.depth_start_m else None},
        "data_quality": {"blocks": len(blocks), "avg_confidence": time_split["avg_confidence"], "unaccounted_minutes": time_split["unaccounted_minutes"]},
    }
