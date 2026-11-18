"""Multi-day Well Operation Summary across all daily drilling & completion reports."""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.precision import rounded
from app.core.time import WAT_LABEL, WAT_TZ_NAME, format_wat, wat_now
from app.domain.operations.default_codes import describe_code
from app.domain.operations.metrics import compute_rop, penetration, period_balance
from app.models.rig_well import Block, Rig, Well
from app.models.vendor_master import Vendor
from app.models.operations import (
    OpsActivityBlock,
    OpsActivityCode,
    OpsDailyMetric,
    OpsDailyReport,
    OpsNptCode,
    OpsOperationCode,
    OpsPlanVersion,
    OpsSurvey,
)


def _num(value: Decimal | float | int | None) -> float | None:
    return round(float(value), 3) if value is not None else None


def _hrs(minutes: int | float) -> float:
    return round(float(minutes) / 60.0, 3)


def well_operation_summary(
    db: Session,
    organization_id: str,
    well_id: str,
    *,
    scope: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_drafts: bool = True,
) -> dict:
    """Compile a complete chronological Well Operation Summary for one well."""
    well = db.scalar(
        select(Well).where(
            Well.id == well_id,
            Well.organization_id == organization_id,
            Well.is_deleted.is_(False),
        )
    )
    if not well:
        raise HTTPException(404, "Well not found in this workspace.")

    rig = db.get(Rig, well.rig_id) if getattr(well, "rig_id", None) else None
    block_row = db.get(Block, well.block_id) if getattr(well, "block_id", None) else None

    q = select(OpsDailyReport).where(
        OpsDailyReport.organization_id == organization_id,
        OpsDailyReport.well_id == well_id,
        OpsDailyReport.is_deleted.is_(False),
    )
    if scope:
        q = q.where(OpsDailyReport.scope == scope)
    if not include_drafts:
        q = q.where(OpsDailyReport.status.in_(("submitted", "approved")))
    if date_from:
        q = q.where(OpsDailyReport.report_date >= date_from)
    if date_to:
        q = q.where(OpsDailyReport.report_date <= date_to)

    reports = list(
        db.scalars(
            q.order_by(OpsDailyReport.report_date.asc(), OpsDailyReport.scope.asc(), OpsDailyReport.created_at.asc())
        ).all()
    )
    report_ids = [r.id for r in reports]

    # Reference maps for clean labels without N+1 queries.
    op_map = {
        c.id: f"{c.operation_code} — {c.operation_name}"
        for c in db.scalars(select(OpsOperationCode).where(OpsOperationCode.organization_id == organization_id)).all()
    }
    act_map = {
        c.id: f"{c.activity_code} — {c.activity_name}"
        for c in db.scalars(select(OpsActivityCode).where(OpsActivityCode.organization_id == organization_id)).all()
    }
    npt_map = {
        c.id: (c.npt_code, c.npt_name)
        for c in db.scalars(select(OpsNptCode).where(OpsNptCode.organization_id == organization_id)).all()
    }
    vendor_map = {
        v.id: v.vendor_name
        for v in db.scalars(select(Vendor).where(Vendor.organization_id == organization_id)).all()
    }
    metrics_by_key = {
        (m.scope, m.report_date): m
        for m in db.scalars(
            select(OpsDailyMetric).where(
                OpsDailyMetric.organization_id == organization_id,
                OpsDailyMetric.well_id == well_id,
            )
        ).all()
    }

    blocks_by_report: dict[str, list[OpsActivityBlock]] = defaultdict(list)
    if report_ids:
        for blk in db.scalars(
            select(OpsActivityBlock)
            .where(
                OpsActivityBlock.organization_id == organization_id,
                OpsActivityBlock.report_id.in_(report_ids),
                OpsActivityBlock.is_deleted.is_(False),
            )
            .order_by(OpsActivityBlock.started_at.asc(), OpsActivityBlock.sequence_no.asc())
        ).all():
            blocks_by_report[blk.report_id].append(blk)

    report_date_map = {r.id: r.report_date for r in reports}
    surveys_raw = (
        list(
            db.scalars(
                select(OpsSurvey)
                .where(
                    OpsSurvey.organization_id == organization_id,
                    OpsSurvey.well_id == well_id,
                    OpsSurvey.report_id.in_(report_ids),
                    OpsSurvey.is_deleted.is_(False),
                )
            ).all()
        )
        if report_ids
        else []
    )
    surveys_raw.sort(
        key=lambda s: (
            float(s.md_m) if s.md_m is not None else 1e12,
            str(report_date_map.get(s.report_id or "", "")),
            s.station_no or 0,
        )
    )

    # Active baseline plan(s).
    plan_q = select(OpsPlanVersion).where(
        OpsPlanVersion.organization_id == organization_id,
        OpsPlanVersion.well_id == well_id,
        OpsPlanVersion.status == "active",
        OpsPlanVersion.is_deleted.is_(False),
    )
    if scope:
        plan_q = plan_q.where(OpsPlanVersion.scope == scope)
    active_plans = list(db.scalars(plan_q).all())
    planned_days_total = (
        round(sum(float(p.planned_days or 0) for p in active_plans), 3)
        if any(p.planned_days is not None for p in active_plans)
        else None
    )

    # Well header attributes drawn from workspace master data + latest populated report fields.
    rig_code = (rig.rig_code if rig else "") or next(
        (r.rig_code_snapshot for r in reversed(reports) if r.rig_code_snapshot), ""
    )
    rig_name = (rig.rig_name if rig else "") or next(
        (r.rig_name_snapshot for r in reversed(reports) if r.rig_name_snapshot), ""
    )
    block_text = (
        (getattr(block_row, "block_code", "") or getattr(block_row, "block_name", "")) if block_row else ""
    ) or next((r.block_text for r in reversed(reports) if r.block_text), "")
    field_site = (
        getattr(well, "field_name", "")
        or next((r.site for r in reversed(reports) if r.site), "")
        or next((r.project for r in reversed(reports) if r.project), "")
    )
    customer = next((r.customer for r in reversed(reports) if r.customer), "")
    uwi = next((r.uwi for r in reversed(reports) if r.uwi), "")
    datum = next((r.datum for r in reversed(reports) if r.datum), "")
    spud_date = next((r.spud_date for r in reports if r.spud_date), None)
    latest_status = next((r.current_status for r in reversed(reports) if r.current_status), "")
    latest_section = next((r.hole_section_text for r in reversed(reports) if r.hole_section_text), "")
    latest_bha = next((r.bha_summary for r in reversed(reports) if r.bha_summary), "")
    latest_csg_r = next(
        (r for r in reversed(reports) if r.last_casing_depth_m is not None or r.last_casing_size_in is not None), None
    )
    last_casing = ""
    if latest_csg_r:
        parts = []
        if latest_csg_r.last_casing_size_in is not None:
            parts.append(f'{rounded(latest_csg_r.last_casing_size_in)}"')
        if latest_csg_r.last_casing_depth_m is not None:
            parts.append(f"@ {rounded(latest_csg_r.last_casing_depth_m)} m MD")
        last_casing = " ".join(parts)
    latest_mud_r = next((r for r in reversed(reports) if r.mud_weight_ppg is not None or r.mud_type), None)
    latest_mud = ""
    if latest_mud_r:
        mp = []
        if latest_mud_r.mud_type:
            mp.append(latest_mud_r.mud_type)
        if latest_mud_r.mud_weight_ppg is not None:
            mp.append(f"{rounded(latest_mud_r.mud_weight_ppg)} ppg")
        if latest_mud_r.mud_viscosity_sec is not None:
            mp.append(f"FV {rounded(latest_mud_r.mud_viscosity_sec)} s/qt")
        if latest_mud_r.mud_pv_cp is not None and latest_mud_r.mud_yp_lbf is not None:
            mp.append(f"PV/YP {rounded(latest_mud_r.mud_pv_cp)}/{rounded(latest_mud_r.mud_yp_lbf)}")
        latest_mud = " · ".join(mp)

    # Accumulators.
    activities: list[dict] = []
    daily_rollup: list[dict] = []
    pt_npt_groups: dict[tuple[str, str, str, str], dict] = {}
    phase_groups: dict[str, dict] = {}

    cum_minutes = 0
    total_planned_min = 0
    total_upa_min = 0
    total_npt_min = 0
    total_prod_min = 0
    total_unaccounted_min = 0
    alloc_min = {"PT": 0, "UPA": 0, "NPT": 0, "SP": 0}
    total_footage = Decimal(0)
    has_footage = False
    rop_footage = Decimal(0)
    rop_rot_hours = Decimal(0)
    total_rot_hours = Decimal(0)
    latest_lag: float | None = None

    for r in reports:
        r_blocks = blocks_by_report.get(r.id, [])
        r_logged = sum(b.duration_minutes for b in r_blocks)
        r_planned = sum(b.duration_minutes for b in r_blocks if b.classification == "Planned")
        r_upa = sum(b.duration_minutes for b in r_blocks if b.classification == "UPA")
        r_npt = sum(b.duration_minutes for b in r_blocks if b.classification == "NPT")
        r_pt = sum(b.duration_minutes for b in r_blocks if b.allocation == "PT")
        r_sp = sum(b.duration_minutes for b in r_blocks if b.allocation == "SP")
        r_alloc_upa = sum(b.duration_minutes for b in r_blocks if b.allocation == "UPA")
        r_alloc_npt = sum(b.duration_minutes for b in r_blocks if b.allocation == "NPT")
        r_prod = sum(b.duration_minutes for b in r_blocks if b.is_productive)
        r_unacc = period_balance(r.report_type, r.period_minutes, r_logged)

        total_planned_min += r_planned
        total_upa_min += r_upa
        total_npt_min += r_npt
        total_prod_min += r_prod
        total_unaccounted_min += r_unacc
        alloc_min["PT"] += r_pt
        alloc_min["UPA"] += r_alloc_upa
        alloc_min["NPT"] += r_alloc_npt
        alloc_min["SP"] += r_sp

        r_foot, r_rot = penetration(r, r_blocks)
        r_rop = compute_rop(r_foot, r_rot)
        day_progress = r_foot
        if day_progress is None and r.progress_m is not None and r.progress_m >= 0:
            day_progress = r.progress_m
        elif (
            day_progress is None
            and r.depth_start_m is not None
            and r.depth_end_m is not None
            and r.depth_end_m >= r.depth_start_m
        ):
            day_progress = r.depth_end_m - r.depth_start_m
        if day_progress is not None and day_progress > 0:
            total_footage += day_progress
            has_footage = True
        if r_rot is not None and r_rot > 0:
            total_rot_hours += r_rot
        elif r.rotating_hours is not None and r.rotating_hours > 0:
            total_rot_hours += r.rotating_hours
        if r_foot is not None and r_rot is not None and r_rot > 0:
            rop_footage += r_foot
            rop_rot_hours += r_rot

        metric = metrics_by_key.get((r.scope, r.report_date))
        day_lag = _num(metric.lag_days) if metric and metric.lag_days is not None else None
        if day_lag is not None:
            latest_lag = day_lag

        section_key = (
            r.hole_section_text
            or (r_blocks[-1].phase_raw if r_blocks and r_blocks[-1].phase_raw else "")
            or r.scope.title()
        )
        pg = phase_groups.setdefault(
            section_key,
            {
                "phase": section_key,
                "scope": r.scope,
                "reports": 0,
                "start_md_m": None,
                "end_md_m": None,
                "end_tvd_m": None,
                "footage_m": Decimal(0),
                "logged_min": 0,
                "planned_min": 0,
                "upa_min": 0,
                "npt_min": 0,
                "rot_hours": Decimal(0),
                "rop_foot": Decimal(0),
                "rop_rot": Decimal(0),
            },
        )
        pg["reports"] += 1
        if r.depth_start_m is not None and (pg["start_md_m"] is None or r.depth_start_m < pg["start_md_m"]):
            pg["start_md_m"] = r.depth_start_m
        if r.depth_end_m is not None and (pg["end_md_m"] is None or r.depth_end_m > pg["end_md_m"]):
            pg["end_md_m"] = r.depth_end_m
        if r.tvd_m is not None and (pg["end_tvd_m"] is None or r.tvd_m > pg["end_tvd_m"]):
            pg["end_tvd_m"] = r.tvd_m
        if day_progress is not None and day_progress > 0:
            pg["footage_m"] += day_progress
        pg["logged_min"] += r_logged
        pg["planned_min"] += r_planned
        pg["upa_min"] += r_upa
        pg["npt_min"] += r_npt
        if r_rot is not None and r_rot > 0:
            pg["rot_hours"] += r_rot
            if r_foot is not None:
                pg["rop_foot"] += r_foot
                pg["rop_rot"] += r_rot

        for b in r_blocks:
            cum_minutes += b.duration_minutes
            dur_h = _hrs(b.duration_minutes)
            cum_d = round(cum_minutes / 1440.0, 3)

            op_label = (
                op_map.get(b.operation_code_id or "")
                or (
                    describe_code(b.source_operation_code, "Operation")
                    if b.source_operation_code
                    else ""
                )
            )
            act_family = "OpenWells code token" if b.source_page else "Activity"
            act_label = (
                act_map.get(b.activity_code_id or "")
                or (describe_code(b.source_activity_code, act_family) if b.source_activity_code else "")
            )
            npt_code, npt_name = npt_map.get(b.npt_code_id or "", (b.npt_code_snapshot or "", ""))
            agency = (
                b.responsible_party
                or vendor_map.get(b.vendor_id or "", "")
                or customer
                or "Unassigned"
            )
            phase_label = b.phase_raw or r.hole_section_text or r.scope.title()
            cause_label = (
                f"{npt_code} — {npt_name}"
                if npt_code and npt_name
                else (npt_code or b.cause_code or b.source_cause_code or b.allocation)
            )
            b_mw = b.mud_weight_ppg if b.mud_weight_ppg is not None else r.mud_weight_ppg
            b_foot = (
                b.footage_m
                if b.footage_m is not None
                else (
                    b.depth_to_m - b.depth_from_m
                    if b.depth_from_m is not None and b.depth_to_m is not None and b.depth_to_m >= b.depth_from_m
                    else None
                )
            )
            b_rop = b.rop_m_per_hr if b.rop_m_per_hr is not None else compute_rop(b_foot, b.rotating_hours)
            npt_h = dur_h if (b.classification == "NPT" or b.allocation == "NPT") else 0.0
            pt_h = 0.0 if npt_h > 0 else dur_h

            activities.append(
                {
                    "id": b.id,
                    "line_no": len(activities) + 1,
                    "report_id": r.id,
                    "block": r.block_text or block_text,
                    "field": r.site or field_site,
                    "rig_name": r.rig_code_snapshot or rig_code,
                    "well_code": r.well_code_snapshot or well.well_code,
                    "well_name": r.well_name_snapshot or well.well_name,
                    "scope": r.scope,
                    "report_date": str(r.report_date),
                    "report_no": r.report_no_text,
                    "report_type": r.report_type,
                    "report_status": r.status,
                    "sequence_no": b.sequence_no,
                    "day_number": r.day_number,
                    "hole_section": r.hole_section_text or "",
                    "start_wat": format_wat(b.started_at, "%Y-%m-%d %H:%M"),
                    "end_wat": format_wat(b.ended_at, "%Y-%m-%d %H:%M"),
                    "duration_minutes": b.duration_minutes,
                    "cum_hours": _hrs(cum_minutes),
                    "phase": phase_label,
                    "phase_code": b.phase_raw or "",
                    "phase_label": phase_label,
                    "operation": op_label,
                    "operation_code": op_label,
                    "activity": act_label,
                    "activity_code": act_label,
                    "classification": b.classification,
                    "allocation": b.allocation,
                    "is_productive": bool(b.is_productive),
                    "narrative": b.narrative,
                    "mud_weight_ppg": _num(b_mw),
                    "depth_from_m": _num(b.depth_from_m),
                    "depth_to_m": _num(b.depth_to_m),
                    "tvd_from_m": _num(b.tvd_from_m),
                    "tvd_to_m": _num(b.tvd_to_m if b.tvd_to_m is not None else (r.tvd_m if b.depth_to_m == r.depth_end_m and b.depth_to_m is not None else None)),
                    "bit_depth_m": _num(b.bit_depth_m),
                    "footage_m": _num(b_foot),
                    "duration_hours": dur_h,
                    "cum_days": cum_d,
                    "pt_hours": pt_h,
                    "npt_hours": npt_h,
                    "rotating_hours": _num(b.rotating_hours),
                    "rop_m_per_hr": _num(b_rop),
                    "agency": "" if agency == "Unassigned" else agency,
                    "responsible_party": "" if agency == "Unassigned" else agency,
                    "npt_code": npt_code,
                    "cause": b.cause_code or b.source_cause_code,
                    "cause_code": b.cause_code or b.source_cause_code or "",
                    "reason": b.reason,
                    "review_state": b.review_state,
                }
            )

            gkey = (agency, phase_label, op_label or "General", cause_label, b.classification, b.allocation)
            grp = pt_npt_groups.setdefault(
                gkey,
                {
                    "agency": agency,
                    "phase": phase_label,
                    "operation": op_label or "General",
                    "cause": cause_label,
                    "cause_code": b.cause_code or b.source_cause_code or "",
                    "npt_code": npt_code or op_label or b.allocation,
                    "classification": b.classification,
                    "allocation": b.allocation,
                    "sample_reason": "",
                    "pt_min": 0,
                    "upa_min": 0,
                    "npt_min": 0,
                    "sp_min": 0,
                    "total_min": 0,
                    "events": 0,
                },
            )
            if not grp["sample_reason"] and (b.reason or b.narrative):
                grp["sample_reason"] = (b.reason or b.narrative)[:200]
            grp["events"] += 1
            grp["total_min"] += b.duration_minutes
            if b.classification == "NPT" or b.allocation == "NPT":
                grp["npt_min"] += b.duration_minutes
            elif b.classification == "UPA" or b.allocation == "UPA":
                grp["upa_min"] += b.duration_minutes
            elif b.allocation == "SP":
                grp["sp_min"] += b.duration_minutes
            else:
                grp["pt_min"] += b.duration_minutes

        r_casing = (
            f'{r.last_casing_size_in}" @ {r.last_casing_depth_m} m'
            if r.last_casing_size_in is not None and r.last_casing_depth_m is not None
            else (f'{r.last_casing_size_in}"' if r.last_casing_size_in is not None else "")
        )
        r_prod_min = sum(b.duration_minutes for b in r_blocks if b.is_productive)
        daily_rollup.append(
            {
                "id": r.id,
                "report_id": r.id,
                "report_date": str(r.report_date),
                "report_no": r.report_no_text,
                "day_number": r.day_number,
                "dfs_days": _num(r.dfs_days),
                "scope": r.scope,
                "report_type": r.report_type,
                "status": r.status,
                "reopened": bool(r.reopened_at),
                "extraction_status": r.extraction_status,
                "rig_code": r.rig_code_snapshot or rig_code,
                "hole_section": r.hole_section_text,
                "depth_start_m": _num(r.depth_start_m),
                "depth_end_m": _num(r.depth_end_m),
                "tvd_start_m": _num(r.tvd_start_m),
                "tvd_m": _num(r.tvd_m),
                "tvd_source": r.tvd_source,
                "bit_depth_m": _num(r.bit_depth_m),
                "progress_m": _num(day_progress),
                "mud_type": r.mud_type,
                "mud_weight_ppg": _num(r.mud_weight_ppg),
                "mud_viscosity_sec": _num(r.mud_viscosity_sec),
                "last_casing": r_casing,
                "rotating_hours": _num(r_rot if r_rot is not None else r.rotating_hours),
                "rop_m_per_hr": _num(r_rop),
                "blocks_count": len(r_blocks),
                "block_count": len(r_blocks),
                "survey_count": sum(1 for s in surveys_raw if s.report_id == r.id),
                "logged_hours": _hrs(r_logged),
                "cum_days": round(cum_minutes / 1440.0, 3),
                "planned_hours": _hrs(r_planned),
                "upa_hours": _hrs(r_upa),
                "npt_hours": _hrs(r_npt),
                "pt_hours": _hrs(r_pt),
                "sp_hours": _hrs(r_sp),
                "productive_pct": round((r_prod_min / r_logged) * 100.0, 2) if r_logged else 0.0,
                "unaccounted_hours": _hrs(r_unacc),
                "lag_days": day_lag,
                "pob_count": r.pob_count,
                "current_status": r.current_status,
                "operation_summary": r.operation_summary,
                "forward_plan": r.forward_plan,
                "hse_summary": r.hse_summary,
            }
        )

    total_logged_h = _hrs(cum_minutes)
    pt_npt_rows = []
    for idx, grp in enumerate(
        sorted(pt_npt_groups.values(), key=lambda g: (-g["npt_min"], -g["upa_min"], -g["total_min"])), 1
    ):
        tot_h = _hrs(grp["total_min"])
        share = round((grp["total_min"] / cum_minutes) * 100.0, 2) if cum_minutes else 0.0
        npt_share = (
            round((grp["npt_min"] / total_npt_min) * 100.0, 2)
            if total_npt_min and grp["npt_min"]
            else 0.0
        )
        pt_npt_rows.append(
            {
                "id": f"ptnpt-{idx}",
                "classification": grp["classification"],
                "allocation": grp["allocation"],
                "agency": grp["agency"],
                "responsible_party": grp["agency"],
                "phase": grp["phase"],
                "operation": grp["operation"],
                "code": grp["npt_code"],
                "cause": grp["cause"],
                "cause_code": grp["cause_code"],
                "pt_hours": _hrs(grp["pt_min"]),
                "upa_hours": _hrs(grp["upa_min"]),
                "npt_hours": _hrs(grp["npt_min"]),
                "sp_hours": _hrs(grp["sp_min"]),
                "hours": tot_h,
                "days": round(grp["total_min"] / 1440.0, 3),
                "total_hours": tot_h,
                "share_pct": share,
                "pct_of_total": share,
                "pct_of_npt": npt_share,
                "events": grp["events"],
                "sample_reason": grp["sample_reason"],
            }
        )

    phase_rows = []
    for idx, pg in enumerate(phase_groups.values(), 1):
        p_rop = compute_rop(pg["rop_foot"], pg["rop_rot"]) if pg["rop_rot"] > 0 else None
        p_prod_min = pg["logged_min"] - pg["npt_min"]
        p_days = round(pg["logged_min"] / 1440.0, 3)
        p_hours = _hrs(pg["logged_min"])
        phase_rows.append(
            {
                "id": f"phase-{idx}",
                "phase": pg["phase"],
                "hole_section": pg.get("hole_section") or pg["scope"].title(),
                "scope": pg["scope"],
                "reports": pg["reports"],
                "events": pg["reports"],
                "start_md_m": _num(pg["start_md_m"]),
                "end_md_m": _num(pg["end_md_m"]),
                "max_md_m": _num(pg["end_md_m"]),
                "end_tvd_m": _num(pg["end_tvd_m"]),
                "max_tvd_m": _num(pg["end_tvd_m"]),
                "footage_m": _num(pg["footage_m"]) or 0.0,
                "logged_hours": p_hours,
                "total_hours": p_hours,
                "days": p_days,
                "total_days": p_days,
                "planned_hours": _hrs(pg["planned_min"]),
                "pt_hours": _hrs(pg["planned_min"]),
                "upa_hours": _hrs(pg["upa_min"]),
                "npt_hours": _hrs(pg["npt_min"]),
                "sp_hours": 0.0,
                "productive_pct": round((p_prod_min / pg["logged_min"]) * 100.0, 2) if pg["logged_min"] else 0.0,
                "npt_pct": round((pg["npt_min"] / pg["logged_min"]) * 100.0, 2) if pg["logged_min"] else 0.0,
                "rotating_hours": _num(pg["rot_hours"]) if pg["rot_hours"] > 0 else None,
                "rop_m_per_hr": _num(p_rop),
            }
        )

    report_no_map = {r.id: r.report_no_text or "" for r in reports}
    survey_rows = [
        {
            "id": s.id,
            "report_id": s.report_id or "",
            "station_no": idx,
            "report_date": str(report_date_map.get(s.report_id or "", "")),
            "report_no": report_no_map.get(s.report_id or "", ""),
            "scope": s.scope,
            "md_m": _num(s.md_m),
            "tvd_m": _num(s.tvd_m),
            "inc_deg": _num(s.inc_deg),
            "azi_deg": _num(s.azi_deg),
            "ns_m": _num(s.ns_m),
            "ew_m": _num(s.ew_m),
            "vsec_m": _num(s.vsec_m),
            "dls_deg_per_30m": _num(s.dls_deg_per_30m),
            "tool": s.tool,
            "source": s.source,
        }
        for idx, s in enumerate(surveys_raw, 1)
    ]

    start_mds = [r.depth_start_m for r in reports if r.depth_start_m is not None]
    end_mds = [r.depth_end_m for r in reports if r.depth_end_m is not None]
    tvds = [r.tvd_m for r in reports if r.tvd_m is not None]
    survey_tvds = [s.tvd_m for s in surveys_raw if s.tvd_m is not None]
    auth_mds = [r.md_auth_m for r in reports if r.md_auth_m is not None]
    bits = [r.bit_depth_m for r in reports if r.bit_depth_m is not None]
    mws = [r.mud_weight_ppg for r in reports if r.mud_weight_ppg is not None]
    incs = [s.inc_deg for s in surveys_raw if s.inc_deg is not None]
    dlss = [s.dls_deg_per_30m for s in surveys_raw if s.dls_deg_per_30m is not None]
    pobs = [r.pob_count for r in reports if r.pob_count is not None]
    overall_rop = compute_rop(rop_footage, rop_rot_hours) if rop_rot_hours > 0 else None
    cum_days_val = round(cum_minutes / 1440.0, 3)
    opening_md_val = _num(start_mds[0]) if start_mds else None
    closing_md_val = _num(end_mds[-1]) if end_mds else None
    closing_tvd_val = _num(tvds[-1]) if tvds else (_num(survey_tvds[-1]) if survey_tvds else None)
    auth_md_val = _num(auth_mds[-1]) if auth_mds else None
    nonprod_min = max(0, cum_minutes - total_prod_min)

    kpis = {
        "total_reports": len(reports),
        "drilling_reports": sum(1 for r in reports if r.scope == "drilling"),
        "completion_reports": sum(1 for r in reports if r.scope == "completion"),
        "draft_reports": sum(1 for r in reports if r.status in ("draft", "in_review", "rejected")),
        "submitted_reports": sum(1 for r in reports if r.status == "submitted"),
        "approved_reports": sum(1 for r in reports if r.status == "approved"),
        "reopened_reports": sum(1 for r in reports if r.reopened_at is not None),
        "awaiting_review": sum(1 for r in reports if r.extraction_status == "needs_review"),
        "total_blocks": len(activities),
        "total_logged_hours": total_logged_h,
        "total_logged_days": cum_days_val,
        "cum_logged_days": cum_days_val,
        "planned_hours": _hrs(total_planned_min),
        "upa_hours": _hrs(total_upa_min),
        "npt_hours": _hrs(total_npt_min),
        "productive_hours": _hrs(total_prod_min),
        "nonproductive_hours": _hrs(nonprod_min),
        "productive_pct": round((total_prod_min / cum_minutes) * 100.0, 2) if cum_minutes else 0.0,
        "npt_pct": round((total_npt_min / cum_minutes) * 100.0, 2) if cum_minutes else 0.0,
        "upa_pct": round((total_upa_min / cum_minutes) * 100.0, 2) if cum_minutes else 0.0,
        "sp_pct": round((alloc_min["SP"] / cum_minutes) * 100.0, 2) if cum_minutes else 0.0,
        "pt_hours": _hrs(alloc_min["PT"]),
        "alloc_upa_hours": _hrs(alloc_min["UPA"]),
        "alloc_npt_hours": _hrs(alloc_min["NPT"]),
        "sp_hours": _hrs(alloc_min["SP"]),
        "unaccounted_hours": _hrs(total_unaccounted_min),
        "opening_md_m": opening_md_val,
        "start_md_m": opening_md_val,
        "closing_md_m": closing_md_val,
        "current_md_m": closing_md_val,
        "max_md_m": _num(max(end_mds)) if end_mds else None,
        "closing_tvd_m": closing_tvd_val,
        "current_tvd_m": closing_tvd_val,
        "max_tvd_m": _num(max([*tvds, *survey_tvds])) if (tvds or survey_tvds) else None,
        "md_auth_m": auth_md_val,
        "authorized_md_m": auth_md_val,
        "latest_bit_depth_m": _num(bits[-1]) if bits else None,
        "latest_mud_weight_ppg": _num(mws[-1]) if mws else None,
        "total_footage_m": _num(total_footage) if has_footage else 0.0,
        "total_rotating_hours": _num(total_rot_hours) if total_rot_hours > 0 else 0.0,
        "avg_rop_m_per_hr": _num(overall_rop),
        "planned_days": planned_days_total,
        "lag_days": latest_lag,
        "schedule_variance_days": latest_lag,
        "survey_count": len(survey_rows),
        "max_inc_deg": _num(max(incs)) if incs else None,
        "max_dls_deg_per_30m": _num(max(dlss)) if dlss else None,
        "latest_pob": pobs[-1] if pobs else None,
    }

    scope_label = scope.title() if scope else "Drilling & Completion"
    return {
        "generated_at": wat_now(),
        "timezone": WAT_TZ_NAME,
        "timezone_label": WAT_LABEL,
        "well_id": well.id,
        "well_code": well.well_code,
        "well_name": well.well_name,
        "rig_code": rig_code,
        "rig_name": rig_name,
        "block_text": block_text,
        "field_site": field_site,
        "customer": customer,
        "uwi": uwi,
        "datum": datum,
        "scope_label": scope_label,
        "include_drafts": include_drafts,
        "spud_date": spud_date,
        "first_report_date": reports[0].report_date if reports else None,
        "last_report_date": reports[-1].report_date if reports else None,
        "latest_status": latest_status,
        "latest_hole_section": latest_section,
        "last_casing": last_casing,
        "latest_mud": latest_mud,
        "latest_bha": latest_bha,
        "kpis": kpis,
        "activities": activities,
        "daily_rollup": daily_rollup,
        "pt_npt_breakdown": pt_npt_rows,
        "phase_breakdown": phase_rows,
        "surveys": survey_rows,
    }
