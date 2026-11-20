"""Well path and well diagram, built from what the workspace actually recorded.

This service turns records into geometry; it never invents a survey, a casing
seat or an inclination. Every output names its provenance so the screen can say
"recorded", "computed" or "unknown" instead of drawing a confident line over
missing data.

Sources, in the order they are trusted for each fact:

* **Surveys** — every ``ops_surveys`` station for the well and scope, from every
  daily report and the manual entry form. ``MD/Inc/Azi/TVD/NS/EW`` are integrated
  with minimum curvature (``domain/operations/trajectory.py``); a printed TVD is
  compared with the integration and a material difference is reported, never
  silently overwritten.
* **Depth** — the latest *current* daily report (submitted or approved preferred,
  then a draft) gives closing MD/TVD/bit depth. The well diagram's "current
  depth" marker is that number, so the picture and the KPI card cannot disagree.
* **Casing seats** — the reports' ``last_casing_size_in`` / ``last_casing_depth_m``
  header pair, plus the configured ``well_sections`` (hole size and from/to
  depth). Where neither exists for a section, the section is drawn as
  *unrecorded* rather than as a guessed shoe.
* **Plan** — the active ``ops_plan_versions`` programme, for the planned depth
  against time line on the same chart.

Completion scope uses the same pipeline: a completion has a tubing/liner
configuration rather than a hole trajectory, so its diagram is drawn from the
configured completion sections and the last casing, and its "depth" is the
completion interval end.
"""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any, Iterable, Sequence

from fastapi import HTTPException
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.domain.operations.trajectory import (
    Station,
    casing_from_section_name,
    casing_label,
    integrate,
    interval_table,
    interpolate_tvd,
    parse_size_in,
    survey_azimuth_from_departure,
    trajectory_summary,
)
from app.models.operations import (
    OpsDailyReport,
    OpsPlanItem,
    OpsSurvey,
)
from app.models.rig_well import Well, WellSection
from app.services.operations import plan_surveys, plans

VERIFIED = ("submitted", "approved")
#: A printed TVD differing from the integrated TVD by more than this is flagged.
TVD_MATERIAL_MISMATCH_M = 1.0


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _reports(db: Session, organization_id: str, well_id: str, scope: str) -> list[OpsDailyReport]:
    return list(
        db.scalars(
            select(OpsDailyReport)
            .where(
                OpsDailyReport.organization_id == organization_id,
                OpsDailyReport.well_id == well_id,
                OpsDailyReport.scope == scope,
                OpsDailyReport.is_deleted.is_(False),
            )
            .order_by(OpsDailyReport.report_date.asc(), OpsDailyReport.created_at.asc())
        ).all()
    )


def _survey_rows(db: Session, organization_id: str, well_id: str, scope: str) -> list[OpsSurvey]:
    """Every current survey row for the well and scope, in measured-depth order."""
    return list(
        db.scalars(
            select(OpsSurvey)
            .where(
                OpsSurvey.organization_id == organization_id,
                OpsSurvey.well_id == well_id,
                OpsSurvey.scope == scope,
                OpsSurvey.is_deleted.is_(False),
                OpsSurvey.is_current.is_(True),
                or_(OpsSurvey.report_id.is_(None), exists().where(
                    OpsDailyReport.id == OpsSurvey.report_id,
                    OpsDailyReport.organization_id == organization_id,
                    OpsDailyReport.well_id == well_id,
                    OpsDailyReport.scope == scope,
                    OpsDailyReport.is_deleted.is_(False),
                )),
            )
            .order_by(OpsSurvey.md_m.asc(), OpsSurvey.created_at.asc(), OpsSurvey.station_no.asc(), OpsSurvey.id.asc())
        ).all()
    )


def _survey_stations(
    db: Session,
    organization_id: str,
    well_id: str,
    scope: str,
    *,
    rows: Sequence[OpsSurvey] | None = None,
) -> tuple[list[Station], list[str]]:
    """Every usable station, de-duplicated by MD, plus the data-quality notes.

    A station needs a measured depth and an inclination. A missing azimuth is only
    filled with zero where the station is vertical (inclination under 1°), because
    azimuth has no meaning there; on a deviated station the horizontal direction
    is genuinely unknown, and inserting north would draw a turn that was never
    surveyed. Such a station is excluded from the path and named in the notes.
    """
    if rows is None:
        rows = _survey_rows(db, organization_id, well_id, scope)
    notes: list[str] = []
    by_md: dict[float, Station] = {}
    for row in rows:
        md = _num(row.md_m)
        inc = _num(row.inc_deg)
        if md is None or inc is None:
            notes.append(
                f"Survey station {row.station_no or '?'} is missing "
                f"{'measured depth' if md is None else 'inclination'} and cannot be plotted."
            )
            continue
        if not 0 <= inc <= 180:
            notes.append(f"Survey at {md:,.2f} m has an out-of-range inclination and cannot be plotted.")
            continue
        if md < 0:
            notes.append(f"Survey station {row.station_no or '?'} has a negative measured depth and cannot be plotted.")
            continue
        azi = _num(row.azi_deg)
        if azi is None:
            if abs(inc) >= 1.0:
                notes.append(
                    f"Survey at {md:,.2f} m has {inc:,.2f}° inclination but no azimuth. "
                    "Its horizontal direction is unknown, so the station is left out of the path "
                    "rather than assumed to point north."
                )
                continue
            azi = 0.0
        if not 0 <= azi <= 360:
            notes.append(f"Survey at {md:,.2f} m has an out-of-range azimuth and cannot be plotted.")
            continue
        station = Station(
            md_m=round(md, 3),
            inc_deg=inc,
            azi_deg=azi,
            tvd_m=_num(row.tvd_m),
            ns_m=_num(row.ns_m),
            ew_m=_num(row.ew_m),
            tool=row.tool or "",
            source=row.source or "",
        )
        existing = by_md.get(station.md_m)
        # A later row at the same MD belongs to a later report and supersedes the
        # earlier one; two stations cannot occupy one depth.
        if existing is not None:
            notes.append(
                f"Two survey stations share MD {station.md_m:,.2f} m; the latest row was kept and "
                "the earlier one is still on its report."
            )
        by_md[station.md_m] = station
    return [by_md[md] for md in sorted(by_md)], notes


def _station_lineage(
    rows: Sequence[OpsSurvey],
    curve: Sequence[Any],
    reports: Sequence[OpsDailyReport],
) -> list[dict[str, Any]]:
    """Per-station provenance for the source drawer, one entry per drawn station.

    The drawer has to answer "where did this dot come from": the stored row, the
    report and page it was read from, the printed values that were *not*
    overwritten by the integration, and whether the row supersedes another. Values
    are the recorded ones, not the integrated ones, so a reader can compare.
    """
    accepted = {round(result.md_m, 3): result for result in curve}
    report_by_id = {report.id: report for report in reports}
    chosen: dict[float, OpsSurvey] = {}
    rows_at_md: dict[float, int] = {}
    for row in rows:
        md = _num(row.md_m)
        if md is None:
            continue
        key = round(md, 3)
        inc, azi = _num(row.inc_deg), _num(row.azi_deg)
        if key not in accepted or md < 0 or inc is None or not 0 <= inc <= 180:
            continue
        rows_at_md[key] = rows_at_md.get(key, 0) + 1
        if (azi is None and abs(inc) >= 1) or (azi is not None and not 0 <= azi <= 360):
            continue
        # Rows arrive oldest first, so the last row at an MD is the one used.
        chosen[key] = row
    out: list[dict[str, Any]] = []
    for md in sorted(chosen):
        row = chosen[md]
        result = accepted[md]
        report = report_by_id.get(row.report_id) if row.report_id else None
        out.append(
            {
                "survey_id": row.id,
                "station_no": row.station_no,
                "md_m": round(md, 3),
                "inc_deg": _num(row.inc_deg),
                "azi_deg": _num(row.azi_deg),
                "recorded_tvd_m": _num(row.tvd_m),
                "recorded_ns_m": _num(row.ns_m),
                "recorded_ew_m": _num(row.ew_m),
                "recorded_vsec_m": _num(row.vsec_m),
                "recorded_dls_deg_per_30m": _num(row.dls_deg_per_30m),
                "tool": row.tool or "",
                "source": row.source or "",
                "source_page": row.source_page,
                "confidence": _num(row.confidence),
                "survey_at": row.survey_at.isoformat() if row.survey_at else None,
                "report_id": row.report_id,
                "report_date": str(report.report_date) if report else None,
                "report_no": (report.report_no_text or "") if report else "",
                "report_status": report.status if report else "",
                "computed_tvd_m": round(result.tvd_m, 3),
                "tvd_difference_m": (
                    round(_num(row.tvd_m) - result.tvd_m, 3) if _num(row.tvd_m) is not None else None
                ),
                "rows_at_md": rows_at_md.get(md, 1),
            }
        )
    return out


def _latest_depth(reports: Sequence[OpsDailyReport]) -> dict[str, Any]:
    """Closing depth of the latest report, preferring a verified one.

    This is the *report* position: what the daily sheet closed at. It is
    deliberately not merged with the deepest survey station, because the two
    answer different questions and one is not evidence for the other.
    """
    empty = {
        "md_m": None,
        "tvd_m": None,
        "bit_depth_m": None,
        "report_date": None,
        "report_id": None,
        "status": "",
        "basis": "no report",
        "verified": False,
        "report_no": "",
        "current_status": "",
        "depth_start_m": None,
        "progress_m": None,
        "tvd_source": "",
        "last_casing_size_in": None,
        "last_casing_depth_m": None,
    }
    if not reports:
        return empty
    verified = [r for r in reports if r.status in VERIFIED]
    pool = verified or list(reports)
    latest = max(pool, key=lambda r: (r.report_date, r.created_at or datetime.min.replace(tzinfo=UTC)))
    return {
        "md_m": _num(latest.depth_end_m),
        "tvd_m": _num(latest.tvd_m),
        "bit_depth_m": _num(latest.bit_depth_m),
        "report_date": str(latest.report_date),
        "report_id": latest.id,
        "status": latest.status,
        "basis": "latest verified report" if verified else "latest draft report",
        "verified": bool(verified),
        "report_no": latest.report_no_text or "",
        "current_status": (latest.current_status or "").strip(),
        "depth_start_m": _num(latest.depth_start_m),
        "progress_m": _num(latest.progress_m),
        "tvd_source": latest.tvd_source or "",
        "last_casing_size_in": _num(latest.last_casing_size_in),
        "last_casing_depth_m": _num(latest.last_casing_depth_m),
    }


def _casing_seats(
    db: Session,
    organization_id: str,
    well: Well,
    scope: str,
    reports: Sequence[OpsDailyReport],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Casing seats from the reports' last-casing header and the configuration.

    The header pair (size, depth) is what the driller prints each day, so it is
    the primary evidence. The configured ``well_sections`` supply the hole size
    and the from/to depth when a report's header omitted them. A seat is only a
    *recorded* seat when a depth is present; size alone cannot place a shoe.
    """
    notes: list[str] = []
    seats: dict[float, dict[str, Any]] = {}
    for report in reports:
        size = _num(report.last_casing_size_in)
        depth = _num(report.last_casing_depth_m)
        if size is None or depth is None or depth <= 0:
            continue
        key = round(size, 3)
        previous = seats.get(key)
        # The deepest printed shoe for a size is the one that was run; a shallower
        # repeat is the same string quoted on an earlier day.
        if previous is None or depth > previous["depth_m"]:
            seats[key] = {
                "size_in": size,
                "size_label": casing_label(size),
                "depth_m": round(depth, 3),
                "source": "report header",
                "report_date": str(report.report_date),
            }
    for section in db.scalars(
        select(WellSection).where(
            WellSection.organization_id == organization_id,
            WellSection.well_id == well.id,
            WellSection.scope == scope,
        )
    ).all():
        hole = section.hole_section
        mapped = casing_from_section_name(getattr(hole, "section_name", "")) or casing_from_section_name(
            getattr(hole, "section_code", "")
        )
        to_depth = _num(section.to_depth)
        if to_depth is None or to_depth <= 0:
            continue
        if mapped:
            size, _name = mapped
            key = round(size, 3)
            if key not in seats:
                seats[key] = {
                    "size_in": size,
                    "size_label": casing_label(size),
                    "depth_m": round(to_depth, 3),
                    "source": "well configuration",
                    "report_date": None,
                }
            continue
        notes.append(
            f"Configured section '{getattr(hole, 'section_name', '') or section.id}' has no recognised casing size; "
            "its shoe is drawn from the configuration interval only."
        )
    ordered = sorted(seats.values(), key=lambda s: s["depth_m"])
    return ordered, notes


def _plan_curve(db: Session, organization_id: str, well_id: str, scope: str) -> dict[str, Any]:
    """Planned depth against planned days from the active programme."""
    version = plans.active_plan(db, organization_id, well_id, scope)
    if version is None:
        return {"label": "", "version_no": None, "points": [], "planned_days": None, "planned_start_at": None}
    items = db.scalars(
        select(OpsPlanItem)
        .where(OpsPlanItem.organization_id == organization_id, OpsPlanItem.plan_version_id == version.id)
        .order_by(OpsPlanItem.sequence_no)
    ).all()
    points = [
        {
            "cum_days": _num(item.cum_planned_days),
            "md_m": _num(item.target_depth_m),
            "sequence_no": item.sequence_no,
            "description": item.description or "",
        }
        for item in items
        if item.cum_planned_days is not None and item.target_depth_m is not None
    ]
    return {
        "label": version.label or f"v{version.version_no}",
        "version_no": version.version_no,
        "points": points,
        "planned_days": _num(version.planned_days),
        "planned_start_at": version.planned_start_at.isoformat() if version.planned_start_at else None,
        "items": len(items),
    }


def _configured_hole_size(section: WellSection) -> float | None:
    """The hole size (inches) a configured interval was drilled with, if known.

    ``well_sections`` names a Master Data hole section rather than a size, so the
    size is read from the section name when the workspace names it the way the
    reports do (``12-1/4"``) and left unknown otherwise. A guessed size would put
    a wrong pipe on the drawing.
    """
    hole = getattr(section, "hole_section", None)
    for value in (
        getattr(hole, "section_code", None),
        getattr(hole, "section_name", None),
    ):
        size = parse_size_in(value)
        if size is not None:
            return size
    return None


def _section_intervals(
    seats: Sequence[dict[str, Any]],
    configuration: Iterable[WellSection],
) -> list[dict[str, Any]]:
    """Turn casing seats into drawn hole sections with an explicit upper shoe.

    A shoe is the bottom of a drilled interval; the next seat above it is the
    top, so the shallowest seat starts at the surface datum. Where the configured
    intervals disagree with the printed seats, the printed seat wins and the
    configuration supplies only its hole size.
    """
    intervals: list[dict[str, Any]] = []
    configured = list(configuration)
    top = 0.0
    for index, seat in enumerate(seats):
        bottom = float(seat["depth_m"])
        if bottom <= top:
            continue
        matched = [s for s in configured if (_num(s.to_depth) is not None and abs(_num(s.to_depth) - bottom) < 1.0)]
        hole_size = next((size for size in (_configured_hole_size(s) for s in matched) if size is not None), None)
        intervals.append(
            {
                "from_depth_m": round(top, 3),
                "to_depth_m": round(bottom, 3),
                "length_m": round(bottom - top, 3),
                "casing_size_in": seat["size_in"],
                "casing_label": seat["size_label"],
                "source": seat["source"],
                "hole_size_in": hole_size,
                "is_deepest": index == len(seats) - 1,
            }
        )
        top = bottom
    return intervals


def _curve_payload(curve):
    return [
        {
            "md_m": round(s.md_m, 3),
            "inc_deg": round(s.inc_deg, 3),
            "azi_deg": round(s.azi_deg, 3),
            "tvd_m": round(s.tvd_m, 3),
            "ns_m": round(s.ns_m, 3),
            "ew_m": round(s.ew_m, 3),
            "vsec_m": round(s.vsec_m, 3),
            "dls_deg_per_30m": round(s.dls_deg_per_30m, 3) if s.dls_deg_per_30m is not None else None,
            "build_deg_per_30m": round(s.build_deg_per_30m, 3) if s.build_deg_per_30m is not None else None,
            "turn_deg_per_30m": round(s.turn_deg_per_30m, 3) if s.turn_deg_per_30m is not None else None,
            "is_anchor": s.is_anchor,
            "interval_valid": s.interval_valid,
            "interval_issue": s.interval_issue,
        }
        for s in curve
    ]


def _anchor_reference(first):
    if first is None:
        return "no survey stations", False
    if all(value is not None for value in (first.tvd_m, first.ns_m, first.ew_m)):
        return "recorded TVD and north/east tie-on", True
    if first.md_m == 0 and all(value in (0, None) for value in (first.tvd_m, first.ns_m, first.ew_m)):
        return "MD zero at the surface origin", True
    return "incomplete tie-on; geometry uses assumed values", False


def _planned_trajectory(plan, rows, stations, az):
    basis, _ = _anchor_reference(stations[0] if stations else None)
    return {
        "plan_version_id": plan.id, "label": plan.label, "version_no": plan.version_no, "status": plan.status,
        "curve": _curve_payload(integrate(stations, vertical_section_azimuth=az)),
        "shared_reference": plan.survey_shared_reference,
        "anchor_basis": basis,
        "sources": sorted({" · ".join(filter(None, (row.source_file or row.source, row.source_sheet))) for row in rows}),
    }


def _comparison_basis(plan, planned_stations, actual_stations):
    if not planned_stations or not actual_stations:
        return False, "Both surveys are needed to compare positions."
    if not plan.survey_shared_reference:
        return False, "The plan has no confirmed shared datum, depth reference and north/east origin. Align the reference before comparing offsets."
    if not all(_anchor_reference(stations[0])[1] for stations in (planned_stations, actual_stations)):
        return False, "At least one survey begins below surface without a complete TVD and north/east tie-on. No position differences are calculated."
    return True, "Shared depth and coordinate references confirmed on the plan. Differences are calculated only at overlapping, usable MDs."


def _projection_azimuth(stations):
    seed = integrate(stations)
    for index, station in enumerate(seed[1:], 1):
        if not station.interval_valid:
            seed = seed[:index]
            break
    return survey_azimuth_from_departure(seed[-1].ns_m, seed[-1].ew_m) if seed else 0.0


def plan_comparison(db, plan, *, include_actual, vertical_section_azimuth=None):
    planned_rows = plan_surveys.rows_for_plan(db, plan)
    planned_stations = [plan_surveys.geometry_station(row) for row in planned_rows]
    rows = _survey_rows(db, plan.organization_id, plan.well_id, plan.scope) if include_actual else []
    stations, _ = _survey_stations(db, plan.organization_id, plan.well_id, plan.scope, rows=rows)
    az = vertical_section_azimuth if vertical_section_azimuth is not None else _projection_azimuth(stations or planned_stations)
    actual_curve = integrate(stations, vertical_section_azimuth=az)
    reports = _reports(db, plan.organization_id, plan.well_id, plan.scope) if rows else []
    comparable, basis = _comparison_basis(plan, planned_stations, stations)
    return {
        "vertical_section_azimuth_deg": round(az, 3),
        "planned_trajectory": _planned_trajectory(plan, planned_rows, planned_stations, az),
        "curve": _curve_payload(actual_curve),
        "survey_stations": _station_lineage(rows, actual_curve, reports),
        "comparable": comparable, "comparison_basis": basis, "actual_visible": include_actual,
    }


def well_path(
    db: Session,
    organization_id: str,
    well_id: str,
    scope: str = "drilling",
    *,
    vertical_section_azimuth: float | None = None,
    include_planned_trajectory: bool = False,
) -> dict[str, Any]:
    """Full well path payload: curve, KPI summary, sections, provenance, warnings."""
    well = db.scalar(
        select(Well).where(
            Well.id == well_id,
            Well.organization_id == organization_id,
            Well.is_deleted.is_(False),
        )
    )
    if well is None:
        raise HTTPException(404, "Well not found in this workspace.")

    rows = _survey_rows(db, organization_id, well_id, scope)
    stations, notes = _survey_stations(db, organization_id, well_id, scope, rows=rows)
    reports = _reports(db, organization_id, well_id, scope)
    depth = _latest_depth(reports)
    plan_version = plans.active_plan(db, organization_id, well_id, scope) if include_planned_trajectory else None
    planned_rows = plan_surveys.rows_for_plan(db, plan_version) if plan_version else []
    planned_stations = [plan_surveys.geometry_station(row) for row in planned_rows]
    az = vertical_section_azimuth if vertical_section_azimuth is not None else _projection_azimuth(stations or planned_stations)
    curve = integrate(stations, vertical_section_azimuth=az)
    planned_trajectory = _planned_trajectory(plan_version, planned_rows, planned_stations, az) if plan_version else None
    comparable, comparison_basis = _comparison_basis(plan_version, planned_stations, stations)

    # A printed TVD that the integration does not reproduce is a data question for
    # the engineer, not something to paper over with either number.
    mismatches = []
    for station, result in zip(stations, curve):
        if station.tvd_m is not None and abs(station.tvd_m - result.tvd_m) > TVD_MATERIAL_MISMATCH_M:
            mismatches.append(
                {
                    "md_m": station.md_m,
                    "printed_tvd_m": round(station.tvd_m, 3),
                    "computed_tvd_m": round(result.tvd_m, 3),
                    "difference_m": round(station.tvd_m - result.tvd_m, 3),
                }
            )

    summary = trajectory_summary(curve)
    assumption = ""
    if not curve:
        assumption = (
            "No survey stations are recorded for this well and scope. The well path is not drawn; "
            "add surveys or extract them from a daily report before relying on the visual."
        )
    elif len(curve) == 1:
        assumption = (
            "Only one survey station is recorded, so there is no interval and no direction change: the path "
            "is a single point, not a line."
        )
    elif (summary["max_inc_deg"] or 0) < 1.0:
        assumption = "The recorded stations are vertical, so TVD equals MD along the drawn path."

    # ------------------------------------------------------------------
    # Three different positions, kept apart on purpose
    # ------------------------------------------------------------------
    # * survey endpoint — the deepest station that was actually measured;
    # * report depth   — the closing MD the chosen daily report printed;
    # * snapshot       — a typed operating depth (bit/tool) from that report.
    # A drawing may show all three, but one is never evidence for another, so no
    # max() is taken across them.
    survey_end_m = round(curve[-1].md_m, 3) if curve else None
    report_depth_m = depth["md_m"]
    marker_md = report_depth_m if report_depth_m is not None else survey_end_m
    gap_m = (
        round(report_depth_m - survey_end_m, 3)
        if report_depth_m is not None and survey_end_m is not None
        else None
    )
    if report_depth_m is not None:
        position_basis = depth["basis"]
    elif survey_end_m is not None:
        position_basis = "deepest accepted survey station (no report closing depth)"
    else:
        position_basis = "no depth recorded"

    current_md = marker_md
    current_tvd = interpolate_tvd(curve, current_md) if current_md is not None else None
    # A position that falls between two stations is an interpolation of the
    # integration, and the caption has to say so rather than imply a measurement.
    at_station = bool(
        current_md is not None and any(abs(station.md_m - current_md) < 1e-6 for station in curve)
    )
    tvd_basis = "survey integration" if at_station else "interpolated between survey stations"
    if current_tvd is None and depth["tvd_m"] is not None:
        current_tvd = depth["tvd_m"]
        tvd_basis = "report header"
    if current_tvd is None and current_md is not None and not curve:
        current_tvd = current_md
        tvd_basis = "assumed vertical (no surveys)"
    if current_tvd is None and current_md is not None and curve:
        # Below the last station there is no direction to convert with. Saying so
        # is the honest answer; extrapolating the last tangent would invent one.
        tvd_basis = "not available below the last survey station"

    if gap_m is not None and gap_m > 0 and curve:
        notes.append(
            f"The report closes at {report_depth_m:,.2f} m MD but the deepest survey station is "
            f"{survey_end_m:,.2f} m. The {(gap_m):,.2f} m between them was drilled without a recorded "
            "direction, so it is shown as unsurveyed rather than as a continuation of the line."
        )
    elif gap_m is not None and gap_m < 0 and curve:
        notes.append(
            f"The survey reaches {abs(gap_m):,.2f} m beyond the selected report's closing depth "
            f"({report_depth_m:,.2f} m). The survey is later than the report and does not rewrite it; the marker "
            "stays at the report's closing depth."
        )

    intervals = interval_table(
        curve,
        {
            round(_num(row.md_m), 3): _num(row.dls_deg_per_30m)
            for row in rows
            if _num(row.md_m) is not None and _num(row.dls_deg_per_30m) is not None
        },
    )
    invalid_intervals = [row for row in intervals if not row.valid]
    for row in invalid_intervals[:5]:
        notes.append(
            f"Interval {row.from_md_m:,.2f} → {row.to_md_m:,.2f} m: {row.issue}"
        )
    for row in intervals:
        if row.valid and row.issue:
            notes.append(f"Interval {row.from_md_m:,.2f} → {row.to_md_m:,.2f} m: {row.issue}")

    stations_payload = _station_lineage(rows, curve, reports)
    anchor = stations_payload[0] if stations_payload else None
    anchor_printed = bool(
        anchor
        and (
            anchor.get("recorded_tvd_m") is not None
            or (anchor.get("recorded_ns_m") is not None and anchor.get("recorded_ew_m") is not None)
        )
    )
    anchor_basis = (
        "printed first-station position"
        if anchor_printed
        else ("assumed tie-on at surface level with zero departure" if anchor else "no station")
    )

    seats, seat_notes = _casing_seats(db, organization_id, well, scope, reports)
    notes.extend(seat_notes)
    sections = _section_intervals(
        seats,
        db.scalars(
            select(WellSection).where(
                WellSection.organization_id == organization_id,
                WellSection.well_id == well_id,
                WellSection.scope == scope,
            )
        ).all(),
    )
    plan = _plan_curve(db, organization_id, well_id, scope)
    open_hole = None
    if sections and current_md is not None:
        deepest = sections[-1]
        if current_md > deepest["to_depth_m"]:
            open_hole = {
                "from_depth_m": deepest["to_depth_m"],
                "to_depth_m": round(current_md, 3),
                "label": "Open hole below the last casing",
            }

    # A bit depth is only comparable with the hole when both come from the same
    # report, datum and bore. When the bit is deeper than the hole, or the two
    # come from different reports, the page says "not comparable" instead of
    # printing a negative off-bottom distance.
    bit_depth_m = depth["bit_depth_m"]
    off_bottom_m = None
    off_bottom_note = ""
    if bit_depth_m is None:
        off_bottom_note = "No bit or string depth was recorded on the selected report."
    elif report_depth_m is None:
        off_bottom_note = "The report carries no closing hole depth, so the bit position cannot be compared with it."
    elif bit_depth_m > report_depth_m + 0.001:
        off_bottom_note = (
            "The reported bit depth is deeper than the same report's closing hole depth; the two "
            "cannot come from the same moment and are shown as not comparable."
        )
    else:
        off_bottom_m = round(report_depth_m - bit_depth_m, 3)
        off_bottom_note = "Both figures are from the same report; the difference is arithmetic, not a measurement."

    snapshot = {
        "hole_depth_m": report_depth_m,
        "hole_tvd_m": depth["tvd_m"],
        "bit_depth_m": bit_depth_m,
        "off_bottom_m": off_bottom_m,
        "off_bottom_note": off_bottom_note,
        "report_id": depth["report_id"],
        "report_date": depth["report_date"],
        "report_no": depth["report_no"],
        "status": depth["status"],
        "verified": depth["verified"],
        "basis": depth["basis"],
        "current_status_text": depth["current_status"],
        "tvd_source": depth["tvd_source"],
        # The record carries one operating depth, not a typed observation with a
        # string id and a time, so the type is not claimed: it may be the bit, a
        # workstring or a long/short string endpoint. The report text stays as
        # evidence beside it.
        "label": "reported operating depth — unclassified",
    }
    survey = {
        "stations": len(curve),
        "first_md_m": round(curve[0].md_m, 3) if curve else None,
        "last_md_m": survey_end_m,
        "first_survey_at": next((s["survey_at"] for s in stations_payload if s["survey_at"]), None),
        "last_survey_at": next((s["survey_at"] for s in reversed(stations_payload) if s["survey_at"]), None),
        "sources": sorted({s["source"] for s in stations_payload if s["source"]}),
        "tools": sorted({s["tool"] for s in stations_payload if s["tool"]}),
        "anchor": anchor,
        "anchor_basis": anchor_basis,
        "intervals": len(intervals),
        "invalid_intervals": len(invalid_intervals),
        "branch": scope,
    }

    return {
        "well_id": well.id,
        "well_code": well.well_code,
        "well_name": well.well_name,
        "scope": scope,
        "datum": "Rotary table / kelly bushing as printed on the reports",
        "vertical_section_azimuth_deg": round(az, 3),
        "curve": _curve_payload(curve),
        "planned_trajectory": planned_trajectory,
        "comparable": comparable,
        "comparison_basis": comparison_basis,
        "survey_stations": stations_payload,
        "intervals": [
            {
                "from_md_m": round(row.from_md_m, 3),
                "to_md_m": round(row.to_md_m, 3),
                "delta_md_m": round(row.delta_md_m, 3),
                "inc1_deg": round(row.inc1_deg, 3),
                "azi1_deg": round(row.azi1_deg, 3),
                "inc2_deg": round(row.inc2_deg, 3),
                "azi2_deg": round(row.azi2_deg, 3),
                "beta_deg": round(row.beta_deg, 5) if row.beta_deg is not None else None,
                "dls_deg_per_30m": round(row.dls_deg_per_30m, 4) if row.dls_deg_per_30m is not None else None,
                "recorded_dls_deg_per_30m": (
                    round(row.recorded_dls_deg_per_30m, 4)
                    if row.recorded_dls_deg_per_30m is not None
                    else None
                ),
                "dls_difference_deg_per_30m": (
                    round(row.dls_difference_deg_per_30m, 4)
                    if row.dls_difference_deg_per_30m is not None
                    else None
                ),
                "valid": row.valid,
                "issue": row.issue,
            }
            for row in intervals
        ],
        "summary": {
            **summary,
            "current_md_m": round(current_md, 3) if current_md is not None else None,
            "current_tvd_m": round(current_tvd, 3) if current_tvd is not None else None,
            "current_tvd_basis": tvd_basis,
            "bit_depth_m": bit_depth_m,
            "latest_report_date": depth["report_date"],
            "latest_report_status": depth["status"],
            "depth_basis": depth["basis"],
            "casing_seats": len(seats),
            "sections_drawn": len(sections),
            "survey_end_md_m": survey_end_m,
            "report_depth_md_m": report_depth_m,
            "survey_to_report_gap_m": gap_m,
            "position_basis": position_basis,
        },
        "position": {
            "marker_md_m": round(current_md, 3) if current_md is not None else None,
            "marker_tvd_m": round(current_tvd, 3) if current_tvd is not None else None,
            "marker_tvd_basis": tvd_basis,
            "survey_end_md_m": survey_end_m,
            "report_depth_md_m": report_depth_m,
            "gap_m": gap_m,
            "basis": position_basis,
            "comparable": gap_m is not None and abs(gap_m) <= 0.5,
            "note": (
                "The marker is the selected report's closing measured depth."
                if report_depth_m is not None
                else "No report closing depth exists, so the marker is the deepest accepted survey station."
            ),
        },
        "snapshot": snapshot,
        "survey": survey,
        "sections": sections,
        "open_hole": open_hole,
        "casing_seats": seats,
        "planned": plan,
        "depth": depth,
        "survey_discrepancies": mismatches,
        "notes": notes,
        "assumption": assumption,
        "is_surveyed": bool(curve),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def dashboard_trajectories(
    db: Session, organization_id: str, well_ids: Sequence[str], scope: str
) -> dict[str, dict[str, Any]]:
    """Compact per-well trajectory for the Operations Dashboard cards.

    The dashboard shows many wells, so it carries only the numbers a card prints
    (current MD/TVD, max inclination, departure) and the drawn curve is fetched
    when one well is opened.
    """
    out: dict[str, dict[str, Any]] = {}
    for well_id in well_ids:
        stations, _notes = _survey_stations(db, organization_id, well_id, scope)
        curve = integrate(stations)
        summary = trajectory_summary(curve)
        depth = _latest_depth(_reports(db, organization_id, well_id, scope))
        current = depth["md_m"] if depth["md_m"] is not None else summary["md_m"]
        tvd = interpolate_tvd(curve, current) if current is not None else None
        out[well_id] = {
            "current_md_m": round(current, 3) if current is not None else None,
            "current_tvd_m": round(tvd, 3) if tvd is not None else depth["tvd_m"],
            "max_inc_deg": summary["max_inc_deg"],
            "departure_m": summary["departure_m"],
            "stations": summary["stations"],
            "latest_report_date": depth["report_date"],
            "latest_report_status": depth["status"],
            "latest_report_id": depth["report_id"],
        }
    return out
