"""Cost Intelligence service: feeds the workspace's own figures to the analysis.

The figures come from the Business Dashboard service, so this module inherits
its tenant scoping, currency handling and capability rules unchanged: an AFE
amount the caller may not read arrives here as ``None`` and the checks that
need it are skipped. Nothing is written except the export audit entry.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha1

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.domain import cost_intelligence as domain
from app.models import User
from app.schemas.cost_intelligence import (
    IntelligenceActivityBreakdown,
    IntelligenceCapabilities,
    IntelligenceCount,
    IntelligenceDay,
    IntelligenceEvidence,
    IntelligenceFinding,
    IntelligenceForecast,
    IntelligenceGroupBreakdown,
    IntelligenceKpis,
    IntelligenceOverview,
    IntelligenceProjection,
    IntelligenceSectionBreakdown,
    IntelligenceSuggestion,
    IntelligenceUnitEconomics,
    IntelligenceWell,
    IntelligenceWellBreakdown,
    IntelligenceWellDetail,
)
from app.services import audit
from app.services import business_dashboard as source

READ_KEY = "cost-intelligence:read"
EXPORT_KEY = "cost-intelligence:export"
# Each analysed well needs its own day-by-day read. Past this many wells the
# largest by recorded cost are analysed and the response says so.
MAX_ANALYSED_WELLS = 40
PROJECTION_DAYS = 120
CATEGORY_LABELS = {
    "budget": "Budget and forecast",
    "trend": "Cost trend",
    "anomaly": "Unusual days",
    "schedule": "Schedule",
    "npt": "Non-productive time",
    "data-quality": "Record quality",
}
METHODS = [
    "Tangibles separation: tangibles (casing, tubing, wellhead, completion hardware) are normally booked in lump sums "
    "at the end of a scope rather than daily. Daily unusual-day detection, trend monitoring and burn-rate projections "
    "evaluate recurring operational cost (services, consumables and other expenses) so tangible entry days never "
    "falsely trigger spike alerts or place a healthy well at risk. Tangible spend is instead evaluated against its "
    "total tangible AFE allowance.",
    "Unusual days: each day's operational cost (excluding tangibles) is compared with the median of up to 7 days "
    "either side using a modified z-score (median and MAD). A day is flagged beyond 3.5, at least 25% from that "
    "median, and only when no neighbouring day comes within 15% of it, so a step to a new level or a recurring peak "
    "is not reported.",
    "Cost trend: Page's two-sided CUSUM on daily operational cost, standardised against the median of the well's "
    "opening period (slack 0.5, limit 4). It detects a sustained change of level that no single day would reveal.",
    "Forecast: recorded cost + mean of the last 7 operational days (unusual days and tangibles excluded) x remaining "
    "planned days + unbooked tangible AFE allowance. The range reflects the recent day-to-day operational spread (80% band).",
    "Budget, depth & efficiency: monitors Actual / AFE %, cost-group variance, operational burn vs depth progress, "
    "NPT & UPA shares, unit economics (cost/day, cost/metre, Cost Performance Index), and record quality.",
    "Health score: 100 less 25 per critical finding, 10 per warning and 3 per note, never below 0. The workspace "
    "score is the AFE-weighted average of its wells.",
    "All findings are advice. Nothing is changed or blocked, and every finding states the rule and the figures used.",
]


def _keys(user: User) -> set[str]:
    return {permission.key for role in user.roles for permission in role.permissions}


def _owner(user: User) -> bool:
    return any(role.is_owner for role in user.roles)


def export_allowed(user: User) -> bool:
    return _owner(user) or EXPORT_KEY in _keys(user)


def _f(value) -> float | None:
    return float(value) if value is not None else None


def _round(value: float | None, places: int = 3) -> float | None:
    return round(value, places) if value is not None else None


def _well_input(row, detail=None) -> domain.WellInput:
    days: tuple[domain.DayCost, ...] = ()
    groups: tuple[domain.GroupCost, ...] = ()
    sections: tuple[domain.SectionCost, ...] = ()
    activities: tuple[domain.ActivityCost, ...] = ()
    warning_sheets = 0
    if detail is not None:
        days = tuple(
            domain.DayCost(
                cost_date=point.cost_date,
                actual=float(point.actual),
                npt=float(point.npt),
                upa=float(point.upa),
                tangibles=float(getattr(point, "tangibles", 0) or 0),
                services=float(getattr(point, "services", 0) or 0),
                consumables=float(getattr(point, "consumables", 0) or 0),
                other_expenses=float(getattr(point, "other_expenses", 0) or 0),
            )
            for point in detail.daily
        )
        groups = tuple(
            domain.GroupCost(label=item.label, planned=_f(item.planned), actual=float(item.actual or 0))
            for item in detail.cost_groups
        )
        sections = tuple(
            domain.SectionCost(
                section_code=sec.section_code,
                section_name=sec.section_name,
                scope=sec.scope,
                planned_days=_f(sec.planned_days),
                active_days=int(sec.active_days or 0),
                amount=float(sec.amount or 0),
                share_percent=_f(sec.share),
            )
            for sec in detail.sections
        )
        activities = tuple(
            domain.ActivityCost(
                activity_code=act.activity_code,
                activity_name=act.activity_name,
                classification=act.classification,
                active_days=int(act.active_days or 0),
                amount=float(act.amount or 0),
                share_percent=_f(act.share),
            )
            for act in detail.activities
        )
        warning_sheets = sum(1 for sheet in detail.sheets if sheet.warning_count)
    return domain.WellInput(
        well_id=row.well_id, well_code=row.well_code, well_name=row.well_name, status=row.status,
        currency=row.currency, afe_amount=_f(row.effective_afe_amount), actual_amount=_f(row.actual_amount),
        planned_days=_f(row.planned_days), actual_days=_f(row.actual_days),
        npt_amount=_f(row.npt_amount), upa_amount=_f(getattr(row, "upa_amount", None)),
        npt_days=_f(getattr(row, "npt_days", None)), upa_days=_f(getattr(row, "upa_days", None)),
        planned_depth=_f(getattr(row, "planned_depth", None)), actual_depth=_f(getattr(row, "actual_depth", None)),
        depth_progress_percent=_f(getattr(row, "depth_progress_percent", None)),
        draft_sheets=row.draft_sheets or 0, sheet_count=row.sheets or 0, warning_sheets=warning_sheets,
        days=days, groups=groups, sections=sections, activities=activities,
    )


def _action(finding: domain.Finding) -> tuple[str, str]:
    """Where the user goes to act on a finding. Paths only; the page decides
    whether the viewer may open them."""
    if finding.category in ("data-quality", "anomaly", "trend", "npt"):
        return f"/daily-cost/analysis/{finding.well_id}", "Open Daily Cost Analysis"
    if finding.code in ("afe-exceeded", "forecast-overrun", "group-overrun", "burn-ahead"):
        return "/afe/register", "Open the AFE register"
    if finding.category == "schedule":
        return "/rig-well/wells", "Open the well register"
    return "/business-dashboard", "Open the Operations dashboard"


def _finding_out(finding: domain.Finding) -> IntelligenceFinding:
    path, label = _action(finding)
    identity = f"{finding.well_id}|{finding.code}|{finding.cost_date or ''}|{finding.title}"
    return IntelligenceFinding(
        id=sha1(identity.encode(), usedforsecurity=False).hexdigest()[:16],  # Stable row key, not a security control.
        code=finding.code, severity=finding.severity, category=finding.category, title=finding.title,
        detail=finding.detail, basis=finding.basis, suggestion=finding.suggestion, well_id=finding.well_id,
        well_code=finding.well_code, cost_date=finding.cost_date, amount=_round(finding.amount),
        evidence=[IntelligenceEvidence(label=label_, value=value) for label_, value in finding.evidence],
        action_path=path, action_label=label,
    )


def _forecast_out(item: domain.Forecast) -> IntelligenceForecast:
    return IntelligenceForecast(
        available=item.available, reason=item.reason, recent_daily=_round(item.recent_daily or None),
        planned_daily=_round(item.planned_daily), remaining_days=_round(item.remaining_days, 1),
        remaining_tangibles=_round(item.remaining_tangibles) or 0.0,
        estimate=_round(item.estimate), low=_round(item.low), high=_round(item.high), variance=_round(item.variance),
        variance_percent=_round(item.variance_percent, 1), exhaustion_date=item.exhaustion_date,
        days_to_exhaustion=_round(item.days_to_exhaustion, 1), past_plan=item.past_plan,
    )


def _well_out(row, analysis: domain.WellAnalysis, analysed: bool = True) -> IntelligenceWell:
    well = analysis.well
    counts = {key: sum(1 for item in analysis.findings if item.severity == key) for key in ("critical", "warning", "info")}
    tangible_total = sum(day.tangibles for day in well.days) if well.days else float(getattr(row, "tangibles_amount", 0) or 0)
    operational_total = (
        max(0.0, well.actual_amount - tangible_total)
        if well.actual_amount is not None else None
    )
    return IntelligenceWell(
        well_id=well.well_id, well_code=well.well_code, well_name=well.well_name, rig_code=row.rig_code,
        status=well.status, currency=well.currency, afe_amount=_round(well.afe_amount),
        actual_amount=_round(well.actual_amount),
        utilisation_percent=_round(well.actual_amount / well.afe_amount * 100, 1)
        if well.afe_amount and well.actual_amount is not None else None,
        operational_amount=_round(operational_total),
        tangible_amount=_round(tangible_total) if well.actual_amount is not None else None,
        planned_days=_round(well.planned_days, 1), actual_days=_round(well.actual_days, 1),
        npt_amount=_round(well.npt_amount),
        npt_share_percent=_round(well.npt_amount / well.actual_amount * 100, 1)
        if well.npt_amount is not None and well.actual_amount else None,
        upa_amount=_round(well.upa_amount),
        upa_share_percent=_round(well.upa_amount / well.actual_amount * 100, 1)
        if well.upa_amount is not None and well.actual_amount else None,
        recorded_days=len(well.days) or (row.recorded_days or 0),
        first_cost_date=row.first_cost_date, last_cost_date=row.last_cost_date,
        score=analysis.score, band=analysis.band, summary=analysis.summary,
        forecast=_forecast_out(analysis.forecast), analysed=analysed, **counts,
    )


def _as_of(rows, date_to: date | None) -> date:
    """The day the record is judged against: the end of the chosen range, or
    today. A range that ends in the past must not call every well stale."""
    today = datetime.now(timezone.utc).date()
    return min(date_to, today) if date_to else today


def _analyse(db: Session, user: User, *, date_from, date_to, rig_id, well_id, well_status, currency, include_draft):
    payload = source.dashboard(
        db, user.organization_id, user, date_from=date_from, date_to=date_to, rig_id=rig_id, well_id=well_id,
        well_status=well_status, currency=currency, include_draft=include_draft,
    )
    as_of = _as_of(payload.wells, date_to)
    rows = sorted(payload.wells, key=lambda row: -(float(row.actual_amount or 0)))
    with_cost = [row for row in rows if (row.sheets or 0) > 0]
    chosen = {row.well_id for row in with_cost[:MAX_ANALYSED_WELLS]}
    results: list[tuple[object, domain.WellAnalysis, bool]] = []
    for row in rows:
        detail = None
        if row.well_id in chosen and payload.capabilities.actuals:
            detail = source.well_detail(
                db, user.organization_id, user, row.well_id, date_from=date_from, date_to=date_to,
                currency=currency, include_draft=include_draft,
            )
        analysed = detail is not None or (row.sheets or 0) == 0
        results.append((row, domain.analyse_well(_well_input(row, detail), as_of=as_of), analysed))
    return payload, as_of, results, len(with_cost) - len(chosen)


def overview(
    db: Session, user: User, *, date_from: date | None = None, date_to: date | None = None, rig_id: str = "",
    well_id: str = "", well_status: str = "", currency: str = "", include_draft: bool = True,
) -> IntelligenceOverview:
    payload, as_of, results, skipped = _analyse(
        db, user, date_from=date_from, date_to=date_to, rig_id=rig_id, well_id=well_id, well_status=well_status,
        currency=currency, include_draft=include_draft,
    )
    wells = [_well_out(row, analysis, analysed) for row, analysis, analysed in results]
    wells.sort(key=lambda item: (item.score, -(item.actual_amount or 0)))
    raw = [finding for _, analysis, _ in results for finding in analysis.findings]
    raw.sort(key=lambda item: (domain.SEVERITY_ORDER[item.severity], -(abs(item.amount) if item.amount else 0.0)))
    findings = [_finding_out(item) for item in raw]

    budget, actuals = payload.capabilities.budget, payload.capabilities.actuals
    afe_total = sum(item.afe_amount or 0 for item in wells) if budget else None
    actual_total = sum(item.actual_amount or 0 for item in wells) if actuals else None
    # A well without a forecast contributes what it has spent (if it has
    # started) or its AFE (if it has not): the portfolio figure stays complete.
    forecast_total = None
    if budget and actuals:
        forecast_total = 0.0
        for item in wells:
            if item.forecast.available and item.forecast.estimate is not None:
                forecast_total += max(item.forecast.estimate, item.actual_amount or 0)
            elif item.actual_amount:
                forecast_total += max(item.actual_amount, item.afe_amount or 0) if item.status not in ("completed", "closed") else item.actual_amount
            else:
                forecast_total += item.afe_amount or 0
    variance = forecast_total - afe_total if forecast_total is not None and afe_total else None
    at_risk = sum(
        max((item.forecast.estimate if item.forecast.available and item.forecast.estimate is not None else item.actual_amount or 0)
            - (item.afe_amount or 0), 0)
        for item in wells if item.afe_amount
    ) if budget and actuals else None
    score = domain.portfolio_score([analysis for _, analysis, _ in results])
    kpis = IntelligenceKpis(
        wells=len(wells), analysed_wells=sum(1 for item in wells if item.analysed and item.recorded_days),
        afe_amount=_round(afe_total), actual_amount=_round(actual_total),
        utilisation_percent=_round(actual_total / afe_total * 100, 1)
        if afe_total and actual_total is not None else None,
        forecast_amount=_round(forecast_total),
        forecast_variance=_round(variance),
        forecast_variance_percent=_round(variance / afe_total * 100, 1) if variance is not None and afe_total else None,
        amount_at_risk=_round(at_risk),
        critical=sum(1 for item in findings if item.severity == "critical"),
        warning=sum(1 for item in findings if item.severity == "warning"),
        info=sum(1 for item in findings if item.severity == "info"),
        wells_at_risk=sum(1 for item in wells if item.band == "at-risk"),
        score=score, band="good" if score >= 80 else "watch" if score >= 55 else "at-risk",
    )

    by_category = []
    for key, label in CATEGORY_LABELS.items():
        group = [item for item in findings if item.category == key]
        by_category.append(IntelligenceCount(
            key=key, label=label, critical=sum(1 for item in group if item.severity == "critical"),
            warning=sum(1 for item in group if item.severity == "warning"),
            info=sum(1 for item in group if item.severity == "info"),
        ))

    suggestions = [
        IntelligenceSuggestion(
            rank=index + 1, severity=item.severity, well_id=item.well_id, well_code=item.well_code, title=item.title,
            suggestion=item.suggestion, amount=item.amount, action_path=item.action_path,
            action_label=item.action_label, finding_id=item.id,
        )
        for index, item in enumerate([item for item in findings if item.severity != "info"][:12])
    ]

    cur = payload.currency
    headline: list[str] = []
    if not wells:
        headline.append("No well matches these filters.")
    else:
        if afe_total and actual_total is not None:
            headline.append(
                f"{len(wells)} well(s) carry an AFE of {domain.money(afe_total, cur)}; "
                f"{domain.money(actual_total, cur)} ({actual_total / afe_total * 100:.0f}%) has been recorded."
            )
        if forecast_total is not None and afe_total and variance is not None:
            headline.append(
                f"At current spending rates the wells are forecast to close near {domain.money(forecast_total, cur)}, "
                f"{domain.money(abs(variance), cur)} {'over' if variance > 0 else 'under'} the combined AFE."
            )
        if kpis.critical or kpis.warning:
            worst = [item for item in wells if item.critical or item.warning][:3]
            headline.append(
                f"{kpis.critical} critical and {kpis.warning} warning finding(s) need attention, mainly on "
                + ", ".join(item.well_code for item in worst) + "."
            )
        else:
            headline.append("No cost, schedule or forecast concern was found in the selected record.")
        if at_risk:
            headline.append(f"Cost above AFE, recorded or forecast, totals {domain.money(at_risk, cur)}.")

    notes: list[str] = []
    if not budget:
        notes.append("AFE amounts are not part of your access, so budget and forecast checks were skipped.")
    if not actuals:
        notes.append("Daily cost is not part of your access, so trend, unusual-day and record checks were skipped.")
    if skipped > 0:
        notes.append(
            f"The {MAX_ANALYSED_WELLS} wells with the most recorded cost were analysed day by day; {skipped} smaller "
            "well(s) show budget position only. Filter by rig or well to analyse them."
        )
    if payload.conversion_pending_afes:
        notes.append(f"{payload.conversion_pending_afes} AFE(s) await a currency conversion rate and are not in these totals.")
    if date_from or date_to:
        notes.append("The date range limits the cost record that is analysed; AFE amounts and planned days are not date-bound.")

    return IntelligenceOverview(
        generated_at=datetime.now(timezone.utc), as_of=as_of, date_from=date_from, date_to=date_to, currency=cur,
        capabilities=IntelligenceCapabilities(
            budget=budget, actuals=actuals, plan=payload.capabilities.plan, export=export_allowed(user)),
        kpis=kpis, headline=headline, wells=wells, findings=findings, suggestions=suggestions,
        by_category=by_category, notes=notes, methods=METHODS,
    )


def _build_breakdown(well: domain.WellInput, analysis: domain.WellAnalysis) -> IntelligenceWellBreakdown:
    """Assemble cost-group variance, section, activity and unit-economics breakdown."""
    total_actual = well.actual_amount or sum(day.actual for day in well.days) or 0.0
    cost_groups: list[IntelligenceGroupBreakdown] = []
    for group in well.groups:
        planned = _round(group.planned)
        actual = round(group.actual, 3)
        balance = _round(group.planned - group.actual) if group.planned is not None else None
        util = _round(group.actual / group.planned * 100, 1) if group.planned and group.planned > 0 else None
        share = _round(group.actual / total_actual * 100, 1) if total_actual > 0 else None
        cost_groups.append(IntelligenceGroupBreakdown(
            label=group.label, planned=planned, actual=actual, balance=balance,
            utilisation_percent=util, share_percent=share,
        ))
    sections = [
        IntelligenceSectionBreakdown(
            section_code=sec.section_code, section_name=sec.section_name, scope=sec.scope,
            planned_days=_round(sec.planned_days, 3), active_days=sec.active_days,
            amount=round(sec.amount, 3), share_percent=_round(sec.share_percent, 1),
        )
        for sec in well.sections
        if sec.amount > 0 or sec.active_days > 0 or (sec.planned_days or 0) > 0
    ]
    activities = [
        IntelligenceActivityBreakdown(
            activity_code=act.activity_code, activity_name=act.activity_name,
            classification=act.classification, active_days=act.active_days,
            amount=round(act.amount, 3), share_percent=_round(act.share_percent, 1),
        )
        for act in sorted(well.activities, key=lambda item: -item.amount)[:15]
    ]
    tangible_afe, tangible_actual = domain._tangible_budget_and_actual(well)
    tangible_days = [day.cost_date for day in well.days if day.tangibles > 0]
    operational_actual = max(0.0, total_actual - tangible_actual)
    op_days = [day for day in well.days if day.operational > 0]
    op_daily_avg = (sum(day.operational for day in op_days) / len(op_days)) if op_days else None
    planned_op_daily = analysis.forecast.planned_daily
    cost_per_meter = (
        total_actual / well.actual_depth
        if well.actual_depth and well.actual_depth > 0 and total_actual > 0 else None
    )
    # Burn efficiency index (CPI): planned operational burn for elapsed days vs
    # actual operational spend (>1.00 = under budget, <1.00 = over-burning).
    cpi: float | None = None
    if planned_op_daily and well.actual_days and well.actual_days > 0 and operational_actual > 0:
        cpi = (planned_op_daily * well.actual_days) / operational_actual
    top_driver = ""
    if cost_groups:
        lead_group = max(cost_groups, key=lambda g: g.actual)
        if lead_group.actual > 0:
            pct = f" ({lead_group.share_percent:.1f}% of spend)" if lead_group.share_percent is not None else ""
            top_driver = f"{lead_group.label}: {domain.money(lead_group.actual, well.currency)}{pct}"
    if activities and activities[0].amount > 0:
        act = activities[0]
        act_pct = f" ({act.share_percent:.1f}%)" if act.share_percent is not None else ""
        top_driver += f" · Top activity: {act.activity_name or act.activity_code} {domain.money(act.amount, well.currency)}{act_pct}"
    unit_economics = IntelligenceUnitEconomics(
        operational_actual=round(operational_actual, 3),
        tangible_actual=round(tangible_actual, 3),
        tangible_afe=_round(tangible_afe),
        tangible_utilisation_percent=_round(tangible_actual / tangible_afe * 100, 1) if tangible_afe else None,
        tangible_booking_dates=tangible_days,
        operational_daily_avg=_round(op_daily_avg),
        planned_operational_daily=_round(planned_op_daily),
        cost_per_meter=_round(cost_per_meter),
        actual_depth=_round(well.actual_depth),
        planned_depth=_round(well.planned_depth),
        depth_progress_percent=_round(well.depth_progress_percent, 1),
        burn_efficiency_index=_round(cpi, 3),
        upa_amount=round(well.upa_amount or 0.0, 3),
        upa_share_percent=_round((well.upa_amount or 0.0) / total_actual * 100, 1) if total_actual > 0 and well.upa_amount else None,
        npt_days=_round(well.npt_days, 3),
        upa_days=_round(well.upa_days, 3),
        top_cost_driver=top_driver,
    )
    return IntelligenceWellBreakdown(
        cost_groups=cost_groups, sections=sections, activities=activities, unit_economics=unit_economics,
    )


def well_detail(
    db: Session, user: User, well_id: str, *, date_from: date | None = None, date_to: date | None = None,
    currency: str = "", include_draft: bool = True,
) -> IntelligenceWellDetail:
    detail = source.well_detail(
        db, user.organization_id, user, well_id, date_from=date_from, date_to=date_to, currency=currency,
        include_draft=include_draft,
    )
    as_of = _as_of([detail.well], date_to)
    analysis = domain.analyse_well(_well_input(detail.well, detail), as_of=as_of)
    well, drift, outlook = analysis.well, analysis.drift, analysis.forecast
    spikes = set(analysis.spikes)
    planned_daily = well.afe_amount / well.planned_days if well.afe_amount and well.planned_days else None
    days: list[IntelligenceDay] = []
    running = 0.0
    for index, day in enumerate(well.days):
        running += day.actual
        days.append(IntelligenceDay(
            cost_date=day.cost_date,
            actual=round(day.actual, 3),
            operational=round(day.operational, 3),
            tangibles=round(day.tangibles, 3),
            services=round(day.services, 3),
            consumables=round(day.consumables, 3),
            other_expenses=round(day.other_expenses, 3),
            tangible_booking_day=day.tangibles > 0,
            cumulative=round(running, 3),
            npt=round(day.npt, 3),
            baseline=round(drift.baseline, 3) if drift.available else None,
            planned_cumulative=round(min(planned_daily * (index + 1), well.afe_amount or 0), 3) if planned_daily else None,
            cusum_up=drift.upper[index] if drift.available else None,
            cusum_down=drift.lower[index] if drift.available else None,
            spike=index in spikes,
        ))
    projection: list[IntelligenceProjection] = []
    if outlook.available and outlook.remaining_days and well.days and well.status not in ("completed", "closed"):
        steps = min(int(round(outlook.remaining_days)), PROJECTION_DAYS)
        spread = ((outlook.high or 0) - (outlook.estimate or 0)) / (outlook.remaining_days ** 0.5) if outlook.remaining_days else 0
        spent = well.actual_amount if well.actual_amount is not None else running
        for step in range(0, steps + 1):
            tangible_bump = outlook.remaining_tangibles if (step == steps and steps > 0) else 0.0
            centre = spent + outlook.recent_daily * step + tangible_bump
            band = spread * (step ** 0.5)
            projection.append(IntelligenceProjection(
                cost_date=well.days[-1].cost_date + timedelta(days=step), estimate=round(centre, 3),
                low=round(max(spent, centre - band), 3), high=round(centre + band, 3),
            ))
    breakdown = _build_breakdown(well, analysis)
    notes = list(detail.notes)
    if breakdown.unit_economics.tangible_booking_dates:
        booking_list = ", ".join(item.isoformat() for item in breakdown.unit_economics.tangible_booking_dates[:5])
        if len(breakdown.unit_economics.tangible_booking_dates) > 5:
            booking_list += f" (+{len(breakdown.unit_economics.tangible_booking_dates) - 5} more)"
        notes.append(
            f"Tangibles ({domain.money(breakdown.unit_economics.tangible_actual, well.currency)}) booked on {booking_list} "
            "were separated from daily operational cost so end-of-scope tangible bookings do not trigger false spike or drift alerts."
        )
    if not drift.available and well.days:
        notes.append(f"The trend check needs at least {domain.CUSUM_MIN_DAYS} recorded days; this well has {len(well.days)}.")
    if not outlook.available and outlook.reason:
        notes.append(outlook.reason)
    return IntelligenceWellDetail(
        well=_well_out(detail.well, analysis), findings=[_finding_out(item) for item in analysis.findings],
        days=days, projection=projection, missing_dates=analysis.missing_dates, cusum_limit=domain.CUSUM_LIMIT,
        drift_baseline=round(drift.baseline, 3) if drift.available else None,
        drift_start=well.days[min(drift.start_index, len(well.days) - 1)].cost_date
        if drift.start_index is not None and well.days else None,
        drift_direction=drift.direction, breakdown=breakdown, notes=notes,
    )


def record_export(db: Session, user: User, *, fmt: str, record_count: int, sections: str, request: Request | None = None) -> None:
    if not export_allowed(user):
        raise HTTPException(status_code=403, detail=f"Permission denied. This action needs {EXPORT_KEY}.")
    audit.record(
        db, organization_id=user.organization_id, actor=user, action="export", entity_type="cost_intelligence",
        entity_label="Cost Intelligence",
        summary=f"Exported the Cost Intelligence report as {fmt.upper()} ({record_count} rows"
                + (f"; sections: {sections[:200]}" if sections else "") + ")",
        request=request,
    )
    db.commit()
