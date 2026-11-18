"""OpenWells print layout: section headings, repeated column signatures and local clocks."""

import re
from datetime import datetime, time, timedelta
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from app.core.units import depth_to_meters
from app.domain.operations.normalise import parse_date_flexible
from app.services.operations.workbooks import number

NUM = r"[+-]?\d[\d,]*(?:\.\d+)?"
CLOCK = r"(?:[01]?\d|2[0-3]):[0-5]\d|24:00"
TIME_ROW = re.compile(rf"^\s*({CLOCK})\s+({CLOCK})\s+(.*)$")
# Multiple spaces separate phase, activity code and classification ("EVAL 1" is one phase).
DETAIL = re.compile(
    rf"^({NUM})\s+(?:([A-Za-z][\w-]*(?: \d+)?)\s{{2,}})?(?:(\d{{1,2}})\s{{2,}})?(?:([PUD])\s+)?(?:({NUM})\s{{2,}}({NUM})(?:\s+|$))?(.*)$"
)
SECTION = re.compile(r"^\s*\d+(?:\.\d+)?\s{2,}([A-Za-z].*)$")


def clean(text):
    return " ".join(text.split())


def parse_pdf(content, fallback_day=None):
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted:
        raise ValueError("Password required. Provide an unencrypted PDF copy.")
    if len(reader.pages) > 80:
        raise ValueError("Split the PDF into individual daily reports (80 pages maximum).")
    pages = []
    for page in reader.pages:
        text = page.extract_text(extraction_mode="layout", layout_mode_space_vertically=False)
        if len(text) > 500_000:
            raise ValueError("Page exceeds the safe text limit.")
        pages.append(text)
    header = pages[0] if pages else ""

    def find(pattern):
        m = re.search(pattern, header, re.IGNORECASE | re.MULTILINE)
        return m[1].strip() if m else ""

    def measured(label):
        m = re.search(rf"\b{label}[ \t]+({NUM})\s*\((m|ft)\)", header, re.IGNORECASE)
        return depth_to_meters(number(m[1]), m[2]) if m else None

    source_date = parse_date_flexible(find(r"Report date[ \t]*:?[ \t]+([\d/.-]+)"))
    day = source_date or fallback_day
    if not day:
        raise ValueError("No readable report date. Select a date or enter the report manually.")

    def at(clock):
        h, m = map(int, clock.split(":"))
        return datetime.combine(day, time.min) + timedelta(hours=h, minutes=m)

    result = {
        "report_date": day,
        "report_no_text": find(r"Report no\.?[ \t]+(\S+)"),
        "event_code": find(r"\bEvent[ \t]+([^\n]+)")[:50],
        "dfs_days": number(find(rf"^\s*DFS[ \t]+({NUM})")),
        "rotating_hours": number(find(rf"^\s*Rotating hours[ \t]+({NUM})")),
        "depth_end_m": measured("MD"),
        "tvd_m": measured("TVD"),
        "progress_m": measured("Progress"),
        "rig_name": find(r"Rig Name/No\.[ \t]+(.+?)[ \t]{2,}Event"),
        "wellbore": find(r"Wellbore Name[ \t]+([^\n]+)"),
        "site": find(r"\bSite[ \t]+([^\n]+)")[:200],
        "well_name": find(r"^\s*Well Name[ \t]+(.+?)[ \t]{2,}Wellbore Name"),
        "operation_summary": clean(find(r"24 hr summary\s+([\s\S]*?)\s+24 hr forecast")),
        "forward_plan": clean(find(r"24 hr forecast[ \t]+([\s\S]*?)\n\s*\d+(?:\.\d+)?\s+[A-Z]")),
        "blocks": [],
        "surveys": [],
        "warnings": [],
    }
    unit = "m"
    block = None
    for page_no, text in enumerate(pages, 1):
        mode = ""
        survey_unit = "m"
        dogleg_per_100ft = False
        for line in text.splitlines():
            heading = SECTION.match(line)
            if heading:
                name = clean(heading[1]).lower()
                mode = "survey" if name.startswith("surveys") else ""
                continue
            if re.search(r"^\s*From\s+To\s+Dur\.", line, re.IGNORECASE) and "Operation" in line:
                mode = "log"
                continue
            if re.fullmatch(
                r"\s*(?:From|Start(?: time)?)\s+(?:To|End(?: time)?)\s+(?:Activity|Operation|Description|Narrative)\s*",
                line,
                re.IGNORECASE,
            ):
                mode = "simple_log"
                block = None
                continue
            if mode == "simple_log":
                if match := TIME_ROW.match(line):
                    a, b, narr = match.groups()
                    start, end = at(a), at(b)
                    if end < start:
                        end += timedelta(days=1)
                    if end > start and narr.strip():
                        result["blocks"].append(
                            {
                                "start": start,
                                "end": end,
                                "narrative": clean(narr)[:5000],
                                "phase_raw": "",
                                "code": "",
                                "mark": "",
                                "source_page": page_no,
                                "source": f"PDF page {page_no}",
                            }
                        )
                continue
            if mode == "survey":
                if "(ft)" in line:
                    survey_unit = "ft"
                if "/100ft" in line:
                    dogleg_per_100ft = True
                vals = line.split()
                if len(vals) >= 8 and all(number(v) is not None for v in vals[:8]):
                    md, inc, azi, tvd, ns, ew, vs, dls = map(number, vals[:8])
                    result["surveys"].append(
                        {
                            "md_m": depth_to_meters(md, survey_unit),
                            "inc_deg": inc,
                            "azi_deg": azi,
                            "tvd_m": depth_to_meters(tvd, survey_unit),
                            "ns_m": depth_to_meters(ns, survey_unit),
                            "ew_m": depth_to_meters(ew, survey_unit),
                            "vsec_m": depth_to_meters(vs, survey_unit),
                            "dls_deg_per_30m": (dls * Decimal("0.9843") if dogleg_per_100ft else dls),
                            "source": "PDF",
                            "tool": " ".join(vals[8:])[:100],
                        }
                    )
                continue
            if mode != "log":
                continue
            if "(hr)" in line and ("(ft)" in line or "(m)" in line):
                unit = "ft" if "(ft)" in line else "m"
                continue
            match = TIME_ROW.match(line)
            if match:
                a, b, rest = match.groups()
                detail = DETAIL.match(rest)
                block = None
                # Next-day lookahead commonly prints 23:59 → 06:00 with blank/zero duration.
                if not detail or number(detail[1]) <= 0:
                    result["warnings"].append(
                        f"Page {page_no}: {a}–{b} has no positive printed duration; excluded from this day."
                    )
                    continue
                hours, phase, code, mark, d1, d2, narr = detail.groups()
                start, end = at(a), at(b)
                if end <= start:
                    end += timedelta(days=1)
                block = {
                    "start": start,
                    "end": end,
                    "phase_raw": phase or "",
                    "code": code or "",
                    "mark": mark or "",
                    "depth_from_m": depth_to_meters(number(d1), unit),
                    "depth_to_m": depth_to_meters(number(d2), unit),
                    "narrative": clean(narr),
                    "source_page": page_no,
                    "source": f"PDF page {page_no}",
                }
                result["blocks"].append(block)
                if abs((end - start).total_seconds() / 3600 - float(hours)) > 0.035:
                    result["warnings"].append(f"Page {page_no}: verify printed duration {hours} h against {a}–{b}.")
            elif block is not None and line.startswith(" " * 35) and len(block["narrative"]) < 5000:
                block["narrative"] = (block["narrative"] + " " + clean(line)).strip()[:5000]
    if not result["blocks"] and not result["operation_summary"]:
        raise ValueError(
            "No readable operation summary in this PDF. For a scan, provide a text-searchable PDF or enter activities manually."
        )
    if result["depth_end_m"] is not None and result["progress_m"] is not None:
        result["depth_start_m"] = result["depth_end_m"] - result["progress_m"]
    elif result["blocks"]:
        result["depth_start_m"] = result["blocks"][0].get("depth_from_m")
    return result
