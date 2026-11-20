"""Directional survey import: one study pipeline for typed sheets and PDFs.

The survey tab of a daily report accepts a directional-survey file the same way
the report flow accepts a DDR: the file is *studied*, never silently imported.
This module builds a **preview** — parsed stations, detected format, unit basis
and every warning the parser wants a human to see — and never writes. The
engineer reviews the preview in the dialog and applies it through the ordinary
report-save path, so there is exactly one write path and one audit trail.

Two source families are supported:

* **CSV / Excel (.xlsx / .xlsm)** — a typed table anywhere in the sheet. The
  header row is located by signature (an ``md``-like column and an
  inclination-like column), not by position, so title rows, logos and header
  blocks above the table do not matter. Units are read from the header cells
  (``md_ft``, ``TVD (ft)`` …) and default to metres; feet are converted exactly
  with the same standardized depth factor as the daily reports (ft ÷ 3.281).
* **PDF** — delegated to the OpenWells study engine (``parse_pdf``), the same
  deterministic parser the DDR extraction uses, so the stations an engineer
  already trusts from DDR extraction come out of a standalone survey PDF
  either way. Scanned/image PDFs carry no text and are refused with a clear
  message.

Nothing here decides that a file is a survey table by guesswork about its file
name. If no MD/INC signature is found, the preview is an error naming what was
expected; a wrong import is worse than a refused one.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO, StringIO
from itertools import islice
from typing import Any

from app.core.precision import plain_decimal, rounded
from app.domain.operations.normalise import parse_date_flexible
from app.services.operations.openwells import parse_pdf
from app.services.operations.workbooks import key, measured_depth, number, workbook

MAX_STATIONS = 200
MAX_SCAN_ROWS = 60
MAX_TABULAR_ROWS = 5000
MAX_PLANNED_STATIONS = 5000

# Unit markers inside a header cell, e.g. "MD (ft)" -> key "md ft".
_FT = re.compile(r"\b(ft|feet|foot)\b")
_M = re.compile(r"\b(m|mt|metre|metres|meter|meters)\b")

_COLUMNS: dict[str, tuple[str, ...]] = {
    "md": ("md", "md m", "md ft", "md metre", "md metres", "md meter", "md meters",
           "mdepth", "m depth", "md measured", "measured depth", "measured depth m", "measured depth ft",
           "measured depth metres", "measured depth meters", "depth", "depth m", "depth ft",
           "depth metres", "depth meters", "survey md", "survey depth", "md measured depth"),
    "inc": ("inc", "inc deg", "incl", "incl deg", "inclination", "inclination deg", "hole inclination",
            "measured inc", "inc from vertical"),
    "azi": ("azi", "azi deg", "azimuth", "azimuth deg", "hole azimuth", "direction", "direction deg",
            "bearing", "grid azimuth", "mag azimuth"),
    "tvd": ("tvd", "tvd m", "tvd ft", "tvd metres", "tvd meters", "tvd metre", "true vertical depth",
            "true vertical depth m", "true vertical depth ft", "vertical depth", "tvd ss", "subsea tvd"),
    "ns": ("ns", "ns m", "ns ft", "n s", "north", "north m", "north ft", "northing", "northing m",
           "northing ft", "n", "y", "north south"),
    "ew": ("ew", "ew m", "ew ft", "e w", "east", "east m", "east ft", "easting", "easting m",
           "easting ft", "e", "x", "east west"),
    "vsec": ("vs", "vs m", "vs ft", "vsec", "vsec m", "vsec ft", "vertical section",
             "vertical section m", "vertical section ft", "departure", "departure m", "departure ft",
             "v s"),
    "dls": ("dls", "dogleg", "dogleg severity", "dog leg", "dog leg severity", "dls 30m", "dls per 30m",
            "dls deg 30m", "dls deg per 30m", "dls deg", "dls deg per", "severity"),
    "tool": ("tool", "mwd", "survey tool", "mwd tool", "tool type", "instrument", "run"),
    "survey_at": ("date", "time", "date time", "datetime", "date and time", "timestamp", "time stamp",
                  "survey at", "survey date", "surveyed at", "survey time", "recorded at", "mwd time"),
}

# Units per depth-ish column: which header words mean feet.
def _unit_for(header_key: str, default: str = "m") -> str:
    if _FT.search(header_key):
        return "ft"
    if _M.search(header_key):
        return "m"
    return default


def _bare_key(value) -> str:
    """Header key with unit tokens removed, so 'N/S (ft)' matches 'n s'."""
    k = key(value)
    k = re.sub(r"\b\d+\s*(ft|feet|foot)\b", " ", k)
    k = re.sub(r"\b(ft|feet|foot|m|mt|metre|metres|meter|meters)\b", " ", k)
    return " ".join(k.split())


def survey_columns(row) -> dict[str, Any] | None:
    """Map a header row to survey columns, or None when not a survey table."""
    cols: dict[str, int] = {}
    for i, val in enumerate(row):
        k = _bare_key(val)
        if not k:
            continue
        for target, aliases in _COLUMNS.items():
            if k in aliases:
                cols.setdefault(target, i)
    # A survey station is meaningless without a measured depth and an
    # inclination; everything else is genuinely optional.
    if "md" in cols and "inc" in cols:
        return cols
    return None


def _header_unit(rows, header_at: int, cols: dict[str, int]) -> str:
    header = rows[header_at]
    for target in ("md", "tvd", "vsec", "ns", "ew"):
        pos = cols.get(target)
        if pos is None:
            continue
        unit = _unit_for(key(header[pos]), "") if pos < len(header) else ""
        if unit:
            return unit
    # A lone "unit" / "units" cell near the table declaring ft or m.
    for row in rows[max(0, header_at - 5): header_at + 2]:
        for i, cell in enumerate(row):
            k = key(cell)
            if k in ("unit", "units"):
                for follower in (row[i + 1] if i + 1 < len(row) else None, cell):
                    fk = key(follower)
                    if _FT.search(fk) or fk in ("ft", "feet"):
                        return "ft"
    return "m"


def _cell(row, pos):
    return row[pos] if pos is not None and pos < len(row) else None


def _survey_at(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day).isoformat()
    text = str(value).strip()
    if not text:
        return None
    parsed = None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M", "%d.%m.%Y %H:%M", "%m/%d/%Y %H:%M", "%d/%m/%y %H:%M"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            continue
    parsed = parse_date_flexible(text)
    if parsed is not None:
        return datetime(parsed.year, parsed.month, parsed.day).isoformat()
    return None


def _fmt(value) -> str | None:
    if value is None:
        return None
    return plain_decimal(rounded(Decimal(value)) if not isinstance(value, Decimal) else rounded(value))


def _fmt_depth(value) -> str | None:
    if value is None:
        return None
    return plain_decimal(Decimal(value).quantize(Decimal("0.001")))


def _validate(stations: list[dict[str, Any]], limit: int) -> list[str]:
    warnings: list[str] = []
    previous_md: Decimal | None = None
    for idx, st in enumerate(stations, 1):
        md = Decimal(st["md_m"]) if st["md_m"] is not None else None
        if md is None:
            warnings.append(f"Station {idx}: measured depth is missing and the station cannot be saved until it is filled in.")
        else:
            if md < 0:
                warnings.append(f"Station {idx}: measured depth {md} m is negative.")
            if previous_md is not None and md < previous_md:
                warnings.append(f"Station {idx}: MD {md} m is above the previous station ({previous_md} m) — the table is not in depth order.")
            previous_md = md
        inc, azi = st.get("inc_deg"), st.get("azi_deg")
        if inc is None:
            warnings.append(f"Station {idx}: inclination is missing.")
        elif not (Decimal(0) <= Decimal(inc) <= Decimal(180)):
            warnings.append(f"Station {idx}: inclination {inc}° is outside 0–180°.")
        if azi is not None and not (Decimal(0) <= Decimal(azi) <= Decimal(360)):
            warnings.append(f"Station {idx}: azimuth {azi}° is outside 0–360°.")
        tvd = st.get("tvd_m")
        if tvd is not None and md is not None and Decimal(tvd) > md + Decimal("0.5"):
            warnings.append(f"Station {idx}: TVD {tvd} m is deeper than MD {md} m — check the unit basis and the column mapping.")
        if st.get("dls_deg_per_30m") is not None and Decimal(st["dls_deg_per_30m"]) < 0:
            warnings.append(f"Station {idx}: dogleg severity is negative.")
    counts = Counter(st["md_m"] for st in stations if st["md_m"] is not None)
    for md in sorted(md for md, count in counts.items() if count > 1):
        warnings.append(f"Duplicate station at MD {md} m appears more than once; remove the duplicate before applying.")
    if len(stations) > limit:
        warnings.append(f"The file holds more than {limit} stations; only the first {limit} are shown.")
    return warnings


def _decode(rows, header_at: int, cols: dict[str, int], unit: str, source: str, limit: int) -> dict[str, Any]:
    stations: list[dict[str, Any]] = []
    warnings: list[str] = []
    dls_per_100ft = False
    dls_pos = cols.get("dls")
    header = rows[header_at]
    if dls_pos is not None and dls_pos < len(header) and "100" in key(header[dls_pos]):
        dls_per_100ft = True
    # Depth-like columns each may declare their own unit; MD wins for the file.
    depth_unit = unit
    skipped = 0
    if len(rows) - header_at - 1 > MAX_TABULAR_ROWS:
        raise ValueError("The survey sheet exceeds 5 000 rows after the header; export only the survey table.")
    for row in rows[header_at + 1:]:
        if stations and len(stations) > limit:
            break
        if not any(cell is not None and str(cell).strip() for cell in row):
            continue
        if isinstance(_cell(row, 0), str) and key(_cell(row, 0)) in ("total", "end of table", "notes", "legend"):
            break
        md_raw = _cell(row, cols.get("md"))
        md = measured_depth(md_raw, _unit_for(key(header[cols["md"]]), depth_unit)) if md_raw is not None else None
        inc = number(_cell(row, cols.get("inc")))
        has_any = any(_cell(row, pos) is not None and str(_cell(row, pos)).strip() for pos in cols.values())
        if not has_any:
            continue
        if md is None:
            skipped += 1
            continue
        tvd_raw = _cell(row, cols.get("tvd"))
        ns_raw = _cell(row, cols.get("ns"))
        ew_raw = _cell(row, cols.get("ew"))
        vs_raw = _cell(row, cols.get("vsec"))
        tvd_unit = _unit_for(key(header[cols["tvd"]]), depth_unit) if "tvd" in cols else depth_unit
        ns_unit = _unit_for(key(header[cols["ns"]]), depth_unit) if "ns" in cols else depth_unit
        ew_unit = _unit_for(key(header[cols["ew"]]), depth_unit) if "ew" in cols else depth_unit
        vs_unit = _unit_for(key(header[cols["vsec"]]), depth_unit) if "vsec" in cols else depth_unit
        tool_raw = _cell(row, cols.get("tool"))
        survey_at_raw = _cell(row, cols.get("survey_at"))
        dls = number(_cell(row, dls_pos)) if dls_pos is not None else None
        if dls is not None and dls_per_100ft:
            dls = rounded(Decimal(dls) * Decimal("0.9843"))
        survey_at = _survey_at(survey_at_raw)
        if survey_at is None and survey_at_raw is not None and str(survey_at_raw).strip():
            warnings.append(f"Station {len(stations) + 1}: the timestamp {str(survey_at_raw).strip()[:40]!r} could not be read and was not imported.")
        stations.append(
            {
                "md_m": _fmt_depth(md),
                "inc_deg": _fmt(inc),
                "azi_deg": _fmt(number(_cell(row, cols.get("azi")))),
                "tvd_m": _fmt_depth(measured_depth(tvd_raw, tvd_unit)) if tvd_raw is not None else None,
                "ns_m": _fmt_depth(measured_depth(ns_raw, ns_unit)) if ns_raw is not None else None,
                "ew_m": _fmt_depth(measured_depth(ew_raw, ew_unit)) if ew_raw is not None else None,
                "vsec_m": _fmt_depth(measured_depth(vs_raw, vs_unit)) if vs_raw is not None else None,
                "dls_deg_per_30m": _fmt(dls),
                "tool": str(tool_raw).strip()[:100] if tool_raw is not None else "",
                "source": source,
                "survey_at": survey_at,
            }
        )
    if skipped:
        warnings.append(f"{skipped} row(s) without a measured depth were skipped.")
    if not stations:
        raise ValueError("The sheet has a survey header but no measured-depth rows under it.")
    warnings.extend(_validate(stations, limit))
    return {"stations": stations[:limit], "warnings": warnings}


def _read_csv(content: bytes) -> list[list[Any]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The CSV is not UTF-8 text. Save it as CSV UTF-8 and upload again.") from exc
    rows = list(islice(csv.reader(StringIO(text)), MAX_SCAN_ROWS + MAX_TABULAR_ROWS + 1))
    if any(len(r) > 200 for r in rows):
        raise ValueError("The CSV has more than 200 columns; export only the survey table.")
    return rows


def survey_preview(filename: str, content: bytes, *, limit: int = MAX_STATIONS, preferred_sheet: str = "") -> dict[str, Any]:
    """Study a survey file and return the stations it contains. Never writes."""
    lower = (filename or "").lower()

    if lower.endswith(".pdf"):
        try:
            parsed = parse_pdf(content)
        except Exception as exc:  # noqa: BLE001 - the reader surfaces its own message
            detail = str(exc).strip()
            raise ValueError(
                "The PDF could not be read as a text document"
                + (f": {detail}" if detail else ".")
                + " If it is a scanned image, print the survey table and import it as Excel or CSV instead."
            ) from exc
        stations = []
        for sv in parsed.get("surveys", []):
            stations.append(
                {
                    "md_m": _fmt_depth(sv.get("md_m")),
                    "inc_deg": _fmt(sv.get("inc_deg")),
                    "azi_deg": _fmt(sv.get("azi_deg")),
                    "tvd_m": _fmt_depth(sv.get("tvd_m")),
                    "ns_m": _fmt_depth(sv.get("ns_m")),
                    "ew_m": _fmt_depth(sv.get("ew_m")),
                    "vsec_m": _fmt_depth(sv.get("vsec_m")),
                    "dls_deg_per_30m": _fmt(sv.get("dls_deg_per_30m")),
                    "tool": str(sv.get("tool") or "").strip()[:100],
                    "source": "PDF",
                    "survey_at": None,
                }
            )
        if not stations:
            raise ValueError(
                "No directional survey table was found in this PDF. "
                "Expected the OpenWells-style table with columns MD, INC, AZI, TVD, N/S, E/W, VS, DLS."
            )
        warnings = [f"{w}" for w in parsed.get("warnings", []) if "survey" in str(w).lower()]
        warnings.extend(_validate(stations, limit))
        warnings.insert(0, f"PDF studied: {len(stations)} survey station(s) found. Review every value before applying.")
        return {
            "format": "pdf",
            "file_name": filename,
            "unit": "m",
            "detected_sheet": None,
            "sheets": [],
            "station_count": len(stations),
            "stations": stations[:limit],
            "warnings": warnings,
        }

    if lower.endswith(".csv"):
        rows = _read_csv(content)
        sheets = ["CSV"]
        sheet = "CSV"
        found = next(((i, c) for i, row in enumerate(rows[:MAX_SCAN_ROWS]) if (c := survey_columns(row))), None)
        if not found:
            raise ValueError("No survey table found in the CSV. Expected at least MD and INC columns (template: md_m, inc_deg, azi_deg, tvd_m, …).")
        header_at, cols = found
        unit = _header_unit(rows, header_at, cols)
        decoded = _decode(rows, header_at, cols, unit, "CSV", limit)
        return {
            "format": "csv",
            "file_name": filename,
            "unit": unit,
            "detected_sheet": sheet,
            "sheets": sheets,
            "station_count": len(decoded["stations"]),
            "stations": decoded["stations"],
            "warnings": decoded["warnings"],
        }

    if lower.endswith((".xlsx", ".xlsm")):
        with workbook(content) as wb:
            matches: dict[str, tuple[int, dict[str, int]]] = {}
            for ws in wb.worksheets:
                if ws.sheet_state != "visible":
                    continue
                for i, row in enumerate(ws.iter_rows(max_row=MAX_SCAN_ROWS, max_col=60, values_only=True)):
                    cols = survey_columns(row)
                    if cols:
                        matches[ws.title] = (i, cols)
                        break
            if not matches:
                raise ValueError(
                    "No survey table found in this workbook. Expected a sheet with at least MD and INC columns "
                    "(template: md_m, inc_deg, azi_deg, tvd_m, ns_m, ew_m, vsec_m, dls_deg_per_30m)."
                )
            # Prefer the sheet with a TVD column, then the one with the most
            # optional columns, then order. Alternatives are reported, never hidden.
            def rank(title: str) -> tuple[int, int]:
                _, cols = matches[title]
                return (1 if "tvd" in cols else 0, len(cols))

            if preferred_sheet and preferred_sheet not in matches:
                raise ValueError("The selected sheet has no readable directional survey table.")
            sheet = preferred_sheet or max(matches, key=rank)
            header_at, cols = matches[sheet]
            ws = wb[sheet]
            if (ws.max_row or 0) > MAX_TABULAR_ROWS + MAX_SCAN_ROWS:
                raise ValueError("The survey sheet exceeds 5 000 rows; export only the survey table.")
            rows = list(islice(ws.iter_rows(max_col=60, values_only=True), MAX_SCAN_ROWS + MAX_TABULAR_ROWS + 1))
        unit = _header_unit(rows, header_at, cols)
        decoded = _decode(rows, header_at, cols, unit, "Excel", limit)
        others = [name for name in matches if name != sheet]
        warnings = list(decoded["warnings"])
        if others:
            warnings.insert(0, f"Other sheets also look like survey tables: {', '.join(others)}. The preview uses {sheet}.")
        return {
            "format": "excel",
            "file_name": filename,
            "unit": unit,
            "detected_sheet": sheet,
            "sheets": list(matches),
            "station_count": len(decoded["stations"]),
            "stations": decoded["stations"],
            "warnings": warnings,
        }

    if lower.endswith(".xls"):
        raise ValueError("Legacy .xls is not supported. Open the workbook, save an unencrypted .xlsx copy, and upload it again.")
    raise ValueError("Choose a .csv, .xlsx, .xlsm or .pdf survey file.")
