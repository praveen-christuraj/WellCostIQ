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
from typing import Any, Iterable, Sequence

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.operations.trajectory import (
    Station,
    casing_from_section_name,
    casing_label,
    integrate,
    interpolate_tvd,
    parse_size_in,
    survey_azimuth_from_departure,
    trajectory_summary,
)
from app.models.operations import (
    OpsDailyReport,
    OpsPlanItem,
    OpsPlanVersion,
    OpsSurvey,
)
from app.models.rig_well import Well, WellSection

VERIFIED = ("submitted", "approved")
#: A printed TVD differing from the integrated TVD by more than this is flagged.
TVD_MATERIAL_MISMATCH_M = 1.0


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
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


def _survey_stations(db: Session, organization_id: str, well_id: str, scope: str) -> tuple[list[Station], list[str]]:
    """Every recorded station, de-duplicated by MD, plus the data-quality notes.

    A station is only used when both MD and inclination exist. A station with a
    printed TVD but no azimuth is still usable for depth (azimuth is read as 0
    only when inclination is under 1°, where it cannot matter).
    """
    rows = db.scalars(
        select(OpsSurvey)
        .where(
            OpsSurvey.organization_id == organization_id,
            OpsSurvey.well_id == well_id,
            OpsSurvey.scope == scope,
            OpsSurvey.is_deleted.is_(False),
            OpsSurvey.is_current.is_(True),
        )
        .order_by(OpsSurvey.md_m.asc(), OpsSurvey.station_no.asc())
    ).all()
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
        azi = _num(row.azi_deg)
        if azi is None:
            if abs(inc) >= 1.0:
                notes.append(
                    f"Survey at {md:,.2f} m has {inc:,.2f}° inclination but no azimuth; "
                    "the horizontal direction of that station is unknown."
                )
            azi = 0.0
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
                f"Two survey stations share MD {station.md_m:,.2f} m; the latest report was kept."
            )
        by_md[station.md_m] = station
    return [by_md[md] for md in sorted(by_md)], notes


def _latest_depth(reports: Sequence[OpsDailyReport]) -> dict[str, Any]:
    """Closing depth of the latest report, preferring a verified one."""
    if not reports:
        return {
            "md_m": None,
            "tvd_m": None,
            "bit_depth_m": None,
            "report_date": None,
            "report_id": None,
            "status": "",
            "basis": "no report",
        }
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
    version = db.scalar(
        select(OpsPlanVersion).where(
            OpsPlanVersion.organization_id == organization_id,
            OpsPlanVersion.well_id == well_id,
            OpsPlanVersion.scope == scope,
            OpsPlanVersion.status == "active",
            OpsPlanVersion.is_deleted.is_(False),
        )
    )
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


def well_path(
    db: Session,
    organization_id: str,
    well_id: str,
    scope: str = "drilling",
    *,
    vertical_section_azimuth: float | None = None,
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

    stations, notes = _survey_stations(db, organization_id, well_id, scope)
    reports = _reports(db, organization_id, well_id, scope)
    depth = _latest_depth(reports)
    az = vertical_section_azimuth
    if az is None:
        # The vertical-section plane follows the well's own closure direction, so
        # the first pass integrates at zero azimuth and the curve is rebuilt in
        # the plane the well actually reached.
        seed = integrate(stations, vertical_section_azimuth=0.0)
        az = (
            survey_azimuth_from_departure(seed[-1].ns_m, seed[-1].ew_m)
            if seed
            else 0.0
        )
    curve = integrate(stations, vertical_section_azimuth=az)

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
    elif len(curve) == 1 or (summary["max_inc_deg"] or 0) < 1.0:
        assumption = "The recorded stations are vertical, so TVD equals MD along the drawn path."

    current_md = summary["md_m"]
    if depth["md_m"] is not None:
        if current_md is None or depth["md_m"] > current_md:
            current_md = depth["md_m"]
    current_tvd = interpolate_tvd(curve, current_md) if current_md is not None else None
    tvd_basis = "survey integration"
    if current_tvd is None and depth["tvd_m"] is not None:
        current_tvd = depth["tvd_m"]
        tvd_basis = "report header"
    if current_tvd is None and current_md is not None and not curve:
        current_tvd = current_md
        tvd_basis = "assumed vertical (no surveys)"

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
    latest_section = next(
        (s for s in reversed(sections) if current_md is not None and s["to_depth_m"] <= current_md + 0.5),
        None,
    )
    open_hole = None
    if sections and current_md is not None:
        deepest = sections[-1]
        if current_md > deepest["to_depth_m"]:
            open_hole = {
                "from_depth_m": deepest["to_depth_m"],
                "to_depth_m": round(current_md, 3),
                "label": "Open hole below the last casing",
            }

    return {
        "well_id": well.id,
        "well_code": well.well_code,
        "well_name": well.well_name,
        "scope": scope,
        "datum": "Rotary table / kelly bushing as printed on the reports",
        "vertical_section_azimuth_deg": round(az, 3),
        "curve": [
            {
                "md_m": round(s.md_m, 3),
                "inc_deg": round(s.inc_deg, 3),
                "azi_deg": round(s.azi_deg, 3),
                "tvd_m": round(s.tvd_m, 3),
                "ns_m": round(s.ns_m, 3),
                "ew_m": round(s.ew_m, 3),
                "vsec_m": round(s.vsec_m, 3),
                "dls_deg_per_30m": round(s.dls_deg_per_30m, 3),
                "build_deg_per_30m": round(s.build_deg_per_30m, 3),
                "turn_deg_per_30m": round(s.turn_deg_per_30m, 3),
            }
            for s in curve
        ],
        "summary": {
            **summary,
            "current_md_m": round(current_md, 3) if current_md is not None else None,
            "current_tvd_m": round(current_tvd, 3) if current_tvd is not None else None,
            "current_tvd_basis": tvd_basis,
            "bit_depth_m": depth["bit_depth_m"],
            "latest_report_date": depth["report_date"],
            "latest_report_status": depth["status"],
            "depth_basis": depth["basis"],
            "casing_seats": len(seats),
            "sections_drawn": len(sections),
        },
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
