"""Dashboard and analytics service."""

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models.operations import OpsActivityBlock, OpsDailyMetric, OpsDailyReport, OpsPlanVersion, OpsPlanItem
from app.models.rig_well import Well


def dashboard(db: Session, organization_id: str, well_id: str | None = None, rig_id: str | None = None, date_from: date | None = None, date_to: date | None = None):
    # Reports query
    q = select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.is_deleted.is_(False))
    if well_id:
        q = q.where(OpsDailyReport.well_id == well_id)
    if rig_id:
        q = q.where(OpsDailyReport.rig_id == rig_id)
    if date_from:
        q = q.where(OpsDailyReport.report_date >= date_from)
    if date_to:
        q = q.where(OpsDailyReport.report_date <= date_to)
    reports = db.scalars(q).all()

    total_reports = len(reports)
    draft_reports = sum(1 for r in reports if r.status == "draft")
    submitted_reports = sum(1 for r in reports if r.status == "submitted")
    approved_reports = sum(1 for r in reports if r.status == "approved")
    awaiting_review = sum(1 for r in reports if r.extraction_status == "needs_review")

    # Aggregate blocks
    block_q = select(OpsActivityBlock).where(OpsActivityBlock.organization_id == organization_id, OpsActivityBlock.is_deleted.is_(False))
    if well_id:
        block_q = block_q.join(OpsDailyReport, OpsActivityBlock.report_id == OpsDailyReport.id).where(OpsDailyReport.well_id == well_id)
    if date_from:
        block_q = block_q.where(OpsActivityBlock.started_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc))
    if date_to:
        block_q = block_q.where(OpsActivityBlock.started_at <= datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc))
    blocks = db.scalars(block_q).all()

    total_min = sum(b.duration_minutes for b in blocks)
    planned_min = sum(b.duration_minutes for b in blocks if b.classification == "Planned")
    npt_min = sum(b.duration_minutes for b in blocks if b.classification == "NPT")
    upa_min = sum(b.duration_minutes for b in blocks if b.classification == "UPA")
    productive_min = sum(b.duration_minutes for b in blocks if b.is_productive)

    productive_pct = (productive_min / total_min * 100) if total_min else 0
    npt_pct = (npt_min / total_min * 100) if total_min else 0

    # NPT by code
    from collections import Counter
    npt_by_code_counter = Counter()
    npt_hours_by_code = {}
    for b in blocks:
        if b.classification == "NPT":
            key = b.npt_code_snapshot or "UNCODED"
            npt_by_code_counter[key] += b.duration_minutes
    npt_by_code = [{"code": k, "minutes": v, "hours": round(v/60, 2), "name": k} for k, v in npt_by_code_counter.most_common(10)]

    npt_by_agency_counter = Counter()
    for b in blocks:
        if b.classification == "NPT":
            key = b.responsible_party or "Unknown"
            npt_by_agency_counter[key] += b.duration_minutes
    npt_by_agency = [{"agency": k, "minutes": v, "hours": round(v/60, 2)} for k, v in npt_by_agency_counter.most_common(10)]

    # Daily trend from metrics
    metric_q = select(OpsDailyMetric).where(OpsDailyMetric.organization_id == organization_id)
    if well_id:
        metric_q = metric_q.where(OpsDailyMetric.well_id == well_id)
    if date_from:
        metric_q = metric_q.where(OpsDailyMetric.report_date >= date_from)
    if date_to:
        metric_q = metric_q.where(OpsDailyMetric.report_date <= date_to)
    metrics = db.scalars(metric_q.order_by(OpsDailyMetric.report_date)).all()
    daily_trend = [{"date": str(m.report_date), "logged_hours": round(m.logged_minutes/60, 2), "npt_hours": round(m.npt_minutes/60, 2), "planned_hours": round(m.planned_minutes/60, 2), "depth_end_m": float(m.depth_end_m) if m.depth_end_m else None} for m in metrics]

    # Recent reports
    recent = sorted(reports, key=lambda r: r.report_date, reverse=True)[:10]
    # Enrich recent with blocks
    for r in recent:
        blks = db.scalars(select(OpsActivityBlock).where(OpsActivityBlock.report_id == r.id, OpsActivityBlock.is_deleted.is_(False))).all()
        r._blocks = blks  # type: ignore
        r._unaccounted_minutes = 0
        r._total_block_minutes = sum(b.duration_minutes for b in blks)

    # Missing reports - naive: days without report for active wells
    missing = []
    wells = db.scalars(select(Well).where(Well.organization_id == organization_id, Well.is_deleted.is_(False))).all()
    wells_total = len(wells)
    wells_covered = len(set(r.well_id for r in reports))

    # Average ROP
    avg_rop = None
    if blocks:
        # Compute ROP where available
        rops = [float(b.rop_m_per_hr) for b in blocks if b.rop_m_per_hr is not None and b.rop_m_per_hr > 0]
        if rops:
            avg_rop = sum(rops) / len(rops)

    # Data quality
    data_quality = 100.0
    if awaiting_review:
        data_quality -= min(20, awaiting_review * 2)
    if npt_min and any(b.classification == "NPT" and not b.npt_code_id for b in blocks):
        data_quality -= 10
    if total_min:
        # penalize unaccounted
        unaccounted_total = sum(0 for r in reports)  # simplified
        data_quality = max(0, data_quality)

    kpis = {
        "total_reports": total_reports,
        "draft_reports": draft_reports,
        "submitted_reports": submitted_reports,
        "approved_reports": approved_reports,
        "reports_awaiting_review": awaiting_review,
        "total_logged_hours": round(total_min/60, 2),
        "planned_hours": round(planned_min/60, 2),
        "npt_hours": round(npt_min/60, 2),
        "upa_hours": round(upa_min/60, 2),
        "productive_pct": round(productive_pct, 1),
        "npt_pct": round(npt_pct, 1),
        "unaccounted_hours": 0,
        "avg_rop": round(avg_rop, 2) if avg_rop else None,
        "lag_days": None,
        "wells_covered": wells_covered,
        "wells_total": wells_total,
        "data_quality_score": round(data_quality, 1),
    }

    return {
        "kpis": kpis,
        "npt_by_code": npt_by_code,
        "npt_by_agency": npt_by_agency,
        "daily_trend": daily_trend,
        "recent_reports": recent,
        "missing_reports": missing,
    }


def time_depth(db: Session, organization_id: str, well_id: str, scope: str = "drilling"):
    reports = db.scalars(select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.well_id == well_id, OpsDailyReport.scope == scope, OpsDailyReport.is_deleted.is_(False)).order_by(OpsDailyReport.report_date)).all()
    if not reports:
        return {"plan": [], "actual": [], "npt_bands": [], "milestones": [], "lag_series": []}

    # Actual curve: cumulative days vs depth
    actual = []
    cum_days = 0
    cum_depth = None
    for r in reports:
        blocks = db.scalars(select(OpsActivityBlock).where(OpsActivityBlock.report_id == r.id, OpsActivityBlock.is_deleted.is_(False)).order_by(OpsActivityBlock.sequence_no)).all()
        day_hours = sum(b.duration_minutes for b in blocks) / 60
        # Use report depth_end_m as depth at end of day
        depth_m = float(r.depth_end_m) if r.depth_end_m else (float(cum_depth) if cum_depth else 0)
        cum_days += day_hours / 24 if day_hours else 0
        # If no depth, keep last
        if r.depth_end_m:
            cum_depth = r.depth_end_m
        actual.append({"cum_days": round(cum_days, 2), "depth_m": depth_m, "report_date": r.report_date.isoformat(), "label": f"{r.report_date} ({r.report_no_text})"})

    # Plan curve from active plan version
    plan = []
    plan_version = db.scalar(select(OpsPlanVersion).where(OpsPlanVersion.organization_id == organization_id, OpsPlanVersion.well_id == well_id, OpsPlanVersion.scope == scope, OpsPlanVersion.status == "active", OpsPlanVersion.is_deleted.is_(False)))
    if not plan_version:
        plan_version = db.scalar(select(OpsPlanVersion).where(OpsPlanVersion.organization_id == organization_id, OpsPlanVersion.well_id == well_id, OpsPlanVersion.scope == scope, OpsPlanVersion.is_deleted.is_(False)).order_by(OpsPlanVersion.version_no.desc()))
    if plan_version:
        items = db.scalars(select(OpsPlanItem).where(OpsPlanItem.organization_id == organization_id, OpsPlanItem.plan_version_id == plan_version.id).order_by(OpsPlanItem.sequence_no)).all()
        cum = 0
        for it in items:
            hrs = float(it.planned_hours) if it.planned_hours else 0
            cum += hrs / 24
            it.cum_planned_days = Decimal(str(round(cum, 2)))  # type: ignore
            plan.append({"cum_days": round(cum, 2), "depth_m": float(it.target_depth_m) if it.target_depth_m else 0, "label": it.description[:60]})

    # NPT bands: intervals where NPT
    npt_bands = []
    for r in reports:
        blocks = db.scalars(select(OpsActivityBlock).where(OpsActivityBlock.report_id == r.id, OpsActivityBlock.classification == "NPT", OpsActivityBlock.is_deleted.is_(False))).all()
        for b in blocks:
            npt_bands.append({"from": b.started_at.isoformat(), "to": b.ended_at.isoformat(), "well_id": well_id, "reason": b.reason or b.narrative[:100]})

    # Milestones: spud, section TDs
    well = db.get(Well, well_id)
    milestones = []
    if well:
        # Add dummy milestones from reports depth jumps
        pass

    # Lag series: actual cumulative days - plan cumulative days at same depth (simplified: compare at each actual point)
    lag_series = []
    if plan and actual:
        # For each actual point, find plan days at that depth via interpolation
        for a in actual:
            depth = a["depth_m"]
            # find plan segment containing depth
            plan_days_at_depth = None
            for i, p in enumerate(plan):
                if p["depth_m"] >= depth:
                    plan_days_at_depth = p["cum_days"]
                    break
            if plan_days_at_depth is None and plan:
                plan_days_at_depth = plan[-1]["cum_days"]
            if plan_days_at_depth is not None:
                lag = round(a["cum_days"] - plan_days_at_depth, 2)
                lag_series.append({"report_date": a["report_date"], "lag_days": lag, "depth_m": depth})

    return {"plan": plan, "actual": actual, "npt_bands": npt_bands, "milestones": milestones, "lag_series": lag_series}
