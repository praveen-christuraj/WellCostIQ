"""Tenant-scoped, capability-gated workspace database & workflow context builder.

The offline Ollama model (``qwen3:4b-q4_K_M``) never executes SQL and never
touches rows outside the caller's organization or role capabilities. Instead,
this module inspects the live workspace through existing domain services and
column-wise queries, performs exact ``Decimal`` arithmetic (including head-to-head
well cost comparisons, budget variances, LIH/mud reconciliation adjustments,
fuel material balances, invoice payable totals, catalogue rates, and entry-check
signals), pairs those figures with the application's workflow guide, and renders
a compact grounded dossier sized for an 8k context window.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Block, Rig, User, Well
from app.models.assistant import AssistantMemory
from app.models.catalogue import CementAdditive, DrillBit, FuelType, MudChemical, Tangible
from app.models.master_data import Currency
from app.models.ndt_inspection import NdtInspection
from app.models.service_master import Service
from app.models.vendor_master import PurchaseOrder, Vendor
from app.schemas.assistant import AssistantFact, AssistantSource, AssistantTable
from app.schemas.daily_cost import DailyCostWellSummary
from app.services import (
    afe as afe_service,
    cost_intelligence as ci_service,
    daily_cost as daily_cost_service,
    entry_checks as entry_checks_service,
    fuel_cost as fuel_cost_service,
    invoice_processing as invoice_service,
    lih_cost as lih_cost_service,
    mud_cost as mud_cost_service,
)

MAX_DOSSIER_CHARS = 14_500
MAX_COMPARED_WELLS = 6

# Concise end-to-end application workflow reference so the AI model understands
# how WellCostIQ modules connect, how numbers are derived, and where each action lives.
WORKFLOW_MAP = """WELLCOSTIQ WORKFLOW & CALCULATION RULES:
1. Master Data (/master-data, capability master-data:read/write): Define default currency, exchange currencies, UOMs, blocks, hole sections, phases, activities, sub-activities, vendors (Inhouse or Third party; active/inactive/blocked), PO/SO orders (with revision chain), services (Day Rate / Per Service Rate / Per Section Rate), and priced catalogue items (Tangibles, Drill Bits, Mud Chemicals, Cement Additives, Fuel) with unit rates, uplifts, and effective dates.
2. Rig & Well Management (/rig-well, capability rig-well:read/write): Register rigs (assigned to blocks), then wells under rigs with separate Drilling and Completion plans (sections, phases, planned depths standardized in metres, planned days, spud date/time, well sub-activities with responsible party, and audited Plan Adjustments). Well status ladder: Upcoming -> Active -> Final review -> Completed (one-step rollback permitted).
3. AFE & SOW Adjustments (/afe, capability afe:read/write): Build Drilling or Completion AFE cost estimates per well across Services, Consumables, and Tangibles in a single standard currency (converting multi-currency lines via explicit AFE exchange rates). Status ladder: Draft -> Submitted -> Reviewed -> Approval (with explicit reopen to Draft). Approved Scope of Work (SOW) adjustments create revised planned amounts and days without erasing the original AFE baseline.
4. Daily Cost Sheets (/daily-cost, capability daily-cost:read/write): Record one daily sheet per well, AFE, and cost date with lines classified under Services, Consumables, Tangibles, and Other Expenses, and activity classification Planned, UPA (Unplanned Activity), or NPT (Non-Productive Time). Draft sheets are editable; Submitted sheets lock edits until reopened. NPT and UPA days equal exact recorded NPT/UPA hours divided by 24. Actual elapsed days count from well Spud Date & Time (3 decimals), falling back to recorded sheet count when unspudded.
5. Daily Entry Checks (/daily-cost, capability daily-cost:read/write): Statistical verification comparing each sheet line against neighbouring AFE sheets and workspace item profiles to catch mistyped digits (10x/100x slips), rate overrides, duplicate lines, unusual exchange rates, and depth discrepancies. Advisory only; reviewers can apply a correction or mark a line as reviewed with an audited note.
6. Companion Operational Registers (capability daily-cost:read/write):
   - Mud Cost (/daily-cost/mud-cost-analysis): Per-well, per-section mud volume balance (Opening + Receipts + Additions - Consumption/Losses + Others = Closing) and WBM/OBM/SOBM Cost/BBL reconciliation feeding AFE comparison totals.
   - Lost In Hole / LIH (/daily-cost/lih-register): Separate per-well downhole loss register; LIH cost is added to Actual Cost (Actual incl. LIH) and explicitly deducted from AFE available budget.
   - Fuel Cost (/daily-cost/fuel-cost-register): Rig-scoped daily fuel (AGO/Diesel) material balance (Rig engines + Company consumption lines, receipts, opening/closing stock & adjustments) plus separate Rig Saving litres never mixed into fuel stock consumption.
   - NDT Inspection (/daily-cost/ndt-inspections): Per-well/scope tubular & tool inspection register tracking quantities received, consumed, backloaded good, and backloaded bad.
7. Cost Intelligence (/reports/cost-intelligence, capability cost-intelligence:read/export): Read-only statistical review scoring each well 0-100 (Good 80-100, Watch 60-79, Attention 0-59), flagging daily cost spikes (rolling median + MAD modified z-score), creeping cost drift (CUSUM), AFE/forecast overrun, burn-ahead, schedule overrun, NPT share, missing/stale sheets, and repeated/zero days, with optional AI analytic review.
8. Invoice Processing & IDVS (/invoice-processing, capability invoice-processing:read/write/verify/epicor/pay): Commercial invoice verification tied to vendors, PO/SO orders, blocks (Own/JV), rigs, and wells. Status ladder: Draft -> Submitted -> Verified & sent to Accounts -> Received for EPICOR -> Approved in EPICOR (plus payment recording). Tracks invoice vs verified subtotals, tax additions/deductions, disallowed amounts, advances, and net payable strictly per currency (never summed across currencies without explicit conversion).
9. Reports, Report Builder, Templates, Backup & Audit: Business Dashboard (/business-dashboard), Well Cost Comparison (/reports/well-cost-comparison), Usage & NPT/UPA matrices (/reports), consolidated 7-report Well Bundle PDF, custom Report Builder (/reports/builder), reusable Templates (/record-templates), Backup & Recovery (/other-management/backup), and immutable column-wise Audit Logs (/other-management/audit)."""

_COMPARE_RE = re.compile(
    r"\b(compare|comparing|comparison|versus|vs\.?|against|difference|diff|between|higher|lower|cheaper|costlier|more expensive)\b",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r"""["'“”‘’]([^"'“”‘’]{1,80})["'“”‘’]""")
_NAMED_WELL_RE = re.compile(
    r"\bwell\s+([A-Za-z0-9][A-Za-z0-9._/-]{0,32})\b",
    re.IGNORECASE,
)
_WELL_STOPWORDS = frozenset(
    {
        "cost", "costs", "total", "totals", "data", "summary", "report", "reports",
        "budget", "afe", "afes", "actual", "actuals", "plan", "plans", "planned",
        "status", "list", "all", "any", "the", "this", "that", "these", "those",
        "with", "and", "for", "from", "into", "over", "under", "compare", "comparison",
        "versus", "vs", "analysis", "spending", "spend", "expense", "expenses",
        "daily", "sheet", "sheets", "mud", "lih", "ndt", "fuel", "drilling",
        "completion", "section", "sections", "depth", "days", "health", "score",
        "number", "code", "name", "wise", "level", "details", "detail", "information",
        "one", "two", "each", "every", "other", "another", "which", "what", "whose",
        "is", "are", "was", "were", "has", "have", "had", "in", "on", "of", "to", "by",
    }
)
_GENERIC_NAME_TOKENS = _WELL_STOPWORDS | frozenset(
    {"well", "wells", "rig", "rigs", "block", "field", "pad", "phase", "test", "deep", "north", "south", "east", "west"}
)

ASSISTANT_SYSTEM_PROMPT = """You are the WellCostIQ offline AI Guide assisting drilling, completion, finance, and cost-control users.

STRICT GROUNDING RULES:
1. Answer ONLY using the facts inside VERIFIED WORKSPACE DATABASE CONTEXT and WELLCOSTIQ WORKFLOW & MEMORY below.
2. Quote every currency code, monetary figure, percentage, day count, well code, AFE code, vendor name, and invoice number EXACTLY as written in the context. Never invent, estimate, or alter figures.
3. Never add or subtract monetary amounts that are in different currencies. State each currency separately.
4. When comparing two or more wells, clearly state each well's recorded total cost (and LIH / Total incl. LIH if non-zero), effective AFE budget, remaining balance, Actual / AFE %, the exact cost difference between them, and the primary cost-group or NPT/UPA drivers.
5. If a requested well, item, or record is listed under UNMATCHED REFERENCES or does not appear in the context, state clearly that it was not found in this workspace and mention the available records shown in the context.
6. If a module is listed under CALLER RESTRICTED CAPABILITIES, state plainly that the caller's role does not grant access to that module and never guess its figures.
7. Write clear, direct, professional plain text (concise paragraphs and short bullet lines using '- ' when helpful). Do not use emojis, raw HTML, or speculative disclaimers."""


@dataclass(frozen=True)
class WellComparisonResult:
    """Deterministic multi-well summary reused by both direct and AI answers."""

    summaries: list[DailyCostWellSummary]
    unmatched: list[str]
    prose: str
    facts: list[AssistantFact]
    tables: list[AssistantTable]
    sources: list[AssistantSource]
    follow_ups: list[str]
    context_block: str


def _money(value: Decimal | int | float | None) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)):,.2f}"


def _signed_money(currency: str, value: Decimal) -> str:
    prefix = f"{currency} " if currency else ""
    if value > 0:
        return f"+{prefix}{_money(value)}"
    if value < 0:
        return f"-{prefix}{_money(abs(value))}"
    return f"{prefix}0.00"


def _pct(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{Decimal(str(value)):.1f}%"


def _days(value: Decimal | int | None) -> str:
    if value is None:
        return "0"
    dec = Decimal(str(value))
    if dec == dec.to_integral_value():
        return str(int(dec))
    return f"{dec:.2f}".rstrip("0").rstrip(".")


def _effective_afe(summary: DailyCostWellSummary) -> Decimal:
    totals = summary.totals
    if totals.has_adjustment and totals.adjusted_planned is not None:
        return totals.adjusted_planned
    return totals.planned


def _effective_balance(summary: DailyCostWellSummary) -> Decimal:
    totals = summary.totals
    if totals.has_adjustment and totals.adjusted_balance is not None:
        return totals.adjusted_balance
    return totals.balance


def _effective_used_pct(summary: DailyCostWellSummary) -> Decimal | None:
    totals = summary.totals
    planned = _effective_afe(summary)
    if planned <= 0:
        return None
    base = totals.actual_including_lih if totals.lih_cost > 0 else totals.actual
    return ((base / planned) * Decimal("100")).quantize(Decimal("0.1"))


def _effective_planned_days(summary: DailyCostWellSummary) -> Decimal:
    totals = summary.totals
    if totals.has_adjustment and totals.adjusted_planned_days is not None:
        return totals.adjusted_planned_days
    return totals.planned_days


def _actual_days(summary: DailyCostWellSummary) -> Decimal:
    totals = summary.totals
    if totals.actual_days is not None:
        return totals.actual_days
    if totals.spud_actual_days is not None:
        return totals.spud_actual_days
    return Decimal(totals.recorded_days)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _phrase_position(haystack: str, needle: str) -> int | None:
    cleaned = _norm(needle)
    if not cleaned:
        return None
    pattern = r"(?<![a-z0-9])" + re.escape(cleaned) + r"(?![a-z0-9])"
    match = re.search(pattern, haystack)
    return match.start() if match else None


def is_comparison_question(question: str) -> bool:
    return bool(_COMPARE_RE.search(question or ""))


def find_well_mentions(
    db: Session,
    organization_id: str,
    question: str,
    *,
    limit: int = MAX_COMPARED_WELLS,
) -> tuple[list[Well], list[str]]:
    """Return wells referenced in ``question`` (in mention order) plus unmatched well labels."""
    wells = db.scalars(
        select(Well)
        .where(Well.organization_id == organization_id, Well.is_deleted.is_(False))
        .order_by(Well.well_code)
    ).all()
    lower = _norm(question)
    hits: list[tuple[int, int, Well]] = []
    matched_ids: set[str] = set()

    # Pass 1: exact well_code or full well_name (longest match wins on overlap).
    for well in wells:
        best_pos: int | None = None
        best_len = 0
        for candidate in (well.well_code, well.well_name):
            pos = _phrase_position(lower, candidate)
            cand_len = len(_norm(candidate))
            if pos is not None and (cand_len > best_len or (cand_len == best_len and (best_pos is None or pos < best_pos))):
                best_pos = pos
                best_len = cand_len
        # Also match "Well <code>" or well_name without a leading "Well " prefix when unambiguous.
        stripped_name = re.sub(r"^well[\s_-]+", "", _norm(well.well_name)).strip()
        if best_pos is None and stripped_name and len(stripped_name) >= 3 and stripped_name not in _GENERIC_NAME_TOKENS:
            same_suffix = [
                other for other in wells
                if re.sub(r"^well[\s_-]+", "", _norm(other.well_name)).strip() == stripped_name
            ]
            if len(same_suffix) == 1:
                pos = _phrase_position(lower, stripped_name)
                if pos is not None:
                    best_pos = pos
                    best_len = len(stripped_name)
        if best_pos is not None:
            hits.append((best_pos, -best_len, well))
            matched_ids.add(well.id)

    # Pass 2: unambiguous distinctive token inside well_name (>= 4 chars).
    token_owners: dict[str, list[Well]] = {}
    for well in wells:
        for tok in re.findall(r"[a-z0-9]{4,}", _norm(well.well_name)):
            if tok in _GENERIC_NAME_TOKENS:
                continue
            token_owners.setdefault(tok, []).append(well)
    for tok, owners in token_owners.items():
        if len(owners) == 1 and owners[0].id not in matched_ids:
            pos = _phrase_position(lower, tok)
            if pos is not None:
                hits.append((pos, -len(tok), owners[0]))
                matched_ids.add(owners[0].id)

    hits.sort(key=lambda item: (item[0], item[1]))
    ordered = [item[2] for item in hits[:limit]]

    # Detect explicit well references ("Well X", 'Well Y') that matched nothing.
    unmatched: list[str] = []
    known_norms: set[str] = set()
    for well in ordered:
        known_norms.add(_norm(well.well_code))
        known_norms.add(_norm(well.well_name))
        known_norms.add(f"well {_norm(well.well_code)}")
        stripped = re.sub(r"^well[\s_-]+", "", _norm(well.well_name)).strip()
        if stripped:
            known_norms.add(stripped)
            known_norms.add(f"well {stripped}")

    for quoted in _QUOTED_RE.findall(question or ""):
        clean_q = quoted.strip()
        norm_q = _norm(clean_q)
        if not norm_q or norm_q in known_norms or norm_q in _WELL_STOPWORDS:
            continue
        if any(norm_q in k or k in norm_q for k in known_norms if k):
            continue
        if norm_q.startswith("well ") or re.fullmatch(r"[a-z]{1,6}[-_][a-z0-9_-]{1,20}", norm_q):
            if clean_q not in unmatched:
                unmatched.append(clean_q)

    for match in _NAMED_WELL_RE.finditer(question or ""):
        token = match.group(1).strip(".,;:!?")
        norm_tok = _norm(token)
        if not norm_tok or norm_tok in _WELL_STOPWORDS:
            continue
        candidate_label = f"Well {token}"
        if (
            norm_tok in known_norms
            or f"well {norm_tok}" in known_norms
            or any(norm_tok == _norm(u) or _norm(candidate_label) == _norm(u) for u in unmatched)
        ):
            continue
        unmatched.append(candidate_label)

    return ordered, unmatched[:4]


def _single_well_block(summary: DailyCostWellSummary) -> str:
    well = summary.well
    t = summary.totals
    cur = t.currency or ""
    p = f"{cur} " if cur else ""
    eff_afe = _effective_afe(summary)
    eff_bal = _effective_balance(summary)
    used_pct = _effective_used_pct(summary)
    lines = [
        f"Well {well.well_code} ({well.well_name}) | Rig: {well.rig_code} ({well.rig_name}) | Status: {well.status} | Plan: {well.config_status} | Currency: {cur or 'unset'}",
        f"  Effective AFE budget: {p}{_money(eff_afe)}"
        + (f" (SOW adjusted from original {p}{_money(t.planned)})" if t.has_adjustment and t.adjusted_planned is not None else ""),
        f"  Recorded actual cost (Daily Cost sheets): {p}{_money(t.actual)}",
        f"  LIH register cost: {p}{_money(t.lih_cost)} ({t.lih_entries} entries, {t.lih_line_count} lines) | Total cost incl. LIH: {p}{_money(t.actual_including_lih)}",
    ]
    if t.has_mud_reconciliation and t.comparison_actual is not None:
        lines.append(
            f"  Mud-reconciled comparison cost: {p}{_money(t.comparison_actual)} "
            f"(incl. LIH: {p}{_money(t.comparison_actual_including_lih)}; mud adjustment: {_signed_money(cur, t.mud_cost_adjustment)})"
        )
    lines.extend(
        [
            f"  Remaining AFE balance: {p}{_money(eff_bal)} | Actual / AFE %: {_pct(used_pct)}",
            f"  Cost groups: Services {p}{_money(t.services)}, Consumables {p}{_money(t.consumables)}, Tangibles {p}{_money(t.tangibles)}, Other Expenses {p}{_money(t.other_expenses)}",
            f"  Unplanned exposure: NPT {p}{_money(t.npt)}, UPA {p}{_money(t.upa)}",
            f"  Schedule & activity: {_days(_actual_days(summary))} actual days ({t.actual_days_basis or 'recorded'}) vs {_days(_effective_planned_days(summary))} planned days | Avg/day: {p}{_money(t.average_per_day)} | Sheets: {t.sheets} ({t.submitted_sheets} submitted, {t.draft_sheets} draft) | Period: {t.first_day or 'none'} to {t.last_day or 'none'}",
        ]
    )
    if summary.afes:
        afe_bits = [
            f"{a.afe_code} ({a.afe_status}, planned {a.currency} {_money(a.planned_total)}, actual {a.currency} {_money(a.actual)})"
            for a in summary.afes[:4]
        ]
        lines.append("  AFEs: " + "; ".join(afe_bits))
    unbudgeted = [b for b in summary.budget_lines if not b.is_planned and b.actual_to_date > 0]
    if unbudgeted:
        unbudgeted.sort(key=lambda item: item.actual_to_date, reverse=True)
        ub_bits = [f"{b.item_name} ({b.cost_group}: {p}{_money(b.actual_to_date)})" for b in unbudgeted[:4]]
        lines.append(f"  Unbudgeted items ({len(unbudgeted)}): " + "; ".join(ub_bits))
    return "\n".join(lines)


def build_well_comparison(
    db: Session,
    organization_id: str,
    wells: Sequence[Well],
    *,
    unmatched: Sequence[str] = (),
    all_well_labels: Sequence[str] = (),
) -> WellComparisonResult:
    """Compute an exact head-to-head comparison for the supplied workspace wells."""
    summaries = [
        daily_cost_service.well_cost_summary(db, organization_id, well.id, include_draft=True)
        for well in wells[:MAX_COMPARED_WELLS]
    ]
    unmatched_list = list(unmatched)
    missing_note = ""
    if unmatched_list:
        missing_names = ", ".join(f"'{name}'" for name in unmatched_list)
        available = f" Available workspace wells: {', '.join(all_well_labels[:8])}." if all_well_labels else ""
        missing_note = f" No workspace well matched {missing_names}.{available}"

    if len(summaries) == 1:
        s = summaries[0]
        t = s.totals
        cur = t.currency
        p = f"{cur} " if cur else ""
        eff_afe = _effective_afe(s)
        eff_bal = _effective_balance(s)
        used = _effective_used_pct(s)
        total_with_lih = t.actual_including_lih if t.lih_cost > 0 else t.actual
        lih_clause = f" (plus {p}{_money(t.lih_cost)} LIH = {p}{_money(total_with_lih)} total incl. LIH)" if t.lih_cost > 0 else ""
        prose = (
            f"{s.well.well_code} ({s.well.well_name}) has recorded actual cost of {p}{_money(t.actual)}{lih_clause} "
            f"against an effective AFE budget of {p}{_money(eff_afe)} ({_pct(used)} used, {p}{_money(eff_bal)} remaining) "
            f"across {t.sheets} daily cost sheet(s).{missing_note}"
        )
        facts = [
            AssistantFact(label=f"{s.well.well_code} actual cost", value=f"{p}{_money(t.actual)}", hint=s.well.well_name, route=f"/daily-cost/analysis/{s.well.id}", permission="daily-cost:read"),
            AssistantFact(label=f"{s.well.well_code} AFE budget", value=f"{p}{_money(eff_afe)}", hint="SOW-adjusted" if t.has_adjustment else "Original AFE", route="/afe/register", permission="afe:read"),
            AssistantFact(label="Remaining balance", value=f"{p}{_money(eff_bal)}", hint=f"Actual / AFE: {_pct(used)}", route=f"/daily-cost/analysis/{s.well.id}", permission="daily-cost:read"),
        ]
        if t.lih_cost > 0:
            facts.append(AssistantFact(label="Total incl. LIH", value=f"{p}{_money(total_with_lih)}", hint=f"Includes {p}{_money(t.lih_cost)} LIH", route="/daily-cost/lih-register", permission="daily-cost:read"))
        table = AssistantTable(
            title=f"{s.well.well_code} · {s.well.well_name} cost breakdown",
            columns=["Category", "Amount"],
            rows=[
                ["Services", f"{p}{_money(t.services)}"],
                ["Consumables", f"{p}{_money(t.consumables)}"],
                ["Tangibles", f"{p}{_money(t.tangibles)}"],
                ["Other expenses", f"{p}{_money(t.other_expenses)}"],
                ["Recorded actual total", f"{p}{_money(t.actual)}"],
                *(
                    [["LIH cost", f"{p}{_money(t.lih_cost)}"], ["Total cost (incl. LIH)", f"{p}{_money(total_with_lih)}"]]
                    if t.lih_cost > 0
                    else []
                ),
                ["NPT exposure", f"{p}{_money(t.npt)}"],
                ["UPA exposure", f"{p}{_money(t.upa)}"],
            ],
            numeric=[1],
            footer=f"Includes draft sheets ({t.submitted_sheets} submitted, {t.draft_sheets} draft).{missing_note}".strip(),
        )
        sources = [
            AssistantSource(label=f"{s.well.well_code} cost analysis", route=f"/daily-cost/analysis/{s.well.id}"),
            AssistantSource(label="Well cost comparison", route="/reports/well-cost-comparison"),
        ]
        ctx = _single_well_block(s)
        if missing_note:
            ctx += f"\nUNMATCHED WELL REFERENCES:{missing_note}"
        return WellComparisonResult(
            summaries=summaries,
            unmatched=unmatched_list,
            prose=prose,
            facts=facts,
            tables=[table],
            sources=sources,
            follow_ups=["Compare all active wells", f"Entry checks for {s.well.well_code}"],
            context_block=ctx,
        )

    if len(summaries) == 2:
        a, b = summaries[0], summaries[1]
        ta, tb = a.totals, b.totals
        ca, cb = ta.currency, tb.currency
        pa, pb = (f"{ca} " if ca else ""), (f"{cb} " if cb else "")
        same_cur = bool(ca and cb and ca == cb)
        afe_a, afe_b = _effective_afe(a), _effective_afe(b)
        bal_a, bal_b = _effective_balance(a), _effective_balance(b)
        used_a, used_b = _effective_used_pct(a), _effective_used_pct(b)
        any_lih = ta.lih_cost > 0 or tb.lih_cost > 0
        tot_a = ta.actual_including_lih if any_lih else ta.actual
        tot_b = tb.actual_including_lih if any_lih else tb.actual
        days_a, days_b = _actual_days(a), _actual_days(b)
        pdays_a, pdays_b = _effective_planned_days(a), _effective_planned_days(b)

        def diff_cell(va: Decimal, vb: Decimal) -> str:
            return _signed_money(ca, va - vb) if same_cur else "Different currencies"

        rows: list[list[str]] = [
            ["Effective AFE budget", f"{pa}{_money(afe_a)}", f"{pb}{_money(afe_b)}", diff_cell(afe_a, afe_b)],
            ["Recorded actual cost", f"{pa}{_money(ta.actual)}", f"{pb}{_money(tb.actual)}", diff_cell(ta.actual, tb.actual)],
        ]
        if any_lih:
            rows.append(["LIH register cost", f"{pa}{_money(ta.lih_cost)}", f"{pb}{_money(tb.lih_cost)}", diff_cell(ta.lih_cost, tb.lih_cost)])
            rows.append(["Total cost (incl. LIH)", f"{pa}{_money(tot_a)}", f"{pb}{_money(tot_b)}", diff_cell(tot_a, tot_b)])
        if ta.has_mud_reconciliation or tb.has_mud_reconciliation:
            comp_a = ta.comparison_actual_including_lih if any_lih else (ta.comparison_actual or ta.actual)
            comp_b = tb.comparison_actual_including_lih if any_lih else (tb.comparison_actual or tb.actual)
            rows.append(["Mud-reconciled total", f"{pa}{_money(comp_a)}", f"{pb}{_money(comp_b)}", diff_cell(comp_a, comp_b)])
        used_diff = "—"
        if used_a is not None and used_b is not None:
            d_pct = used_a - used_b
            used_diff = f"{'+' if d_pct > 0 else ''}{d_pct:.1f} pp"
        day_diff = days_a - days_b
        day_diff_text = f"{'+' if day_diff > 0 else ''}{_days(day_diff)} d"
        rows.extend(
            [
                ["Remaining AFE balance", f"{pa}{_money(bal_a)}", f"{pb}{_money(bal_b)}", diff_cell(bal_a, bal_b)],
                ["Actual / AFE %", _pct(used_a), _pct(used_b), used_diff],
                ["Services", f"{pa}{_money(ta.services)}", f"{pb}{_money(tb.services)}", diff_cell(ta.services, tb.services)],
                ["Consumables", f"{pa}{_money(ta.consumables)}", f"{pb}{_money(tb.consumables)}", diff_cell(ta.consumables, tb.consumables)],
                ["Tangibles", f"{pa}{_money(ta.tangibles)}", f"{pb}{_money(tb.tangibles)}", diff_cell(ta.tangibles, tb.tangibles)],
                ["Other expenses", f"{pa}{_money(ta.other_expenses)}", f"{pb}{_money(tb.other_expenses)}", diff_cell(ta.other_expenses, tb.other_expenses)],
                ["NPT cost", f"{pa}{_money(ta.npt)}", f"{pb}{_money(tb.npt)}", diff_cell(ta.npt, tb.npt)],
                ["UPA cost", f"{pa}{_money(ta.upa)}", f"{pb}{_money(tb.upa)}", diff_cell(ta.upa, tb.upa)],
                ["Actual / planned days", f"{_days(days_a)} / {_days(pdays_a)} d", f"{_days(days_b)} / {_days(pdays_b)} d", day_diff_text],
                ["Average daily cost", f"{pa}{_money(ta.average_per_day)}", f"{pb}{_money(tb.average_per_day)}", diff_cell(ta.average_per_day, tb.average_per_day)],
                ["Daily sheets", f"{ta.sheets} ({ta.draft_sheets} draft)", f"{tb.sheets} ({tb.draft_sheets} draft)", f"{ta.sheets - tb.sheets:+d}"],
            ]
        )

        label_metric = "total cost (incl. LIH)" if any_lih else "total actual cost"
        driver_sentence = ""
        if same_cur:
            delta = tot_a - tot_b
            pct_vs_b = ""
            if tot_b > 0:
                rel = ((delta / tot_b) * Decimal("100")).quantize(Decimal("0.1"))
                pct_vs_b = f" ({'+' if rel > 0 else ''}{rel}% vs {b.well.well_code})"
            if delta > 0:
                relation = f"{a.well.well_code} is {pa}{_money(delta)} higher than {b.well.well_code}{pct_vs_b}"
            elif delta < 0:
                relation = f"{a.well.well_code} is {pa}{_money(abs(delta))} lower than {b.well.well_code}{pct_vs_b}"
            else:
                relation = f"{a.well.well_code} and {b.well.well_code} have identical {label_metric}"
            group_deltas = [
                ("Services", ta.services - tb.services),
                ("Consumables", ta.consumables - tb.consumables),
                ("Tangibles", ta.tangibles - tb.tangibles),
                ("Other expenses", ta.other_expenses - tb.other_expenses),
            ]
            if any_lih:
                group_deltas.append(("LIH", ta.lih_cost - tb.lih_cost))
            top_group, top_gap = max(group_deltas, key=lambda item: abs(item[1]))
            if top_gap != 0:
                driver_sentence = f" Largest variance driver: {top_group} ({_signed_money(ca, top_gap)})."
            prose = (
                f"{a.well.well_code} ({a.well.well_name}) {label_metric} is {pa}{_money(tot_a)} "
                f"(AFE {pa}{_money(afe_a)}, {_pct(used_a)} used), compared with "
                f"{b.well.well_code} ({b.well.well_name}) at {pb}{_money(tot_b)} "
                f"(AFE {pb}{_money(afe_b)}, {_pct(used_b)} used) — {relation}.{driver_sentence}{missing_note}"
            )
            diff_fact_value = _signed_money(ca, delta)
            diff_fact_hint = f"{a.well.well_code} minus {b.well.well_code}{pct_vs_b}"
            footer_text = f"All amounts in {ca}; includes submitted and draft daily sheets."
        else:
            prose = (
                f"{a.well.well_code} ({a.well.well_name}) {label_metric} is {pa}{_money(tot_a)} "
                f"(AFE {pa}{_money(afe_a)}, {_pct(used_a)} used), while "
                f"{b.well.well_code} ({b.well.well_name}) is {pb}{_money(tot_b)} "
                f"(AFE {pb}{_money(afe_b)}, {_pct(used_b)} used). Because the two wells report in different currencies "
                f"({ca or 'unset'} vs {cb or 'unset'}), monetary totals are kept separate without unverified conversion.{missing_note}"
            )
            diff_fact_value = f"{ca or '—'} vs {cb or '—'}"
            diff_fact_hint = f"Actual / AFE delta: {used_diff}"
            footer_text = "Currencies differ between wells; direct cash differences are omitted until expressed in one currency."

        facts = [
            AssistantFact(
                label=f"{a.well.well_code} total cost",
                value=f"{pa}{_money(tot_a)}",
                hint=f"{a.well.well_name} · {_pct(used_a)} of AFE",
                route=f"/daily-cost/analysis/{a.well.id}",
                permission="daily-cost:read",
            ),
            AssistantFact(
                label=f"{b.well.well_code} total cost",
                value=f"{pb}{_money(tot_b)}",
                hint=f"{b.well.well_name} · {_pct(used_b)} of AFE",
                route=f"/daily-cost/analysis/{b.well.id}",
                permission="daily-cost:read",
            ),
            AssistantFact(
                label="Cost difference",
                value=diff_fact_value,
                hint=diff_fact_hint,
                route="/reports/well-cost-comparison",
                permission="daily-cost:read",
            ),
            AssistantFact(
                label=f"{a.well.well_code} balance",
                value=f"{pa}{_money(bal_a)}",
                hint=f"AFE {pa}{_money(afe_a)}",
                route=f"/daily-cost/analysis/{a.well.id}",
                permission="daily-cost:read",
            ),
            AssistantFact(
                label=f"{b.well.well_code} balance",
                value=f"{pb}{_money(bal_b)}",
                hint=f"AFE {pb}{_money(afe_b)}",
                route=f"/daily-cost/analysis/{b.well.id}",
                permission="daily-cost:read",
            ),
        ]
        table = AssistantTable(
            title=f"Well cost comparison · {a.well.well_code} vs {b.well.well_code}",
            columns=[
                "Metric",
                f"{a.well.well_code} · {a.well.well_name}",
                f"{b.well.well_code} · {b.well.well_name}",
                f"Difference ({a.well.well_code} − {b.well.well_code})",
            ],
            rows=rows,
            numeric=[1, 2, 3],
            footer=f"{footer_text}{missing_note}".strip(),
        )
        sources = [
            AssistantSource(label=f"{a.well.well_code} cost analysis", route=f"/daily-cost/analysis/{a.well.id}"),
            AssistantSource(label=f"{b.well.well_code} cost analysis", route=f"/daily-cost/analysis/{b.well.id}"),
            AssistantSource(label="Well cost comparison", route="/reports/well-cost-comparison"),
        ]
        ctx_lines = [
            f"EXACT PAIRWISE WELL COMPARISON ({a.well.well_code} vs {b.well.well_code}):",
            _single_well_block(a),
            _single_well_block(b),
            "  Computed deltas (" + f"{a.well.well_code} minus {b.well.well_code}" + "): "
            + (
                f"Recorded actual {diff_cell(ta.actual, tb.actual)}, Total incl. LIH {diff_cell(tot_a, tot_b)}, "
                f"AFE budget {diff_cell(afe_a, afe_b)}, Balance {diff_cell(bal_a, bal_b)}, "
                f"Services {diff_cell(ta.services, tb.services)}, Consumables {diff_cell(ta.consumables, tb.consumables)}, "
                f"Tangibles {diff_cell(ta.tangibles, tb.tangibles)}, Other {diff_cell(ta.other_expenses, tb.other_expenses)}, "
                f"NPT {diff_cell(ta.npt, tb.npt)}, UPA {diff_cell(ta.upa, tb.upa)}, Actual/AFE {used_diff}, Days {day_diff_text}."
                if same_cur
                else f"Different standard currencies ({ca} vs {cb}); do not subtract cash amounts. Actual/AFE delta: {used_diff}, Days delta: {day_diff_text}."
            ),
        ]
        if missing_note:
            ctx_lines.append(f"UNMATCHED WELL REFERENCES:{missing_note}")
        return WellComparisonResult(
            summaries=summaries,
            unmatched=unmatched_list,
            prose=prose,
            facts=facts,
            tables=[table],
            sources=sources,
            follow_ups=[
                f"Cost breakdown of {a.well.well_code}",
                f"Cost breakdown of {b.well.well_code}",
                "Which wells have cost anomalies?",
            ],
            context_block="\n".join(ctx_lines),
        )

    # 3+ wells comparison matrix
    matrix_rows: list[list[str]] = []
    currencies = {s.totals.currency for s in summaries if s.totals.currency}
    for s in summaries:
        t = s.totals
        p = f"{t.currency} " if t.currency else ""
        total_cost = t.actual_including_lih if t.lih_cost > 0 else t.actual
        matrix_rows.append(
            [
                f"{s.well.well_code} · {s.well.well_name}",
                s.well.rig_code,
                s.well.status.replace("_", " ").title(),
                f"{p}{_money(_effective_afe(s))}",
                f"{p}{_money(total_cost)}",
                f"{p}{_money(t.lih_cost)}",
                f"{p}{_money(_effective_balance(s))}",
                _pct(_effective_used_pct(s)),
                f"{p}{_money(t.npt)}",
                f"{_days(_actual_days(s))} / {_days(_effective_planned_days(s))}",
            ]
        )

    facts = [
        AssistantFact(label="Wells compared", value=str(len(summaries)), route="/reports/well-cost-comparison", permission="daily-cost:read"),
    ]
    if len(currencies) == 1:
        cur = next(iter(currencies))
        p = f"{cur} "
        ranked = sorted(
            summaries,
            key=lambda item: item.totals.actual_including_lih if item.totals.lih_cost > 0 else item.totals.actual,
            reverse=True,
        )
        top, low = ranked[0], ranked[-1]
        top_val = top.totals.actual_including_lih if top.totals.lih_cost > 0 else top.totals.actual
        low_val = low.totals.actual_including_lih if low.totals.lih_cost > 0 else low.totals.actual
        combined = sum((s.totals.actual_including_lih if s.totals.lih_cost > 0 else s.totals.actual) for s in summaries)
        facts.extend(
            [
                AssistantFact(label="Highest cost", value=f"{top.well.well_code} · {p}{_money(top_val)}", hint=top.well.well_name, route=f"/daily-cost/analysis/{top.well.id}", permission="daily-cost:read"),
                AssistantFact(label="Lowest cost", value=f"{low.well.well_code} · {p}{_money(low_val)}", hint=low.well.well_name, route=f"/daily-cost/analysis/{low.well.id}", permission="daily-cost:read"),
                AssistantFact(label="Combined spend", value=f"{p}{_money(combined)}", hint=f"Spread {p}{_money(top_val - low_val)}", route="/reports/well-cost-comparison", permission="daily-cost:read"),
            ]
        )
        prose = (
            f"Compared {len(summaries)} wells ({cur}): {top.well.well_code} has the highest total cost at {p}{_money(top_val)} "
            f"({_pct(_effective_used_pct(top))} of AFE) and {low.well.well_code} has the lowest at {p}{_money(low_val)} "
            f"({_pct(_effective_used_pct(low))} of AFE); spread is {p}{_money(top_val - low_val)} and combined spend is {p}{_money(combined)}.{missing_note}"
        )
    else:
        prose = (
            f"Compared {len(summaries)} workspace wells across {len(currencies) or 1} reporting currencies "
            f"({', '.join(sorted(currencies)) or 'unset'}). Each row preserves its well's standard currency.{missing_note}"
        )

    table = AssistantTable(
        title=f"Multi-well cost comparison ({len(summaries)} wells)",
        columns=["Well", "Rig", "Status", "AFE Budget", "Total Cost", "LIH", "Remaining", "Actual / AFE %", "NPT", "Days"],
        rows=matrix_rows,
        numeric=[3, 4, 5, 6, 7, 8, 9],
        footer=f"Total Cost includes LIH where recorded; includes draft sheets.{missing_note}".strip(),
    )
    sources = [AssistantSource(label="Well cost comparison", route="/reports/well-cost-comparison")] + [
        AssistantSource(label=f"{s.well.well_code} analysis", route=f"/daily-cost/analysis/{s.well.id}")
        for s in summaries[:3]
    ]
    ctx = "MULTI-WELL COMPARISON:\n" + "\n".join(_single_well_block(s) for s in summaries)
    if missing_note:
        ctx += f"\nUNMATCHED WELL REFERENCES:{missing_note}"
    return WellComparisonResult(
        summaries=summaries,
        unmatched=unmatched_list,
        prose=prose,
        facts=facts,
        tables=[table],
        sources=sources,
        follow_ups=["Which wells have cost anomalies?", "Show workspace summary"],
        context_block=ctx,
    )


def _catalogue_section(db: Session, organization_id: str, question: str) -> str:
    tokens = [
        tok for tok in re.findall(r"[a-z0-9./\"'-]{3,}", _norm(question))
        if tok not in _WELL_STOPWORDS
        and tok not in {"price", "prices", "rate", "rates", "catalogue", "catalog", "item", "items", "unit", "show", "find", "give", "need"}
    ]
    lines: list[str] = []
    default_cur = db.scalar(
        select(Currency.currency_code).where(
            Currency.organization_id == organization_id,
            Currency.is_deleted.is_(False),
            Currency.is_default.is_(True),
        )
    ) or "unset"
    vendor_count = db.scalar(
        select(func.count(Vendor.id)).where(Vendor.organization_id == organization_id, Vendor.is_deleted.is_(False))
    ) or 0
    po_count = db.scalar(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
            PurchaseOrder.is_current.is_(True),
        )
    ) or 0
    svc_count = db.scalar(
        select(func.count(Service.id)).where(Service.organization_id == organization_id, Service.is_deleted.is_(False))
    ) or 0
    lines.append(
        f"Master data overview: default currency={default_cur}, active vendors={vendor_count}, current PO/SO orders={po_count}, active services={svc_count}."
    )

    if tokens:
        vendors = db.scalars(
            select(Vendor)
            .where(Vendor.organization_id == organization_id, Vendor.is_deleted.is_(False))
            .order_by(Vendor.vendor_code)
        ).all()
        matched_vendors = [
            v for v in vendors
            if any(tok in f"{v.vendor_code} {v.vendor_name} {v.category}".lower() for tok in tokens)
        ][:8]
        if matched_vendors:
            lines.append(
                "Matching vendors: "
                + "; ".join(f"{v.vendor_code} ({v.vendor_name}, {v.vendor_type}, {v.category or 'uncategorized'}, status={v.status})" for v in matched_vendors)
            )

        services = db.scalars(
            select(Service)
            .where(Service.organization_id == organization_id, Service.is_deleted.is_(False))
            .order_by(Service.service_code)
        ).all()
        matched_services = [
            s for s in services
            if any(
                tok in f"{s.service_code} {s.service_name} {s.service_group} {s.service_category}".lower()
                for tok in tokens
            )
        ][:8]
        if matched_services:
            lines.append(
                "Matching services: "
                + "; ".join(
                    f"{s.service_code} ({s.service_name}, category={s.service_category}, group={s.service_group}, "
                    f"provider={s.vendor.vendor_name if s.vendor else s.provider_type})"
                    for s in matched_services
                )
            )

        cat_hits: list[str] = []
        catalogue_specs = (
            ("Tangible", Tangible, "tangible_code", "tangible_name", "uom"),
            ("Drill bit", DrillBit, "bit_code", "bit_name", ""),
            ("Mud chemical", MudChemical, "chemical_code", "chemical_name", "uom"),
            ("Cement additive", CementAdditive, "additive_code", "additive_name", "uom"),
            ("Fuel", FuelType, "fuel_code", "fuel_name", "uom"),
        )
        for label, model, code_attr, name_attr, uom_attr in catalogue_specs:
            rows = db.scalars(
                select(model).where(model.organization_id == organization_id, model.is_deleted.is_(False))
            ).all()
            for row in rows:
                code = getattr(row, code_attr)
                name = getattr(row, name_attr)
                extra = f"{getattr(row, 'size', '')} {getattr(row, 'model_no', '')} {getattr(row, 'part_number', '')} {row.remarks}"
                hay = f"{code} {name} {extra}".lower()
                if any(tok in hay for tok in tokens):
                    cur = row.currency or default_cur
                    uom = getattr(row, uom_attr, "EA") if uom_attr else "EA"
                    eff = f", eff {row.effective_date}" if row.effective_date else ""
                    final_note = (
                        f", final incl. uplift {cur} {_money(row.final_cost)}"
                        if row.final_cost is not None and row.final_cost != row.unit_rate
                        else ""
                    )
                    cat_hits.append(f"{label} {code} ({name}): {cur} {_money(row.unit_rate)}/{uom or 'unit'}{final_note}{eff}")
                    if len(cat_hits) >= 12:
                        break
            if len(cat_hits) >= 12:
                break
        if cat_hits:
            lines.append("Matching priced catalogue items:\n  - " + "\n  - ".join(cat_hits))
    return "\n".join(lines)


def _operational_registers_section(
    db: Session,
    organization_id: str,
    question: str,
    focus_wells: Sequence[Well],
    all_wells: Sequence[Well],
) -> str:
    lower = _norm(question)
    parts: list[str] = []
    target_wells = list(focus_wells[:3]) if focus_wells else list(all_wells[:4])

    if any(k in lower for k in ("mud", "obm", "wbm", "sobm", "bbl", "barrel", "loss", "losses", "reconcil")):
        mud_lines: list[str] = []
        for well in target_wells:
            recon = mud_cost_service.mud_cost_reconciliation(
                db, organization_id, rig_id=well.rig_id, well_id=well.id
            )
            if recon.entry_count > 0 or recon.configured_section_count > 0:
                cur = recon.currency or ""
                p = f"{cur} " if cur else ""
                mud_lines.append(
                    f"  - {well.well_code} ({well.well_name}): {recon.entry_count} entries, {recon.configured_section_count} configured sections, "
                    f"actual mud cost {p}{_money(recon.total_actual_cost)}, reconciled {p}{_money(recon.total_reconciled_cost)}, "
                    f"adjustment {_signed_money(cur, recon.total_adjustment)}, total losses {_days(recon.total_consumption_losses)} bbl, "
                    f"latest Cost/BBL {p}{_money(recon.latest_cost_per_bbl) if recon.latest_cost_per_bbl is not None else '—'}"
                )
        parts.append("Mud Cost Register:\n" + ("\n".join(mud_lines) if mud_lines else "  No mud cost entries recorded for the inspected wells."))

    if any(k in lower for k in ("lih", "lost in hole", "lost-in-hole", "fish", "downhole loss")):
        lih_lines: list[str] = []
        for well in target_wells:
            rep = lih_cost_service.well_report(db, organization_id, well_id=well.id)
            if rep.entry_count > 0:
                p = f"{rep.currency} " if rep.currency else ""
                lih_lines.append(
                    f"  - {well.well_code} ({well.well_name}): {rep.entry_count} LIH day(s), {rep.line_count} item(s), total {p}{_money(rep.total)}"
                )
        parts.append("LIH (Lost In Hole) Register:\n" + ("\n".join(lih_lines) if lih_lines else "  No LIH entries recorded for the inspected wells."))

    if any(k in lower for k in ("fuel", "ago", "diesel", "hsd", "litre", "liter", "rig saving", "gas saving", "gas consumption")):
        rigs = db.scalars(
            select(Rig).where(Rig.organization_id == organization_id, Rig.is_deleted.is_(False)).order_by(Rig.rig_code)
        ).all()
        fuel_lines: list[str] = []
        for rig in rigs[:8]:
            fs = fuel_cost_service.rig_summary(db, organization_id, rig_id=rig.id)
            if fs.total_active_days > 0:
                fuel_lines.append(
                    f"  - Rig {rig.rig_code} ({rig.rig_name}): {fs.total_active_days} day(s) ({fs.earliest_date} to {fs.latest_date}), "
                    f"opening {_days(fs.opening_stock)}, receipts {_days(fs.receipt)}, rig engines {_days(fs.rig_engine_consumption)}, "
                    f"company lines {_days(fs.company_consumption)}, total consumed {_days(fs.total_consumption)}, "
                    f"actual closing {_days(fs.actual_closing_stock)}, adjustments {_days(fs.adjustments)}, rig saving {_days(fs.rig_saving_litres)} L"
                )
        parts.append("Fuel Cost Register (rig-scoped):\n" + ("\n".join(fuel_lines) if fuel_lines else "  No fuel days recorded in this workspace."))

    if any(k in lower for k in ("ndt", "inspection", "backload", "backloaded", "mpi", "tubular inspection")):
        ndt_rows = db.scalars(
            select(NdtInspection)
            .where(NdtInspection.organization_id == organization_id, NdtInspection.is_deleted.is_(False))
            .order_by(NdtInspection.well_code_snapshot, NdtInspection.created_at.desc())
        ).all()
        if focus_wells:
            focus_ids = {w.id for w in focus_wells}
            ndt_rows = [row for row in ndt_rows if row.well_id in focus_ids]
        if ndt_rows:
            ndt_lines = [
                f"  - {r.well_code_snapshot} ({r.scope}): {r.description} | recv {_days(r.quantity_received)}, "
                f"consumed {_days(r.quantity_consumed)}, backload good {_days(r.quantity_backloaded_good)}, bad {_days(r.quantity_backloaded_bad)}"
                for r in ndt_rows[:10]
            ]
            parts.append(f"NDT Inspection Register ({len(ndt_rows)} matching line(s)):\n" + "\n".join(ndt_lines))
        else:
            parts.append("NDT Inspection Register: No NDT inspection lines recorded.")

    return "\n".join(parts)


def _invoice_section(db: Session, organization_id: str, question: str, focus_wells: Sequence[Well]) -> str:
    dash = invoice_service.dashboard_data(db, organization_id)
    lines = [
        f"Invoice Processing / IDVS summary (as of {dash.as_of}): total={dash.total_invoices}, "
        f"draft={dash.draft_count}, submitted={dash.submitted_count}, sent_to_accounts={dash.sent_to_accounts_count}, "
        f"epicor_pending={dash.epicor_pending_count}, approved={dash.approved_count}, paid={dash.paid_count}, "
        f"overdue={dash.overdue_count}, with_discrepancy={dash.discrepancy_count}."
    ]
    if dash.currency_totals:
        cur_bits = [
            f"{ct.currency_code}: invoiced {_money(ct.invoice_total)}, verified {_money(ct.verified_total)}, net payable {_money(ct.net_payable_amount)} ({ct.invoice_count} inv)"
            for ct in dash.currency_totals[:6]
        ]
        lines.append("Invoice totals by currency (never combine across currencies): " + " | ".join(cur_bits))

    all_invoices = invoice_service.list_invoices(db, organization_id)
    if all_invoices:
        lower = _norm(question)
        focus_well_ids = {w.id for w in focus_wells}
        tokens = [
            t for t in re.findall(r"[a-z0-9_-]{3,}", lower)
            if t not in _WELL_STOPWORDS and t not in {"invoice", "invoices", "idvs", "epicor", "paid", "payable", "vendor", "vendors", "status"}
        ]
        filtered = [
            inv for inv in all_invoices
            if (inv.well_id and inv.well_id in focus_well_ids)
            or any(tok in f"{inv.idvs_number} {inv.invoice_number} {inv.vendor_name} {inv.vendor_code} {inv.well_code}".lower() for tok in tokens)
        ]
        chosen = (filtered or all_invoices)[:8]
        lines.append("Invoice records:")
        for inv in chosen:
            overdue_tag = " [OVERDUE]" if inv.is_overdue else ""
            lines.append(
                f"  - {inv.idvs_number} / Inv {inv.invoice_number} | Vendor: {inv.vendor_name} | Well: {inv.well_code or '—'} | "
                f"Status: {inv.display_status}{overdue_tag} | {inv.currency_code} invoiced {_money(inv.invoice_total)}, "
                f"verified {_money(inv.verified_total)}, net payable {_money(inv.net_payable_amount)} | Due: {inv.due_date}"
            )
    return "\n".join(lines)


def _has_cap(capabilities: set[str], key: str) -> bool:
    return "*" in capabilities or key in capabilities


def _anomaly_section(
    db: Session,
    organization_id: str,
    user: User,
    capabilities: set[str],
    focus_wells: Sequence[Well],
) -> str:
    lines: list[str] = []
    if _has_cap(capabilities, "cost-intelligence:read"):
        well_filter = focus_wells[0].id if len(focus_wells) == 1 else ""
        overview = ci_service.overview(
            db,
            user,
            well_id=well_filter,
            include_draft=True,
        )
        k = overview.kpis
        lines.append(
            f"Cost Intelligence overview (as of {overview.as_of}): {k.wells} well(s) ({k.analysed_wells} analysed), "
            f"portfolio health score {k.score}/100 ({k.band}), wells at risk={k.wells_at_risk}, "
            f"findings: {k.critical} critical, {k.warning} warning, {k.info} info."
        )
        for f in overview.findings[:8]:
            d_txt = f" on {f.cost_date}" if f.cost_date else ""
            lines.append(f"  - [{f.severity.upper()}] {f.well_code}{d_txt} · {f.title}: {f.detail} (Basis: {f.basis})")

    if _has_cap(capabilities, "daily-cost:read") and entry_checks_service.enabled():
        for well in focus_wells[:3]:
            checks = entry_checks_service.checks_for_well(db, organization_id, well.id)
            if checks.open_warnings or checks.open_notices:
                lines.append(
                    f"Entry-check potential mistakes on {well.well_code}: {checks.open_warnings} warning(s), "
                    f"{checks.open_notices} notice(s) across {checks.sheets_with_findings}/{checks.sheets_checked} sheet(s):"
                )
                shown = 0
                for sheet in checks.sheets:
                    for item in sheet.checks:
                        if item.reviewed:
                            continue
                        fix = f" -> suggested {item.suggested_display}" if item.suggested_display else ""
                        lines.append(
                            f"  - [{item.severity.upper()}] {sheet.daily_cost_code} ({sheet.cost_date}) {item.title}: "
                            f"{item.message}{fix}"
                        )
                        shown += 1
                        if shown >= 6:
                            break
                    if shown >= 6:
                        break
    return "\n".join(lines)


def build_assistant_dossier(
    db: Session,
    organization_id: str,
    *,
    user: User,
    question: str,
    route: str,
    capabilities: set[str],
    matched_memories: Sequence[AssistantMemory],
    focus_wells: Sequence[Well],
    unmatched_wells: Sequence[str],
    comparison: WellComparisonResult | None,
) -> str:
    """Assemble a bounded, tenant-scoped database + workflow dossier for Ollama."""
    lower = _norm(question)
    watched_caps = (
        "master-data:read",
        "rig-well:read",
        "afe:read",
        "daily-cost:read",
        "cost-intelligence:read",
        "invoice-processing:read",
        "reports:read",
        "backup:read",
        "audit:read",
    )
    granted = [cap for cap in watched_caps if _has_cap(capabilities, cap)]
    restricted = [cap for cap in watched_caps if not _has_cap(capabilities, cap)]

    sections: list[str] = [
        f"CURRENT DATE: {date.today().isoformat()}\n"
        f"CALLER PAGE ROUTE: {route or '/'}\n"
        f"CALLER PERMITTED CAPABILITIES: {', '.join(granted) or 'assistant:read only'}\n"
        f"CALLER RESTRICTED CAPABILITIES (no data loaded for these): {', '.join(restricted) or 'none'}",
        WORKFLOW_MAP,
    ]

    if matched_memories:
        mem_lines = ["MATCHING WORKSPACE & APPLICATION MEMORY RULES:"]
        for mem in matched_memories[:5]:
            scope_tag = "Application rule" if mem.is_system else "Workspace rule"
            route_hint = f" [Page: {mem.route}]" if mem.route else ""
            steps_hint = f" Steps: {mem.steps.replace(chr(10), ' -> ')}" if mem.steps.strip() else ""
            mem_lines.append(f"- ({scope_tag}) {mem.title}{route_hint}: {mem.body}{steps_hint}")
        sections.append("\n".join(mem_lines))

    all_wells: list[Well] = []
    if _has_cap(capabilities, "rig-well:read") or _has_cap(capabilities, "daily-cost:read"):
        all_wells = list(
            db.scalars(
                select(Well)
                .where(Well.organization_id == organization_id, Well.is_deleted.is_(False))
                .order_by(Well.well_code)
            ).all()
        )

    if _has_cap(capabilities, "rig-well:read"):
        rig_count = db.scalar(
            select(func.count(Rig.id)).where(Rig.organization_id == organization_id, Rig.is_deleted.is_(False))
        ) or 0
        block_count = db.scalar(
            select(func.count(Block.id)).where(Block.organization_id == organization_id, Block.is_deleted.is_(False))
        ) or 0
        status_counts: dict[str, int] = {}
        for w in all_wells:
            status_counts[w.status] = status_counts.get(w.status, 0) + 1
        status_txt = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items())) or "none"
        sections.append(
            f"WORKSPACE ASSET COUNTS: blocks={block_count}, rigs={rig_count}, wells={len(all_wells)} ({status_txt})."
        )

    if _has_cap(capabilities, "daily-cost:read") and all_wells:
        # Portfolio register across wells (capped at 15 so prompt stays compact).
        reg_lines = [f"VERIFIED WELL COST REGISTER ({min(len(all_wells), 15)} of {len(all_wells)} well(s), includes draft sheets):"]
        portfolio_by_cur: dict[str, dict[str, Decimal]] = {}
        for well in all_wells[:15]:
            ws = daily_cost_service.well_cost_summary(db, organization_id, well.id, include_draft=True)
            t = ws.totals
            cur = t.currency or "UNSET"
            p = f"{t.currency} " if t.currency else ""
            eff_afe = _effective_afe(ws)
            eff_bal = _effective_balance(ws)
            used = _effective_used_pct(ws)
            lih_note = f", LIH={p}{_money(t.lih_cost)}, total_incl_LIH={p}{_money(t.actual_including_lih)}" if t.lih_cost > 0 else ""
            reg_lines.append(
                f"- {well.well_code} ({well.well_name}) | rig={ws.well.rig_code} | status={well.status} | "
                f"AFE={p}{_money(eff_afe)} | actual={p}{_money(t.actual)}{lih_note} | balance={p}{_money(eff_bal)} | "
                f"used={_pct(used)} | svc={p}{_money(t.services)}, cons={p}{_money(t.consumables)}, tang={p}{_money(t.tangibles)}, "
                f"other={p}{_money(t.other_expenses)} | NPT={p}{_money(t.npt)}, UPA={p}{_money(t.upa)} | "
                f"days={_days(_actual_days(ws))}/{_days(_effective_planned_days(ws))} | sheets={t.sheets}"
            )
            bucket = portfolio_by_cur.setdefault(
                cur,
                {"afe": Decimal("0"), "actual": Decimal("0"), "lih": Decimal("0"), "total": Decimal("0"), "npt": Decimal("0"), "upa": Decimal("0")},
            )
            bucket["afe"] += eff_afe
            bucket["actual"] += t.actual
            bucket["lih"] += t.lih_cost
            bucket["total"] += t.actual_including_lih
            bucket["npt"] += t.npt
            bucket["upa"] += t.upa
        for cur, agg in sorted(portfolio_by_cur.items()):
            label_cur = "" if cur == "UNSET" else f"{cur} "
            reg_lines.append(
                f"Portfolio total ({cur}): AFE={label_cur}{_money(agg['afe'])}, recorded_actual={label_cur}{_money(agg['actual'])}, "
                f"LIH={label_cur}{_money(agg['lih'])}, total_incl_LIH={label_cur}{_money(agg['total'])}, "
                f"NPT={label_cur}{_money(agg['npt'])}, UPA={label_cur}{_money(agg['upa'])}."
            )
        sections.append("\n".join(reg_lines))
    elif _has_cap(capabilities, "rig-well:read") and all_wells:
        well_lines = ["WORKSPACE WELLS (caller lacks daily-cost:read so cost figures are omitted):"]
        for w in all_wells[:15]:
            well_lines.append(f"- {w.well_code} ({w.well_name}) | status={w.status} | plan={w.config_status}")
        sections.append("\n".join(well_lines))

    if comparison is not None:
        sections.append(comparison.context_block)
    elif unmatched_wells:
        available = ", ".join(f"{w.well_code} ({w.well_name})" for w in all_wells[:10]) or "none"
        sections.append(
            f"UNMATCHED REFERENCES: No well in this workspace matched {', '.join(repr(u) for u in unmatched_wells)}. "
            f"Available workspace wells: {available}."
        )

    if _has_cap(capabilities, "afe:read") and (
        focus_wells or any(k in lower for k in ("afe", "budget", "estimate", "sow", "scope of work", "approval", "approved"))
    ):
        afes = afe_service.list_afes(db, organization_id, deleted=False)
        if focus_wells:
            fids = {w.id for w in focus_wells}
            focused_afes = [a for a in afes if a.well_id in fids]
            afes_to_show = focused_afes or afes
        else:
            afes_to_show = afes
        if afes_to_show:
            afe_lines = [f"AFE REGISTER ({len(afes_to_show)} matching of {len(afes)} total active AFE(s)):"]
            for a in afes_to_show[:10]:
                cur = f"{a.standard_currency} " if a.standard_currency else ""
                sow = (
                    f", SOW rev {a.sow_revision} adjusted={cur}{_money(a.adjusted_total)}"
                    if a.has_sow_adjustment and a.adjusted_total is not None
                    else ""
                )
                afe_lines.append(
                    f"- {a.afe_code} ({a.afe_name}) | well={a.well_code} | scope={a.configuration_scope} | status={a.status} | "
                    f"total={cur}{_money(a.total_cost)} (svc={cur}{_money(a.services_total)}, cons={cur}{_money(a.consumables_total)}, "
                    f"tang={cur}{_money(a.tangibles_total)}){sow}"
                )
            sections.append("\n".join(afe_lines))
        else:
            sections.append("AFE REGISTER: 0 active AFEs in this workspace.")

    if _has_cap(capabilities, "daily-cost:read"):
        ops = _operational_registers_section(db, organization_id, question, focus_wells, all_wells)
        if ops:
            sections.append(ops)

    if _has_cap(capabilities, "invoice-processing:read") and any(
        k in lower for k in ("invoice", "invoices", "idvs", "epicor", "payable", "overdue", "payment", "paid", "disallowed", "vendor", "bill", "accounts", "summary", "overview", "workspace")
    ):
        sections.append(_invoice_section(db, organization_id, question, focus_wells))

    if _has_cap(capabilities, "master-data:read") and any(
        k in lower for k in (
            "price", "rate", "cost", "catalogue", "catalog", "vendor", "supplier", "po", "so", "order",
            "service", "tangible", "casing", "tubing", "bit", "chemical", "barite", "bentonite",
            "cement", "additive", "fuel", "currency", "master data",
        )
    ):
        cat = _catalogue_section(db, organization_id, question)
        if cat:
            sections.append(cat)

    if any(
        k in lower for k in (
            "anomal", "spike", "drift", "mistake", "error", "wrong", "health", "score", "risk",
            "overrun", "over budget", "forecast", "check", "flag", "warning", "missing", "stale", "npt", "upa", "review",
        )
    ):
        anom = _anomaly_section(db, organization_id, user, capabilities, focus_wells)
        if anom:
            sections.append(anom)

    # Assemble within the token-safe character budget while keeping priority sections intact.
    assembled: list[str] = []
    used_chars = 0
    for block in sections:
        text = block.strip()
        if not text:
            continue
        if used_chars + len(text) + 2 > MAX_DOSSIER_CHARS:
            remaining = MAX_DOSSIER_CHARS - used_chars - 40
            if remaining > 300:
                assembled.append(text[:remaining].rsplit("\n", 1)[0] + "\n[...additional rows truncated for context budget]")
            break
        assembled.append(text)
        used_chars += len(text) + 2
    return "\n\n".join(assembled)
