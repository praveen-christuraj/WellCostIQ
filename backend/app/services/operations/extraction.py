"""Explicit report intake. File parsing and identity checks precede one atomic draft write."""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.domain.operations.classify import suggest
from app.domain.operations.default_codes import describe_code, find_code
from app.domain.operations.durations import resolve_period, utc
from app.domain.operations.taxonomy import code_key
from app.models.master_data import Activity, HoleSection, Phase
from app.models.operations import (
    OpsActivityBlock,
    OpsAgency,
    OpsCause,
    OpsDailyReport,
    OpsExtractionJob,
    OpsMarkRule,
    OpsOperation,
    OpsPlanItem,
    OpsPlanVersion,
    OpsSubPhase,
    OpsSurvey,
)
from app.models.rig_well import Well
from app.services.audit import record
from app.services.operations import correlations as correlation_svc
from app.services.operations import documents, scope, settings
from app.services.operations import reports as reports_svc
from app.services.operations.openwells import parse_pdf
from app.services.operations.plans import active_plan
from app.services.operations.workbooks import daily_workbook


def extract(db, org, document_id, requested_day, user, request, target_id=None, *, use_ai: bool = False):
    doc = documents.get_document(db, org, document_id)
    well, rig = scope.resolve(db, org, doc.well_id, doc.scope, doc.rig_id)
    cfg = settings.get_settings(db, org)
    target = None
    if target_id:
        target = db.scalar(
            select(OpsDailyReport)
            .where(
                OpsDailyReport.id == target_id,
                OpsDailyReport.organization_id == org,
                OpsDailyReport.is_deleted.is_(False),
            )
            .with_for_update()
        )
        if not target:
            raise HTTPException(404, "Report not found")
        if target.status != "draft" or target.well_id != well.id or target.scope != doc.scope:
            raise HTTPException(409, "Extract only into a draft in the same well and scope.")
        requested_day = target.report_date
    day = requested_day or doc.document_date
    try:
        if doc.file_name.lower().endswith(".pdf"):
            parsed = parse_pdf(doc.content, day)
        elif doc.file_name.lower().endswith((".xlsx", ".xlsm", ".xls")):
            parsed = daily_workbook(doc.content, day, cfg.day_boundary_hour)
        else:
            raise ValueError(
                "Time-log extraction supports searchable PDF and .xlsx workbooks. Use register Import for CSV."
            )
    except Exception as exc:
        detail = (
            str(exc)
            if isinstance(exc, ValueError)
            else "File could not be read. Provide a searchable PDF or a valid .xlsx workbook."
        )
        raise HTTPException(422, detail) from exc
    day = parsed.get("report_date") or day
    if not day or (requested_day and requested_day != day):
        raise HTTPException(
            422, f"Report date in the file ({day}) does not match the selected day ({requested_day})."
        )
    event = parsed.get("event_code", "").upper()
    if ("COMPLETION" in event and doc.scope != "completion") or ("DRILLING" in event and doc.scope != "drilling"):
        raise HTTPException(422, f"The report event {event} does not match its {doc.scope} folder.")
    existing = db.scalar(
        select(OpsDailyReport).where(
            OpsDailyReport.organization_id == org,
            OpsDailyReport.well_id == well.id,
            OpsDailyReport.scope == doc.scope,
            OpsDailyReport.report_date == day,
        )
    )
    if existing:
        if existing.is_deleted:
            raise HTTPException(409, "This report is in Deleted entries. Restore it before extracting.")
        applied = db.scalar(
            select(OpsExtractionJob.id).where(
                OpsExtractionJob.organization_id == org,
                OpsExtractionJob.report_id == existing.id,
                OpsExtractionJob.document_id == doc.id,
                OpsExtractionJob.status == "completed",
            )
        )
        if applied:
            return existing
        if not target or existing.id != target.id:
            raise HTTPException(
                409,
                "A report already exists for this day. Open its draft to add a source without replacing engineer edits.",
            )
    start, end = resolve_period(day, cfg.day_boundary_hour, cfg.operating_timezone)
    report = target or OpsDailyReport(
        organization_id=org,
        well_id=well.id,
        rig_id=rig.id,
        well_code_snapshot=well.well_code,
        well_name_snapshot=well.well_name,
        rig_code_snapshot=rig.rig_code,
        rig_name_snapshot=rig.rig_name,
        scope=doc.scope,
        report_type=parsed.get("report_type")
        or (
            doc.document_type
            if doc.document_type in ("DDR", "DCR", "RMR")
            else ("DCR" if doc.scope == "completion" else "DDR")
        ),
        report_date=day,
        period_start_at=start,
        period_end_at=end,
        period_minutes=int((end - start).total_seconds() / 60),
        created_by=user.email,
        status="draft",
    )
    warnings = parsed["warnings"]
    if parsed.get("well_name"):
        warnings.append(f"Source well: {parsed['well_name']}. Verify against folder {well.well_name}.")

    # A folder is selected by the engineer, not inferred from a possibly misleading filename.
    # An exact match to another configured well is a conflict; unrecognised aliases need review.
    def ident(name):
        return re.sub(r"[^a-z0-9]", "", str(name).lower())

    names = {ident(parsed.get(k, "")) for k in ("well_name", "wellbore")} - {""}
    if names and not names.intersection((ident(well.well_name), ident(well.well_code))):
        for candidate in db.scalars(
            select(Well).where(Well.organization_id == org, Well.is_deleted.is_(False), Well.id != well.id)
        ):
            if names.intersection((ident(candidate.well_name), ident(candidate.well_code))):
                raise HTTPException(
                    422, "Source identifies a different workspace well. File it in the matching well folder."
                )
    if parsed.get("rig_name"):
        warnings.append(f"Source rig: {parsed['rig_name']}. Folder: {rig.rig_code}.")
    if (
        target
        and parsed["blocks"]
        and db.scalar(
            select(OpsActivityBlock.id)
            .where(OpsActivityBlock.report_id == target.id, OpsActivityBlock.is_deleted.is_(False))
            .limit(1)
        )
    ):
        raise HTTPException(409, "This draft already has a time log. Extraction will not overwrite it.")
    if target and target.report_type == "DMR" and parsed["blocks"]:
        target.report_type = (
            "RMR" if doc.document_type == "RMR" else ("DCR" if doc.scope == "completion" else "DDR")
        )
        warnings.append(
            "Time log added to a mud-report draft. Check the existing mud measurements and summary against this report."
        )
    if not parsed.get("report_no_text") and doc.report_no_text:
        parsed["report_no_text"] = doc.report_no_text
    if not parsed.get("day_number") and parsed.get("report_no_text") and str(parsed["report_no_text"]).isdigit():
        candidate_day = int(parsed["report_no_text"])
        if 1 <= candidate_day <= 9999:
            parsed["day_number"] = candidate_day
    for field, limit in [
        ("report_no_text", 50),
        ("customer", 200),
        ("project", 200),
        ("site", 200),
        ("datum", 100),
        ("supervisor", 200),
        ("engineer", 200),
        ("uwi", 100),
        ("block_text", 100),
        ("event_code", 50),
        ("tvd_source", 40),
        ("hole_section_text", 120),
        ("current_status", 500),
        ("mud_type", 100),
        ("bha_summary", 500),
    ]:
        if parsed.get(field):
            parsed[field] = str(parsed[field])[:limit]
    for field in (
        "report_no_text",
        "day_number",
        "customer",
        "project",
        "site",
        "datum",
        "supervisor",
        "engineer",
        "uwi",
        "block_text",
        "spud_date",
        "depth_start_m",
        "depth_end_m",
        "tvd_start_m",
        "tvd_m",
        "tvd_source",
        "bit_depth_m",
        "progress_m",
        "dfs_days",
        "est_days",
        "md_auth_m",
        "rotating_hours",
        "cum_rotating_hours",
        "last_casing_size_in",
        "last_casing_depth_m",
        "hole_section_text",
        "hole_size_in",
        "current_status",
        "mud_type",
        "mud_weight_ppg",
        "mud_viscosity_sec",
        "mud_pv_cp",
        "mud_yp_lbf",
        "bha_summary",
        "pob_count",
        "event_code",
        "operation_summary",
        "forward_plan",
        "hse_summary",
    ):
        if parsed.get(field) is not None and getattr(report, field) in ("", None):
            setattr(report, field, parsed[field])
    # Match workspace master-data HoleSection & Phase when not already selected.
    from app.models.master_data import HoleSection, Phase
    from app.models.vendor_master import Vendor
    from app.services.operations.openwells import interpolate_tvd

    if not report.hole_section_id and (report.hole_section_text or report.hole_size_in is not None):
        hs_rows = db.scalars(
            select(HoleSection).where(
                HoleSection.organization_id == org,
                HoleSection.is_deleted.is_(False),
            )
        ).all()
        hs_target = code_key(report.hole_section_text or "")
        size_token = str(report.hole_size_in.normalize()) if report.hole_size_in is not None else ""
        for hs in hs_rows:
            hs_name = str(getattr(hs, "section_name", "") or getattr(hs, "name", "") or "")
            hs_code = str(getattr(hs, "section_code", "") or getattr(hs, "code", "") or "")
            if (hs_target and hs_target in (code_key(hs_name), code_key(hs_code))) or (
                size_token and size_token in hs_name
            ):
                report.hole_section_id = hs.id
                break
    if not report.phase_id:
        ph_rows = db.scalars(
            select(Phase).where(Phase.organization_id == org, Phase.is_deleted.is_(False))
        ).all()
        want_phase = "completion" if doc.scope == "completion" else "drilling"
        for ph in ph_rows:
            ph_name = str(getattr(ph, "phase_name", "") or getattr(ph, "name", "") or "").lower()
            if want_phase in ph_name:
                report.phase_id = ph.id
                break

    # Cross-report directional profile: fill missing opening/closing TVD from well survey history.
    prior_profile = [
        (s.md_m, s.tvd_m, s.inc_deg)
        for s in db.scalars(
            select(OpsSurvey).where(
                OpsSurvey.organization_id == org,
                OpsSurvey.well_id == well.id,
                OpsSurvey.is_deleted.is_(False),
                OpsSurvey.md_m.is_not(None),
                OpsSurvey.tvd_m.is_not(None),
            )
        ).all()
        if s.md_m is not None and s.tvd_m is not None and s.tvd_m <= s.md_m + 1
    ]
    for sv in parsed.get("surveys", []):
        if sv.get("md_m") is not None and sv.get("tvd_m") is not None and sv["tvd_m"] <= sv["md_m"] + 1:
            prior_profile.append((sv["md_m"], sv["tvd_m"], sv.get("inc_deg")))
    if report.depth_end_m is not None and report.tvd_m is not None and report.tvd_source == "header":
        prior_profile.append((report.depth_end_m, report.tvd_m, None))
    if report.tvd_m is None and report.depth_end_m is not None and prior_profile:
        est_tvd = interpolate_tvd(report.depth_end_m, prior_profile)
        if est_tvd is not None:
            report.tvd_m = est_tvd
            report.tvd_source = "survey"
            warnings.append(
                f"Pre-filled closing TVD {est_tvd} m from well directional survey trajectory at {report.depth_end_m} m MD — verify before submitting."
            )
    if report.tvd_start_m is None and report.depth_start_m is not None and prior_profile:
        report.tvd_start_m = interpolate_tvd(report.depth_start_m, prior_profile)
    # Cross-report opening MD continuity when source left start MD blank.
    if report.depth_start_m is None and parsed.get("report_type") != "RMR":
        prev_end = db.scalar(
            select(OpsDailyReport.depth_end_m)
            .where(
                OpsDailyReport.organization_id == org,
                OpsDailyReport.well_id == well.id,
                OpsDailyReport.scope == doc.scope,
                OpsDailyReport.is_deleted.is_(False),
                OpsDailyReport.report_date < day,
                OpsDailyReport.depth_end_m.is_not(None),
            )
            .order_by(OpsDailyReport.report_date.desc())
            .limit(1)
        )
        if prev_end is not None and (report.depth_end_m is None or prev_end <= report.depth_end_m):
            report.depth_start_m = prev_end
            if report.depth_end_m is not None and report.progress_m is None:
                from app.core.precision import rounded

                report.progress_m = rounded(report.depth_end_m - prev_end)
            if report.tvd_start_m is None and prior_profile:
                report.tvd_start_m = interpolate_tvd(prev_end, prior_profile)
    if target and parsed.get("report_type") == "DMR" and target.operation_summary != parsed["operation_summary"]:
        report.remarks = ((report.remarks or "") + "\nMud report: " + parsed["operation_summary"]).strip()
    report.source_document_id = report.source_document_id or doc.id
    report.updated_by = user.email
    report.extraction_status = "needs_review"
    db.add(report)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A report was created for this period. Refresh the register.") from exc
    job = OpsExtractionJob(
        organization_id=org,
        report_id=report.id,
        document_id=doc.id,
        status="completed",
        report_type=report.report_type,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        findings="\n".join(warnings),
        payload_summary=f"{len(parsed['blocks'])} time blocks",
    )
    db.add(job)
    db.flush()
    report.current_extraction_id = job.id
    plan = (
        db.get(OpsPlanVersion, report.baseline_plan_id)
        if report.baseline_plan_id
        else active_plan(db, org, well.id, doc.scope)
    )
    if plan:
        report.baseline_plan_id = plan.id
    timeline = []
    hours = 0.0
    if plan:
        for item in db.scalars(
            select(OpsPlanItem)
            .where(OpsPlanItem.organization_id == org, OpsPlanItem.plan_version_id == plan.id)
            .order_by(OpsPlanItem.sequence_no)
        ):
            end_hour = hours + float(item.planned_hours)
            timeline.append((item, hours, end_hour))
            hours = end_hour

    def lookup(model, *keys):
        query = select(model).where(model.organization_id == org, model.is_deleted.is_(False))
        if hasattr(model, "is_active"):
            query = query.where(model.is_active.is_(True))
        rows = db.scalars(query)
        return {code_key(getattr(row, k)): row for row in rows for k in keys if getattr(row, k, None)}

    # Master Data: Activities carry their own type, which becomes the block's
    # Activity; Hole Sections and Phases are the shared registers the costing
    # module also reads (no FK, no dependency — simply the same definitions).
    activities = lookup(Activity, "activity_code", "activity_name")
    hole_sections = lookup(HoleSection, "section_code", "section_name")
    phases = lookup(Phase, "phase_code", "phase_name")
    # Code Library lists.
    operations = lookup(OpsOperation, "operation_code", "operation_name")
    causes = lookup(OpsCause, "cause_code", "cause_name")
    sub_phases = lookup(OpsSubPhase, "sub_phase_code", "sub_phase_name")
    agencies = lookup(OpsAgency, "agency_code", "agency_name")
    mark_rules = lookup(OpsMarkRule, "mark_code")

    def _master_by_label(rows, raw: str, *fields: str):
        """Pick a Master Data record from printed text, preferring the code."""
        key = code_key(raw)
        if not key:
            return None
        for field in fields:
            row = rows.get(key) if field == "code" else None
            if row is not None:
                return row
        for row in rows.values():
            for field in fields:
                if code_key(getattr(row, field, "") or "") == key:
                    return row
        return None
    # Workspace correlations and multi-criteria code links pre-select the
    # organisation's own codes. They never override a printed code and never approve the block.
    correlation_map = correlation_svc.correlation_map(db, org)
    code_links = correlation_svc.list_code_links(db, org, scope=doc.scope, active_only=True)
    active_vendors = db.scalars(
        select(Vendor).where(
            Vendor.organization_id == org,
            Vendor.is_deleted.is_(False),
            Vendor.status == "active",
        )
    ).all()
    vendor_lookup = {
        code_key(k): v
        for v in active_vendors
        for k in (v.vendor_code, v.vendor_name)
        if k
    }

    def _infer_printed_operation(raw_op: str, phase_raw: str, narr: str):
        """A printed operation token is interpreted by its own printed vocabulary."""
        if raw_op and (direct := operations.get(code_key(raw_op))):
            return direct
        pr = (phase_raw or "").upper()
        nl = (narr or "").lower()
        candidates: list[str] = []
        if "cement" in nl or "cmt" in nl:
            candidates.extend(("H", "Cementing job", "Cementing"))
        elif pr.startswith("CSG") or "run casing" in nl or "running casing" in nl or "r/u casing" in nl:
            candidates.extend(("G", "Casing job", "Casing"))
        elif pr.startswith("EVAL") or "wireline" in nl or "logging" in nl or "gyro" in nl:
            candidates.extend(("J", "Logging"))
        elif "bop" in nl or "wellhead" in nl or "xmas tree" in nl or "x-mas tree" in nl:
            candidates.extend(("C", "Wellhead and BOP", "BOP"))
        elif "slickline" in nl:
            candidates.extend(("R", "Slickline"))
        elif "coiled tubing" in nl:
            candidates.extend(("S", "Coiled tubing"))
        elif "gravel pack" in nl or "sand control" in nl:
            candidates.extend(("N", "Sand control"))
        elif "completion" in nl or pr.startswith("COMP"):
            candidates.extend(("K", "Well completion", "Completion"))
        elif "rig move" in nl or "skid" in nl:
            candidates.extend(("A", "MOVING (Rig up / Rig down)", "B", "Skidding"))
        elif pr.startswith("DRL") or "drilled" in nl or "drill ahead" in nl or "rotary" in nl or "slide" in nl:
            candidates.extend(("E", "Drilling"))
        return next((operations[code_key(c)] for c in candidates if code_key(c) in operations), None)

    def _infer_operation_code(raw_c: str, raw_m: str, narr: str, cls_name: str, alloc_name: str):
        """Guided Operations pre-selection for downtime; never an approval."""
        direct = operations.get(code_key(raw_c or raw_m))
        if direct:
            return direct
        if cls_name != "NPT" and alloc_name != "NPT":
            return None
        nl = (narr or "").lower()
        hints = (
            (("lost circulation", "mud loss", "losses"), "TP01"),
            (("stuck pipe", "pack off", "packed off", "differentially stuck"), "TP02"),
            (("kick", "well control", "influx"), "TP03"),
            (("drawwork",), "TR01"),
            (("mud pump", "liner wash", "standpipe"), "TR02"),
            (("engine", "generator", "power", "scr", "vfd"), "TR03"),
            (("top drive", "tds", "saver sub"), "TR04"),
            (("bop", "annular", "koomey"), "TR05"),
            (("mwd", "lwd", "motor", "bha", "washout", "twist off", "fish"), "TD01"),
            (("wireline", "gyro", "logging tool"), "TD04"),
            (("coiled tubing",), "TD05"),
            (("weather", "rain", "storm", "lightning"), "TW01"),
            (("wait on", "waiting on", "wom", "woe"), "TW02"),
        )
        for words, t_code in hints:
            if any(w in nl for w in words) and code_key(t_code) in operations:
                return operations[code_key(t_code)]
        return None

    zone = ZoneInfo(cfg.operating_timezone)
    unmapped_codes = set()
    new_blocks: list[OpsActivityBlock] = []
    for seq, b in enumerate(parsed["blocks"], 1):
        a = b["start"].replace(tzinfo=zone).astimezone(UTC)
        z = b["end"].replace(tzinfo=zone).astimezone(UTC)
        raw_activity = b["code"].strip()
        activity_family = "OpenWells code token" if b.get("source_page") else "Activity"
        code = activities.get(code_key(raw_activity))
        elapsed = (
            (a - utc(plan.planned_start_at)).total_seconds() / 3600 if plan and plan.planned_start_at else None
        )
        if elapsed is None and report.scope == "drilling" and report.dfs_days is not None:
            elapsed = float(report.dfs_days) * 24 - (end - a).total_seconds() / 3600
        raw_mark = b["mark"].strip()
        raw_cause = b.get("cause", "").strip()
        raw_operation = b.get("operation", "").strip()
        rule = mark_rules.get(code_key(raw_mark))
        classification = suggest(
            raw_mark,
            b["narrative"],
            code.default_allocation if code else None,
            timeline,
            elapsed,
            mark_rule=rule,
            printed_allocation=b.get("allocation", ""),
        )
        evidence = []
        if raw_activity:
            label = f"{raw_activity} — {code.activity_name}" if code else describe_code(raw_activity, activity_family)
            evidence.append(f"Activity: {label}")
            if not code and raw_activity.isdigit() and not find_code(raw_activity, activity_family):
                unmapped_codes.add(raw_activity)
        evidence.append(classification["classification_evidence"])
        if plan and (timeline or classification["classification_source"] == "timeline"):
            evidence.append(f"Programme: {plan.label[:70]} v{plan.version_no}")
        if b.get("allocation"):
            evidence.append(f"Summary allocation: {b['allocation']}")
        party = b.get("party", "").strip()
        matched_vendor = vendor_lookup.get(code_key(party)) if party else None
        if party:
            if matched_vendor:
                evidence.append(f"Source agency: {party[:80]} (matched vendor {matched_vendor.vendor_code})")
            else:
                evidence.append(f"Source agency: {party[:80]}; choose vendor")
        cause = causes.get(code_key(raw_cause))
        default_operation = find_code(raw_cause or raw_mark, "Trouble / NPT")
        operation = _infer_operation_code(
            raw_cause,
            raw_mark,
            b["narrative"],
            classification["classification"],
            classification["allocation"],
        ) or _infer_printed_operation(raw_operation, b.get("phase_raw", ""), b["narrative"])
        # A direct workspace code hit is stronger than a correlation. A
        # narrative guess is not: use it only if the rule leaves Operations empty.
        direct_operation = operations.get(code_key(raw_cause or raw_mark)) or operations.get(code_key(raw_operation))
        if direct_operation != operation:
            direct_operation = None  # Preserve the existing fallback order when no rule supplies Operations.
        printed_activity = activities.get(code_key(raw_activity))
        hole_section = (
            _master_by_label(hole_sections, b.get("hole_section_raw", ""), "code", "name")
            or (db.get(HoleSection, report.hole_section_id) if report.hole_section_id else None)
        )
        phase = (
            _master_by_label(phases, b.get("phase_raw", ""), "code", "name")
            or (db.get(Phase, report.phase_id) if report.phase_id else None)
        )
        sub_phase = sub_phases.get(code_key(b.get("phase_raw", "")))
        responsible_agency = agencies.get(code_key(party)) if party else None
        classification["classification_evidence"] = " · ".join(evidence)[:500]

        d_from = b.get("depth_from_m")
        d_to = b.get("depth_to_m")
        tvd_from = b.get("tvd_from_m")
        tvd_to = b.get("tvd_to_m")
        if tvd_from is None and d_from is not None and prior_profile:
            tvd_from = interpolate_tvd(d_from, prior_profile)
        if tvd_to is None and d_to is not None and prior_profile:
            tvd_to = interpolate_tvd(d_to, prior_profile)
        footage = d_to - d_from if d_from is not None and d_to is not None and d_to >= d_from else None
        rot_b = b.get("rotating_hours")
        from app.domain.operations.metrics import compute_rop

        rop_b = None if doc.scope == "completion" else compute_rop(footage, rot_b)
        reason_txt = str(b.get("reason") or "").strip()[:500]
        if (
            not reason_txt
            and (classification["classification"] in ("NPT", "UPA") or classification["allocation"] in ("NPT", "UPA"))
            and b.get("narrative")
        ):
            first_sentence = re.split(r"(?<=[.;])\s+", b["narrative"].strip(), maxsplit=1)[0]
            reason_txt = first_sentence[:240]

        block = OpsActivityBlock(
            organization_id=org,
            report_id=report.id,
            sequence_no=seq,
            started_at=a,
            ended_at=z,
            duration_minutes=round((z - a).total_seconds() / 60),
            phase_raw=b["phase_raw"][:20],
            source_activity_code=raw_activity[:100],
            source_operation_code=raw_operation[:100],
            source_cause_code=raw_cause[:50],
            source_mark=raw_mark[:30],
            activity_id=printed_activity.id if printed_activity else None,
            operation_id=direct_operation.id if direct_operation else None,
            operation_snapshot=direct_operation.operation_code if direct_operation else "",
            cause_code=cause.cause_code if cause else raw_cause[:50],
            hole_section_id=hole_section.id if hole_section else None,
            phase_id=phase.id if phase else None,
            sub_phase_id=sub_phase.id if sub_phase else None,
            responsible_agency_id=responsible_agency.id if responsible_agency else None,
            vendor_id=matched_vendor.id if matched_vendor else None,
            responsible_party=matched_vendor.vendor_name if matched_vendor else (party[:200] if party else ""),
            reason=reason_txt,
            bit_depth_m=b.get("bit_depth_m"),
            mud_weight_ppg=b.get("mud_weight_ppg") if b.get("mud_weight_ppg") is not None else report.mud_weight_ppg,
            rotating_hours=rot_b,
            footage_m=footage,
            rop_m_per_hr=rop_b,
            depth_from_m=d_from,
            depth_to_m=d_to,
            tvd_from_m=tvd_from,
            tvd_to_m=tvd_to,
            source_page=b.get("source_page", 0),
            source_bbox=b["source"],
            narrative=b["narrative"],
            review_state="suggested",
            **classification,
        )
        # Workspace correlations fill only what the source left empty. The
        # evidence names the correlation so the engineer can tell a pre-selection
        # from a printed code, and the block stays a suggestion.
        correlation_tokens = {
            "operation": (raw_operation, raw_cause, raw_mark),
            "cause": (raw_cause, raw_mark),
            "sub-phase": (b.get("phase_raw", ""),),
            "responsible-party": (party,),
            "agency": (party,),
        }
        # OpenWells PDFs put the operation number in the Code column, which
        # the parser preserves as source_activity_code. Never interpret an
        # identically numbered workbook Activity as an OpenWells operation.
        if b.get("source_page") and raw_activity:
            pdf_code = code_key(raw_activity)  # e.g. [2] or (02) is printed code 02
            if pdf_code.isdigit():
                pdf_code = pdf_code.zfill(2)
            pdf_rule = correlation_map.get(("operation", pdf_code))
            if pdf_rule and pdf_rule.source_family == "OpenWells operation code":
                correlation_tokens["operation"] += (pdf_code,)
        correlation_evidence = correlation_svc.apply_to_block(
            block,
            correlation_map,
            db=db,
            report_scope=doc.scope,
            tokens_by_kind=correlation_tokens,
        )
        if not block.operation_id:
            block.operation_id = operation.id if operation else None
            block.operation_snapshot = operation.operation_code if operation else (default_operation.code if default_operation else "")
        link_evidence = correlation_svc.apply_code_links_to_block(
            db, block, code_links, report_scope=doc.scope
        )
        all_evidence = [*correlation_evidence, *link_evidence]
        if all_evidence:
            note = block.classification_evidence or ""
            block.classification_evidence = " · ".join(filter(None, [note, *all_evidence]))[:500]
        db.add(block)
        new_blocks.append(block)
    if unmapped_codes:
        warnings.append('Unmapped numeric activity codes: ' + ', '.join(sorted(unmapped_codes)[:20])
                        + '. Compare with the source or configure a workspace code.')
        job.findings = '\n'.join(warnings)
    # Supplemental mud measurements follow, rather than renumber, the previous source's stations.
    last_station = (
        db.scalar(
            select(func.max(OpsSurvey.station_no)).where(
                OpsSurvey.organization_id == org, OpsSurvey.report_id == report.id
            )
        )
        or 0
    )
    for idx, survey in enumerate(parsed["surveys"], last_station + 1):
        db.add(
            OpsSurvey(
                organization_id=org, report_id=report.id, well_id=well.id, scope=doc.scope, station_no=idx, **survey
            )
        )
    # The visible comparison is generated as soon as the draft exists, so the
    # engineer reviews the suggested lead/lag with the same pass that reviews the codes.
    db.flush()
    reports_svc._suggest_comparison(db, report)
    doc.status = "extracted"
    doc.extraction_job_id = job.id
    record(
        db,
        organization_id=org,
        actor=user,
        action="extract",
        entity_type="ops_report",
        entity_id=report.id,
        entity_label=doc.file_name,
        summary=f"Extracted {len(parsed['blocks'])} suggested blocks into draft",
        request=request,
    )
    db.commit()
    if use_ai:
        from app.services.operations.ops_ai import refine_report_prefill

        ai_out = refine_report_prefill(db, org, report.id, user, request=request, from_extract=True)
        if ai_out.get("notes") or ai_out.get("ai_error"):
            extra = list(ai_out.get("notes") or [])
            if ai_out.get("ai_error"):
                extra.append(f"AI prefill notice: {ai_out['ai_error']}")
            job_row = db.get(OpsExtractionJob, job.id)
            if job_row and extra:
                job_row.findings = "\n".join(filter(None, [job_row.findings, *extra]))
                db.commit()
        db.refresh(report)
    return report
