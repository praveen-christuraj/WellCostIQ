"""Opt-in AI cost analysis for Cost Intelligence backed by offline LAN Ollama.

Deterministic Cost Intelligence in ``services/cost_intelligence.py`` remains
completely unchanged and runs without any model by default. This module is called
only when a user explicitly engages the AI toggle to review portfolio or well
costs for anomalies, suspected data-entry mistakes, and automated cost reviews.
"""

from datetime import datetime, timezone
import re
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.domain import cost_intelligence as domain
from app.models import User
from app.schemas.cost_intelligence import (
    AiFindingCategory,
    IntelligenceAiEntrySignal,
    IntelligenceAiFinding,
    IntelligenceAiReviewIn,
    IntelligenceAiReviewOut,
    IntelligenceOverview,
    IntelligenceWellDetail,
)
from app.services import (
    audit,
    cost_intelligence as ci_service,
    daily_cost as daily_cost_service,
    entry_checks as entry_checks_service,
    ollama as ollama_service,
)

MAX_PROMPT_CHARS = 14_500
MAX_AI_FINDINGS = 12
MAX_AI_LIST = 8
MAX_ENTRY_SIGNALS = 16

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_VALID_SEVERITIES = {"critical", "warning", "info"}
_VALID_POSTURES = {"good", "watch", "at-risk"}
_CATEGORY_MAP: dict[str, AiFindingCategory] = {
    "anomaly": "anomaly",
    "spike": "anomaly",
    "entry-mistake": "entry-mistake",
    "entry_mistake": "entry-mistake",
    "mistake": "entry-mistake",
    "keying": "entry-mistake",
    "duplicate": "entry-mistake",
    "budget": "budget",
    "forecast": "budget",
    "overrun": "budget",
    "afe": "budget",
    "trend": "trend",
    "drift": "trend",
    "schedule": "trend",
    "npt": "npt-upa",
    "upa": "npt-upa",
    "npt-upa": "npt-upa",
    "npt_upa": "npt-upa",
    "data-quality": "data-quality",
    "data_quality": "data-quality",
    "missing": "data-quality",
    "stale": "data-quality",
}

FOCUS_INSTRUCTIONS: dict[str, str] = {
    "full": (
        "Perform a complete automated cost analytic review covering: (1) overall AFE vs actual vs forecast health, "
        "(2) daily cost anomalies and upward drift, (3) suspected data-entry mistakes (mistyped digits, rate slips, "
        "duplicate lines, missing/stale/draft sheets, repeated or zero days, unbudgeted bookings), and "
        "(4) prioritized cost-control and audit actions."
    ),
    "anomalies": (
        "Focus primarily on statistical cost anomalies: single-day cost spikes (distinguishing true anomalies from "
        "planned lump-sum tangible bookings), CUSUM upward spending drift, sudden unit-rate shifts, unbudgeted line "
        "items, and NPT/UPA cost surges."
    ),
    "mistakes": (
        "Focus primarily on suspected data-entry mistakes and record hygiene: 10x/100x digit slips, overridden rates, "
        "duplicate sheet lines, unusual exchange rates, missing daily cost dates, repeated identical totals, zero-cost "
        "days, unsubmitted draft sheets, and discrepancies between daily sheets and LIH/mud reconciliation."
    ),
    "budget": (
        "Focus primarily on AFE budget performance and completion forecast: Actual/AFE utilisation, SOW adjustment "
        "coverage, LIH deductions, forecasted final variance, operational daily burn rate vs plan, cost-group overruns, "
        "and concrete actions to contain budget exposure."
    ),
}

REVIEW_SYSTEM_PROMPT = """You are a senior drilling & completion cost-control auditor operating inside WellCostIQ.

STRICT RULES:
1. Base every statement ONLY on the verified figures, statistical findings, and daily-sheet entry checks provided below.
2. Quote exact currency codes, monetary amounts, percentages, well codes, sheet codes, and dates verbatim. Never invent figures, dates, or wells.
3. Never add monetary amounts from different currencies.
4. Distinguish legitimate lump-sum tangible bookings (e.g. casing/tubing/wellhead runs) from anomalous operational cost spikes or data-entry mistakes.
5. Respond with ONE valid JSON object using this exact schema (plain text values, no emojis, no HTML):
{
  "risk_posture": "good" | "watch" | "at-risk",
  "executive_summary": "Concise 2-4 sentence executive review grounded in the exact figures.",
  "findings": [
    {
      "severity": "critical" | "warning" | "info",
      "category": "anomaly" | "entry-mistake" | "budget" | "trend" | "npt-upa" | "data-quality",
      "well_code": "Exact well code from context or empty string",
      "reference": "Exact date or daily sheet code if applicable, else empty string",
      "title": "Short specific title",
      "detail": "Evidence citing exact numbers from the data",
      "recommendation": "Concrete verification or corrective step"
    }
  ],
  "recommendations": [
    "Ranked actionable recommendation citing well codes and amounts"
  ],
  "data_quality_notes": [
    "Record completeness, entry-mistake pattern, draft backlog, or reconciliation observation"
  ]
}"""


def _clean(value: Any, limit: int = 800) -> str:
    if not isinstance(value, str):
        return ""
    return _CONTROL_RE.sub("", value).strip()[:limit]


def _permissions(user: User) -> set[str]:
    if any(role.is_owner for role in user.roles):
        return {"*"}
    return {perm.key for role in user.roles for perm in role.permissions}


def _has_cap(capabilities: set[str], key: str) -> bool:
    return "*" in capabilities or key in capabilities


def _fmt(amount: float | None, currency: str) -> str:
    if amount is None:
        return "unknown"
    return domain.money(amount, currency)


def _collect_entry_signals(
    db: Session,
    organization_id: str,
    capabilities: set[str],
    well_pairs: list[tuple[str, str]],
) -> tuple[int, list[IntelligenceAiEntrySignal]]:
    """Collect open daily-sheet entry checks across the inspected wells."""
    if not _has_cap(capabilities, "daily-cost:read") or not entry_checks_service.enabled():
        return 0, []
    total_open = 0
    collected: list[IntelligenceAiEntrySignal] = []
    for well_id, well_code in well_pairs[:8]:
        report = entry_checks_service.checks_for_well(db, organization_id, well_id)
        for sheet in report.sheets:
            for item in sheet.checks:
                if item.reviewed:
                    continue
                total_open += 1
                collected.append(
                    IntelligenceAiEntrySignal(
                        well_id=well_id,
                        well_code=well_code,
                        entry_id=sheet.entry_id,
                        daily_cost_code=sheet.daily_cost_code,
                        cost_date=sheet.cost_date,
                        severity="warning" if item.severity == "warning" else "notice",
                        title=item.title,
                        message=item.message,
                        current_display=item.current_display,
                        suggested_display=item.suggested_display,
                        action_path=f"/daily-cost/entries/{sheet.entry_id}",
                    )
                )
    collected.sort(key=lambda sig: (0 if sig.severity == "warning" else 1, -sig.cost_date.toordinal()))
    return total_open, collected[:MAX_ENTRY_SIGNALS]


def _ledger_reconciliation_lines(
    db: Session,
    organization_id: str,
    capabilities: set[str],
    well_pairs: list[tuple[str, str]],
    *,
    include_draft: bool,
) -> list[str]:
    """Pull unbudgeted items, LIH cost, mud reconciliation, and draft counts."""
    if not _has_cap(capabilities, "daily-cost:read"):
        return []
    lines: list[str] = []
    for well_id, well_code in well_pairs[:6]:
        summary = daily_cost_service.well_cost_summary(
            db, organization_id, well_id, include_draft=include_draft
        )
        t = summary.totals
        cur = t.currency or ""
        p = f"{cur} " if cur else ""
        unbudgeted = [b for b in summary.budget_lines if not b.is_planned and b.actual_to_date > 0]
        unbudgeted_total = sum((b.actual_to_date for b in unbudgeted), start=0)
        extras: list[str] = []
        if t.draft_sheets > 0:
            extras.append(f"draft_sheets={t.draft_sheets}/{t.sheets}")
        if t.lih_cost > 0:
            extras.append(f"LIH={p}{t.lih_cost:,.3f} (total_incl_LIH={p}{t.actual_including_lih:,.3f})")
        if t.has_mud_reconciliation:
            extras.append(f"mud_reconciliation_adj={p}{t.mud_cost_adjustment:+,.3f}")
        if t.has_adjustment and t.adjusted_planned is not None:
            extras.append(f"SOW_revised_AFE={p}{t.adjusted_planned:,.3f} (orig {p}{t.planned:,.3f})")
        if unbudgeted:
            top_ub = ", ".join(
                f"{b.item_name} ({b.cost_group} {p}{b.actual_to_date:,.3f})"
                for b in sorted(unbudgeted, key=lambda item: item.actual_to_date, reverse=True)[:3]
            )
            extras.append(f"unbudgeted_lines={len(unbudgeted)} totalling {p}{unbudgeted_total:,.3f} [{top_ub}]")
        if summary.warnings:
            extras.append(
                "warnings="
                + "; ".join(
                    f"[{w.severity}] {w.message}" if hasattr(w, "message") else str(w)
                    for w in summary.warnings[:2]
                )
            )
        if extras:
            lines.append(f"- {well_code}: " + " | ".join(extras))
    return lines


def _build_review_context(
    *,
    data: IntelligenceAiReviewIn,
    overview: IntelligenceOverview,
    detail: IntelligenceWellDetail | None,
    entry_signals: list[IntelligenceAiEntrySignal],
    total_entry_signals: int,
    ledger_lines: list[str],
) -> str:
    cur = overview.currency
    k = overview.kpis
    blocks: list[str] = [
        f"REVIEW SCOPE: {data.scope.upper()} | FOCUS: {data.focus} | AS OF: {overview.as_of.isoformat()} | "
        f"INCLUDE DRAFT SHEETS: {data.include_draft} | REPORTING CURRENCY: {cur or 'multi/unset'}",
        f"PORTFOLIO KPIS: wells={k.wells} (analysed={k.analysed_wells}, at_risk={k.wells_at_risk}), "
        f"health_score={k.score}/100 ({k.band}), AFE={_fmt(k.afe_amount, cur)}, actual={_fmt(k.actual_amount, cur)} "
        f"({f'{k.utilisation_percent:.1f}%' if k.utilisation_percent is not None else 'n/a'}), "
        f"forecast={_fmt(k.forecast_amount, cur)}, forecast_variance={_fmt(k.forecast_variance, cur)} "
        f"({f'{k.forecast_variance_percent:+.1f}%' if k.forecast_variance_percent is not None else 'n/a'}), "
        f"amount_at_risk={_fmt(k.amount_at_risk, cur)}, findings={k.critical} critical / {k.warning} warning / {k.info} info.",
    ]

    if overview.wells:
        w_lines = [f"WELL HEALTH SUMMARY ({min(len(overview.wells), 14)} of {len(overview.wells)} well(s)):"]
        for w in overview.wells[:14]:
            wc = w.currency or cur
            fc = (
                f"forecast={_fmt(w.forecast.estimate, wc)} (var {_fmt(w.forecast.variance, wc)})"
                if w.forecast.available and w.forecast.estimate is not None
                else f"forecast=unavailable ({w.forecast.reason or 'insufficient data'})"
            )
            w_lines.append(
                f"- {w.well_code} ({w.well_name or 'unnamed'}) | rig={w.rig_code or '—'} | status={w.status} | "
                f"score={w.score}/100 ({w.band}) | AFE={_fmt(w.afe_amount, wc)} | actual={_fmt(w.actual_amount, wc)} "
                f"(op={_fmt(w.operational_amount, wc)}, tang={_fmt(w.tangible_amount, wc)}, util={f'{w.utilisation_percent:.1f}%' if w.utilisation_percent is not None else 'n/a'}) | "
                f"{fc} | NPT={_fmt(w.npt_amount, wc)} ({f'{w.npt_share_percent:.1f}%' if w.npt_share_percent is not None else '0%'}) | "
                f"UPA={_fmt(w.upa_amount, wc)} | days={w.actual_days or 0}/{w.planned_days or 'n/a'} | "
                f"findings={w.critical}C/{w.warning}W/{w.info}I"
            )
        blocks.append("\n".join(w_lines))

    if detail is not None:
        dw = detail.well
        wc = dw.currency or cur
        d_lines = [
            f"SELECTED WELL DEEP PROFILE — {dw.well_code} ({dw.well_name}):",
            f"  Drift: direction={detail.drift_direction or 'none'}, start={detail.drift_start or 'none'}, "
            f"baseline={_fmt(detail.drift_baseline, wc)}/day, cusum_limit={detail.cusum_limit:.3f}",
            f"  Missing daily sheet dates ({len(detail.missing_dates)}): "
            + (", ".join(d.isoformat() for d in detail.missing_dates[:12]) if detail.missing_dates else "none"),
        ]
        spike_days = [d for d in detail.days if d.spike]
        if spike_days:
            d_lines.append(
                "  Statistical spike days: "
                + "; ".join(
                    f"{d.cost_date} actual={_fmt(d.actual, wc)} (op={_fmt(d.operational, wc)}, tang={_fmt(d.tangibles, wc)}, "
                    f"baseline={_fmt(d.baseline, wc)}, tangible_run={d.tangible_booking_day})"
                    for d in spike_days[:8]
                )
            )
        if detail.breakdown is not None:
            ue = detail.breakdown.unit_economics
            d_lines.append(
                f"  Unit economics: op_daily_avg={_fmt(ue.operational_daily_avg, wc)} vs planned={_fmt(ue.planned_operational_daily, wc)}, "
                f"burn_efficiency_CPI={ue.burn_efficiency_index if ue.burn_efficiency_index is not None else 'n/a'}, "
                f"cost_per_m={_fmt(ue.cost_per_meter, wc)}, depth={ue.actual_depth or 0}/{ue.planned_depth or 'n/a'} m "
                f"({f'{ue.depth_progress_percent:.1f}%' if ue.depth_progress_percent is not None else 'n/a'}), "
                f"NPT_days={ue.npt_days or 0}, UPA_days={ue.upa_days or 0}, top_driver={ue.top_cost_driver or 'none'}"
            )
            if detail.breakdown.cost_groups:
                d_lines.append(
                    "  Cost groups: "
                    + " | ".join(
                        f"{g.label}: planned={_fmt(g.planned, wc)}, actual={_fmt(g.actual, wc)}, bal={_fmt(g.balance, wc)}"
                        for g in detail.breakdown.cost_groups
                    )
                )
            if detail.breakdown.activities:
                d_lines.append(
                    "  Top activities: "
                    + " | ".join(
                        f"{a.activity_code} ({a.classification}): {_fmt(a.amount, wc)} over {a.active_days}d"
                        for a in detail.breakdown.activities[:6]
                    )
                )
        if detail.days:
            d_lines.append(
                "  Recent daily costs: "
                + "; ".join(
                    f"{d.cost_date}: total={_fmt(d.actual, wc)} (svc={_fmt(d.services, wc)}, cons={_fmt(d.consumables, wc)}, "
                    f"tang={_fmt(d.tangibles, wc)}, npt={_fmt(d.npt, wc)})"
                    for d in detail.days[-8:]
                )
            )
        blocks.append("\n".join(d_lines))

    target_findings = detail.findings if detail is not None else overview.findings
    if target_findings:
        f_lines = [f"STATISTICAL ANOMALY & RISK FINDINGS ({min(len(target_findings), 16)} of {len(target_findings)}):"]
        for f in target_findings[:16]:
            dt = f" [{f.cost_date}]" if f.cost_date else ""
            f_lines.append(
                f"- [{f.severity.upper()} | {f.category}] {f.well_code}{dt} {f.title}: {f.detail} | "
                f"Basis: {f.basis} | Rule suggestion: {f.suggestion}"
            )
        blocks.append("\n".join(f_lines))
    else:
        blocks.append("STATISTICAL ANOMALY & RISK FINDINGS: None triggered (all checked rules within threshold).")

    if entry_signals:
        e_lines = [
            f"DAILY COST SHEET ENTRY-CHECK MISTAKE SIGNALS ({len(entry_signals)} shown of {total_entry_signals} unreviewed):"
        ]
        for sig in entry_signals:
            fix = f" | Suggested correction: {sig.suggested_display}" if sig.suggested_display else ""
            cur_val = f" | Entered: {sig.current_display}" if sig.current_display else ""
            e_lines.append(
                f"- [{sig.severity.upper()}] {sig.well_code} sheet {sig.daily_cost_code} ({sig.cost_date}) — "
                f"{sig.title}: {sig.message}{cur_val}{fix}"
            )
        blocks.append("\n".join(e_lines))
    else:
        blocks.append("DAILY COST SHEET ENTRY-CHECK MISTAKE SIGNALS: 0 unreviewed line-level anomalies found.")

    if ledger_lines:
        blocks.append("LEDGER RECONCILIATION, UNBUDGETED ITEMS & DRAFT BACKLOG:\n" + "\n".join(ledger_lines))

    if overview.notes:
        blocks.append("SCOPE NOTES: " + " | ".join(overview.notes[:4]))

    assembled: list[str] = []
    used = 0
    for block in blocks:
        if used + len(block) + 2 > MAX_PROMPT_CHARS:
            rem = MAX_PROMPT_CHARS - used - 40
            if rem > 250:
                assembled.append(block[:rem].rsplit("\n", 1)[0] + "\n[...truncated]")
            break
        assembled.append(block)
        used += len(block) + 2
    return "\n\n".join(assembled)


def _parse_review_payload(
    text: str,
    *,
    default_posture: str,
    wells_by_code: dict[str, tuple[str, str]],
    sheets_by_code: dict[str, str],
) -> tuple[str, str, list[IntelligenceAiFinding], list[str], list[str]]:
    parsed = ollama_service.extract_json_object(text)
    if parsed is None:
        # Graceful fallback when a compact 4B model emits plain text instead of JSON.
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        bullets = [_clean(ln.lstrip("-*•0123456789.) "), 360) for ln in lines if ln.startswith(("-", "*", "•"))]
        prose_lines = [ln for ln in lines if not ln.startswith(("-", "*", "•"))]
        summary = _clean(" ".join(prose_lines) if prose_lines else text, 1600)
        posture = default_posture if default_posture in _VALID_POSTURES else "watch"
        return posture, summary, [], [b for b in bullets if b][:MAX_AI_LIST], []

    raw_posture = _clean(parsed.get("risk_posture", ""), 20).lower().replace("_", "-")
    if raw_posture in {"attention", "critical", "high", "high-risk"}:
        raw_posture = "at-risk"
    elif raw_posture in {"medium", "moderate", "caution"}:
        raw_posture = "watch"
    elif raw_posture in {"low", "healthy", "normal"}:
        raw_posture = "good"
    posture = raw_posture if raw_posture in _VALID_POSTURES else (
        default_posture if default_posture in _VALID_POSTURES else "watch"
    )

    summary = _clean(
        parsed.get("executive_summary") or parsed.get("summary") or parsed.get("overview") or "",
        1800,
    )

    findings: list[IntelligenceAiFinding] = []
    raw_findings = parsed.get("findings")
    if isinstance(raw_findings, list):
        for entry in raw_findings[:MAX_AI_FINDINGS]:
            if not isinstance(entry, dict):
                continue
            title = _clean(entry.get("title"), 180)
            detail = _clean(entry.get("detail") or entry.get("description") or entry.get("observation"), 700)
            if not title and not detail:
                continue
            sev = _clean(entry.get("severity"), 20).lower()
            if sev in {"high", "error", "severe"}:
                sev = "critical"
            elif sev in {"medium", "moderate", "warn"}:
                sev = "warning"
            elif sev not in _VALID_SEVERITIES:
                sev = "info"

            cat_raw = _clean(entry.get("category"), 30).lower()
            category: AiFindingCategory = _CATEGORY_MAP.get(cat_raw, "anomaly")
            well_code_in = _clean(entry.get("well_code"), 50)
            ref = _clean(entry.get("reference") or entry.get("cost_date") or entry.get("date"), 80)
            rec = _clean(entry.get("recommendation") or entry.get("action") or entry.get("suggestion"), 500)

            matched_well_id = ""
            matched_well_code = ""
            if well_code_in:
                hit = wells_by_code.get(well_code_in.lower())
                if hit is not None:
                    matched_well_id, matched_well_code = hit

            action_path = ""
            action_label = ""
            sheet_entry_id = sheets_by_code.get(ref.lower()) if ref else None
            if sheet_entry_id:
                action_path = f"/daily-cost/entries/{sheet_entry_id}"
                action_label = "Open sheet"
            elif matched_well_id:
                action_path = f"/daily-cost/analysis/{matched_well_id}"
                action_label = "Well analysis"

            findings.append(
                IntelligenceAiFinding(
                    severity=sev,  # type: ignore[arg-type]
                    category=category,
                    well_id=matched_well_id,
                    well_code=matched_well_code,
                    reference=ref,
                    title=title or detail[:90],
                    detail=detail or title,
                    recommendation=rec,
                    action_path=action_path,
                    action_label=action_label,
                )
            )

    order = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda item: order.get(item.severity, 2))

    recommendations: list[str] = []
    raw_recs = parsed.get("recommendations")
    if isinstance(raw_recs, list):
        for item in raw_recs[:MAX_AI_LIST]:
            cleaned = _clean(item, 420) if isinstance(item, str) else _clean(item.get("action") if isinstance(item, dict) else "", 420)
            if cleaned:
                recommendations.append(cleaned)

    notes: list[str] = []
    raw_notes = parsed.get("data_quality_notes") or parsed.get("notes")
    if isinstance(raw_notes, list):
        for item in raw_notes[:MAX_AI_LIST]:
            cleaned = _clean(item, 380) if isinstance(item, str) else ""
            if cleaned:
                notes.append(cleaned)

    if not summary:
        if findings:
            summary = f"Reviewed workspace costs and identified {len(findings)} anomaly and audit item(s) requiring attention."
        else:
            summary = "Reviewed recorded costs, statistical thresholds, and sheet entry checks; no material anomalies were flagged."

    return posture, summary, findings, recommendations, notes


def generate_review(
    db: Session,
    user: User,
    data: IntelligenceAiReviewIn,
    request: Request | None = None,
) -> IntelligenceAiReviewOut:
    """Run an audited, opt-in Ollama cost analytic review over tenant records."""
    if data.scope == "well" and not data.well_id.strip():
        raise HTTPException(status_code=422, detail="Select a well before requesting a single-well AI review.")

    # Verify Ollama is enabled before doing heavy inspection, so disabled setups
    # return an immediate, actionable alert.
    try:
        cfg = ollama_service.ensure_enabled()
    except ollama_service.OllamaCommunicationError as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc

    effective_well_filter = data.well_id.strip() if data.scope == "well" else data.well_id.strip()
    detail: IntelligenceWellDetail | None = None
    if data.scope == "well":
        detail = ci_service.well_detail(
            db,
            user,
            effective_well_filter,
            date_from=data.date_from,
            date_to=data.date_to,
            currency=data.currency,
            include_draft=data.include_draft,
        )

    overview = ci_service.overview(
        db,
        user,
        date_from=data.date_from,
        date_to=data.date_to,
        rig_id=data.rig_id,
        well_id=effective_well_filter,
        well_status=data.well_status,
        currency=data.currency,
        include_draft=data.include_draft,
    )

    caps = _permissions(user)
    if detail is not None:
        well_pairs = [(detail.well.well_id, detail.well.well_code)]
    else:
        well_pairs = [(w.well_id, w.well_code) for w in overview.wells]

    total_entry_signals, entry_signals = _collect_entry_signals(
        db, user.organization_id, caps, well_pairs
    )
    ledger_lines = _ledger_reconciliation_lines(
        db,
        user.organization_id,
        caps,
        well_pairs,
        include_draft=data.include_draft,
    )

    context_text = _build_review_context(
        data=data,
        overview=overview,
        detail=detail,
        entry_signals=entry_signals,
        total_entry_signals=total_entry_signals,
        ledger_lines=ledger_lines,
    )
    focus_directive = FOCUS_INSTRUCTIONS.get(data.focus, FOCUS_INSTRUCTIONS["full"])
    custom_q = _clean(data.question, 500)
    question_block = f"\nOPERATOR SPECIFIC QUESTION:\n{custom_q}\n" if custom_q else ""
    user_prompt = (
        f"ANALYTIC OBJECTIVE:\n{focus_directive}\n"
        f"{question_block}\n"
        f"VERIFIED COST INTELLIGENCE & ENTRY-CHECK DATA:\n{context_text}\n\n"
        "Return the JSON cost analytic review strictly grounded in the figures above."
    )

    label_target = detail.well.well_code if detail is not None else f"portfolio ({overview.kpis.wells} well(s))"
    try:
        reply = ollama_service.chat(
            system_prompt=REVIEW_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            json_mode=True,
            settings=cfg,
        )
    except ollama_service.OllamaCommunicationError as exc:
        audit.record(
            db,
            organization_id=user.organization_id,
            action="ai-review",
            entity_type="cost_intelligence",
            actor=user,
            entity_id=detail.well.well_id if detail is not None else None,
            entity_label=label_target,
            summary=f"Cost Intelligence AI review failed ({exc.code}) for {label_target} on model {exc.model}",
            request=request,
        )
        db.commit()
        raise HTTPException(status_code=503, detail=exc.message) from exc

    wells_by_code = {w.well_code.lower(): (w.well_id, w.well_code) for w in overview.wells}
    if detail is not None:
        wells_by_code[detail.well.well_code.lower()] = (detail.well.well_id, detail.well.well_code)
    sheets_by_code = {sig.daily_cost_code.lower(): sig.entry_id for sig in entry_signals}

    default_posture = detail.well.band if detail is not None else overview.kpis.band
    posture, summary, ai_findings, recs, notes = _parse_review_payload(
        reply.content,
        default_posture=default_posture,
        wells_by_code=wells_by_code,
        sheets_by_code=sheets_by_code,
    )
    stat_count = len(detail.findings) if detail is not None else len(overview.findings)

    audit.record(
        db,
        organization_id=user.organization_id,
        action="ai-review",
        entity_type="cost_intelligence",
        actor=user,
        entity_id=detail.well.well_id if detail is not None else None,
        entity_label=label_target,
        summary=(
            f"Generated Cost Intelligence AI review ({data.focus}) for {label_target} "
            f"using {reply.model}: {len(ai_findings)} finding(s), posture={posture}"
        ),
        request=request,
    )
    db.commit()

    return IntelligenceAiReviewOut(
        generated_at=datetime.now(timezone.utc),
        as_of=overview.as_of,
        scope=data.scope,
        focus=data.focus,
        well_id=detail.well.well_id if detail is not None else "",
        well_code=detail.well.well_code if detail is not None else "",
        currency=detail.well.currency if detail is not None and detail.well.currency else overview.currency,
        model=reply.model,
        endpoint=reply.endpoint,
        duration_ms=reply.duration_ms,
        inspected_wells=1 if detail is not None else overview.kpis.wells,
        statistical_findings_count=stat_count,
        entry_signals_count=total_entry_signals,
        risk_posture=posture,  # type: ignore[arg-type]
        executive_summary=summary,
        findings=ai_findings,
        recommendations=recs,
        data_quality_notes=notes,
        entry_signals=entry_signals,
    )
