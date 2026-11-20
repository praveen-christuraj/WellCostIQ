"""Well trajectory geometry: minimum-curvature survey integration and the well diagram.

Everything here is deterministic arithmetic over *recorded* surveys. Nothing in
this module guesses an inclination, an azimuth or a casing seat: when the record
does not contain a station, the caller is told what is missing so the diagram can
be drawn as unknown rather than as a straight line that was never drilled.

Two published conventions are implemented, and each states its own rules so the
same input can never yield two different numbers in two screens:

1. **Minimum curvature** (the industry standard for a survey station pair, as
   used by welleng and every directional contractor's software). Between station
   *i-1* and *i*::

       dogleg (rad) = 2 * asin( sqrt( sin²(Δinc/2)
                                       + sin(inc1) sin(inc2) sin²(Δazi/2) ) )
       ratio        = 2 / dogleg * tan(dogleg / 2)        (→ 1 as dogleg → 0)
       ΔMD          = MD2 - MD1
       ΔTVD         = ΔMD / 2 * (cos inc1 + cos inc2) * ratio
       ΔN           = ΔMD / 2 * (sin inc1 cos azi1 + sin inc2 cos azi2) * ratio
       ΔE           = ΔMD / 2 * (sin inc1 sin azi1 + sin inc2 sin azi2) * ratio

   Dogleg severity is reported in **degrees per 30 m** (the workspace unit),
   converted from the printed ``°/100 ft`` where that is what the report shows
   (1 °/100 ft = 0.9843 °/30 m, i.e. ``× 30 / 30.48`` — never the ft-to-m length
   factor).

   DLS belongs to an **interval**, not to a station. The first accepted station
   therefore has no interval and no severity (``None``, drawn as ``—``), which is
   a different statement from a straight pair whose severity really is zero. An
   interval whose two directions cannot be trusted (a repeated or decreasing
   measured depth, an out-of-range angle, near-opposed directions) is reported as
   invalid rather than as a number, so a chart can say "no interval" where the
   record does not support one.

2. **Casing-seat sectioning** for the well diagram. A hole section is the
   interval between two casing seats read from the recorded reports (last casing
   size and depth) and/or the configured ``well_sections``. A section whose upper
   seat is unknown starts at surface; a section with no recorded seat at all is
   not drawn.

A **vertical well with no surveys** is a legitimate case: the diagram then falls
back to TVD = MD (explicitly labelled as an assumption) with zero departure. Any
deviation that *is* recorded always wins over that fallback.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Sequence

DEG = math.pi / 180.0
#: The workspace reports dogleg severity in °/30 m. The printed OpenWells table
#: uses °/100 ft, so conversions name both ends explicitly.
DEG_PER_100FT_TO_DEG_PER_30M = 0.9842519685
#: A station cannot physically repeat, so a repeated station is a data fault.
MIN_STATION_GAP_M = 0.0
#: Above this the printed dogleg is a data fault rather than a tight turn.
MAX_PLAUSIBLE_DLS = 90.0
#: Two tangent directions closer to opposed than this cannot be integrated as a
#: smooth arc: the minimum-curvature ratio factor explodes and the answer would be
#: an artefact of rounding. Such a pair is held for review instead of drawn.
MAX_INTEGRABLE_DOGLEG_DEG = 170.0
#: A station gap wider than this still integrates, but the result is a coarse
#: average over the whole gap rather than the curvature inside it, and the chart
#: says so.
COARSE_STATION_GAP_M = 100.0
#: The magnitude the tool and the report use for dogleg severity.
DLS_REFERENCE_M = 30.0


@dataclass(frozen=True)
class Station:
    """One survey station, straight from the record (always metric)."""

    md_m: float
    inc_deg: float
    azi_deg: float
    tvd_m: float | None = None
    ns_m: float | None = None
    ew_m: float | None = None
    tool: str = ""
    source: str = ""

    @property
    def is_vertical(self) -> bool:
        return abs(self.inc_deg) < 1e-9


@dataclass(frozen=True)
class StationResult:
    md_m: float
    inc_deg: float
    azi_deg: float
    tvd_m: float
    ns_m: float
    ew_m: float
    vsec_m: float
    #: ``None`` for the first accepted station (there is no interval before it)
    #: and for a pair the record cannot support. A straight pair is ``0.0``.
    dls_deg_per_30m: float | None
    build_deg_per_30m: float | None
    turn_deg_per_30m: float | None
    #: True where the value came from an arithmetic integration, false where the
    #: record printed it and the integration only reproduced it.
    computed: bool = True
    #: True for the station that seeds the path. Its position is the tie-on.
    is_anchor: bool = False
    #: False where the interval that ends at this station is unusable as a number.
    interval_valid: bool = True
    #: Words for a chart or a drawer: why an interval has no severity, or why the
    #: spacing makes its average coarse.
    interval_issue: str = ""


@dataclass(frozen=True)
class DoglegInterval:
    """One survey-to-survey interval, which is the unit DLS is defined on.

    ``beta_deg`` is the angle between the two tangent directions, ``dls`` is that
    angle normalised to 30 m, and ``recorded_dls`` is the printed/typed severity
    kept beside the calculated one so the two can be compared rather than one
    silently replacing the other.
    """

    from_md_m: float
    to_md_m: float
    delta_md_m: float
    inc1_deg: float
    azi1_deg: float
    inc2_deg: float
    azi2_deg: float
    beta_deg: float | None
    dls_deg_per_30m: float | None
    recorded_dls_deg_per_30m: float | None = None
    valid: bool = True
    issue: str = ""

    @property
    def dls_difference_deg_per_30m(self) -> float | None:
        if self.dls_deg_per_30m is None or self.recorded_dls_deg_per_30m is None:
            return None
        return self.recorded_dls_deg_per_30m - self.dls_deg_per_30m


def _norm_azi(value: float) -> float:
    return value % 360.0


def dogleg_angle(inc1: float, azi1: float, inc2: float, azi2: float) -> float:
    """Return the dogleg between two stations in radians (minimum curvature)."""
    i1, i2 = inc1 * DEG, inc2 * DEG
    da = (azi2 - azi1) * DEG
    a = math.sin((i2 - i1) / 2.0)
    b = math.sin(da / 2.0)
    inner = a * a + math.sin(i1) * math.sin(i2) * b * b
    inner = max(0.0, min(1.0, inner))
    return 2.0 * math.asin(math.sqrt(inner))


def build_and_turn(inc1: float, azi1: float, inc2: float, azi2: float, delta_md: float) -> tuple[float, float]:
    """Build and turn rates in °/30 m, independent of the total dogleg."""
    if delta_md <= 0:
        return 0.0, 0.0
    scale = 30.0 / delta_md
    build = (inc2 - inc1) * scale
    delta = (azi2 - azi1 + 540.0) % 360.0 - 180.0
    turn = delta * math.sin((inc1 + inc2) * DEG / 2.0) * scale
    return build, turn


def deg_per_100ft_to_deg_per_30m(value: float | None) -> float | None:
    """Convert a printed ``°/100 ft`` severity to the workspace's ``°/30 m``.

    The factor is ``30 / 30.48`` — the ratio of the two reference lengths — not
    the ft-to-m length factor (0.3048) and never a per-metre rate.
    """
    if value is None or not math.isfinite(value):
        return None
    return value * DLS_REFERENCE_M / 30.48


def dogleg_interval(
    from_md_m: float,
    from_inc_deg: float,
    from_azi_deg: float,
    to_md_m: float,
    to_inc_deg: float,
    to_azi_deg: float,
    *,
    recorded_dls_deg_per_30m: float | None = None,
) -> DoglegInterval:
    """Facts for one interval, including whether it may be shown as a number.

    Validity is stated explicitly instead of being encoded as zero: a first
    station, a repeated measured depth or an out-of-range angle carry
    ``valid=False`` and the reason, so a caller can print "— no interval" rather
    than plotting a severity the record does not support.
    """
    delta_md = to_md_m - from_md_m
    values = (from_md_m, from_inc_deg, from_azi_deg, to_md_m, to_inc_deg, to_azi_deg)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        return DoglegInterval(
            from_md_m=from_md_m, to_md_m=to_md_m, delta_md_m=delta_md,
            inc1_deg=from_inc_deg, azi1_deg=from_azi_deg,
            inc2_deg=to_inc_deg, azi2_deg=to_azi_deg,
            beta_deg=None, dls_deg_per_30m=None, recorded_dls_deg_per_30m=recorded_dls_deg_per_30m,
            valid=False, issue="An interval endpoint is not a finite number.",
        )
    if not (0.0 <= from_inc_deg <= 180.0 and 0.0 <= to_inc_deg <= 180.0):
        return DoglegInterval(
            from_md_m=from_md_m, to_md_m=to_md_m, delta_md_m=delta_md,
            inc1_deg=from_inc_deg, azi1_deg=from_azi_deg,
            inc2_deg=to_inc_deg, azi2_deg=to_azi_deg,
            beta_deg=None, dls_deg_per_30m=None, recorded_dls_deg_per_30m=recorded_dls_deg_per_30m,
            valid=False, issue="Inclination is outside 0–180°; the direction cannot be trusted.",
        )
    if delta_md <= MIN_STATION_GAP_M:
        return DoglegInterval(
            from_md_m=from_md_m, to_md_m=to_md_m, delta_md_m=delta_md,
            inc1_deg=from_inc_deg, azi1_deg=from_azi_deg,
            inc2_deg=to_inc_deg, azi2_deg=to_azi_deg,
            beta_deg=None, dls_deg_per_30m=None, recorded_dls_deg_per_30m=recorded_dls_deg_per_30m,
            valid=False, issue="The stations do not move down the hole; there is no interval.",
        )
    beta = dogleg_angle(from_inc_deg, from_azi_deg, to_inc_deg, to_azi_deg)
    beta_deg = beta / DEG
    if beta_deg > MAX_INTEGRABLE_DOGLEG_DEG:
        return DoglegInterval(
            from_md_m=from_md_m, to_md_m=to_md_m, delta_md_m=delta_md,
            inc1_deg=from_inc_deg, azi1_deg=from_azi_deg,
            inc2_deg=to_inc_deg, azi2_deg=to_azi_deg,
            beta_deg=beta_deg, dls_deg_per_30m=None,
            recorded_dls_deg_per_30m=recorded_dls_deg_per_30m,
            valid=False,
            issue=(
                f"The two directions are {beta_deg:.1f}° apart (near-opposed); the arc between them "
                "is not integrable as a smooth path. Check the azimuth or inclination."
            ),
        )
    dls = beta_deg * DLS_REFERENCE_M / delta_md
    issue = ""
    if delta_md > COARSE_STATION_GAP_M:
        issue = (
            f"The stations are {delta_md:,.1f} m apart, so this is the average severity over that "
            "interval, not the curvature inside it."
        )
    return DoglegInterval(
        from_md_m=from_md_m, to_md_m=to_md_m, delta_md_m=delta_md,
        inc1_deg=from_inc_deg, azi1_deg=from_azi_deg,
        inc2_deg=to_inc_deg, azi2_deg=to_azi_deg,
        beta_deg=beta_deg, dls_deg_per_30m=dls,
        recorded_dls_deg_per_30m=recorded_dls_deg_per_30m,
        valid=True, issue=issue,
    )


def integrate(
    stations: Sequence[Station],
    *,
    vertical_section_azimuth: float = 0.0,
    anchor: tuple[float, float, float] | None = None,
) -> list[StationResult]:
    """Integrate a survey list with minimum curvature.

    Stations must already be sorted by MD and de-duplicated. The first station
    seeds the position: TVD/N/S/E/W from the printed values when present, else
    ``MD * cos(inc)`` for TVD and zero departure. That fallback is a *tie-on
    assumption*, not a measurement, so the result is marked ``is_anchor`` and the
    caller exposes the basis in words instead of drawing an assumed surface tie as
    if it were surveyed.

    ``anchor`` overrides the seed with an explicit (TVD, N, E) tie-on — for
    example a header's surface coordinates or a reviewed tie-on point. The first
    station then keeps its own recorded MD/Inc/Azi but starts from that position.

    Later stations integrate, and a printed TVD that the integration contradicts
    is kept as data evidence in ``survey_discrepancies`` by the caller — the
    curve itself stays arithmetic. An interval the record cannot support keeps
    ``dls_deg_per_30m=None`` and carries the reason, so no screen can print a
    fabricated severity.
    """
    if not stations:
        return []
    out: list[StationResult] = []
    first = stations[0]
    if anchor is not None:
        tvd, ns, ew = anchor
        anchor_printed = True
    else:
        tvd = first.tvd_m if first.tvd_m is not None else first.md_m * math.cos(first.inc_deg * DEG)
        ns = first.ns_m if first.ns_m is not None else 0.0
        ew = first.ew_m if first.ew_m is not None else 0.0
        anchor_printed = first.tvd_m is not None
    out.append(
        StationResult(
            md_m=first.md_m,
            inc_deg=first.inc_deg,
            azi_deg=_norm_azi(first.azi_deg),
            tvd_m=tvd,
            ns_m=ns,
            ew_m=ew,
            vsec_m=_vertical_section(ns, ew, vertical_section_azimuth),
            # No interval ends at the first station, so there is no severity. A
            # zero here would claim the hole was straight, which was not measured.
            dls_deg_per_30m=None,
            build_deg_per_30m=None,
            turn_deg_per_30m=None,
            computed=not anchor_printed,
            is_anchor=True,
            interval_valid=False,
            interval_issue="First station: no interval above it, so there is no dogleg severity.",
        )
    )
    prev = first
    for station in stations[1:]:
        delta_md = station.md_m - prev.md_m
        if delta_md <= MIN_STATION_GAP_M:
            # A repeated station carries no displacement; skip rather than
            # invent a horizontal jump from a zero-length interval.
            continue
        interval = dogleg_interval(
            prev.md_m, prev.inc_deg, prev.azi_deg,
            station.md_m, station.inc_deg, station.azi_deg,
        )
        dogleg = dogleg_angle(prev.inc_deg, prev.azi_deg, station.inc_deg, station.azi_deg)
        if dogleg < 1e-9:
            ratio = 1.0
        else:
            ratio = 2.0 / dogleg * math.tan(dogleg / 2.0)
        i1, i2 = prev.inc_deg * DEG, station.inc_deg * DEG
        a1, a2 = prev.azi_deg * DEG, station.azi_deg * DEG
        tvd += delta_md / 2.0 * (math.cos(i1) + math.cos(i2)) * ratio
        ns += delta_md / 2.0 * (math.sin(i1) * math.cos(a1) + math.sin(i2) * math.cos(a2)) * ratio
        ew += delta_md / 2.0 * (math.sin(i1) * math.sin(a1) + math.sin(i2) * math.sin(a2)) * ratio
        build, turn = build_and_turn(prev.inc_deg, prev.azi_deg, station.inc_deg, station.azi_deg, delta_md)
        out.append(
            StationResult(
                md_m=station.md_m,
                inc_deg=station.inc_deg,
                azi_deg=_norm_azi(station.azi_deg),
                tvd_m=tvd,
                ns_m=ns,
                ew_m=ew,
                vsec_m=_vertical_section(ns, ew, vertical_section_azimuth),
                dls_deg_per_30m=interval.dls_deg_per_30m,
                build_deg_per_30m=build,
                turn_deg_per_30m=turn,
                computed=True,
                interval_valid=interval.valid,
                interval_issue=interval.issue,
            )
        )
        prev = station
    return out


def _vertical_section(ns: float, ew: float, azimuth: float) -> float:
    return ns * math.cos(azimuth * DEG) + ew * math.sin(azimuth * DEG)


def survey_azimuth_from_departure(ns: float, ew: float) -> float:
    """Azimuth of the horizontal departure, the natural vertical-section plane."""
    if abs(ns) < 1e-9 and abs(ew) < 1e-9:
        return 0.0
    return _norm_azi(math.degrees(math.atan2(ew, ns)))


def interpolate_tvd(curve: Sequence[StationResult], depth_m: float) -> float | None:
    """TVD at a free measured depth on an integrated curve (None outside it)."""
    if not curve or depth_m is None:
        return None
    if depth_m < curve[0].md_m - 1e-6 or depth_m > curve[-1].md_m + 1e-6:
        return None
    for a, b in zip(curve, curve[1:]):
        if a.md_m <= depth_m <= b.md_m:
            if b.md_m - a.md_m < 1e-9:
                return b.tvd_m
            f = (depth_m - a.md_m) / (b.md_m - a.md_m)
            return a.tvd_m + f * (b.tvd_m - a.tvd_m)
    return curve[-1].tvd_m


def trajectory_summary(curve: Sequence[StationResult]) -> dict[str, Any]:
    """The numbers a KPI card needs, each named for exactly what it measures."""
    if not curve:
        return {
            "stations": 0,
            "md_m": None,
            "tvd_m": None,
            "departure_m": None,
            "displacement_m": None,
            "closure_azimuth_deg": None,
            "max_inc_deg": None,
            "max_dls_deg_per_30m": None,
            "max_dls_to_md_m": None,
            "intervals": 0,
            "invalid_intervals": 0,
            "vertical_section_m": None,
            "kickoff_md_m": None,
        }
    last = curve[-1]
    kickoff = next((s.md_m for s in curve if s.inc_deg >= 1.0), None)
    displacement = math.hypot(last.ns_m, last.ew_m)
    measured = [s for s in curve if s.dls_deg_per_30m is not None]
    peak = max(measured, key=lambda s: s.dls_deg_per_30m or 0.0) if measured else None
    return {
        "stations": len(curve),
        "md_m": round(last.md_m, 3),
        "tvd_m": round(last.tvd_m, 3),
        "departure_m": round(displacement, 3),
        "displacement_m": round(displacement, 3),
        "closure_azimuth_deg": round(survey_azimuth_from_departure(last.ns_m, last.ew_m), 2),
        "max_inc_deg": round(max(s.inc_deg for s in curve), 2),
        "max_dls_deg_per_30m": round(peak.dls_deg_per_30m, 3) if peak and peak.dls_deg_per_30m is not None else None,
        # Which interval the peak belongs to: severity is a property of an
        # interval, so the deepest station of that interval is the reference.
        "max_dls_to_md_m": round(peak.md_m, 3) if peak else None,
        "intervals": len(measured),
        "invalid_intervals": sum(1 for s in curve if not s.interval_valid) - (1 if curve else 0),
        "vertical_section_m": round(last.vsec_m, 3),
        "kickoff_md_m": round(kickoff, 3) if kickoff is not None else None,
    }


def interval_table(
    curve: Sequence[StationResult],
    recorded_dls: dict[float, float] | None = None,
) -> list[DoglegInterval]:
    """One row per interval between accepted stations, in measured-depth order.

    ``recorded_dls`` maps an interval's *deeper* station MD to the severity the
    record printed or the engineer typed. It is carried beside the calculation so
    a chart can show both marks and a drawer can quote the difference, without
    either value being overwritten to force agreement.
    """
    recorded = recorded_dls or {}
    rows: list[DoglegInterval] = []
    for previous, current in zip(curve, curve[1:]):
        rows.append(
            dogleg_interval(
                previous.md_m, previous.inc_deg, previous.azi_deg,
                current.md_m, current.inc_deg, current.azi_deg,
                recorded_dls_deg_per_30m=recorded.get(round(current.md_m, 3)),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Well diagram — casing seats and hole sections
# ---------------------------------------------------------------------------
#: Nominal outside diameter (inches) of common hole sections, keyed by the
#: printed hole size the reports carry (``17-1/2"``, ``12-1/4"``, ``8-1/2"`` …).
#: A hole size maps to the casing that is run *after* it, which is what the
#: diagram draws: the pipe, not the open hole.
HOLE_TO_CASING_IN: dict[str, tuple[float, str]] = {
    "36": (30.0, "Conductor"),
    "26": (20.0, "Surface conductor"),
    "17.5": (13.375, "Surface"),
    "16": (13.375, "Surface"),
    "14.75": (11.75, "Intermediate"),
    "12.25": (9.625, "Intermediate"),
    "12": (9.625, "Intermediate"),
    "9.5": (7.0, "Production liner"),
    "8.5": (7.0, "Production"),
    "8.75": (7.0, "Production"),
    "6": (4.5, "Slim hole / liner"),
    "5.875": (4.5, "Slim hole / liner"),
}
#: Printed section names (Master Data hole sections, report text) mapped to the
#: nominal casing size that section is drilled for.
SECTION_NAME_TO_CASING_IN: dict[str, tuple[float, str]] = {
    "conductor": (30.0, "Conductor"),
    "surface": (13.375, "Surface"),
    "surface casing": (13.375, "Surface"),
    "intermediate": (9.625, "Intermediate"),
    "intermediate casing": (9.625, "Intermediate"),
    "production": (7.0, "Production"),
    "production casing": (7.0, "Production"),
    "liner": (7.0, "Production liner"),
    "production liner": (7.0, "Production liner"),
    "hole opening": (13.375, "Section"),
}
#: Casing wall thickness (inches) used only for drawing width, never for volumes.
CASING_WALL_IN = {"30": 0.5, "20": 0.375, "13.375": 0.375, "11.75": 0.375, "9.625": 0.3125, "7": 0.25, "4.5": 0.1875}


def casing_from_hole_size(hole_size_in: float | None) -> tuple[float, str] | None:
    if hole_size_in is None:
        return None
    key = f"{float(hole_size_in):.3f}".rstrip("0").rstrip(".")
    for candidate, value in HOLE_TO_CASING_IN.items():
        if abs(float(candidate) - float(key)) < 0.01:
            return value
    return None


def casing_from_section_name(name: str | None) -> tuple[float, str] | None:
    if not name:
        return None
    return SECTION_NAME_TO_CASING_IN.get(name.strip().lower())


def casing_label(size_in: float) -> str:
    """Render a casing size the way the reports print it: ``9-5/8"``, ``13-3/8"``."""
    from fractions import Fraction

    whole = int(size_in)
    fraction = Fraction(round((size_in - whole) * 8), 8)
    if fraction == 0:
        return f'{whole}"'
    prefix = f"{whole}-" if whole else ""
    return f'{prefix}{fraction.numerator}/{fraction.denominator}"'


_SIZE_RE = re.compile(r"(?<![\d.])(\d{1,2}(?:[.-]\d+)?)\s*(?:\"|''|in\b|inch)", re.IGNORECASE)
_FRACTION_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2})")
_MIXED_RE = re.compile(r"(?<![\d.])(\d{1,2})/(\d{1,2})")


def parse_size_in(text: str | None) -> float | None:
    """Read a printed hole or casing size in inches from a section name or code.

    Accepts ``12-1/4"``, ``8 1/2"``, ``9-5/8``, ``17.5`` and ``12.25``. A bare
    depth-like number without a unit or a fraction is refused: ``3850`` is a
    depth, and reading it as a 3850-inch hole would be worse than saying unknown.
    """
    if not text:
        return None
    value = str(text).strip()
    match = _FRACTION_RE.search(value)
    if match:
        whole, numerator, denominator = match.groups()
        return _fraction(whole, numerator, denominator)
    # A mixed numeral such as "8 1/2" has no dash; read the whole part beside it.
    for mixed in _MIXED_RE.finditer(value):
        numerator, denominator = mixed.groups()
        before = value[: mixed.start()].strip()
        whole = before.split()[-1] if before else ""
        if whole.isdigit() and len(whole) <= 2:
            return _fraction(whole, numerator, denominator)
    match = _SIZE_RE.search(value)
    if not match:
        # A plain decimal is accepted only when it is a plausible pipe size.
        bare = re.fullmatch(r"(\d{1,2}(?:\.\d+)?)", value)
        if not bare:
            return None
        size = float(bare.group(1))
        return size if 3.0 <= size <= 40.0 else None
    try:
        size = float(match.group(1).replace("-", "."))
    except ValueError:
        return None
    return size if 3.0 <= size <= 40.0 else None


def _fraction(whole: str, numerator: str, denominator: str) -> float | None:
    try:
        denominator_value = int(denominator)
        if denominator_value == 0:
            return None
        size = round(float(whole) + float(numerator) / denominator_value, 4)
    except ValueError:
        return None
    return size if 3.0 <= size <= 40.0 else None
