"""Read-only, bounded workbook adapters. Never evaluate formulas or rewrite protected sheets."""

import csv
import re
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
from itertools import islice
from zipfile import ZipFile

from openpyxl import load_workbook

from app.core.units import depth_to_meters

MAX_ITEMS = 2000


def key(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def number(value):
    try:
        n = Decimal(str(value).strip().replace(",", ""))
        return n.quantize(Decimal("0.0000000001")) if n.is_finite() and abs(n) < 10**16 else None
    except (InvalidOperation, ValueError):
        return None


@contextmanager
def workbook(content):
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValueError(
            "Encrypted or legacy Excel file. Open it with the owner password and provide an unencrypted .xlsx copy."
        )
    with ZipFile(BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(i.file_size for i in entries) > 64 * 1024**2:
            raise ValueError("Workbook exceeds the safe expanded-size limit.")
        if any(i.flag_bits & 1 for i in entries):
            raise ValueError("Password required. Provide an unencrypted copy.")
    wb = load_workbook(BytesIO(content), read_only=True, data_only=True, keep_links=False)
    try:
        if len(wb.worksheets) > 80:
            raise ValueError("Too many sheets. Export the timeline or report sheet separately.")
        yield wb
    finally:
        wb.close()


def timeline_columns(row):
    cols = {}
    for i, val in enumerate(row):
        k = key(val)
        if k in (
            "well programme",
            "activity",
            "operation",
            "description",
            "operational steps",
            "activity operation",
            "operations description",
            "input lookahead",
        ):
            cols.setdefault("description", i)
        if k.startswith(("target depth", "depth m", "depth md", "depth ft")) or k == "depth":
            cols.setdefault("depth", i)
        if k in (
            "planned hours",
            "hours",
            "planned hrs",
            "iteration dist hrs",
            "predicted time hrs",
            "time taken hr",
            "calc time hr",
            "time hr",
        ):
            cols.setdefault("hours", i)
        if k == "time for operational tracking hr":
            cols["hours"] = i
    return cols if "description" in cols and "hours" in cols else None


def timeline_preview(filename, content, sheet=""):
    """Find candidate sheets by header signature, not by well or file name."""

    def decode(rows, header_at, mapping):
        items, warnings = [], []
        header = rows[header_at]
        for idx, row in enumerate(rows[header_at + 1 :], header_at + 2):
            if any(key(c) in ("timeline summary", "total days", "total hours") for c in row[:5]):
                break

            def cell(col, row=row):
                pos = mapping.get(col)
                return row[pos] if pos is not None and pos < len(row) else None

            desc = str(cell("description") or "").strip()
            if not desc or key(desc) in ("total", "activity", "description"):
                continue
            hrs, depth = number(cell("hours")), number(cell("depth"))
            if hrs is None or hrs < 0:
                warnings.append(
                    f"Row {idx}: enter planned hours; the cell is missing, invalid or has no cached formula result."
                )
                hrs = None
            if depth is not None and "ft" in key(header[mapping["depth"]]).split():
                depth = depth_to_meters(depth, "ft")
            if len(desc) > 500:
                warnings.append(f"Row {idx}: shorten the activity description to 500 characters before saving.")
            items.append(
                {
                    "sequence_no": len(items) + 1,
                    "description": desc,
                    "planned_hours": hrs,
                    "target_depth_m": depth,
                    "source_row": idx,
                }
            )
            if len(items) > MAX_ITEMS:
                raise ValueError("A timeline can contain at most 2,000 activities.")
        if not items:
            raise ValueError("The selected sheet has no timeline activities.")
        return {"items": items, "warnings": warnings}

    def locate(rows):
        return next(((i, cols) for i, row in enumerate(rows) if (cols := timeline_columns(row))), None)

    if filename.lower().endswith(".csv"):
        rows = list(islice(csv.reader(StringIO(content.decode("utf-8-sig"))), 10001))
        if len(rows) > 10000 or any(len(r) > 200 for r in rows):
            raise ValueError("Export the timeline with at most 10,000 rows and 200 columns.")
        found = locate(rows[:30])
        if not found:
            raise ValueError("Expected description, planned_hours and optional target_depth_m columns.")
        return dict(sheets=["CSV"], sheet="CSV", **decode(rows, *found))
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise ValueError("Choose an .xlsx workbook or a .csv timeline.")
    with workbook(content) as wb:
        matches = {}
        for ws in wb.worksheets:
            if ws.sheet_state == "visible":
                found = locate(ws.iter_rows(max_row=30, max_col=50, values_only=True))
                if found:
                    matches[ws.title] = found
        if not matches:
            raise ValueError(
                "No timeline table found. Use the template with description, target_depth_m and planned_hours."
            )
        # Prefer a full time/depth programme to an Input-lookahead summary. Always expose alternatives.
        name = sheet or next((n for n, (_, cols) in matches.items() if "depth" in cols), next(iter(matches)))
        if name not in matches:
            raise ValueError("Select one of the detected timeline sheets.")
        ws = wb[name]
        if (ws.max_row or 0) > 10000:
            raise ValueError("Timeline sheet exceeds 10,000 rows. Export the programme table separately.")
        rows = list(islice(ws.iter_rows(max_col=50, values_only=True), 10001))
        if len(rows) > 10000:
            raise ValueError("Timeline exceeds 10,000 rows.")
        return dict(sheets=list(matches), sheet=name, **decode(rows, *matches[name]))


def daily_workbook(content, day, boundary=0):
    with workbook(content) as wb:
        by_name = {s.title.strip().lower(): s for s in wb.worksheets if s.sheet_state == "visible"}
        mud = by_name.get("obm") or by_name.get("wbm") or by_name.get("dmr")
        if mud is not None:
            # These protected sheets declare >1M rows. The header is a small printed form.
            fields = {}
            for row in mud.iter_rows(max_row=30, max_col=20, values_only=True):
                for i, v in enumerate(row):
                    if isinstance(v, str):
                        val = next((c for c in row[i + 1 : i + 4] if c is not None), None)
                        if val is not None:
                            fields.setdefault(key(v), val)
            date_val = fields.get("report date")
            summary = "; ".join(
                f"{label}: {fields[k]}"
                for k, label in [
                    ("mud type", "Mud type"),
                    ("present activity", "Activity"),
                    ("bit depth m", "Bit depth (m)"),
                    ("total circulating volume", "Circulating volume (bbl)"),
                ]
                if fields.get(k) is not None
            )
            if not summary:
                raise ValueError("The mud report header was not recognised.")
            return {
                "report_date": date_val.date() if isinstance(date_val, datetime) else None,
                "report_type": "DMR",
                "well_name": str(fields.get("well name no") or ""),
                "site": str(fields.get("field") or ""),
                "rig_name": str(fields.get("rig") or ""),
                "report_no_text": str(fields.get("report no") or ""),
                "depth_end_m": number(fields.get("hole depth m")),
                "tvd_m": number(fields.get("tvd m")),
                "operation_summary": summary,
                "blocks": [],
                "surveys": [{"inc_deg": number(fields["incl"]), "source": "DMR"}]
                if number(fields.get("incl")) is not None
                else [],
                "warnings": ["Mud measurements do not allocate any activity hours."],
            }
        ws = by_name.get("summary")
        if ws is None:
            for candidate in by_name.values():
                if parsed := tabular_day(candidate, day, boundary):
                    return parsed
            raise ValueError(
                "Unrecognised workbook. Provide a Summary, DMR or actual time log with From, To and Activity columns."
            )
        if day is None:
            raise ValueError(
                "For an operations Summary workbook select a report date. Expected a sheet named Summary."
            )
        if (ws.max_row or 0) > 10000:
            raise ValueError("Export the Summary sheet with at most 10,000 rows.")
        rows = ws.iter_rows(max_col=56, values_only=True)
        header = [key(c) for c in next(rows, ())]

        def col(prefix):
            return next((i for i, k in enumerate(header) if k.startswith(prefix)), None)

        start, end, narrative = col("start time"), col("end time"), col("details of activit")
        if None in (start, end, narrative):
            raise ValueError("Summary needs Start Time, End Time and Details of Activity columns.")
        begin = datetime.combine(day, time(boundary))
        finish = begin + timedelta(days=1)
        blocks = []
        well_name = rig_name = ""
        warnings = []
        depth_col = col("depth end")
        bit_col = col("bit depth")

        def depth_value(row, i):
            return (
                depth_to_meters(number(row[i]), "ft" if "ft" in header[i].split() else "m")
                if i is not None
                else None
            )

        if depth_col is not None and "ft" in header[depth_col].split():
            warnings.append(
                "Summary labels depth in feet; converted to metres. Verify the printed unit against the daily report."
            )
        for idx, row in enumerate(islice(rows, 10000), 2):
            if idx > 10000:
                raise ValueError("Export the Summary sheet with at most 10,000 rows.")
            a, b = row[start], row[end]
            if not isinstance(a, datetime) or not isinstance(b, datetime) or b <= begin or a >= finish or b <= a:
                continue

            def cell(label, row=row):
                idx = col(label)
                return row[idx] if idx is not None else None

            well_name = str(cell("well name") or well_name)
            rig_name = str(cell("rig name") or rig_name)
            cause = str(cell("cause") or "").strip()
            # 'Plan' and the PT/NPT allocation are distinct in these workbooks. E.g. a U row
            # can carry NPT hours for an equipment failure. Keep both until reviewed.
            alloc = (
                cause.upper()
                if cause.upper() in ("UPA", "SP")
                else (
                    "NPT"
                    if (number(cell("npt hrs")) or 0) > Decimal("0.0001")
                    else ("PT" if (number(cell("pt hrs")) or 0) > Decimal("0.0001") else "")
                )
            )
            blocks.append(
                {
                    "start": max(a, begin),
                    "end": min(b, finish),
                    "narrative": str(row[narrative] or "")[:5000],
                    "mark": str(cell("plan") or ""),
                    "allocation": alloc,
                    "cause": cause,
                    "operation": str(cell("operation") or ""),
                    "depth_to_m": depth_value(row, depth_col) if b <= finish else None,
                    "bit_depth_m": depth_value(row, bit_col) if b <= finish else None,
                    "phase_raw": str(cell("phase") or "")[:20],
                    "party": str(cell("agency") or ""),
                    "code": str(cell("activity") or ""),
                    "source": f"Summary row {idx}",
                }
            )
        if not blocks:
            raise ValueError("No time blocks overlap this report date in Summary.")
        return {
            "report_date": day,
            "well_name": well_name,
            "rig_name": rig_name,
            "blocks": blocks,
            "depth_end_m": blocks[-1]["depth_to_m"],
            "surveys": [],
            "warnings": warnings,
            "operation_summary": " ".join(b["narrative"][:150] for b in blocks[:3]),
        }


def tabular_day(sheet, day, boundary):
    """Import an actual time log, not an arbitrary worksheet containing a couple of dates."""
    from datetime import date

    columns = None
    for i, row in enumerate(sheet.iter_rows(max_row=30, max_col=56, values_only=True), 1):
        h = [key(v) for v in row]
        cols = {
            k: next((n for n, v in enumerate(h) if v in labels), None)
            for k, labels in {
                "start": ("from", "start time", "started at"),
                "end": ("to", "end time", "ended at"),
                "description": ("operation", "activity", "description", "narrative"),
                "date": ("date", "report date"),
                "mark": ("class", "classification", "plan"),
                "depth": ("depth m", "depth ft", "end md m", "closing md m"),
                "phase": ("phase", "phase code"),
                "code": ("activity code", "code"),
            }.items()
        }
        if all(cols[k] is not None for k in ("start", "end", "description")):
            columns = cols
            break
    if not columns:
        return None
    if not day:
        raise ValueError("Select a report date for the tabular time log.")
    if (sheet.max_row or 0) > 10000:
        raise ValueError("Time log exceeds 10,000 rows.")

    def moment(value, d):
        if isinstance(value, datetime):
            return value
        if isinstance(value, time):
            return datetime.combine(d, value)
        raw = str(value or "").strip()
        try:
            return datetime.combine(d, time.fromisoformat(raw)) if len(raw) <= 8 else datetime.fromisoformat(raw)
        except ValueError:
            return None

    start = datetime.combine(day, time(boundary))
    end = start + timedelta(days=1)
    blocks = []
    warnings = []
    for n, row in enumerate(
        sheet.iter_rows(min_row=i + 1, max_row=min(sheet.max_row or 10000, 10000), max_col=56, values_only=True),
        i + 1,
    ):

        def cell(k, row=row):
            return row[cols[k]] if cols[k] is not None else None

        d = cell("date") or day
        if isinstance(d, datetime):
            d = d.date()
        if not isinstance(d, date):
            try:
                d = date.fromisoformat(str(d))
            except ValueError:
                raise ValueError(f"Row {n}: expected an Excel or ISO report date.")
        if not any((cell("start"), cell("end"), cell("description"))):
            continue
        a, z = moment(cell("start"), d), moment(cell("end"), d)
        if not a or not z or a.tzinfo or z.tzinfo:
            raise ValueError(f"Row {n}: enter local start and end timestamps or clocks.")
        if z < a and not isinstance(cell("end"), datetime):
            z += timedelta(days=1)
        if z <= a:
            raise ValueError(f"Row {n}: the end time must follow the start time.")
        if a >= end or z <= start:
            continue
        depth = depth_to_meters(
            number(cell("depth")), "ft" if cols["depth"] is not None and "ft" in h[cols["depth"]] else "m"
        )
        blocks.append(
            {
                "start": max(a, start),
                "end": min(z, end),
                "phase_raw": str(cell("phase") or ""),
                "code": str(cell("code") or ""),
                "mark": str(cell("mark") or ""),
                "source": f"{sheet.title} row {n}",
                "narrative": str(cell("description") or "")[:5000],
                "depth_to_m": depth if z <= end else None,
            }
        )
    if not blocks:
        raise ValueError("The time log has no activities in the selected operating day.")
    return {
        "report_date": day,
        "blocks": blocks,
        "depth_end_m": blocks[-1]["depth_to_m"],
        "surveys": [],
        "warnings": warnings,
        "operation_summary": "",
    }
