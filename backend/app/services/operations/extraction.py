"""Extraction engine — PDF and Excel parsing with classification."""

import hashlib
import io
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.units import depth_to_meters
from app.domain.operations.classify import classify_block
from app.domain.operations.durations import resolve_period
from app.domain.operations.normalise import parse_date_flexible, parse_depth
from app.models import User
from app.models.operations import OpsActivityBlock, OpsDailyReport, OpsDocument, OpsExtractionJob
from app.models.rig_well import Rig, Well
from app.services.audit import record as audit_record

# Lazy imports for optional libs
try:
    import pypdf  # type: ignore
    HAS_PYPDF = True
except Exception:
    HAS_PYPDF = False

try:
    import openpyxl  # type: ignore
    HAS_OPENPYL = True
except Exception:
    HAS_OPENPYL = False


def _well_rig_lookup(db: Session, organization_id: str):
    rigs = db.scalars(select(Rig).where(Rig.organization_id == organization_id, Rig.is_deleted.is_(False))).all()
    wells = db.scalars(select(Well).where(Well.organization_id == organization_id, Well.is_deleted.is_(False))).all()
    rig_by_code = {r.rig_code.lower().replace(" ", "").replace("/", "").replace("-", ""): r for r in rigs}
    rig_by_name = {r.rig_name.lower(): r for r in rigs}
    well_by_code = {w.well_code.lower().replace(" ", "").replace("-", ""): w for w in wells}
    well_by_name = {w.well_name.lower(): w for w in wells}
    return rigs, wells, rig_by_code, rig_by_name, well_by_code, well_by_name


def _normalize_name_for_match(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def resolve_identity(db: Session, organization_id: str, text_blob: str, file_name: str):
    rigs, wells, rig_by_code, rig_by_name, well_by_code, well_by_name = _well_rig_lookup(db, organization_id)
    blob_norm = _normalize_name_for_match(text_blob + " " + file_name)
    well_match = None
    rig_match = None
    well_conf = 0.0
    rig_conf = 0.0
    for key, well in well_by_code.items():
        nk = _normalize_name_for_match(key)
        if nk and nk in blob_norm:
            well_match = well
            well_conf = 0.85
            break
    if not well_match:
        for key, well in well_by_name.items():
            nk = _normalize_name_for_match(key)
            if len(nk) > 4 and nk in blob_norm:
                well_match = well
                well_conf = 0.65
                break
    for key, rig in rig_by_code.items():
        nk = _normalize_name_for_match(key)
        if nk and len(nk) > 2 and nk in blob_norm:
            rig_match = rig
            rig_conf = 0.75
            break
    return well_match, well_conf, rig_match, rig_conf


def extract_pdf_text(file_bytes: bytes) -> str:
    if not HAS_PYPDF:
        return ""
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(parts)
    except Exception as ex:
        return f""


def parse_openwells_pdf(file_bytes: bytes, text_blob: str) -> dict[str, Any]:
    """Heuristic parser for OpenWells DDR/DCR PDFs."""
    # Extract header fields via regex
    report_no = ""
    m = re.search(r"report\s*no\.?\s*[:\-]?\s*([A-Za-z0-9\-\s/]+)", text_blob, re.I)
    if m:
        report_no = m.group(1).strip().split("\n")[0][:50]
    report_date = None
    # Look for dates like 16-11-2026, 16/11/2026, 16.11.2026
    for pat in [r"(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4})", r"(\d{2,4}[-/\.]\d{1,2}[-/\.]\d{1,2})"]:
        m = re.search(pat, text_blob)
        if m:
            report_date = parse_date_flexible(m.group(1))
            if report_date:
                break
    # Event / scope
    scope = "drilling"
    if re.search(r"COMPLETION", text_blob, re.I):
        scope = "completion"
    # Depth: MD, TVD
    md_val, md_unit = None, "m"
    m = re.search(r"MD\s*[:\-]?\s*([\d,\.]+)\s*(m|ft|')", text_blob, re.I)
    if m:
        try:
            md_val = Decimal(m.group(1).replace(",", ""))
            md_unit = "ft" if "ft" in m.group(2).lower() or "'" in m.group(2) else "m"
        except Exception:
            pass
    tvd_val = None
    m = re.search(r"TVD\s*[:\-]?\s*([\d,\.]+)\s*(m|ft|')", text_blob, re.I)
    if m:
        try:
            tvd_val = Decimal(m.group(1).replace(",", ""))
        except Exception:
            pass

    # Operation summary blocks — look for time patterns like 0:00 1:30 2:00
    blocks = []
    # Find Operation Summary section
    op_start = re.search(r"Operation Summary", text_blob, re.I)
    search_text = text_blob[op_start.start():] if op_start else text_blob
    # Extract rows with time pattern
    # Pattern: HH:MM HH:MM duration Phase Code Sub/Class
    row_pattern = re.compile(
        r"(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})\s+(\d{1,2}\.?\d*)\s+([A-Z0-9]{3,10})\s+(\d{1,2})\s+([PUD ]?)\s*(.+?)(?=\n\d{1,2}:\d{2}|\Z)",
        re.S | re.I,
    )
    # Fallback simpler: lines starting with time
    lines = text_blob.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = re.match(r"(\d{1,2}:\d{2})\s+(\d{1,2}:\d{2})\s+(\d+\.?\d*)\s+(\S+)\s+(\d+)\s+([PUD])?\s*(.*)", line, re.I)
        if m:
            from_s, to_s, dur_s, phase_raw, code_s, sub_c, narr = m.groups()
            try:
                dur_min = int(round(float(dur_s) * 60))
            except Exception:
                dur_min = 60
            blocks.append({
                "from_str": from_s,
                "to_str": to_s,
                "dur_hr": dur_s,
                "phase_raw": phase_raw or "",
                "code": code_s or "",
                "sub_class": (sub_c or "").strip(),
                "narrative": (narr or "").strip()[:1000],
                "duration_minutes": dur_min,
            })

    # If regex table above found more structured rows, prefer those
    if not blocks:
        for m in row_pattern.finditer(search_text):
            from_s, to_s, dur_s, phase_raw, code_s, sub_c, narr = m.groups()
            try:
                dur_min = int(round(float(dur_s) * 60))
            except Exception:
                dur_min = 60
            blocks.append({
                "from_str": from_s,
                "to_str": to_s,
                "dur_hr": dur_s,
                "phase_raw": phase_raw or "",
                "code": code_s or "",
                "sub_class": (sub_c or "").strip(),
                "narrative": (narr or "").strip()[:1000],
                "duration_minutes": dur_min,
            })

    # Cap blocks
    blocks = blocks[:30]
    # If still no blocks, create a placeholder from summary
    if not blocks:
        summary = ""
        if op_start:
            summary = text_blob[op_start.start():op_start.start()+2000]
        blocks.append({
            "from_str": "00:00",
            "to_str": "12:00",
            "phase_raw": "",
            "code": "",
            "sub_class": "P",
            "narrative": summary[:500] or "Operations as per report",
            "duration_minutes": 720,
        })
        blocks.append({
            "from_str": "12:00",
            "to_str": "24:00",
            "phase_raw": "",
            "code": "",
            "sub_class": "P",
            "narrative": "Continued operations",
            "duration_minutes": 720,
        })

    return {
        "report_no_text": report_no[:50],
        "report_date": report_date,
        "scope": scope,
        "md_val": md_val,
        "md_unit": md_unit,
        "tvd_val": tvd_val,
        "blocks": blocks,
        "operation_summary": (text_blob[op_start.start():op_start.start()+3000] if op_start else text_blob[:3000]),
        "report_type": "DCR" if scope == "completion" else "DDR",
    }


def parse_mud_excel(file_bytes: bytes) -> dict[str, Any]:
    if not HAS_OPENPYL:
        return {"blocks": [], "report_type": "DMR"}
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        texts = []
        for ws in wb.worksheets:
            if ws.sheet_state == "hidden":
                continue
            for row in ws.iter_rows(values_only=True):
                texts.append(" ".join(str(c) if c is not None else "" for c in row))
        blob = "\n".join(texts)
        return {
            "report_no_text": "",
            "report_date": None,
            "scope": "drilling",
            "md_val": None,
            "md_unit": "m",
            "tvd_val": None,
            "blocks": [{"from_str": "00:00", "to_str": "24:00", "phase_raw": "", "code": "", "sub_class": "P", "narrative": blob[:1000], "duration_minutes": 1440}],
            "operation_summary": blob[:3000],
            "report_type": "DMR",
        }
    except Exception:
        return {"blocks": [], "report_type": "DMR"}


def parse_ops_summary_excel(file_bytes: bytes) -> dict[str, Any]:
    if not HAS_OPENPYL:
        return {"blocks": [], "report_type": "DDR"}
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        # Look for Summary sheet
        ws = None
        for name in ["Summary", "SUMMARY", "summary", "PT-NPT DATASHEET"]:
            if name in wb.sheetnames:
                ws = wb[name]
                break
        if ws is None:
            ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return {"blocks": [], "report_type": "DDR"}
        header = None
        header_idx = 0
        for idx, row in enumerate(rows[:20]):
            if row and any(isinstance(c, str) and "start" in c.lower() for c in row if c):
                header = row
                header_idx = idx
                break
            if row and any(isinstance(c, str) and "block" in c.lower() for c in row if c):
                header = row
                header_idx = idx
                break
        if header is None:
            header = rows[0]
            header_idx = 0
        # Build col index map
        col_map = {}
        for i, h in enumerate(header):
            if h and isinstance(h, str):
                col_map[h.strip().lower()] = i
        blocks = []
        for row in rows[header_idx+1:]:
            if not row or all(c is None or str(c).strip() == "" for c in row):
                continue
            # Try to find start/end/phase/code columns
            def _cell(key):
                idx = col_map.get(key.lower())
                if idx is None:
                    return None
                return row[idx] if idx < len(row) else None
            narrative = str(_cell("operation") or _cell("activity") or _cell("details of activities") or _cell("details") or row[7] if len(row) > 7 else "" )
            dur_val = _cell("dur") or _cell("duration") or _cell("hrs") or 0
            try:
                dur_min = int(round(float(str(dur_val).replace(",", "")) * 60)) if dur_val else 60
            except Exception:
                dur_min = 60
            if len(blocks) > 200:
                break
            blocks.append({
                "from_str": str(_cell("start time") or _cell("from") or "00:00"),
                "to_str": str(_cell("end time") or _cell("to") or "01:00"),
                "phase_raw": str(_cell("phase") or ""),
                "code": str(_cell("code") or ""),
                "sub_class": str(_cell("plan") or _cell("p/u/npt") or "P"),
                "narrative": narrative[:1000],
                "duration_minutes": dur_min,
            })
        if not blocks:
            return {"blocks": [], "report_type": "DDR"}
        return {
            "report_no_text": "",
            "report_date": None,
            "scope": "drilling",
            "md_val": None,
            "md_unit": "m",
            "tvd_val": None,
            "blocks": blocks,
            "operation_summary": "Imported from operations summary workbook",
            "report_type": "DDR",
        }
    except Exception as ex:
        return {"blocks": [], "report_type": "DDR", "error": str(ex)}


def _build_block_times(blocks_raw: list[dict], report_date: date) -> list[dict]:
    """Assign real datetimes to blocks based on report_date."""
    result = []
    base = datetime.combine(report_date, time(0, 0), tzinfo=timezone.utc)
    cursor = base
    for idx, b in enumerate(blocks_raw):
        dur = int(b.get("duration_minutes", 60))
        if dur <= 0:
            dur = 60
        started_at = cursor
        ended_at = cursor + timedelta(minutes=dur)
        result.append({**b, "started_at": started_at, "ended_at": ended_at, "sequence_no": idx + 1})
        cursor = ended_at
    return result


def run_extraction(
    db: Session,
    organization_id: str,
    document: OpsDocument,
    user: User,
    request=None,
) -> OpsExtractionJob:
    job = OpsExtractionJob(
        organization_id=organization_id,
        document_id=document.id,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()

    document.status = "extracting"
    document.extraction_job_id = job.id
    db.flush()

    try:
        file_bytes = document.content or b""
        lower_name = document.file_name.lower()
        parsed: dict[str, Any] = {}

        if lower_name.endswith(".pdf"):
            text_blob = extract_pdf_text(file_bytes)
            if len(text_blob.strip()) < 50:
                # fallback: treat as generic
                text_blob = file_bytes.decode(errors="ignore")[:5000] if file_bytes else ""
            parsed = parse_openwells_pdf(file_bytes, text_blob)
        elif lower_name.endswith((".xlsx", ".xlsm", ".xls")):
            # Check if DMR
            if "dmr" in lower_name or "mud" in lower_name:
                parsed = parse_mud_excel(file_bytes)
            else:
                parsed = parse_ops_summary_excel(file_bytes)
                if not parsed.get("blocks"):
                    parsed = parse_mud_excel(file_bytes)
        elif lower_name.endswith(".csv"):
            try:
                txt = file_bytes.decode(errors="ignore")
                parsed = {"blocks": [{"from_str": "00:00", "to_str": "24:00", "phase_raw": "", "code": "", "sub_class": "P", "narrative": txt[:1000], "duration_minutes": 1440}], "report_type": "DDR", "report_no_text": "", "report_date": None, "scope": "drilling", "operation_summary": txt[:3000]}
            except Exception:
                parsed = {"blocks": [], "report_type": "DDR"}
        else:
            text_blob = file_bytes.decode(errors="ignore")[:5000] if file_bytes else ""
            parsed = parse_openwells_pdf(file_bytes, text_blob)

        # Resolve identity
        text_for_identity = parsed.get("operation_summary", "") + " " + document.file_name
        well_match, well_conf, rig_match, rig_conf = resolve_identity(db, organization_id, text_for_identity, document.file_name)

        # Determine report date fallback
        report_date = parsed.get("report_date") or document.document_date or date.today()
        if isinstance(report_date, str):
            report_date = parse_date_flexible(report_date) or date.today()

        report_type = parsed.get("report_type") or document.document_type or "DDR"
        scope = parsed.get("scope") or document.scope or "drilling"
        blocks_raw = parsed.get("blocks") or []
        blocks_with_times = _build_block_times(blocks_raw, report_date)

        # Classify each block
        enriched_blocks = []
        for b in blocks_with_times:
            cls, alloc, conf, reasons = classify_block(b.get("sub_class", ""), b.get("phase_raw", ""), b.get("code", ""), b.get("narrative", ""))
            is_productive = cls != "NPT"
            enriched_blocks.append({**b, "classification": cls, "allocation": alloc, "confidence": conf, "reasons": reasons, "is_productive": is_productive})

        # Store or update report? Create draft report linked to document
        # Check if report exists for well/scope/date
        well_id = (well_match.id if well_match else document.well_id)
        rig_id = (rig_match.id if rig_match else document.rig_id)
        # If no well resolved, keep document's well_id if any
        if not well_id:
            raise ValueError("Well identity could not be resolved — please select well manually")

        existing_report = db.scalar(select(OpsDailyReport).where(OpsDailyReport.organization_id == organization_id, OpsDailyReport.well_id == well_id, OpsDailyReport.scope == scope, OpsDailyReport.report_date == report_date, OpsDailyReport.is_deleted.is_(False)))
        if existing_report:
            # Update draft only
            report = existing_report
            report.report_no_text = parsed.get("report_no_text") or report.report_no_text
            report.rig_id = rig_id or report.rig_id
            report.operation_summary = parsed.get("operation_summary", "")[:10000]
            report.source_document_id = document.id
            report.extraction_status = "needs_review"
            report.current_extraction_id = job.id
            # Update rig snapshots
            if rig_match:
                report.rig_code_snapshot = rig_match.rig_code
                report.rig_name_snapshot = rig_match.rig_name
            # Delete old blocks
            db.execute(select(OpsActivityBlock).where(OpsActivityBlock.report_id == report.id).delete() if False else select(OpsActivityBlock).where(OpsActivityBlock.report_id == report.id))  # no-op for compat
            old_blocks = db.scalars(select(OpsActivityBlock).where(OpsActivityBlock.report_id == report.id)).all()
            for ob in old_blocks:
                db.delete(ob)
            db.flush()
        else:
            # Create new report
            period_start, period_end = resolve_period(report_date, 0)
            rig_snap_code = rig_match.rig_code if rig_match else (document.rig_code_snapshot or "")
            rig_snap_name = rig_match.rig_name if rig_match else (document.rig_name_snapshot or "")
            well_obj = db.get(Well, well_id) if well_id else None
            report = OpsDailyReport(
                organization_id=organization_id,
                well_id=well_id,
                rig_id=rig_id,
                rig_code_snapshot=rig_snap_code,
                rig_name_snapshot=rig_snap_name,
                well_code_snapshot=well_obj.well_code if well_obj else document.well_code_snapshot,
                well_name_snapshot=well_obj.well_name if well_obj else document.well_name_snapshot,
                scope=scope,
                report_type=report_type,
                report_date=report_date,
                report_no_text=parsed.get("report_no_text") or document.report_no_text or "",
                period_start_at=period_start,
                period_end_at=period_end,
                period_minutes=1440,
                depth_start_m=depth_to_meters(parsed.get("md_val"), parsed.get("md_unit", "m")) if parsed.get("md_val") else None,
                depth_end_m=depth_to_meters(parsed.get("md_val"), parsed.get("md_unit", "m")) if parsed.get("md_val") else None,
                depth_unit=parsed.get("md_unit", "m"),
                operation_summary=parsed.get("operation_summary", "")[:10000],
                source_document_id=document.id,
                status="draft",
                extraction_status="needs_review",
                current_extraction_id=job.id,
                created_by=user.email or "",
                updated_by=user.email or "",
            )
            # Try to compute day_number from well spud if available
            if well_obj:
                # Use drilling spud logic
                try:
                    from app.models.rig_well import Well as WellModel
                    # well.spud is stored as plan? Check Well model for spud
                    pass
                except Exception:
                    pass
            db.add(report)
            db.flush()

        # Create blocks
        for b in enriched_blocks:
            # Depth handling
            df_m = None
            dt_m = None
            if b.get("depth_from"):
                try:
                    df_m = depth_to_meters(Decimal(str(b["depth_from"])), b.get("depth_unit", "m"))
                except Exception:
                    pass
            if b.get("depth_to"):
                try:
                    dt_m = depth_to_meters(Decimal(str(b["depth_to"])), b.get("depth_unit", "m"))
                except Exception:
                    pass
            footage = None
            if df_m is not None and dt_m is not None and dt_m > df_m:
                footage = dt_m - df_m
            rop = None
            if footage is not None and b.get("rotating_hours"):
                try:
                    rh = Decimal(str(b["rotating_hours"]))
                    if rh > 0:
                        rop = footage / rh
                except Exception:
                    pass
            block = OpsActivityBlock(
                organization_id=organization_id,
                report_id=report.id,
                sequence_no=b["sequence_no"],
                started_at=b["started_at"],
                ended_at=b["ended_at"],
                duration_minutes=b["duration_minutes"],
                phase_raw=b.get("phase_raw", "")[:20],
                classification=b.get("classification", "Planned"),
                allocation=b.get("allocation", "PT"),
                is_productive=b.get("is_productive", True),
                classification_source="keyword",
                depth_from_m=df_m,
                depth_to_m=dt_m,
                depth_unit=b.get("depth_unit", "m"),
                footage_m=footage,
                rop_m_per_hr=rop,
                narrative=b.get("narrative", "")[:5000],
                confidence=Decimal(str(b.get("confidence", 0.5))),
                review_state="suggested",
                source_page=0,
            )
            db.add(block)

        job.status = "completed"
        job.report_type = report_type
        job.confidence = Decimal(str(sum(b["confidence"] for b in enriched_blocks) / len(enriched_blocks) if enriched_blocks else 0)).quantize(Decimal("0.01"))
        job.findings = json.dumps([{"block": b["sequence_no"], "reasons": b["reasons"]} for b in enriched_blocks])
        job.payload_summary = json.dumps({"blocks": len(enriched_blocks), "report_type": report_type, "scope": scope, "well_conf": well_conf})
        job.completed_at = datetime.now(timezone.utc)

        document.status = "extracted"
        document.document_date = report_date

        db.flush()
        audit_record(db, organization_id=organization_id, actor=user, action="extract", entity_type="ops_document", entity_id=document.id, entity_label=document.file_name, summary=f"Extracted {len(enriched_blocks)} blocks from {document.file_name}", request=request)
        db.commit()
        db.refresh(job)
        return job

    except Exception as ex:
        job.status = "failed"
        job.error_message = str(ex)[:2000]
        job.completed_at = datetime.now(timezone.utc)
        document.status = "extraction_failed"
        db.commit()
        db.refresh(job)
        # Do not raise — extraction failure is stored
        return job
