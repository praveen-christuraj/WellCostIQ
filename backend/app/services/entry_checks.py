"""Entry checks for daily cost sheets: reading the ledger, reviews, profiles.

The rules themselves live in :mod:`app.domain.entry_rules` and are pure. This
module gives them their facts and stores the two things the checks keep:

* **Reviews.** "Keep as entered" records that a user looked at one finding on
  a saved Draft sheet and kept the value. The review is tied to the exact
  value, so changing the value brings the finding back. Reviewing and
  reopening are audited.
* **Workspace profiles.** What each item usually carries across the
  workspace's recent sheets, used while a well's own history is still too
  short. A profile is rebuilt from the cost ledger after a response has been
  sent, never while a user waits, and never crosses a workspace boundary.

Every finding is advice. Nothing here rejects a save, changes a figure or
reprices a line, and the preview swallows any failure of the checks so the
daily sheet keeps working exactly as it did without them.

Where "usual" comes from
------------------------
1. The sheets of the same AFE nearest in date (``ENTRY_CHECK_HISTORY_SHEETS``),
   read live from the ledger, never including the sheet being checked.
2. When that history is too short -- a new well -- the workspace profile.
3. For rates and exchange rates, the AFE's own locked figures.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Sequence

from fastapi import HTTPException, Request
from sqlalchemy import case, delete, func, literal, select, union_all
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.domain import entry_rules as rules
from app.domain import entry_statistics as stats
from app.domain.entry_rules import Finding, History, LineFact, Plan, ProfileKey, SectionPlan, SheetFacts, WorkspaceProfile
from app.models.afe import Afe, AfeExchangeRate
from app.models.daily_cost import (
    DailyCostBaselineBudgetLine,
    DailyCostBaselineExchangeRate,
    DailyCostBaselineSection,
    DailyCostBaselineServiceRate,
    DailyCostCatalogueRateSnapshot,
    DailyCostConsumableLine,
    DailyCostEntry,
    DailyCostOtherExpenseLine,
    DailyCostServiceCostItem,
    DailyCostServiceLine,
    DailyCostTangibleLine,
)
from app.models.entities import User
from app.models.entry_check import DailyCostCheckReview, DailyCostItemProfile
from app.models.rig_well import Well
from app.schemas.entry_check import (
    DailyCostCheckLine,
    DailyCostCheckReopenIn,
    DailyCostCheckReviewIn,
    DailyCostEntryCheck,
    DailyCostEntryChecksOut,
    DailyCostSheetChecks,
    DailyCostWellChecksOut,
)
from app.services import audit

log = logging.getLogger("app.entry_checks")

# The well-level review reads at most this many of a well's newest sheets.
WELL_REVIEW_SHEETS = 120
MAX_HISTORY_SHEETS = 120

# Workspace profiles: how many observations one profile keeps, how many ledger
# lines are read per item to find them, and how often one item may be queued.
PROFILE_SAMPLE = 120
PROFILE_ROWS_PER_SUBJECT = PROFILE_SAMPLE * 3
PROFILE_REQUEST_INTERVAL_SECONDS = 60.0
PROFILE_REFRESH_BATCH = 300
PROFILE_KINDS = ("service", "consumable", "tangible")
# A drill bit is priced from its own AFE allowance when it has one; every other
# consumable is priced from the well's catalogue snapshot.
ALLOWANCE_PRICED_KINDS = ("drill_bit",)


# ---------------------------------------------------------------------------
# Facts from rows held in memory (the priced rows of a preview)
# ---------------------------------------------------------------------------


def facts_from_rows(
    entry: Any,
    service_rows: Sequence[Any],
    consumable_rows: Sequence[Any],
    tangible_rows: Sequence[Any],
    other_rows: Sequence[Any],
) -> list[LineFact]:
    """The lines of an unsaved sheet as the rules read them."""
    service_rates = {row.id: row.currency for row in entry.baseline.service_rates}
    allowances = {row.id: row.currency for row in entry.baseline.budget_lines}
    snapshots = {row.id: row.currency for row in entry.rate_baseline.catalogue_rates}

    def catalogue_currency(row: Any, *, allowance_priced: bool) -> str:
        if allowance_priced and row.baseline_budget_line_id in allowances:
            return allowances[row.baseline_budget_line_id]
        return snapshots.get(row.catalogue_rate_snapshot_id, "")

    def common(row: Any) -> dict[str, Any]:
        return dict(
            quantity=row.quantity, captured_rate=row.captured_rate, override_rate=row.override_rate,
            currency=row.currency, usd_fx=row.usd_exchange_rate, amount=row.standard_amount,
            depth_m=row.actual_depth, depth_input=row.actual_depth_input, depth_unit=row.actual_depth_unit,
            depth_seq=row.depth_entry_seq, section_id=row.hole_section_id, phase_id=row.phase_id,
            sub_activity_id=row.sub_activity_id,
        )

    facts: list[LineFact] = []
    for index, row in enumerate(service_rows):
        facts.append(rules.line_fact(
            group="services", index=index, kind="service", subject_id=row.service_id,
            variant_a=row.charging_basis, variant_b=row.charge_category, unit=row.quantity_unit,
            code=row.service_code_snapshot, name=row.service_name_snapshot,
            captured_currency=service_rates.get(row.baseline_service_rate_id, ""),
            itemised=bool(row.cost_items), **common(row),
        ))
    for index, row in enumerate(consumable_rows):
        facts.append(rules.line_fact(
            group="consumables", index=index, kind="consumable", subject_id=row.item_id,
            variant_a=row.item_kind, variant_b="", unit=row.uom,
            code=row.item_code_snapshot, name=row.item_name_snapshot,
            captured_currency=catalogue_currency(row, allowance_priced=row.item_kind in ALLOWANCE_PRICED_KINDS),
            itemised=False, **common(row),
        ))
    for index, row in enumerate(tangible_rows):
        facts.append(rules.line_fact(
            group="tangibles", index=index, kind="tangible", subject_id=row.tangible_id,
            variant_a="", variant_b="", unit=row.uom,
            code=row.tangible_code_snapshot, name=row.tangible_name_snapshot,
            captured_currency=catalogue_currency(row, allowance_priced=True),
            itemised=False, **common(row),
        ))
    for index, row in enumerate(other_rows):
        facts.append(rules.line_fact(
            group="other_expenses", index=index, kind="other", subject_id=row.expense_type,
            variant_a="", variant_b="", unit=row.quantity_unit, code="", name=row.expense_type_label,
            captured_currency="", itemised=False, detail=row.expense_description or "", **common(row),
        ))
    return facts


# ---------------------------------------------------------------------------
# Facts from the ledger
# ---------------------------------------------------------------------------


def _line_statement(organization_id: str, entry_ids: Sequence[str]):
    """Every line of the given sheets, from the four line tables, in one statement."""
    service, consumable = DailyCostServiceLine, DailyCostConsumableLine
    tangible, other = DailyCostTangibleLine, DailyCostOtherExpenseLine
    service_rate, snapshot, allowance = (
        DailyCostBaselineServiceRate, DailyCostCatalogueRateSnapshot, DailyCostBaselineBudgetLine,
    )
    blank = literal("")
    ids = list(entry_ids)

    def branch(
        model: Any, kind: str, group: str, *, subject: Any, variant_a: Any, variant_b: Any, unit: Any,
        code: Any, name: Any, captured_currency: Any, itemised: Any, detail: Any,
    ):
        return select(
            model.entry_id.label("entry_id"), literal(kind).label("kind"), literal(group).label("grp"),
            subject.label("subject_id"), variant_a.label("variant_a"), variant_b.label("variant_b"),
            unit.label("unit"), code.label("code"), name.label("name"),
            model.quantity.label("quantity"), model.captured_rate.label("captured_rate"),
            captured_currency.label("captured_currency"), model.override_rate.label("override_rate"),
            model.currency.label("currency"), model.usd_exchange_rate.label("usd_fx"),
            model.standard_amount.label("amount"), model.actual_depth.label("depth_m"),
            model.actual_depth_input.label("depth_input"), model.actual_depth_unit.label("depth_unit"),
            model.depth_entry_seq.label("depth_seq"), model.hole_section_id.label("section_id"),
            model.phase_id.label("phase_id"), model.sub_activity_id.label("sub_activity_id"),
            model.sort_order.label("sort_order"), itemised.label("itemised"), detail.label("detail"),
        ).where(model.organization_id == organization_id, model.entry_id.in_(ids))

    has_items = (
        select(func.count(DailyCostServiceCostItem.id))
        .where(DailyCostServiceCostItem.service_line_id == service.id)
        .correlate(service)
        .scalar_subquery()
    )
    services = branch(
        service, "service", "services", subject=service.service_id, variant_a=service.charging_basis,
        variant_b=service.charge_category, unit=service.quantity_unit, code=service.service_code_snapshot,
        name=service.service_name_snapshot, captured_currency=func.coalesce(service_rate.currency, ""),
        itemised=has_items, detail=blank,
    ).outerjoin(service_rate, service_rate.id == service.baseline_service_rate_id)
    consumables = branch(
        consumable, "consumable", "consumables", subject=consumable.item_id, variant_a=consumable.item_kind,
        variant_b=blank, unit=consumable.uom, code=consumable.item_code_snapshot, name=consumable.item_name_snapshot,
        captured_currency=case(
            (consumable.item_kind.in_(ALLOWANCE_PRICED_KINDS), func.coalesce(allowance.currency, snapshot.currency, "")),
            else_=func.coalesce(snapshot.currency, ""),
        ),
        itemised=literal(0), detail=blank,
    ).outerjoin(snapshot, snapshot.id == consumable.catalogue_rate_snapshot_id).outerjoin(
        allowance, allowance.id == consumable.baseline_budget_line_id,
    )
    tangibles = branch(
        tangible, "tangible", "tangibles", subject=tangible.tangible_id, variant_a=blank, variant_b=blank,
        unit=tangible.uom, code=tangible.tangible_code_snapshot, name=tangible.tangible_name_snapshot,
        captured_currency=func.coalesce(allowance.currency, snapshot.currency, ""),
        itemised=literal(0), detail=blank,
    ).outerjoin(snapshot, snapshot.id == tangible.catalogue_rate_snapshot_id).outerjoin(
        allowance, allowance.id == tangible.baseline_budget_line_id,
    )
    others = branch(
        other, "other", "other_expenses", subject=other.expense_type, variant_a=blank, variant_b=blank,
        unit=other.quantity_unit, code=blank, name=other.expense_type_label, captured_currency=blank,
        itemised=literal(0), detail=other.expense_description,
    )
    return union_all(services, consumables, tangibles, others).subquery()


def load_lines(db: Session, organization_id: str, entry_ids: Sequence[str]) -> dict[str, list[LineFact]]:
    """The lines of the given sheets as facts, in the order each sheet shows them."""
    result: dict[str, list[LineFact]] = {entry_id: [] for entry_id in entry_ids}
    if not entry_ids:
        return result
    statement = _line_statement(organization_id, entry_ids)
    columns = statement.c
    # Rows are read as plain tuples in this fixed order: a sheet's history is a
    # few thousand lines, and reading each column by name costs more than the query.
    rows = [tuple(row) for row in db.execute(select(
        columns.entry_id, columns.grp, columns.sort_order, columns.kind, columns.subject_id,
        columns.variant_a, columns.variant_b, columns.unit, columns.code, columns.name,
        columns.quantity, columns.captured_rate, columns.captured_currency, columns.override_rate,
        columns.currency, columns.usd_fx, columns.amount, columns.depth_m, columns.depth_input,
        columns.depth_unit, columns.depth_seq, columns.section_id, columns.phase_id,
        columns.sub_activity_id, columns.itemised, columns.detail,
    ))]
    group_order = rules.GROUP_ORDER
    rows.sort(key=lambda row: (str(row[0]), group_order.get(row[1], 9), int(row[2] or 0)))
    position: dict[tuple[str, str], int] = defaultdict(int)
    for (
        entry_id, group, _sort_order, kind, subject_id, variant_a, variant_b, unit, code, name,
        quantity, captured_rate, captured_currency, override_rate, currency, usd_fx, amount,
        depth_m, depth_input, depth_unit, depth_seq, section_id, phase_id, sub_activity_id,
        itemised, detail,
    ) in rows:
        entry_id = str(entry_id)
        index = position[(entry_id, group)]
        position[(entry_id, group)] = index + 1
        result.setdefault(entry_id, []).append(rules.line_fact(
            group=group, index=index, kind=kind, subject_id=subject_id,
            variant_a=variant_a or "", variant_b=variant_b or "", unit=unit or "",
            code=code or "", name=name or "", quantity=quantity, captured_rate=captured_rate,
            captured_currency=captured_currency or "", override_rate=override_rate,
            currency=currency or "", usd_fx=usd_fx, amount=amount, depth_m=depth_m,
            depth_input=depth_input, depth_unit=depth_unit or "m", depth_seq=depth_seq,
            section_id=section_id, phase_id=phase_id, sub_activity_id=sub_activity_id,
            itemised=bool(itemised), detail=detail or "",
        ))
    return result


_HEADER_COLUMNS = (
    DailyCostEntry.id, DailyCostEntry.daily_cost_code, DailyCostEntry.cost_date, DailyCostEntry.status,
    DailyCostEntry.afe_id, DailyCostEntry.baseline_id, DailyCostEntry.total_cost,
    DailyCostEntry.usd_exchange_rate, DailyCostEntry.standard_currency, DailyCostEntry.well_id,
    DailyCostEntry.afe_code_snapshot,
)


def _sheet_from_header(row: Any, lines: list[LineFact] | None = None) -> SheetFacts:
    return SheetFacts(
        entry_id=str(row.id), code=row.daily_cost_code, cost_date=row.cost_date, status=row.status,
        afe_id=str(row.afe_id), baseline_id=str(row.baseline_id), total=rules.to_decimal(row.total_cost),
        usd_fx=rules.to_decimal(row.usd_exchange_rate), standard_currency=(row.standard_currency or "USD").upper(),
        lines=lines if lines is not None else [],
    )


def _nearest(headers: Sequence[Any], target: date, limit: int) -> list[Any]:
    """The sheets nearest in date to ``target``; an earlier sheet wins a tie."""
    ordered = sorted(headers, key=lambda row: (abs((row.cost_date - target).days), row.cost_date, row.daily_cost_code))
    return ordered[: max(0, limit)]


def _neighbour_headers(db: Session, organization_id: str, *, afe_id: str, well_id: str, exclude_id: str) -> list[Any]:
    return list(db.execute(
        select(*_HEADER_COLUMNS).where(
            DailyCostEntry.organization_id == organization_id,
            DailyCostEntry.afe_id == afe_id,
            DailyCostEntry.well_id == well_id,
            DailyCostEntry.is_deleted.is_(False),
            DailyCostEntry.id != exclude_id,
        )
    ).all())


def load_neighbours(
    db: Session, organization_id: str, *, afe_id: str, well_id: str, exclude_id: str, cost_date: date, limit: int,
) -> list[SheetFacts]:
    """The other sheets of the same AFE nearest in date, with their lines."""
    headers = _nearest(
        _neighbour_headers(db, organization_id, afe_id=afe_id, well_id=well_id, exclude_id=exclude_id), cost_date, limit,
    )
    lines = load_lines(db, organization_id, [str(row.id) for row in headers])
    return [_sheet_from_header(row, lines.get(str(row.id), [])) for row in headers]


# ---------------------------------------------------------------------------
# The locked plan
# ---------------------------------------------------------------------------


def _usd_table(rates: dict[str, Decimal], standard: str, standard_usd: Decimal) -> dict[str, float]:
    """USD per unit of each currency.

    ``rates`` holds standard-currency units per unit of each foreign currency;
    ``standard_usd`` is one unit of the standard currency in USD.
    """
    if standard == "USD":
        return {code: float(rate) for code, rate in rates.items() if code != "USD" and rate > 0}
    if "USD" in rates and rates["USD"] > 0:
        # The table states its own price of a dollar; prefer it to the sheet's.
        standard_usd = Decimal("1") / rates["USD"]
    if standard_usd <= 0:
        return {}
    table = {code: float(rate * standard_usd) for code, rate in rates.items() if code != "USD" and rate > 0}
    table[standard] = float(standard_usd)
    return table


def _rates_by_code(rows: Iterable[Any]) -> dict[str, Decimal]:
    return {row.currency_code.upper(): Decimal(row.rate) for row in rows if row.rate and row.rate > 0}


def plan_from_entry(entry: Any, entry_usd_fx: Decimal) -> Plan:
    """The plan of a fully loaded sheet: the preview already holds all of it."""
    baseline = entry.baseline
    standard = (entry.standard_currency or "USD").upper()
    afe = getattr(entry, "afe", None)
    sheet_usd = rules.to_decimal(entry_usd_fx) if standard != "USD" else Decimal("1")
    return Plan(
        scope=(getattr(afe, "configuration_scope", "") or ""),
        standard_currency=standard,
        sections={
            section.hole_section_id: SectionPlan(
                section_id=section.hole_section_id,
                label=rules.join_label(section.section_code_snapshot, section.section_name_snapshot),
                top=float(section.from_depth or 0), bottom=float(section.to_depth or 0),
            )
            for section in baseline.well_sections
        },
        estimate_usd_fx=_usd_table(_rates_by_code(afe.exchange_rates if afe is not None else ()), standard, sheet_usd),
        current_usd_fx=_usd_table(_rates_by_code(baseline.exchange_rates), standard, sheet_usd),
    )


def load_plans(db: Session, organization_id: str, sheets: Sequence[SheetFacts]) -> dict[str, Plan]:
    """Plans of saved sheets, one per sheet id, read with four light statements."""
    plans: dict[str, Plan] = {}
    if not sheets:
        return plans
    baseline_ids = sorted({sheet.baseline_id for sheet in sheets})
    afe_ids = sorted({sheet.afe_id for sheet in sheets})
    scopes = {
        str(row.id): (row.configuration_scope or "")
        for row in db.execute(
            select(Afe.id, Afe.configuration_scope).where(Afe.organization_id == organization_id, Afe.id.in_(afe_ids))
        ).all()
    }
    sections: dict[str, dict[str, SectionPlan]] = defaultdict(dict)
    for row in db.execute(
        select(
            DailyCostBaselineSection.baseline_id, DailyCostBaselineSection.hole_section_id,
            DailyCostBaselineSection.section_code_snapshot, DailyCostBaselineSection.section_name_snapshot,
            DailyCostBaselineSection.from_depth, DailyCostBaselineSection.to_depth,
        ).where(
            DailyCostBaselineSection.organization_id == organization_id,
            DailyCostBaselineSection.baseline_id.in_(baseline_ids),
        )
    ).all():
        sections[str(row.baseline_id)][row.hole_section_id] = SectionPlan(
            section_id=row.hole_section_id,
            label=rules.join_label(row.section_code_snapshot, row.section_name_snapshot),
            top=float(row.from_depth or 0), bottom=float(row.to_depth or 0),
        )
    estimate: dict[str, dict[str, Decimal]] = defaultdict(dict)
    for row in db.execute(
        select(AfeExchangeRate.afe_id, AfeExchangeRate.currency_code, AfeExchangeRate.rate).where(
            AfeExchangeRate.organization_id == organization_id, AfeExchangeRate.afe_id.in_(afe_ids),
        )
    ).all():
        if row.rate and row.rate > 0:
            estimate[str(row.afe_id)][row.currency_code.upper()] = Decimal(row.rate)
    current: dict[str, dict[str, Decimal]] = defaultdict(dict)
    for row in db.execute(
        select(
            DailyCostBaselineExchangeRate.baseline_id, DailyCostBaselineExchangeRate.currency_code,
            DailyCostBaselineExchangeRate.rate,
        ).where(
            DailyCostBaselineExchangeRate.organization_id == organization_id,
            DailyCostBaselineExchangeRate.baseline_id.in_(baseline_ids),
        )
    ).all():
        if row.rate and row.rate > 0:
            current[str(row.baseline_id)][row.currency_code.upper()] = Decimal(row.rate)
    for sheet in sheets:
        standard = sheet.standard_currency
        sheet_usd = sheet.usd_fx if standard != "USD" else Decimal("1")
        plans[sheet.entry_id] = Plan(
            scope=scopes.get(sheet.afe_id, ""), standard_currency=standard,
            sections=sections.get(sheet.baseline_id, {}),
            estimate_usd_fx=_usd_table(estimate.get(sheet.afe_id, {}), standard, sheet_usd),
            current_usd_fx=_usd_table(current.get(sheet.baseline_id, {}), standard, sheet_usd),
        )
    return plans


# ---------------------------------------------------------------------------
# Workspace profiles: read now, rebuilt after the response
# ---------------------------------------------------------------------------

_pending: dict[str, set[tuple[str, str]]] = defaultdict(set)
_requested_at: dict[tuple[str, str, str], float] = {}
_pending_lock = threading.Lock()


def _as_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _request_refresh(organization_id: str, subjects: Iterable[tuple[str, str]]) -> None:
    """Queue items whose workspace profile is missing or stale."""
    moment = time.monotonic()
    with _pending_lock:
        if len(_requested_at) > 20000:
            _requested_at.clear()
        for kind, subject_id in subjects:
            marker = (organization_id, kind, subject_id)
            last = _requested_at.get(marker)
            if last is not None and moment - last < PROFILE_REQUEST_INTERVAL_SECONDS:
                continue
            _requested_at[marker] = moment
            _pending[organization_id].add((kind, subject_id))


def has_pending_refresh(organization_id: str) -> bool:
    with _pending_lock:
        return bool(_pending.get(organization_id))


def forget_pending_refreshes() -> None:
    """Drop every queued refresh (used by tests and on shutdown)."""
    with _pending_lock:
        _pending.clear()
        _requested_at.clear()


def load_profiles(
    db: Session, organization_id: str, subjects: set[tuple[str, str]],
) -> dict[ProfileKey, WorkspaceProfile]:
    """Workspace profiles of the given items; missing or stale ones are queued."""
    if not subjects:
        return {}
    rows = db.scalars(
        select(DailyCostItemProfile).where(
            DailyCostItemProfile.organization_id == organization_id,
            DailyCostItemProfile.subject_id.in_(sorted({subject_id for _kind, subject_id in subjects})),
        )
    ).all()
    max_age = timedelta(hours=get_settings().entry_check_profile_max_age_hours)
    moment = datetime.now(timezone.utc)
    fresh: set[tuple[str, str]] = set()
    profiles: dict[ProfileKey, WorkspaceProfile] = {}
    for row in rows:
        subject = (row.subject_kind, row.subject_id)
        if subject not in subjects:
            continue
        refreshed = _as_utc(row.refreshed_at)
        if refreshed is not None and moment - refreshed <= max_age:
            fresh.add(subject)
        if row.sample_count <= 0 or row.median_value <= 0:
            continue
        profiles[(row.subject_kind, row.subject_id, row.variant, row.metric, row.unit)] = WorkspaceProfile(
            profile=stats.Profile(
                count=int(row.sample_count), median=float(row.median_value), spread=float(row.spread),
                low=float(row.low_value), high=float(row.high_value),
                common=float(row.common_value) if row.common_value is not None else None,
            ),
            wells=int(row.well_count),
        )
    stale = subjects - fresh
    if stale:
        _request_refresh(organization_id, stale)
    return profiles


def _profile_rows(db: Session, organization_id: str, kind: str, subject_ids: Sequence[str], since: date):
    """The newest lines of the given items across the workspace, capped per item."""
    entry = DailyCostEntry
    itemised: Any = literal(0)
    if kind == "service":
        model = DailyCostServiceLine
        subject, variant_a, variant_b, unit = model.service_id, model.charging_basis, model.charge_category, model.quantity_unit
        itemised = (
            select(func.count(DailyCostServiceCostItem.id))
            .where(DailyCostServiceCostItem.service_line_id == model.id)
            .correlate(model)
            .scalar_subquery()
        )
    elif kind == "consumable":
        model = DailyCostConsumableLine
        subject, variant_a, variant_b, unit = model.item_id, model.item_kind, literal(""), model.uom
    else:
        model = DailyCostTangibleLine
        subject, variant_a, variant_b, unit = model.tangible_id, literal(""), literal(""), model.uom
    ranked = (
        select(
            entry.id.label("entry_id"), entry.cost_date.label("cost_date"), entry.well_id.label("well_id"),
            subject.label("subject_id"), variant_a.label("variant_a"), variant_b.label("variant_b"),
            unit.label("unit"), model.quantity.label("quantity"), model.captured_rate.label("captured_rate"),
            model.override_rate.label("override_rate"), model.currency.label("currency"),
            itemised.label("itemised"),
            func.row_number().over(
                partition_by=subject, order_by=(entry.cost_date.desc(), entry.id, model.sort_order),
            ).label("position"),
        )
        .join(entry, model.entry_id == entry.id)
        .where(
            model.organization_id == organization_id,
            entry.organization_id == organization_id,
            entry.is_deleted.is_(False),
            entry.cost_date >= since,
            subject.in_(list(subject_ids)),
        )
        .subquery()
    )
    return db.execute(select(ranked).where(ranked.c.position <= PROFILE_ROWS_PER_SUBJECT)).all()


def _quantized(value: float) -> Decimal:
    return Decimal(repr(value)).quantize(Decimal("0.0000000001"))


def _build_profile_rows(
    organization_id: str, kind: str, subject_ids: Sequence[str], rows: Sequence[Any], moment: datetime,
) -> list[DailyCostItemProfile]:
    """Profiles of one kind of item from its newest ledger lines."""
    day_sums: dict[tuple[str, str, str], dict[str, tuple[date, str, Decimal]]] = defaultdict(dict)
    rates: dict[tuple[str, str, str], list[tuple[date, str, float]]] = defaultdict(list)
    for row in rows:
        subject_id = str(row.subject_id)
        if kind == "service":
            factor, norm_unit = rules.service_normalisation(row.variant_a or "", row.unit or "")
            variant = f"{row.variant_a or ''}|{row.variant_b or ''}"
            one_time = row.variant_a == "Day Rate" and row.variant_b in rules.ONE_TIME_CATEGORIES
        else:
            factor, norm_unit, variant, one_time = Decimal("1"), row.unit or "", row.variant_a or "", False
        quantity = rules.to_decimal(row.quantity)
        if not one_time and quantity > 0:
            bucket = day_sums[(subject_id, variant, norm_unit)]
            entry_id = str(row.entry_id)
            previous = bucket.get(entry_id)
            bucket[entry_id] = (row.cost_date, str(row.well_id), quantity * factor + (previous[2] if previous else Decimal("0")))
        rate = row.override_rate if row.override_rate is not None else row.captured_rate
        if rate is not None and rules.to_decimal(rate) > 0 and not row.itemised:
            rates[(subject_id, variant, (row.currency or "").upper())].append((row.cost_date, str(row.well_id), float(rate)))
    built: list[DailyCostItemProfile] = []
    covered: set[str] = set()

    def add(subject_id: str, variant: str, metric: str, unit: str, observations: list[tuple[date, str, float]]) -> None:
        newest = sorted(observations, key=lambda item: item[0], reverse=True)[:PROFILE_SAMPLE]
        profile = stats.build_profile(value for _day, _well, value in newest)
        if profile is None:
            return
        covered.add(subject_id)
        built.append(DailyCostItemProfile(
            organization_id=organization_id, subject_kind=kind, subject_id=subject_id, variant=variant,
            metric=metric, unit=unit, sample_count=profile.count,
            well_count=len({well for _day, well, _value in newest}),
            median_value=_quantized(profile.median), spread=_quantized(profile.spread),
            low_value=_quantized(profile.low), high_value=_quantized(profile.high),
            common_value=_quantized(profile.common) if profile.common is not None else None,
            last_observed_on=newest[0][0], refreshed_at=moment,
        ))

    for (subject_id, variant, unit), bucket in day_sums.items():
        add(subject_id, variant, "quantity", unit, [(day, well, float(total)) for day, well, total in bucket.values()])
    for (subject_id, variant, currency), observations in rates.items():
        add(subject_id, variant, "rate", currency, observations)
    # "Looked for, nothing recorded yet" is remembered too, so the same search
    # is not repeated on every preview.
    for subject_id in subject_ids:
        if subject_id not in covered:
            built.append(DailyCostItemProfile(
                organization_id=organization_id, subject_kind=kind, subject_id=subject_id, variant="",
                metric="quantity", unit="", sample_count=0, well_count=0, refreshed_at=moment,
            ))
    return built


def refresh_profiles(db: Session, organization_id: str, subjects: Iterable[tuple[str, str]]) -> int:
    """Rebuild the workspace profiles of the given items from the cost ledger.

    A profile is always recomputed from the ledger, never adjusted in place, so
    it cannot drift: a deleted or corrected sheet simply stops counting at the
    next refresh. Returns the number of profile rows written.
    """
    by_kind: dict[str, set[str]] = defaultdict(set)
    for kind, subject_id in subjects:
        if kind in PROFILE_KINDS and subject_id:
            by_kind[kind].add(subject_id)
    if not by_kind:
        return 0
    since = date.today() - timedelta(days=get_settings().entry_check_profile_window_days)
    moment = datetime.now(timezone.utc)
    written = 0
    for kind, ids in by_kind.items():
        ordered = sorted(ids)
        for start in range(0, len(ordered), PROFILE_REFRESH_BATCH):
            batch = ordered[start:start + PROFILE_REFRESH_BATCH]
            built = _build_profile_rows(
                organization_id, kind, batch, _profile_rows(db, organization_id, kind, batch, since), moment,
            )
            db.execute(
                delete(DailyCostItemProfile).where(
                    DailyCostItemProfile.organization_id == organization_id,
                    DailyCostItemProfile.subject_kind == kind,
                    DailyCostItemProfile.subject_id.in_(batch),
                )
            )
            db.add_all(built)
            written += len(built)
    db.commit()
    return written


def run_pending_profile_refresh(organization_id: str) -> int:
    """Rebuild every queued profile of one workspace, after the response.

    It opens its own session, so it never shares a transaction with a request,
    and it never raises: a failed refresh only means the same profiles are
    asked for again later.
    """
    with _pending_lock:
        subjects = _pending.pop(organization_id, set())
    if not subjects:
        return 0
    try:
        with SessionLocal() as db:
            try:
                return refresh_profiles(db, organization_id, subjects)
            except IntegrityError:
                # Another worker rebuilt the same items at the same moment.
                db.rollback()
                return 0
    except SQLAlchemyError:
        log.exception("Workspace entry-check profiles could not be refreshed")
    except Exception:  # noqa: BLE001 - background work must never surface to a user
        log.exception("Unexpected failure while refreshing entry-check profiles")
    return 0


# ---------------------------------------------------------------------------
# Reviews and presentation
# ---------------------------------------------------------------------------


def _reviews(db: Session, organization_id: str, entry_ids: Sequence[str]) -> dict[str, dict[str, DailyCostCheckReview]]:
    result: dict[str, dict[str, DailyCostCheckReview]] = defaultdict(dict)
    if not entry_ids:
        return result
    for row in db.scalars(
        select(DailyCostCheckReview).where(
            DailyCostCheckReview.organization_id == organization_id,
            DailyCostCheckReview.entry_id.in_(list(entry_ids)),
        )
    ).all():
        result[row.entry_id][row.check_key] = row
    return result


def _to_schema(finding: Finding, reviews: dict[str, DailyCostCheckReview]) -> DailyCostEntryCheck:
    review = reviews.get(finding.key)
    # A review accepts one exact value; a different value is open again.
    accepted = review if review is not None and review.fingerprint == finding.fingerprint else None
    return DailyCostEntryCheck(
        key=finding.key, code=finding.code, severity=finding.severity, title=finding.title,
        message=finding.message, basis=finding.basis, scope=finding.scope, subject_label=finding.subject_label,
        lines=[DailyCostCheckLine(group=group, index=index) for group, index in finding.lines],
        field=finding.field_name, current_value=finding.current_value, current_display=finding.current_display,
        suggested_value=finding.suggested_value, suggested_display=finding.suggested_display,
        apply_to=[DailyCostCheckLine(group=group, index=index) for group, index in finding.apply_to],
        usual_display=finding.usual_display, history_count=finding.history_count, fingerprint=finding.fingerprint,
        reviewed=accepted is not None,
        reviewed_by=accepted.reviewed_by if accepted else "",
        reviewed_at=_as_utc(accepted.reviewed_at) if accepted else None,
        review_note=accepted.note if accepted else "",
    )


def _present(findings: Sequence[Finding], reviews: dict[str, DailyCostCheckReview]) -> list[DailyCostEntryCheck]:
    """Open findings first; the rule order is kept inside each half."""
    checks = [_to_schema(finding, reviews) for finding in findings]
    return [item for item in checks if not item.reviewed] + [item for item in checks if item.reviewed]


def _counts(checks: Sequence[DailyCostEntryCheck]) -> tuple[int, int, int]:
    open_warnings = sum(1 for item in checks if not item.reviewed and item.severity == "warning")
    open_notices = sum(1 for item in checks if not item.reviewed and item.severity != "warning")
    return open_warnings, open_notices, sum(1 for item in checks if item.reviewed)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def enabled() -> bool:
    return bool(get_settings().entry_checks_enabled)


def _history_limit() -> int:
    return max(0, min(int(get_settings().entry_check_history_sheets), MAX_HISTORY_SHEETS))


def checks_for_preview(
    db: Session,
    entry: Any,
    service_rows: Sequence[Any],
    consumable_rows: Sequence[Any],
    tangible_rows: Sequence[Any],
    other_rows: Sequence[Any],
    *,
    total: Decimal,
    entry_usd_fx: Decimal,
) -> list[DailyCostEntryCheck]:
    """Findings for the unsaved state of a sheet, from its already priced rows.

    Never raises: the preview must return its totals whatever happens here.
    Only SELECT statements are issued and the session does not autoflush, so
    nothing the preview holds in memory is written.
    """
    if not enabled():
        return []
    try:
        sheet = SheetFacts(
            entry_id=entry.id, code=entry.daily_cost_code, cost_date=entry.cost_date, status=entry.status,
            afe_id=entry.afe_id, baseline_id=entry.baseline_id, total=rules.to_decimal(total),
            usd_fx=rules.to_decimal(entry_usd_fx), standard_currency=(entry.standard_currency or "USD").upper(),
            lines=facts_from_rows(entry, service_rows, consumable_rows, tangible_rows, other_rows),
        )
        history = History(load_neighbours(
            db, entry.organization_id, afe_id=entry.afe_id, well_id=entry.well_id,
            exclude_id=entry.id, cost_date=entry.cost_date, limit=_history_limit(),
        ))
        profiles = load_profiles(db, entry.organization_id, rules.thin_subjects(sheet, history))
        findings = rules.evaluate(sheet, history, plan_from_entry(entry, entry_usd_fx), profiles)
        reviews = _reviews(db, entry.organization_id, [entry.id]).get(entry.id, {}) if findings else {}
        return _present(findings, reviews)
    except SQLAlchemyError:
        # Leave the session usable for whatever the caller does next.
        db.rollback()
        log.exception("Entry checks could not read history for daily cost entry %s", getattr(entry, "id", "?"))
    except Exception:  # noqa: BLE001 - advice must never break the sheet it advises on
        log.exception("Entry checks failed for the preview of daily cost entry %s", getattr(entry, "id", "?"))
    return []


def _header_or_404(db: Session, organization_id: str, entry_id: str) -> Any:
    row = db.execute(
        select(*_HEADER_COLUMNS).where(
            DailyCostEntry.id == entry_id,
            DailyCostEntry.organization_id == organization_id,
            DailyCostEntry.is_deleted.is_(False),
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Daily cost entry not found in this workspace")
    return row


def _saved_findings(db: Session, organization_id: str, header: Any) -> tuple[list[Finding], int]:
    """Findings on the saved state of one sheet, and how many sheets it was compared with."""
    entry_id = str(header.id)
    headers = _nearest(
        _neighbour_headers(db, organization_id, afe_id=header.afe_id, well_id=header.well_id, exclude_id=entry_id),
        header.cost_date, _history_limit(),
    )
    lines = load_lines(db, organization_id, [entry_id, *[str(row.id) for row in headers]])
    sheet = _sheet_from_header(header, lines.get(entry_id, []))
    history = History([_sheet_from_header(row, lines.get(str(row.id), [])) for row in headers])
    plan = load_plans(db, organization_id, [sheet]).get(entry_id, Plan())
    profiles = load_profiles(db, organization_id, rules.thin_subjects(sheet, history))
    return rules.evaluate(sheet, history, plan, profiles), len(headers)


def _entry_out(
    db: Session, organization_id: str, entry_id: str, findings: Sequence[Finding], history_sheets: int,
) -> DailyCostEntryChecksOut:
    reviews = _reviews(db, organization_id, [entry_id]).get(entry_id, {}) if findings else {}
    checks = _present(findings, reviews)
    open_warnings, open_notices, reviewed = _counts(checks)
    return DailyCostEntryChecksOut(
        entry_id=entry_id, checks=checks, open_warnings=open_warnings, open_notices=open_notices,
        reviewed=reviewed, history_sheets=history_sheets,
    )


def checks_for_entry(db: Session, organization_id: str, entry_id: str) -> DailyCostEntryChecksOut:
    """Findings for the saved state of one sheet."""
    header = _header_or_404(db, organization_id, entry_id)
    if not enabled():
        return DailyCostEntryChecksOut(entry_id=entry_id, enabled=False)
    findings, history_sheets = _saved_findings(db, organization_id, header)
    return _entry_out(db, organization_id, entry_id, findings, history_sheets)


def _draft_header_or_409(db: Session, organization_id: str, entry_id: str, action: str) -> Any:
    header = _header_or_404(db, organization_id, entry_id)
    if header.status != "draft":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Entry checks can be {action} on a Draft sheet only. "
                "Reopen the sheet with the authorized workflow first."
            ),
        )
    if not enabled():
        raise HTTPException(status_code=409, detail="Entry checks are turned off for this deployment.")
    return header


def _review_label(subject: str, code: str, value: str) -> str:
    return " ".join(part for part in (subject or code, f"({value})" if value else "") if part)


def review_checks(
    db: Session, organization_id: str, entry_id: str, data: DailyCostCheckReviewIn, user: User, request: Request | None,
) -> DailyCostEntryChecksOut:
    """Record that the values behind these findings are kept as entered.

    Only a finding that the saved sheet still carries, with the value the user
    saw, can be reviewed: the stored review describes the ledger, not whatever
    a client sends.
    """
    header = _draft_header_or_409(db, organization_id, entry_id, "reviewed")
    findings, history_sheets = _saved_findings(db, organization_id, header)
    current = {finding.key: finding for finding in findings}
    wanted = {item.key: item.fingerprint for item in data.items}
    changed = [key for key, fingerprint in wanted.items() if key not in current or current[key].fingerprint != fingerprint]
    if changed:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(changed)} of these entry checks changed after they were shown. "
                "Save the sheet, refresh the checks and review them again."
            ),
        )
    existing = _reviews(db, organization_id, [entry_id]).get(entry_id, {})
    moment = datetime.now(timezone.utc)
    actor = user.full_name or user.email
    kept: list[str] = []
    for key, fingerprint in wanted.items():
        finding = current[key]
        review = existing.get(key)
        if review is not None and review.fingerprint == fingerprint and review.note == data.note:
            continue
        if review is None:
            review = DailyCostCheckReview(organization_id=organization_id, entry_id=entry_id, check_key=key)
            db.add(review)
        review.check_code = finding.code[:40]
        review.fingerprint = fingerprint
        review.subject_label = (finding.subject_label or finding.title)[:255]
        review.value_label = finding.current_display[:120]
        review.note = data.note
        review.reviewed_by = actor[:255]
        review.reviewed_at = moment
        kept.append(_review_label(finding.subject_label, finding.code, finding.current_display))
    if kept:
        audit.record(
            db, organization_id=organization_id, actor=user, action="update", entity_type="daily_cost",
            entity_id=entry_id, entity_label=header.daily_cost_code,
            summary=(
                f"Entry checks on {header.daily_cost_code}: kept {len(kept)} value(s) as entered: "
                f"{rules.listed(kept)}" + (f". Note: {data.note}" if data.note else "")
            )[:1000],
            request=request,
        )
        try:
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="These entry checks were reviewed by someone else at the same moment. Refresh the sheet and retry.",
            ) from error
    return _entry_out(db, organization_id, entry_id, findings, history_sheets)


def reopen_checks(
    db: Session, organization_id: str, entry_id: str, data: DailyCostCheckReopenIn, user: User, request: Request | None,
) -> DailyCostEntryChecksOut:
    """Withdraw reviews, so the findings are open again."""
    header = _draft_header_or_409(db, organization_id, entry_id, "reopened")
    existing = _reviews(db, organization_id, [entry_id]).get(entry_id, {})
    removed = [existing[key] for key in dict.fromkeys(data.keys) if key in existing]
    if removed:
        labels = [_review_label(row.subject_label, row.check_code, row.value_label) for row in removed]
        for row in removed:
            db.delete(row)
        audit.record(
            db, organization_id=organization_id, actor=user, action="update", entity_type="daily_cost",
            entity_id=entry_id, entity_label=header.daily_cost_code,
            summary=(
                f"Entry checks on {header.daily_cost_code}: reopened {len(removed)} reviewed check(s): "
                f"{rules.listed(labels)}"
            )[:1000],
            request=request,
        )
        db.commit()
    findings, history_sheets = _saved_findings(db, organization_id, header)
    return _entry_out(db, organization_id, entry_id, findings, history_sheets)


def checks_for_well(db: Session, organization_id: str, well_id: str, afe_id: str | None = None) -> DailyCostWellChecksOut:
    """Findings across a well's saved sheets, each read against its own neighbours."""
    known = db.scalar(select(Well.id).where(
        Well.id == well_id, Well.organization_id == organization_id, Well.is_deleted.is_(False),
    ))
    if known is None:
        raise HTTPException(status_code=404, detail="Well not found in this workspace")
    statement = select(*_HEADER_COLUMNS).where(
        DailyCostEntry.organization_id == organization_id,
        DailyCostEntry.well_id == well_id,
        DailyCostEntry.is_deleted.is_(False),
    )
    if afe_id:
        statement = statement.where(DailyCostEntry.afe_id == afe_id)
    headers = list(db.execute(
        statement.order_by(DailyCostEntry.cost_date.desc(), DailyCostEntry.daily_cost_code).limit(WELL_REVIEW_SHEETS + 1)
    ).all())
    result = DailyCostWellChecksOut(
        well_id=well_id, enabled=enabled(), truncated=len(headers) > WELL_REVIEW_SHEETS,
    )
    headers = headers[:WELL_REVIEW_SHEETS]
    if not headers or not result.enabled:
        return result
    lines = load_lines(db, organization_id, [str(row.id) for row in headers])
    sheets = [_sheet_from_header(row, lines.get(str(row.id), [])) for row in headers]
    afe_codes = {str(row.id): row.afe_code_snapshot for row in headers}
    plans = load_plans(db, organization_id, sheets)
    by_afe: dict[str, list[SheetFacts]] = defaultdict(list)
    for sheet in sheets:
        by_afe[sheet.afe_id].append(sheet)
    limit = _history_limit()
    histories: dict[str, History] = {}
    needed: set[tuple[str, str]] = set()
    for group in by_afe.values():
        for sheet in group:
            others = [other for other in group if other.entry_id != sheet.entry_id]
            others.sort(key=lambda other, day=sheet.cost_date: (abs((other.cost_date - day).days), other.cost_date, other.code))
            histories[sheet.entry_id] = History(others[:limit])
            needed |= rules.thin_subjects(sheet, histories[sheet.entry_id])
    profiles = load_profiles(db, organization_id, needed)
    reviews = _reviews(db, organization_id, [sheet.entry_id for sheet in sheets])
    result.sheets_checked = len(sheets)
    for sheet in sorted(sheets, key=lambda item: (item.cost_date, item.code), reverse=True):
        findings = rules.evaluate(sheet, histories[sheet.entry_id], plans.get(sheet.entry_id, Plan()), profiles)
        if not findings:
            continue
        checks = _present(findings, reviews.get(sheet.entry_id, {}))
        open_warnings, open_notices, reviewed = _counts(checks)
        result.sheets.append(DailyCostSheetChecks(
            entry_id=sheet.entry_id, daily_cost_code=sheet.code, cost_date=sheet.cost_date, status=sheet.status,
            afe_code=afe_codes.get(sheet.entry_id, ""), open_warnings=open_warnings, open_notices=open_notices,
            reviewed=reviewed, checks=checks,
        ))
        result.open_warnings += open_warnings
        result.open_notices += open_notices
        result.reviewed += reviewed
    result.sheets_with_findings = len(result.sheets)
    return result
