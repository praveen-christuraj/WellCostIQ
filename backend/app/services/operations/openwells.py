"""OpenWells print layout parser: headers, hole/casing, mud, BHA, surveys, safety, POB, and local clocks."""

import math
import re
from datetime import datetime, time, timedelta
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from app.core.precision import rounded
from app.domain.operations.normalise import parse_date_flexible
from app.services.operations.workbooks import measured_depth, number

NUM = r"[+-]?\d[\d,]*(?:\.\d+)?"
POS_NUM = r"\d[\d,]*(?:\.\d+)?"
CLOCK = r"(?:[01]?\d|2[0-3]):[0-5]\d|24:00"
TIME_ROW = re.compile(rf"^\s*({CLOCK})\s+({CLOCK})\s+(.*)$")
# PDF text layout uses columns separated by runs of spaces, including after
# multiword phases such as EVAL 1. A bracketed activity is not a class mark.
DETAIL = re.compile(
    rf"^({NUM})(?=\s|$)\s*(?:([A-Za-z][\w/-]*(?: [\w/-]+)*)\s{{2,}})?"
    rf"(?:(\d{{1,3}}|\[\s*\d{{1,3}}\s*\]|\(\s*\d{{1,3}}\s*\))\s{{2,}})?"
    rf"(?:(P|U|D|PT|UPA|NPT|SP|N|[TX][A-Z]\d{{2}})\s{{2,}})?"
    rf"(?:({NUM})\s{{2,}}({NUM})(?:\s+|$))?(.*)$",
    re.IGNORECASE,
)
SECTION = re.compile(r"^\s{0,12}\d+(?:\.\d+)*\s{2,}([A-Za-z0-9#].*)$")
LOG_HEADER = re.compile(r"^\s*From\s+To\s+Dur(?:ation)?\.?\s+.*?\b(MD from|Depth from)\b.*\bOperation\b", re.I)
FOOTER = re.compile(
    r"(?:Open\s*\d*\s*Wells|Page \d+(?: of \d+)?|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w* \d{1,2}, \d{4} at .*)",
    re.I,
)

# Fraction normalization for casing & hole sizes (e.g. 9 5/8, 13-3/8, 12¼, 8½).
_UNICODE_FRACS = {
    "¼": ".25",
    "½": ".5",
    "¾": ".75",
    "⅛": ".125",
    "⅜": ".375",
    "⅝": ".625",
    "⅞": ".875",
}

# Explicit narrative MD + TVD pairs (e.g. "4076.66M MD, INC 38.49, AZI 127.64, 3122.30M TVD"
# or "SURVEY AT 3060M MD / 2997M TVD" or "MD: 3960.69 m ... TVD: 3029.65 m").
_MD_TVD_PAIR_RE = re.compile(
    rf"(?:({POS_NUM})\s*(m|ft)\s*(?:MD\b)?[^;*]{{0,95}}?\b(?:({POS_NUM})\s*(m|ft)\s*TVD\b|TVD\s*[:=/]?\s*({POS_NUM})\s*(m|ft)\b)"
    rf"|\bMD\s*[:=@]?\s*({POS_NUM})\s*(m|ft)\b[^;*]{{0,95}}?\bTVD\s*[:=@/]?\s*({POS_NUM})\s*(m|ft)?\b)",
    re.IGNORECASE,
)
# Standalone explicit TVD mention (e.g. "SHOE TVD = 1815.40 M", "3122.30M TVD", "TVD 2997 M").
_TVD_SINGLE_RE = re.compile(
    rf"(?:\bTVD\s*[:=@]?\s*({POS_NUM})\s*(m|ft)\b|\b({POS_NUM})\s*(m|ft)\s*TVD\b)",
    re.IGNORECASE,
)
# Explicit bit / string operating depth in status or tripping narrative.
_BIT_DEPTH_RE = re.compile(
    rf"(?:\b(?:bit\s+depth|bit\s+at|rih\b[^.;\n]{{0,55}}?(?:to|@|at)|c/o\s+assy\s*@\s*|clean\s*out\s+assy\s*@\s*|tagged\s+(?:at|@|toc\s+at))\s*({POS_NUM})\s*(m|ft)\b"
    rf"|\bpooh\b[^.;\n]{{0,55}}?\bfrom\s+({POS_NUM})\s*(m|ft)\b)",
    re.IGNORECASE,
)
_BLOCK_CODE_RE = re.compile(r"\b(O[MP]L[-\s]?\d{1,4}[A-Z]?)\b", re.IGNORECASE)
_MUD_ROW_RE = re.compile(
    rf"^\s*([A-Za-z][A-Za-z0-9()/\s.-]{{1,38}}?)\s{{2,}}({POS_NUM})\s+({POS_NUM})\s+"
    rf"\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\s+\d{{1,2}}:\d{{2}}"
    rf"(?:\s+({POS_NUM}))?(?:\s+({POS_NUM}))?(?:\s+({POS_NUM}))?",
    re.IGNORECASE,
)
_HOLE_ROW_RE = re.compile(
    rf"^(?:.{{0,80}}?)\s+(Open Hole|Casing|Liner)\s+({POS_NUM})(?:\s+({POS_NUM}))?\s+({POS_NUM})\s+({POS_NUM})\b",
    re.IGNORECASE,
)
_MW_NARR_RE = re.compile(rf"\b(\d{{1,2}}(?:\.\d{{1,2}})?)\s*ppg\b", re.IGNORECASE)


def clean(text: str) -> str:
    return " ".join((text or "").split())


def _strip_footer_lines(text: str) -> str:
    kept = []
    for raw in (text or "").splitlines():
        s = clean(raw)
        if not s or FOOTER.fullmatch(s):
            continue
        kept.append(s)
    return " ".join(kept).strip()


def _parse_inch_size(raw: str) -> Decimal | None:
    if not raw:
        return None
    txt = raw.strip()
    for ch, rep in _UNICODE_FRACS.items():
        txt = txt.replace(ch, rep)
    txt = txt.replace('"', "").replace("''", "").replace("in", "").strip()
    mixed = re.match(r"^(\d+)[\s-]+(\d+)/(\d+)$", txt)
    if mixed:
        num, top, bot = int(mixed[1]), int(mixed[2]), int(mixed[3])
        if bot > 0:
            return rounded(Decimal(num) + Decimal(top) / Decimal(bot))
    frac = re.match(r"^(\d+)/(\d+)$", txt)
    if frac and int(frac[2]) > 0:
        return rounded(Decimal(int(frac[1])) / Decimal(int(frac[2])))
    plain = re.match(r"^(\d+(?:\.\d+)?)", txt)
    return number(plain[1]) if plain else None


def _parse_last_casing(text: str) -> tuple[Decimal | None, Decimal | None]:
    if not text:
        return None, None
    m = re.search(
        rf"(\d+(?:[\s-]+\d+/\d+|\.\d+|[¼½¾⅛⅜⅝⅞])?)\s*(?:in|\"|'')?\s*@\s*({POS_NUM})\s*(m|ft)\b",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None, None
    size = _parse_inch_size(m[1])
    depth = measured_depth(m[2], m[3])
    return size, depth


def extract_narrative_md_tvd_pairs(text: str, default_unit: str = "m") -> list[tuple[Decimal, Decimal]]:
    """Extract explicitly paired (MD_m, TVD_m) measurements from engineering narrative."""
    pairs: list[tuple[Decimal, Decimal]] = []
    for m in _MD_TVD_PAIR_RE.finditer(text or ""):
        if m[1]:
            md_raw, md_u = m[1], m[2] or default_unit
            tvd_raw = m[3] or m[5]
            tvd_u = m[4] or m[6] or md_u
        else:
            md_raw, md_u = m[7], m[8] or default_unit
            tvd_raw, tvd_u = m[9], m[10] or md_u
        md_val = measured_depth(md_raw, md_u)
        tvd_val = measured_depth(tvd_raw, tvd_u)
        if (
            md_val is not None
            and tvd_val is not None
            and md_val > 0
            and tvd_val > 0
            and tvd_val <= md_val + Decimal("1.0")
        ):
            pairs.append((md_val, min(tvd_val, md_val)))
    return pairs


def extract_single_tvds(text: str, max_md: Decimal | None = None) -> list[Decimal]:
    """Extract standalone explicit TVD measurements bounded by wellbore MD."""
    found: list[Decimal] = []
    for m in _TVD_SINGLE_RE.finditer(text or ""):
        raw, unit = (m[1], m[2]) if m[1] else (m[3], m[4])
        val = measured_depth(raw, unit)
        if val is None or val <= Decimal("10"):
            continue
        if max_md is not None and val > max_md + Decimal("1.0"):
            continue
        found.append(min(val, max_md) if max_md is not None else val)
    return found


def extract_bit_depth(text: str) -> Decimal | None:
    """Extract operating bit/string depth from status or tripping narrative."""
    if not text:
        return None
    best: Decimal | None = None
    for m in _BIT_DEPTH_RE.finditer(text):
        raw, unit = (m[1], m[2]) if m[1] else (m[3], m[4])
        val = measured_depth(raw, unit)
        if val is not None and Decimal("5") <= val <= Decimal("15000"):
            best = val
    return best


def interpolate_tvd(
    md: Decimal | None,
    profile: list[tuple[Decimal, Decimal, Decimal | None]],
) -> Decimal | None:
    """Compute TVD at `md` from sorted `(md_m, tvd_m, inc_deg)` survey/anchor points."""
    if md is None or md < 0 or not profile:
        return None
    if md == 0:
        return Decimal("0.000")
    ordered = sorted(
        (pt for pt in profile if pt[0] is not None and pt[1] is not None and pt[0] >= 0 and pt[1] >= 0),
        key=lambda item: item[0],
    )
    if not ordered:
        return None
    # Deduplicate same-MD anchors (keep last).
    dedup: list[tuple[Decimal, Decimal, Decimal | None]] = []
    for pt in ordered:
        if dedup and abs(dedup[-1][0] - pt[0]) <= Decimal("0.05"):
            dedup[-1] = pt
        else:
            dedup.append(pt)
    # Exact match within 0.5 m.
    for s_md, s_tvd, _ in dedup:
        if abs(md - s_md) <= Decimal("0.5"):
            return rounded(min(s_tvd, md))
    # Bracketed interpolation between two known survey/anchor points.
    if md < dedup[0][0]:
        s_md, s_tvd, _ = dedup[0]
        if s_md > 0 and s_tvd <= s_md:
            return rounded(min(md, md * (s_tvd / s_md)))
        return None
    for idx in range(len(dedup) - 1):
        m1, t1, _ = dedup[idx]
        m2, t2, _ = dedup[idx + 1]
        if m1 <= md <= m2 and m2 > m1:
            frac = (md - m1) / (m2 - m1)
            est = t1 + frac * (t2 - t1)
            if Decimal(0) <= est <= md + Decimal("0.5"):
                return rounded(min(est, md))
            return None
    # Short tangent projection below deepest survey station using measured inclination.
    last_md, last_tvd, last_inc = dedup[-1]
    delta = md - last_md
    if Decimal(0) < delta <= Decimal("300"):
        if last_inc is not None and Decimal(0) <= last_inc <= Decimal("92"):
            cos_i = Decimal(str(math.cos(math.radians(float(last_inc)))))
            est = last_tvd + delta * cos_i
            if Decimal(0) <= est <= md:
                return rounded(est)
        elif len(dedup) >= 2:
            prev_md, prev_tvd, _ = dedup[-2]
            if last_md > prev_md:
                slope = (last_tvd - prev_tvd) / (last_md - prev_md)
                if Decimal("-0.05") <= slope <= Decimal("1.001"):
                    est = last_tvd + delta * min(slope, Decimal(1))
                    if Decimal(0) <= est <= md:
                        return rounded(est)
    return None


def _left_field(header: str, label: str, stop_labels: tuple[str, ...] = ()) -> str:
    """Extract a two-column OpenWells header field without bleeding into the right column."""
    stop = "|".join(re.escape(s) for s in stop_labels)
    for line in header.splitlines():
        m = re.match(rf"^\s*{label}[ \t]*:?[ \t]+(.*)$", line, re.IGNORECASE)
        if not m:
            continue
        rest = m[1]
        if stop:
            rest = re.split(rf"(?:[ \t]{{2,}}|\b)(?:{stop})\b", rest, maxsplit=1, flags=re.IGNORECASE)[0]
        else:
            rest = re.split(r"[ \t]{4,}[A-Z][A-Za-z ./#()-]{1,22}[ \t]{2,}", rest, maxsplit=1)[0]
        val = clean(rest)
        if val and stop_labels and any(val.lower().startswith(s.lower()) for s in stop_labels):
            return ""
        return val
    return ""


def _status_block(header: str, label: str, next_pattern: str) -> str:
    """Extract single- or multi-line OpenWells Status section fields (even when value wraps to next line)."""
    m = re.search(
        rf"^[ \t]*{label}[ \t]*:?[ \t]*([\s\S]*?)(?=^[ \t]*{next_pattern})",
        header,
        re.IGNORECASE | re.MULTILINE,
    )
    return _strip_footer_lines(m[1]) if m else ""


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
    full_text = "\n".join(pages)

    def find(pattern, src=header):
        m = re.search(pattern, src, re.IGNORECASE | re.MULTILINE)
        return m[1].strip() if m else ""

    def measured(label):
        m = re.search(rf"\b{label}\b[ \t]+({NUM})\s*\((m|ft)\)", header, re.IGNORECASE)
        return measured_depth(m[1], m[2]) if m else None

    source_date = parse_date_flexible(find(r"Report date[ \t]*:?[ \t]+([\d/.-]+)"))
    day = source_date or fallback_day
    if not day:
        raise ValueError("No readable report date. Select a date or enter the report manually.")

    def at(clock):
        h, m = map(int, clock.split(":"))
        return datetime.combine(day, time.min) + timedelta(hours=h, minutes=m)

    # Report number: guard against capturing adjacent "Report date" label when blank.
    raw_report_no = _left_field(header, r"Report no\.?", ("Report date",))
    if raw_report_no.lower().startswith("report"):
        raw_report_no = ""
    report_no_token = raw_report_no.split()[0] if raw_report_no else ""
    day_number = int(report_no_token) if report_no_token.isdigit() and 1 <= int(report_no_token) <= 9999 else None

    # Detect report type from title banner when present.
    title_head = "\n".join(header.splitlines()[:12]).upper()
    detected_type = ""
    if "COMPLETION REPORT" in title_head or "DAILY COMPLETION" in title_head:
        detected_type = "DCR"
    elif "RIG MOVE" in title_head:
        detected_type = "RMR"
    elif "DRILLING REPORT" in title_head:
        detected_type = "DDR"

    company = _left_field(header, "Company", ("Project", "Report date"))[:200]
    project = _left_field(header, "Project", ("Site", "Country"))[:200]
    site = _left_field(header, "Site", ("Rig Name/No.", "Rig Name", "Event"))[:200]
    supervisor = _left_field(header, "Supervisor", ("Engineer", "Wellbore"))[:200]
    engineer = find(r"\bEngineer[ \t]+([^\n]+)")[:200]
    datum = _left_field(header, r"(?:Active datum|Datum)", ("Water depth", "Spud date", "Elevation"))[:100]
    spud_date = parse_date_flexible(find(r"Spud date[ \t]*:?[ \t]+([\d/.-]+)"))

    raw_uwi = _left_field(header, "UWI", ("Spud date", "API", "Active datum"))
    # OpenWells occasionally prints Spud date directly glued to UWI (e.g. "03/09/2026").
    if raw_uwi and re.fullmatch(r"[\d/.-]{6,12}", raw_uwi) and parse_date_flexible(raw_uwi):
        if not spud_date:
            spud_date = parse_date_flexible(raw_uwi)
        raw_uwi = ""

    block_text = _left_field(header, r"(?:Block|Lease|License|Licence)", ("Field", "Slot", "Lat", "Long", "State"))[:100]
    if not block_text:
        blk_match = _BLOCK_CODE_RE.search(f"{company} {project} {site}")
        if blk_match:
            block_text = re.sub(r"\s+", "-", blk_match[1].upper())

    last_casing_raw = _left_field(header, "Last Casing", ("Next Casing", "LOT", "FIT", "MAASP"))
    csg_size, csg_depth = _parse_last_casing(last_casing_raw)

    header_md = measured("MD")
    header_tvd = measured("TVD")
    progress_m = measured("Progress")
    md_auth_m = measured("MD auth")
    rot_hrs = number(find(rf"\bRotating hours[ \t]+({NUM})"))
    cum_rot_hrs = number(find(rf"\bCum\.?\s*Rot\.?\s*(?:Hrs|hours)[ \t]+({NUM})"))
    dfs_days = number(find(rf"^\s*DFS[ \t]+({NUM})"))
    est_days = number(find(rf"\bEst\.?\s*days[ \t]+({NUM})"))

    current_status = _status_block(header, "Current status", r"24 hr summary\b")[:500]
    op_summary = _status_block(header, "24 hr summary", r"24 hr forecast\b")
    if not op_summary:
        op_summary = clean(find(r"24 hr summary\s+([\s\S]*?)\s+24 hr forecast"))
    forward_plan = _status_block(header, "24 hr forecast", r"\d+(?:\.\d+)?\s{2,}[A-Z]")
    if not forward_plan:
        forward_plan = _strip_footer_lines(find(r"24 hr forecast[ \t]*([\s\S]*?)\n\s*\d+(?:\.\d+)?\s+[A-Z]"))

    result = {
        "report_date": day,
        "report_type": detected_type,
        "report_no_text": report_no_token[:50],
        "day_number": day_number,
        "event_code": _left_field(header, "Event", ("Report no", "Objective"))[:50] or find(r"\bEvent[ \t]+([^\n]+)")[:50],
        "customer": company,
        "project": project,
        "site": site,
        "datum": datum,
        "supervisor": supervisor,
        "engineer": clean(engineer)[:200],
        "uwi": raw_uwi[:100],
        "block_text": block_text[:100],
        "spud_date": spud_date,
        "dfs_days": dfs_days,
        "est_days": est_days,
        "rotating_hours": rot_hrs,
        "cum_rotating_hours": cum_rot_hrs,
        "depth_start_m": None,
        "depth_end_m": header_md,
        "tvd_start_m": None,
        "tvd_m": header_tvd,
        "tvd_source": "header" if header_tvd is not None else "",
        "bit_depth_m": None,
        "progress_m": progress_m,
        "md_auth_m": md_auth_m,
        "last_casing_size_in": csg_size,
        "last_casing_depth_m": csg_depth,
        "hole_section_text": "",
        "hole_size_in": None,
        "current_status": current_status,
        "mud_type": "",
        "mud_weight_ppg": None,
        "mud_viscosity_sec": None,
        "mud_pv_cp": None,
        "mud_yp_lbf": None,
        "bha_summary": "",
        "pob_count": None,
        "hse_summary": "",
        "rig_name": find(r"Rig Name/No\.[ \t]+(.+?)[ \t]{2,}Event") or _left_field(header, r"Rig Name/No\.?", ("Event",)),
        "wellbore": find(r"Wellbore Name[ \t]+([^\n]+)"),
        "well_name": find(r"^\s*Well Name[ \t]+(.+?)[ \t]{2,}Wellbore Name") or _left_field(header, "Well Name", ("Wellbore Name",)),
        "operation_summary": op_summary,
        "forward_plan": forward_plan,
        "blocks": [],
        "surveys": [],
        "warnings": [],
    }

    unit = "m"
    hole_unit = "m"
    mud_md_check: Decimal | None = None
    open_hole_rows: list[tuple[str, Decimal | None, Decimal | None, Decimal | None]] = []
    casing_rows: list[tuple[Decimal | None, Decimal | None]] = []
    bha_no = ""
    bha_len_m: Decimal | None = None
    bha_min_id: Decimal | None = None
    bha_purpose = ""
    bit_info = ""
    dslti_days: str = ""
    dslta_days: str = ""
    stop_cards: str = ""
    safety_topic = ""
    pob_count: int | None = None

    block = None
    continuation_start = 0
    for page_no, text in enumerate(pages, 1):
        mode = ""
        survey_unit = "m"
        dogleg_per_100ft = False
        for line in text.splitlines():
            # Personnel total can sit inside any trailing Personnel section.
            pob_match = re.search(r"Total No\.?\s*of People\s*:\s*(\d+)", line, re.IGNORECASE)
            if pob_match:
                val = int(pob_match[1])
                if 0 < val <= 50000:
                    pob_count = val

            heading = SECTION.match(line)
            if heading:
                name = clean(heading[1]).lower()
                if name.startswith("surveys"):
                    mode = "survey"
                elif "hole section" in name:
                    mode = "hole"
                elif name == "mud" or name.startswith("mud ") or name == "fluids":
                    mode = "mud"
                elif name.startswith("bha"):
                    mode = "bha"
                    if not bha_no:
                        bm = re.search(r"bha\s*(?:no\.?\s*)?#?\s*(\w+)", name, re.IGNORECASE)
                        if bm:
                            bha_no = bm[1]
                elif name.startswith("bit data"):
                    mode = "bit"
                elif "safety" in name or (mode == "safety" and name in ("general", "drills", "incidents")):
                    mode = "safety"
                else:
                    mode = ""
                block = None
                continue

            if (log_header := LOG_HEADER.match(line)) or (
                re.search(r"^\s*From\s+To\s+Dur\.", line, re.I) and "Operation" in line
            ):
                mode = "log"
                continuation_start = log_header.start(1) if log_header else 35
                continue

            if re.fullmatch(
                r"\s*(?:From|Start(?: time)?)\s+(?:To|End(?: time)?)\s+(?:Activity|Operation|Description|Narrative)\s*",
                line,
                re.IGNORECASE,
            ):
                mode = "simple_log"
                block = None
                continue

            if mode == "hole":
                if re.search(r"\bMD\s*\(ft\)", line, re.IGNORECASE):
                    hole_unit = "ft"
                elif re.search(r"\bMD\s*\(m\)", line, re.IGNORECASE):
                    hole_unit = "m"
                hm = _HOLE_ROW_RE.search(line)
                if hm:
                    kind = hm[1].lower()
                    diam = number(hm[2])
                    top_m = measured_depth(hm[4], hole_unit)
                    base_m = measured_depth(hm[5], hole_unit)
                    prefix = line[: hm.start(1)]
                    # Extract section name column (second column when wellbore sits on left).
                    parts = [p.strip() for p in re.split(r"[ \t]{2,}", prefix.strip()) if p.strip()]
                    sec_name = parts[-1] if parts else ""
                    if sec_name and "/" in sec_name and len(parts) == 1:
                        sec_name = ""
                    if kind == "open hole":
                        open_hole_rows.append((sec_name, diam, top_m, base_m))
                    else:
                        casing_rows.append((diam, base_m))
                continue

            if mode == "mud":
                mm = _MUD_ROW_RE.match(line)
                if mm and result["mud_weight_ppg"] is None:
                    m_type = clean(mm[1])
                    mw = number(mm[2])
                    fv = number(mm[3])
                    md_chk = measured_depth(mm[4], "ft" if "(ft)" in line.lower() else "m") if mm[4] else None
                    pv = number(mm[5]) if mm[5] else None
                    yp = number(mm[6]) if mm[6] else None
                    if mw is not None and Decimal("5") <= mw <= Decimal("25"):
                        result["mud_type"] = m_type[:100]
                        result["mud_weight_ppg"] = mw
                        result["mud_viscosity_sec"] = fv
                        result["mud_pv_cp"] = pv
                        result["mud_yp_lbf"] = yp
                        if md_chk is not None and md_chk > 0:
                            mud_md_check = md_chk
                continue

            if mode == "bha":
                lm = re.search(rf"BHA Length[ \t]+({POS_NUM})\s*\((m|ft)\)", line, re.IGNORECASE)
                if lm and bha_len_m is None:
                    bha_len_m = measured_depth(lm[1], lm[2])
                idm = re.search(rf"Min\.?\s*ID[ \t]+({POS_NUM})\s*\(in\)", line, re.IGNORECASE)
                if idm and bha_min_id is None:
                    bha_min_id = number(idm[1])
                pm = re.search(r"Purpose[ \t]{2,}([^\n]+)", line, re.IGNORECASE)
                if pm and not bha_purpose:
                    bha_purpose = re.split(r"[ \t]{3,}", pm[1].strip())[0][:120]
                continue

            if mode == "bit":
                bm = re.search(rf"Bit size[ \t]+({POS_NUM})\s*\(in\)", line, re.IGNORECASE)
                tm = re.search(r"(?:Bit type|IADC|Model|Name)[ \t]{2,}([A-Za-z0-9 ./-]+)", line, re.IGNORECASE)
                if bm and not bit_info:
                    bit_info = f'Bit {bm[1]}"'
                    if tm:
                        bit_info += f" {clean(tm[1])[:40]}"
                continue

            if mode == "safety":
                dm = re.search(rf"\bDSLTI[ \t]+({POS_NUM})\s*\(days\)", line, re.IGNORECASE)
                if dm and not dslti_days:
                    dslti_days = dm[1]
                am = re.search(rf"\bDSLTA[ \t]+({POS_NUM})\s*\(days\)", line, re.IGNORECASE)
                if am and not dslta_days:
                    dslta_days = am[1]
                sm = re.search(rf"\bSTOP Cards[ \t]+({POS_NUM})", line, re.IGNORECASE)
                if sm and not stop_cards:
                    stop_cards = sm[1].split(".")[0]
                tm = re.search(r"\bTopic[ \t]{2,}([^\n]+)", line, re.IGNORECASE)
                if tm and not safety_topic:
                    safety_topic = re.split(r"[ \t]{4,}", tm[1].strip())[0][:120]
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
                    md, inc, azi, tvd, ns, ew, vs, dls = vals[:8]
                    result["surveys"].append(
                        {
                            "md_m": measured_depth(md, survey_unit),
                            "inc_deg": number(inc),
                            "azi_deg": number(azi),
                            "tvd_m": measured_depth(tvd, survey_unit),
                            "ns_m": measured_depth(ns, survey_unit),
                            "ew_m": measured_depth(ew, survey_unit),
                            "vsec_m": measured_depth(vs, survey_unit),
                            "dls_deg_per_30m": rounded(
                                Decimal(dls.replace(",", ""))
                                * (Decimal("0.9843") if dogleg_per_100ft else Decimal(1))
                            ),
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
                if not detail or (number(detail[1], precision=False) or 0) <= 0:
                    result["warnings"].append(
                        f"Page {page_no}: {a}–{b} has no positive printed duration; excluded from this day."
                    )
                    continue
                hours, phase, code, mark, d1, d2, narr = detail.groups()
                start, end = at(a), at(b)
                if end == start:
                    result["warnings"].append(f"Page {page_no}: {a}–{b} has identical clocks; verify it in the source.")
                    continue
                if end < start:
                    end += timedelta(days=1)
                if not narr.strip() and not (phase or code):
                    result["warnings"].append(f"Page {page_no}: {a}–{b} has no readable operation. Check the source.")
                block = {
                    "start": start,
                    "end": end,
                    "phase_raw": phase or "",
                    "code": code or "",
                    "mark": mark or "",
                    "depth_from_m": measured_depth(d1, unit),
                    "depth_to_m": measured_depth(d2, unit),
                    "tvd_from_m": None,
                    "tvd_to_m": None,
                    "bit_depth_m": None,
                    "mud_weight_ppg": None,
                    "narrative": clean(narr)[:5000],
                    "source_page": page_no,
                    "source": f"PDF page {page_no}",
                }
                result["blocks"].append(block)
                if abs((end - start).total_seconds() / 3600 - float(hours)) > 0.035:
                    result["warnings"].append(f"Page {page_no}: verify printed duration {hours} h against {a}–{b}.")
            elif (
                block is not None
                and line.strip()
                and line.startswith(" " * continuation_start)
                and not FOOTER.fullmatch(clean(line))
                and len(block["narrative"]) < 5000
            ):
                block["narrative"] = (block["narrative"] + " " + clean(line)).strip()[:5000]

    if not result["blocks"] and not result["operation_summary"]:
        raise ValueError(
            "No readable operation summary in this PDF. For a scan, provide a text-searchable PDF or enter activities manually."
        )

    # Populate hole section & casing fallbacks from Section 3.1.
    if open_hole_rows:
        sec_name, diam, _top_m, _base_m = open_hole_rows[-1]
        if diam is not None:
            result["hole_size_in"] = diam
        label = sec_name or (f'{diam.normalize()}" Hole' if diam is not None else "")
        result["hole_section_text"] = label[:120]
    if casing_rows and result["last_casing_depth_m"] is None:
        deepest_csg = max(
            (r for r in casing_rows if r[0] is not None and r[0] > 0 and r[1] is not None and r[1] > 0),
            key=lambda r: r[1],
            default=(None, None),
        )
        if deepest_csg[1] is not None:
            result["last_casing_size_in"] = deepest_csg[0]
            result["last_casing_depth_m"] = deepest_csg[1]
    if result["last_casing_size_in"] is not None and result["last_casing_size_in"] <= 0:
        result["last_casing_size_in"] = None
        result["last_casing_depth_m"] = None

    # Populate BHA, HSE and POB summaries.
    bha_parts = []
    if bha_no:
        bha_parts.append(f"BHA #{bha_no}")
    if bit_info:
        bha_parts.append(bit_info)
    if bha_len_m is not None:
        bha_parts.append(f"Length {bha_len_m} m")
    if bha_min_id is not None:
        bha_parts.append(f'Min ID {bha_min_id}"')
    if bha_purpose:
        bha_parts.append(bha_purpose)
    result["bha_summary"] = " · ".join(bha_parts)[:500]

    hse_parts = []
    if dslti_days:
        hse_parts.append(f"DSLTI: {dslti_days} days")
    if dslta_days and dslta_days != dslti_days:
        hse_parts.append(f"DSLTA: {dslta_days} days")
    if stop_cards:
        hse_parts.append(f"STOP cards: {stop_cards}")
    if safety_topic:
        hse_parts.append(f"Safety topic: {safety_topic}")
    if pob_count is not None:
        result["pob_count"] = pob_count
        hse_parts.append(f"POB: {pob_count}")
    result["hse_summary"] = " · ".join(hse_parts)

    # Resolve closing & opening MD accurately.
    block_end_mds = [b["depth_to_m"] for b in result["blocks"] if b.get("depth_to_m") is not None]
    block_start_mds = [b["depth_from_m"] for b in result["blocks"] if b.get("depth_from_m") is not None]
    if result["depth_end_m"] is None and block_end_mds:
        result["depth_end_m"] = max(block_end_mds)
    elif result["depth_end_m"] is None and open_hole_rows:
        hole_bases = [r[3] for r in open_hole_rows if r[3] is not None and r[3] > 0]
        if hole_bases:
            result["depth_end_m"] = max(hole_bases)
            result["warnings"].append(
                f"Header MD was blank; pre-filled closing MD {result['depth_end_m']} m from Section 3.1 Hole Sections."
            )

    if result["depth_end_m"] is not None and result["progress_m"] is not None:
        result["depth_start_m"] = result["depth_end_m"] - result["progress_m"]
    elif block_start_mds:
        result["depth_start_m"] = block_start_mds[0]
    elif (
        mud_md_check is not None
        and result["depth_end_m"] is not None
        and Decimal("50") < mud_md_check <= result["depth_end_m"]
    ):
        result["depth_start_m"] = mud_md_check
    elif result["depth_end_m"] is not None and not block_end_mds:
        # Stationary casing/cementing/completion day at constant wellbore TD.
        result["depth_start_m"] = result["depth_end_m"]

    if (
        result["progress_m"] is None
        and result["depth_start_m"] is not None
        and result["depth_end_m"] is not None
        and result["depth_end_m"] >= result["depth_start_m"]
    ):
        result["progress_m"] = rounded(result["depth_end_m"] - result["depth_start_m"])

    # Build MD->TVD profile from survey table + narrative MWD survey pairs + header TVD.
    profile: list[tuple[Decimal, Decimal, Decimal | None]] = []
    for sv in result["surveys"]:
        if sv.get("md_m") is not None and sv.get("tvd_m") is not None and sv["tvd_m"] <= sv["md_m"] + Decimal("1.0"):
            profile.append((sv["md_m"], min(sv["tvd_m"], sv["md_m"]), sv.get("inc_deg")))

    narrative_blob = "\n".join(
        [result["current_status"], result["operation_summary"], *(b["narrative"] for b in result["blocks"])]
    )
    narr_pairs = extract_narrative_md_tvd_pairs(narrative_blob, unit)
    for n_md, n_tvd in narr_pairs:
        profile.append((n_md, n_tvd, None))

    if result["depth_end_m"] is not None and result["tvd_m"] is not None and result["tvd_source"] == "header":
        if result["tvd_m"] <= result["depth_end_m"] + Decimal("1.0"):
            profile.append((result["depth_end_m"], min(result["tvd_m"], result["depth_end_m"]), None))

    # Pre-fill report TVD when header left TVD blank.
    if result["tvd_m"] is None:
        max_md = result["depth_end_m"]
        # Prefer explicit narrative/survey pairs, picking the deepest valid station.
        candidates: list[tuple[Decimal, Decimal, str]] = []
        for sv in result["surveys"]:
            if sv.get("md_m") is not None and sv.get("tvd_m") is not None and sv["tvd_m"] > 0:
                if max_md is None or sv["md_m"] <= max_md + Decimal("5"):
                    candidates.append((sv["md_m"], min(sv["tvd_m"], sv["md_m"]), "survey"))
        for n_md, n_tvd in narr_pairs:
            if max_md is None or n_md <= max_md + Decimal("5"):
                candidates.append((n_md, n_tvd, "narrative"))
        if candidates:
            best_md, best_tvd, src = max(candidates, key=lambda item: item[0])
            result["tvd_m"] = rounded(best_tvd)
            result["tvd_source"] = src
            label = "directional survey table" if src == "survey" else "activity narrative MWD survey"
            result["warnings"].append(
                f"Header TVD was blank; pre-filled TVD {result['tvd_m']} m from {label} at {best_md} m MD — confirm against closing depth."
            )
        else:
            singles = extract_single_tvds(narrative_blob, max_md)
            if singles:
                result["tvd_m"] = rounded(max(singles))
                result["tvd_source"] = "narrative"
                result["warnings"].append(
                    f"Header TVD was blank; pre-filled TVD {result['tvd_m']} m from narrative TVD reference — verify before submitting."
                )

    # Pre-fill opening TVD and per-block TVD, bit depth, and mud weight.
    if result["depth_start_m"] is not None:
        result["tvd_start_m"] = interpolate_tvd(result["depth_start_m"], profile)
        if (
            result["tvd_start_m"] is None
            and result["depth_end_m"] is not None
            and result["tvd_m"] is not None
            and result["depth_start_m"] == result["depth_end_m"]
            and result["tvd_source"] == "header"
        ):
            result["tvd_start_m"] = result["tvd_m"]

    last_bit: Decimal | None = extract_bit_depth(result["current_status"])
    for blk in result["blocks"]:
        narr = blk.get("narrative") or ""
        # Per-block bit depth from tripping/cleanout narrative (never treated as drilled footage).
        b_bit = extract_bit_depth(narr)
        if b_bit is not None:
            blk["bit_depth_m"] = b_bit
            if last_bit is None:
                last_bit = b_bit
        elif blk.get("depth_to_m") is not None and blk.get("depth_from_m") is not None and blk["depth_to_m"] > blk["depth_from_m"]:
            blk["bit_depth_m"] = blk["depth_to_m"]

        # Per-block mud/brine weight (explicit narrative ppg or report Section 4.1 density).
        mw_m = _MW_NARR_RE.search(narr)
        if mw_m:
            mw_v = number(mw_m[1])
            if mw_v is not None and Decimal("6") <= mw_v <= Decimal("23"):
                blk["mud_weight_ppg"] = mw_v
        if blk["mud_weight_ppg"] is None and result["mud_weight_ppg"] is not None:
            blk["mud_weight_ppg"] = result["mud_weight_ppg"]

        # Per-block TVD from profile or explicit narrative MD/TVD pair.
        if blk.get("depth_from_m") is not None:
            blk["tvd_from_m"] = interpolate_tvd(blk["depth_from_m"], profile)
        if blk.get("depth_to_m") is not None:
            blk["tvd_to_m"] = interpolate_tvd(blk["depth_to_m"], profile)
        if blk["tvd_to_m"] is None:
            blk_pairs = extract_narrative_md_tvd_pairs(narr, unit)
            if blk_pairs:
                blk["tvd_to_m"] = rounded(blk_pairs[-1][1])
                if len(blk_pairs) >= 2 and blk["tvd_from_m"] is None:
                    blk["tvd_from_m"] = rounded(blk_pairs[0][1])

    if last_bit is not None:
        result["bit_depth_m"] = last_bit
    elif block_end_mds and result["progress_m"] and result["progress_m"] > 0:
        result["bit_depth_m"] = result["depth_end_m"]

    return result
