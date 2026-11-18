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
from app.models.operations import (
    OpsActivityBlock,
    OpsActivityCode,
    OpsCause,
    OpsDailyReport,
    OpsExtractionJob,
    OpsMarkRule,
    OpsNptCode,
    OpsOperationCode,
    OpsPlanItem,
    OpsPlanVersion,
    OpsSurvey,
)
from app.models.rig_well import Well
from app.services.audit import record
from app.services.operations import documents, scope, settings
from app.services.operations.openwells import parse_pdf
from app.services.operations.plans import active_plan
from app.services.operations.workbooks import daily_workbook


def extract(db, org, document_id, requested_day, user, request, target_id=None):
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
    for field, limit in [("report_no_text", 50), ("site", 200), ("event_code", 50)]:
        if parsed.get(field):
            parsed[field] = str(parsed[field])[:limit]
    for field in (
        "report_no_text",
        "depth_start_m",
        "depth_end_m",
        "tvd_m",
        "progress_m",
        "dfs_days",
        "rotating_hours",
        "event_code",
        "operation_summary",
        "forward_plan",
        "site",
    ):
        if parsed.get(field) is not None and getattr(report, field) in ("", None):
            setattr(report, field, parsed[field])
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
        rows = db.scalars(
            select(model).where(
                model.organization_id == org, model.is_active.is_(True), model.is_deleted.is_(False)
            )
        )
        return {code_key(getattr(row, k)): row for row in rows for k in keys}

    codes = lookup(OpsActivityCode, "activity_code", "activity_name")
    operations = lookup(OpsOperationCode, "operation_code", "operation_name")
    causes = lookup(OpsCause, "cause_code", "cause_name")
    trouble = lookup(OpsNptCode, "npt_code", "npt_name")
    mark_rules = lookup(OpsMarkRule, "mark_code")
    zone = ZoneInfo(cfg.operating_timezone)
    unmapped_codes = set()
    for seq, b in enumerate(parsed["blocks"], 1):
        a = b["start"].replace(tzinfo=zone).astimezone(UTC)
        z = b["end"].replace(tzinfo=zone).astimezone(UTC)
        raw_activity = b["code"].strip()
        activity_family = 'OpenWells code token' if b.get('source_page') else 'Activity'
        code = codes.get(code_key(raw_activity))
        elapsed = (
            (a - utc(plan.planned_start_at)).total_seconds() / 3600 if plan and plan.planned_start_at else None
        )
        if elapsed is None and report.scope == "drilling" and report.dfs_days is not None:
            elapsed = float(report.dfs_days) * 24 - (end - a).total_seconds() / 3600
        raw_mark = b['mark'].strip()
        raw_cause = b.get('cause', '').strip()
        raw_operation = b.get('operation', '').strip()
        rule = mark_rules.get(code_key(raw_mark))
        classification = suggest(
            raw_mark, b['narrative'], code.default_allocation if code else None, timeline, elapsed,
            mark_rule=rule, printed_allocation=b.get('allocation', ''),
        )
        evidence = []
        if raw_activity:
            label = f'{raw_activity} — {code.activity_name}' if code else describe_code(raw_activity, activity_family)
            evidence.append(f'Activity: {label}')
            if not code and raw_activity.isdigit() and not find_code(raw_activity, activity_family):
                unmapped_codes.add(raw_activity)
        evidence.append(classification['classification_evidence'])
        if plan and (timeline or classification['classification_source'] == 'timeline'):
            evidence.append(f'Programme: {plan.label[:70]} v{plan.version_no}')
        if b.get('allocation'):
            evidence.append(f'Summary allocation: {b["allocation"]}')
        party = b.get('party', '')
        if party:
            evidence.append(f'Source agency: {party[:80]}; choose vendor')
        cause = causes.get(code_key(raw_cause))
        default_trouble = find_code(raw_cause or raw_mark, 'Trouble / NPT')
        npt = trouble.get(code_key(raw_cause or raw_mark))
        operation = operations.get(code_key(raw_operation))
        classification['classification_evidence'] = ' · '.join(evidence)
        classification["classification_evidence"] = classification["classification_evidence"][:500]
        db.add(
            OpsActivityBlock(
                organization_id=org,
                report_id=report.id,
                sequence_no=seq,
                started_at=a,
                ended_at=z,
                duration_minutes=round((z - a).total_seconds() / 60),
                phase_raw=b['phase_raw'][:20],
                source_activity_code=raw_activity[:100],
                source_operation_code=raw_operation[:100],
                source_cause_code=raw_cause[:50],
                source_mark=raw_mark[:30],
                activity_code_id=code.id if code else None,
                operation_code_id=operation.id if operation else None,
                cause_code=cause.cause_code if cause else raw_cause[:50],
                npt_code_id=npt.id if npt else None,
                npt_code_snapshot=npt.npt_code if npt else (default_trouble.code if default_trouble else ""),
                bit_depth_m=b.get("bit_depth_m"),
                rotating_hours=b.get("rotating_hours"),
                depth_from_m=b.get("depth_from_m"),
                depth_to_m=b.get("depth_to_m"),
                source_page=b.get("source_page", 0),
                source_bbox=b["source"],
                narrative=b["narrative"],
                review_state="suggested",
                **classification,
            )
        )
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
    return report
