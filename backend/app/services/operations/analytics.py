"""Operations-only metrics. Register counts include drafts; performance requires submission."""

import itertools
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.time import as_wat
from app.domain.operations.durations import utc
from app.domain.operations.metrics import compute_rop, penetration, period_balance
from app.models.operations import (
    OpsActivityBlock,
    OpsDailyReport,
    OpsPlanItem,
    OpsPlanVersion,
    OpsSettings,
)
from app.models.rig_well import Well
from app.services.operations.plans import active_plan
from app.services.operations.scope import available

VERIFIED = ("submitted", "approved")


def _blocks(db, org, reports):
    by_report = defaultdict(list)
    for b in db.scalars(
        select(OpsActivityBlock)
        .where(
            OpsActivityBlock.organization_id == org,
            OpsActivityBlock.report_id.in_([r.id for r in reports]),
            OpsActivityBlock.is_deleted.is_(False),
        )
        .order_by(OpsActivityBlock.sequence_no)
    ):
        by_report[b.report_id].append(b)
    return by_report


def _gaps(db, org, wells, reports, scope, date_from, date_to):
    """Only expect time logs during dated active programmes, not every configured well's lifetime."""
    cfg = db.scalar(select(OpsSettings).where(OpsSettings.organization_id == org))
    zone = ZoneInfo(cfg.operating_timezone if cfg else "Africa/Lagos")
    boundary = timedelta(hours=cfg.day_boundary_hour if cfg else 0)
    last = min(date_to or datetime.now(zone).date(), (datetime.now(zone) - boundary).date() - timedelta(days=1))
    first = max(date_from or last - timedelta(days=6), last - timedelta(days=30))
    seen = {(r.well_id, r.scope, r.report_date) for r in reports if r.report_type != "DMR"}
    lookup = {w.id: w for w in wells}
    gaps = []
    plans = db.scalars(
        select(OpsPlanVersion).where(
            OpsPlanVersion.organization_id == org,
            OpsPlanVersion.well_id.in_(lookup),
            OpsPlanVersion.is_deleted.is_(False),
            OpsPlanVersion.status == "active",
            OpsPlanVersion.planned_start_at.is_not(None),
        )
    )
    for p in plans:
        if (scope and p.scope != scope) or not available(lookup[p.well_id], p.scope) or not p.planned_days:
            continue
        a = utc(p.planned_start_at).astimezone(zone) - boundary
        current = max(first, a.date())
        while current <= last and (current - a.date()).days < float(p.planned_days):
            if (p.well_id, p.scope, current) not in seen:
                gaps.append(
                    {
                        "well_code": lookup[p.well_id].well_code,
                        "scope": p.scope,
                        "date": str(current),
                        "reason": "No daily log in active programme",
                    }
                )
            current += timedelta(days=1)
    return sorted(gaps, key=lambda g: (g["date"], g["well_code"]), reverse=True)[:100]


def dashboard(db, organization_id, well_id=None, rig_id=None, date_from=None, date_to=None, scope=None):
    q = select(OpsDailyReport).where(
        OpsDailyReport.organization_id == organization_id,
        OpsDailyReport.is_deleted.is_(False),
        OpsDailyReport.is_current.is_(True),
    )
    well_q = select(Well).where(Well.organization_id == organization_id, Well.is_deleted.is_(False))
    if well_id:
        q = q.where(OpsDailyReport.well_id == well_id)
        well_q = well_q.where(Well.id == well_id)
    if rig_id:
        q = q.where(OpsDailyReport.rig_id == rig_id)
        well_q = well_q.where(Well.rig_id == rig_id)
    if scope:
        q = q.where(OpsDailyReport.scope == scope)
    if date_from:
        q = q.where(OpsDailyReport.report_date >= date_from)
    if date_to:
        q = q.where(OpsDailyReport.report_date <= date_to)
    reports = db.scalars(q.order_by(OpsDailyReport.report_date.desc(), OpsDailyReport.created_at.desc())).all()
    allocations = Counter()
    logged = Counter()
    by_code = Counter()
    by_agency = Counter()
    trends = defaultdict(Counter)
    periods = unaccounted = productive = gain = hours = 0
    blocks = _blocks(db, organization_id, reports)
    for report in reports:
        rows = blocks[report.id]
        minutes = sum(b.duration_minutes for b in rows)
        report._blocks = rows
        report._total_block_minutes = minutes
        report._unaccounted_minutes = period_balance(report.report_type, report.period_minutes, minutes)
        if report.status not in VERIFIED or (report.report_type == "DMR" and not rows):
            continue
        periods += report.period_minutes
        unaccounted += report._unaccounted_minutes
        if report.scope != "completion":
            g, h = penetration(report, rows)
            if h:
                gain += g
                hours += h
        for b in rows:
            logged[b.classification] += b.duration_minutes
            trends[report.report_date][b.classification] += b.duration_minutes
            allocations[b.allocation] += b.duration_minutes
            if b.is_productive:
                productive += b.duration_minutes
            if b.allocation == "NPT":
                by_code[b.operation_snapshot or "Uncoded"] += b.duration_minutes
                by_agency[b.responsible_party or "Not assigned"] += b.duration_minutes
    total = sum(logged.values())
    counts = Counter(r.status for r in reports)
    lag = None
    if well_id and scope:
        # One basis for lead/lag across the product: whatever the report list
        # shows for these reports, in date order, is what the dashboard reports.
        recorded = _recorded_lag_from_time_depth(
            db, organization_id, well_id, scope, [r.id for r in reports]
        )
        ordered = [recorded[r.id] for r in reports if r.id in recorded]
        lag = ordered[0]["lag_days"] if ordered else None
    wells = db.scalars(well_q).all()
    # The well picture on the dashboard: current depth from the latest report,
    # casing seats and surveys exactly as the Well Path page reads them.
    from app.services.operations import well_path as well_path_svc

    drawn_well = None
    if well_id and scope:
        drawn = well_path_svc.well_path(db, organization_id, well_id, scope)
        drawn_well = {
            "well_id": drawn["well_id"],
            "well_code": drawn["well_code"],
            "well_name": drawn["well_name"],
            "scope": drawn["scope"],
            "summary": drawn["summary"],
            "sections": drawn["sections"],
            "open_hole": drawn["open_hole"],
            "assumption": drawn["assumption"],
            "is_surveyed": drawn["is_surveyed"],
        }
        # The same numbers the card shows, taken from the drawing's own service so
        # a KPI and its picture can never disagree. ``date_reported`` is the last
        # day with a report inside the selected period, which tells a reader how
        # fresh the depth is.
        last_report = reports[0] if reports else None
        drawn_well["depth"] = {
            "current_md_m": drawn["summary"]["current_md_m"],
            "current_tvd_m": drawn["summary"]["current_tvd_m"],
            "tvd_basis": drawn["summary"]["current_tvd_basis"],
            "bit_depth_m": drawn["summary"]["bit_depth_m"],
            "date_reported": last_report.report_date.isoformat() if last_report else None,
            "report_no": last_report.report_no_text if last_report else None,
            "report_status": last_report.status if last_report else None,
            "basis": drawn["summary"]["depth_basis"],
        }
    return {
        "kpis": {
            "total_reports": len(reports),
            "draft_reports": counts["draft"],
            "submitted_reports": counts["submitted"],
            "approved_reports": counts["approved"],
            "reports_awaiting_review": sum(r.extraction_status == "needs_review" for r in reports),
            "total_logged_hours": round(total / 60, 3),
            "planned_hours": round(logged["Planned"] / 60, 3),
            "npt_hours": round(logged["NPT"] / 60, 3),
            "upa_hours": round(logged["UPA"] / 60, 3),
            "unaccounted_hours": round(unaccounted / 60, 3),
            "productive_hours": round(productive / 60, 3),
            "nonproductive_hours": round((total - productive) / 60, 3),
            "allocation_hours": {k: round(allocations[k] / 60, 3) for k in ("PT", "UPA", "NPT", "SP")},
            "productive_pct": round(100 * productive / total, 1) if total else 0,
            "npt_pct": round(100 * logged["NPT"] / total, 1) if total else 0,
            # Only drilling contributes gain/hours above, so a completion-only view
            # naturally has no rate; the explicit scope check keeps the contract
            # obvious and stops a stray block from ever producing one.
            "avg_rop": None if scope == "completion" or not hours else round(gain / hours, 3),
            "lag_days": lag,
            "wells_covered": len({r.well_id for r in reports}),
            "wells_total": sum(
                any(available(w, s) for s in ((scope,) if scope else ("drilling", "completion"))) for w in wells
            ),
            "data_quality_score": round(100 * (periods - unaccounted) / periods, 1) if periods else 0,
        },
        "recent_reports": reports[:10],
        "missing_reports": _gaps(db, organization_id, wells, reports, scope, date_from, date_to),
        "well_visual": drawn_well,
        # The Operations code is what a downtime block is grouped by; ``code``/``name``
        # stay for the existing chart series.
        "npt_by_code": [
            {"code": k, "name": k, "minutes": v, "hours": round(v / 60, 3)} for k, v in by_code.most_common(10)
        ],
        "npt_by_operation": [
            {"operation_code": k, "minutes": v, "hours": round(v / 60, 3)} for k, v in by_code.most_common(10)
        ],
        "npt_by_agency": [
            {"agency": k, "minutes": v, "hours": round(v / 60, 3)} for k, v in by_agency.most_common(10)
        ],
        "daily_trend": [
            {
                "date": d.isoformat(),
                "logged_hours": round(sum(c.values()) / 60, 3),
                "planned_hours": round(c["Planned"] / 60, 3),
                "npt_hours": round(c["NPT"] / 60, 3),
                "upa_hours": round(c["UPA"] / 60, 3),
            }
            for d, c in sorted(trends.items())
        ],
    }


def planned_at_depth(points, depth):
    """Interpolate between measured targets. A plateau has no unique inverse."""
    candidates = set()
    for point in points:
        if point["depth_m"] == depth:
            candidates.add(point["cum_days"])
    for a, b in itertools.pairwise(points):
        lo, hi = a["depth_m"], b["depth_m"]
        if lo is not None and hi is not None and min(lo, hi) < depth < max(lo, hi):
            candidates.add(a["cum_days"] + (b["cum_days"] - a["cum_days"]) * (depth - lo) / (hi - lo))
    return next(iter(candidates)) if len(candidates) == 1 else None


def _recorded_lag_from_time_depth(db, organization_id, well_id, scope, report_ids):
    """The lead/lag the engineer can see on the report list, one per report.

    ``time_depth`` interpolates planned days at a measured depth, so it is the
    only place that can compare a day against a programme that prints depth but
    no confirmed checkpoint. The dashboard reuses it instead of computing a
    second, differently-basis number.
    """
    series = time_depth(db, organization_id, well_id, scope)["lag_series"]
    included = set(report_ids)
    return {row["report_id"]: row for row in series if row["report_id"] in included}


def time_depth(db, organization_id, well_id, scope="drilling"):
    reports = db.scalars(
        select(OpsDailyReport)
        .where(
            OpsDailyReport.organization_id == organization_id,
            OpsDailyReport.well_id == well_id,
            OpsDailyReport.scope == scope,
            OpsDailyReport.is_deleted.is_(False),
            OpsDailyReport.is_current.is_(True),
            OpsDailyReport.status.in_(VERIFIED),
        )
        .order_by(OpsDailyReport.report_date)
    ).all()
    version = active_plan(db, organization_id, well_id, scope)
    baseline_ids = {r.baseline_plan_id for r in reports if r.baseline_plan_id}
    if version:
        baseline_ids.add(version.id)
    versions = {
        v.id: v
        for v in db.scalars(
            select(OpsPlanVersion).where(
                OpsPlanVersion.id.in_(baseline_ids),
                OpsPlanVersion.organization_id == organization_id,
                OpsPlanVersion.well_id == well_id,
                OpsPlanVersion.scope == scope,
            )
        )
    }
    timelines = defaultdict(list)
    checkpoints = {}
    for item in db.scalars(
        select(OpsPlanItem)
        .where(OpsPlanItem.organization_id == organization_id, OpsPlanItem.plan_version_id.in_(versions))
        .order_by(OpsPlanItem.sequence_no)
    ):
        days = float(item.cum_planned_days or 0)
        checkpoints[item.id] = days
        # Completions have no meaningful depth axis: the same programme measured in
        # activity numbers (1..n) is what the engineer can read against days.
        sequence = len(timelines[item.plan_version_id]) + 1
        timelines[item.plan_version_id].append(
            {
                "cum_days": days,
                "depth_m": float(item.target_depth_m) if item.target_depth_m is not None else None,
                "label": item.description,
                "activity_no": sequence,
                "activity_id": item.id,
            }
        )
    plan = timelines[version.id] if version else []
    actual = []
    lag = []
    activity_numbers = {
        item.id: index
        for index, item in enumerate(
            db.scalars(
                select(OpsPlanItem)
                .where(
                    OpsPlanItem.organization_id == organization_id,
                    OpsPlanItem.plan_version_id.in_(versions),
                )
                .order_by(OpsPlanItem.sequence_no)
            ),
            1,
        )
    }
    npt = []
    projection = []
    blocks = _blocks(db, organization_id, reports)
    for r in reports:
        for b in blocks[r.id]:
            if b.allocation == "NPT":
                npt.append(
                    {
                        "from": (as_wat(b.started_at) or b.started_at).isoformat(),
                        "to": (as_wat(b.ended_at) or b.ended_at).isoformat(),
                        "reason": b.reason or b.narrative[:100],
                    }
                )
        baseline = versions.get(r.baseline_plan_id)
        origin = baseline.planned_start_at if baseline else None
        # Campaign days are never the sum of the reported time blocks.
        if origin and r.period_end_at:
            elapsed = (utc(r.period_end_at) - utc(origin)).total_seconds() / 86400
            basis = "programme start"
        elif r.scope == "drilling" and r.dfs_days is not None:
            elapsed = float(r.dfs_days)
            basis = "reported DFS"
        elif r.period_end_at and reports[0].period_start_at:
            elapsed = (utc(r.period_end_at) - utc(reports[0].period_start_at)).total_seconds() / 86400
            basis = "first submitted period"
        else:
            continue
        depth = float(r.depth_end_m) if r.depth_end_m is not None else None
        # compute_rop() itself returns None for completion scope, so the page and
        # the export never render a drilling rate against completion work.
        rop = compute_rop(*penetration(r, blocks[r.id]), scope=r.scope)
        actual.append(
            {
                "cum_days": round(elapsed, 3),
                "depth_m": depth,
                "report_date": str(r.report_date),
                "label": r.report_no_text,
                "report_id": r.id,
                "rop": float(rop) if rop is not None else None,
                "basis": basis,
            }
        )
        planned = checkpoints.get(r.completed_plan_item_id)
        activity_no = activity_numbers.get(r.completed_plan_item_id) if r.completed_plan_item_id else None
        actual[-1]["activity_no"] = activity_no
        comparison = "confirmed programme activity" if planned is not None else "at measured depth"
        if planned is None and baseline and depth is not None:
            planned = planned_at_depth(timelines[baseline.id], depth)
        if planned is not None and baseline and basis != "first submitted period":
            lag.append(
                {
                    "report_date": str(r.report_date),
                    "report_id": r.id,
                    # Lead positive, lag negative — the same sign the UI and guide use.
                    "lag_days": round(planned - elapsed, 3),
                    "depth_m": depth,
                    "basis": comparison,
                    "baseline": f"{baseline.label} v{baseline.version_no}",
                }
            )
    if (
        scope != "completion"
        and actual
        and actual[-1]["depth_m"] is not None
        and actual[-1]["rop"]
        and actual[-1]["rop"] > 0
    ):
        last = actual[-1]
        target = next((p for p in plan if p["depth_m"] is not None and p["depth_m"] > last["depth_m"]), None)
        if target:
            days = (target["depth_m"] - last["depth_m"]) / last["rop"] / 24
            projection = [
                last,
                {"cum_days": round(last["cum_days"] + days, 3), "depth_m": target["depth_m"], "label": "Next deeper target"},
            ]
    # A completion has no depth to plot: report the ordinal basis explicitly so the
    # chart labels activity numbers rather than inventing a depth column.
    if scope == "completion":
        mode = "activity"
    else:
        mode = "depth" if any(row["depth_m"] is not None for row in plan + actual) else "activity"
    return {
        "mode": mode,
        "plan": plan,
        "actual": actual,
        "npt_bands": npt,
        "milestones": [],
        "lag_series": lag,
        "projection": projection,
    }
