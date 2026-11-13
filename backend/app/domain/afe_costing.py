"""AFE cost estimation engine.

Pure, framework-free pricing rules. The service layer converts stored rows or a
validated request into the immutable inputs below, and this module returns the
priced result. Nothing here reads or writes the database.

Rules
-----
* Charge categories are fixed. Mobilization, Demobilization and Fixed Charge are
  one-time per service line. The other categories are day-based.
* Day Rate services charge ``days x unit rate`` per day-based category. Hours
  convert with ``/ 24``. An explicit Operation quantity replaces the planned
  Operation days; otherwise the planned days of the line's scope are used.
* A Day Rate service is configured in **one dialog spanning the whole well**.
  Each charge category (Operation, Standby, Mobilization, ...) may carry one
  shared rate for every scope, or its own rate for each (section, optional
  phase) where that scope's rate differs. A shared rate applies to every scope
  the service is used on; a scope rate overrides it for that scope alone. Each
  category is therefore priced once per scope — never duplicated — and the
  line's amount is the sum of all of them.
* A Day Rate line with no scope rows at all is split across the configured
  sections by each section's planned days, so every section shows its own share
  (one-time categories stay well-level).
* Per Section Rate charges one amount per (section, optional phase). Per Service
  Rate charges one lump sum for its section and phase.
* Consumables and tangibles cost ``quantity x effective rate``. The effective
  rate is the override when one is entered, otherwise the captured rate.
* Sections and phases must come from the well configuration. Anything outside it
  is reported as a warning and is never silently priced into a section.
* Entered and calculated decimals are retained to 10 places (half-up).
* Currency. Every line keeps its entered currency. The estimate has one standard
  currency. When only one currency is detected, that currency is the standard and
  no rate is needed. When several are detected, a standard currency must be chosen
  and each other currency needs a conversion rate (units of standard per one unit
  of the foreign currency). Converted totals are None until every rate is present.
  Amounts as entered per currency are always reported separately.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.precision import DECIMAL_QUANT

ONE_TIME_CATEGORIES: tuple[str, ...] = ("Mobilization", "Demobilization", "Fixed Charge")
DAY_CATEGORIES: tuple[str, ...] = ("Operation", "Standby", "Personnel-Operation", "Personnel-Standby", "Others")
CHARGE_CATEGORIES: tuple[str, ...] = (
    "Mobilization",
    "Demobilization",
    "Operation",
    "Standby",
    "Personnel-Operation",
    "Personnel-Standby",
    "Fixed Charge",
    "Others",
)

BASIS_DAY_RATE = "Day Rate"
BASIS_PER_SERVICE = "Per Service Rate"
BASIS_PER_SECTION = "Per Section Rate"
CHARGING_BASES: tuple[str, ...] = (BASIS_DAY_RATE, BASIS_PER_SERVICE, BASIS_PER_SECTION)

UNIT_DAYS = "days"
UNIT_HOURS = "hours"
HOURS_PER_DAY = Decimal("24")

CONSUMABLE_LUMP_SUM: tuple[str, ...] = ("Mud Chemicals", "Cement Additives", "Fuel")
CONSUMABLE_DRILL_BITS = "Drill Bits"
CONSUMABLE_CATEGORIES: tuple[str, ...] = CONSUMABLE_LUMP_SUM + (CONSUMABLE_DRILL_BITS,)

GROUP_SERVICES = "Services"
GROUP_CONSUMABLES = "Consumables"
GROUP_TANGIBLES = "Tangibles"

WELL_LEVEL_LABEL = "Well-level (not section-specific)"

_MONEY = DECIMAL_QUANT
_QTY = DECIMAL_QUANT


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_MONEY, rounding=ROUND_HALF_UP)


def _qty(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_QTY, rounding=ROUND_HALF_UP)


def effective_rate(captured: Decimal, override: Decimal | None) -> Decimal:
    """The override wins when entered; otherwise the captured master-data rate applies."""

    return Decimal(override) if override is not None else Decimal(captured)


def normalize_days(quantity: Decimal, unit: str) -> Decimal:
    """Return the quantity in days. Hours convert with ``/ 24``; days pass through."""

    value = Decimal(quantity)
    if unit == UNIT_HOURS:
        value = value / HOURS_PER_DAY
    return _qty(value)


# ---------------------------------------------------------------------------
# Well configuration scope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseScope:
    phase_id: str
    label: str
    days: Decimal


@dataclass(frozen=True)
class SectionScope:
    section_id: str
    label: str
    phases: tuple[PhaseScope, ...] = ()

    @property
    def days(self) -> Decimal:
        return sum((phase.days for phase in self.phases), Decimal("0"))

    def phase(self, phase_id: str | None) -> PhaseScope | None:
        if phase_id is None:
            return None
        return next((phase for phase in self.phases if phase.phase_id == phase_id), None)


@dataclass(frozen=True)
class WellScope:
    """The planned sections and phases of a well, as configured."""

    sections: tuple[SectionScope, ...] = ()

    @property
    def total_days(self) -> Decimal:
        return sum((section.days for section in self.sections), Decimal("0"))

    def section(self, section_id: str | None) -> SectionScope | None:
        if section_id is None:
            return None
        return next((section for section in self.sections if section.section_id == section_id), None)

    def planned_days(self, section_id: str | None, phase_id: str | None) -> Decimal:
        """Planned days for a scope. Unknown scopes have no planned days."""

        if section_id is None:
            return self.total_days
        section = self.section(section_id)
        if section is None:
            return Decimal("0")
        if phase_id is None:
            return section.days
        phase = section.phase(phase_id)
        return phase.days if phase is not None else Decimal("0")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateInput:
    category: str
    unit_rate: Decimal


@dataclass(frozen=True)
class ChargeInput:
    category: str
    quantity: Decimal
    unit: str = UNIT_DAYS


@dataclass(frozen=True)
class SectionRateInput:
    section_id: str
    phase_id: str | None
    amount: Decimal


@dataclass(frozen=True)
class ServiceRateInput:
    """One entered unit rate for a charge category.

    A row without ``section_id`` is the shared rate for that category and applies
    to every scope of the line. A row with ``section_id`` (and an optional
    ``phase_id``) is the rate for that scope only and overrides the shared one.
    """

    category: str
    unit_rate: Decimal
    section_id: str | None = None
    phase_id: str | None = None

    @property
    def is_scope_rate(self) -> bool:
        return self.section_id is not None


@dataclass(frozen=True)
class ScopeDaysInput:
    """Explicit day quantity for one (section, optional phase) of a line."""

    category: str
    quantity: Decimal
    unit: str = UNIT_DAYS
    section_id: str | None = None
    phase_id: str | None = None

    @property
    def is_scope_days(self) -> bool:
        return self.section_id is not None


@dataclass(frozen=True)
class ServiceLine:
    key: str
    label: str
    charging_basis: str
    currency: str = ""
    section_id: str | None = None
    phase_id: str | None = None
    service_amount: Decimal = Decimal("0")
    rates: tuple[RateInput, ...] = ()
    charges: tuple[ChargeInput, ...] = ()
    section_rates: tuple[SectionRateInput, ...] = ()
    # Scope-aware rate card. Any entry here takes precedence over ``rates`` and
    # ``charges``; a shared rate (no section) covers every scope of the line.
    service_rates: tuple[ServiceRateInput, ...] = ()
    scope_days: tuple[ScopeDaysInput, ...] = ()

    def rate_for(self, category: str) -> Decimal:
        for rate in self.rates:
            if rate.category == category:
                return Decimal(rate.unit_rate)
        return Decimal("0")

    def scope_rate_for(self, category: str, section_id: str | None, phase_id: str | None) -> Decimal | None:
        """The scoped rate when one is entered for exactly this (section, phase)."""

        look_section, look_phase = (section_id, phase_id) if section_id is not None else (None, None)
        for rate in self.service_rates:
            if rate.category != category:
                continue
            if rate.section_id == look_section and rate.phase_id == look_phase:
                return Decimal(rate.unit_rate)
        return None

    def shared_rate_for(self, category: str) -> Decimal | None:
        for rate in self.service_rates:
            if rate.category == category and rate.section_id is None:
                return Decimal(rate.unit_rate)
        return self.rate_for(category) if not self.service_rates else None

    def scope_days_for(self, category: str, section_id: str | None, phase_id: str | None) -> Decimal | None:
        look_section, look_phase = (section_id, phase_id) if section_id is not None else (None, None)
        for row in self.scope_days:
            if row.category == category and row.section_id == look_section and row.phase_id == look_phase:
                return normalize_days(row.quantity, row.unit)
        return None


@dataclass(frozen=True)
class ConsumableLine:
    key: str
    label: str
    category: str
    section_id: str
    phase_id: str | None = None
    quantity: Decimal = Decimal("1")
    captured_rate: Decimal = Decimal("0")
    override_rate: Decimal | None = None
    estimated_amount: Decimal | None = None
    currency: str = ""


@dataclass(frozen=True)
class TangibleLine:
    key: str
    label: str
    quantity: Decimal = Decimal("1")
    captured_rate: Decimal = Decimal("0")
    override_rate: Decimal | None = None
    currency: str = ""
    uom: str = ""


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Component:
    group: str
    category: str
    description: str
    amount: Decimal
    section_id: str | None = None
    phase_id: str | None = None
    quantity: Decimal | None = None
    rate: Decimal | None = None
    unit: str = ""


@dataclass(frozen=True)
class LineResult:
    key: str
    group: str
    label: str
    amount: Decimal
    currency: str
    components: tuple[Component, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CurrencySetup:
    """The standard currency and the conversion rates an estimate was priced with.

    ``exchange_rates`` holds only the rates that are needed: one per detected currency
    other than the standard. ``missing_rates`` lists detected currencies without one.
    """

    standard_currency: str
    currencies: tuple[str, ...]
    exchange_rates: tuple[tuple[str, Decimal], ...] = ()
    missing_rates: tuple[str, ...] = ()
    standard_missing: bool = False

    @property
    def multi_currency(self) -> bool:
        return len(self.currencies) > 1

    @property
    def converted(self) -> bool:
        return not self.standard_missing and not self.missing_rates

    def factor(self, currency: str) -> Decimal | None:
        """Units of the standard currency per one unit of ``currency``; None when unknown."""

        if currency == self.standard_currency:
            return Decimal("1")
        return dict(self.exchange_rates).get(currency)


def resolve_currency(currencies: Iterable[str], standard: str = "", rates: Mapping[str, Decimal] | None = None) -> CurrencySetup:
    """Work out the standard currency and the rates needed for the detected currencies."""

    detected = tuple(sorted({(code or "").strip().upper() for code in currencies}))
    requested = (standard or "").strip().upper()
    if len(detected) <= 1:
        # A single currency is its own standard. Any stored choice is ignored.
        return CurrencySetup(standard_currency=detected[0] if detected else requested, currencies=detected)
    if not requested:
        return CurrencySetup(standard_currency="", currencies=detected, standard_missing=True)

    supplied = {(code or "").strip().upper(): Decimal(value) for code, value in (rates or {}).items()}
    used: list[tuple[str, Decimal]] = []
    missing: list[str] = []
    for code in detected:
        if code == requested:
            continue
        rate = supplied.get(code)
        if rate is None or rate <= 0:
            missing.append(code)
        else:
            used.append((code, rate))
    return CurrencySetup(
        standard_currency=requested,
        currencies=detected,
        exchange_rates=tuple(used),
        missing_rates=tuple(missing),
    )


@dataclass(frozen=True)
class SectionSummary:
    section_id: str | None
    label: str
    planned_days: Decimal
    services: Decimal | None
    consumables: Decimal | None
    tangibles: Decimal | None

    @property
    def total(self) -> Decimal | None:
        if self.services is None or self.consumables is None or self.tangibles is None:
            return None
        return money(self.services + self.consumables + self.tangibles)


@dataclass(frozen=True)
class EstimateResult:
    services: tuple[LineResult, ...]
    consumables: tuple[LineResult, ...]
    tangibles: tuple[LineResult, ...]
    by_section: tuple[SectionSummary, ...]
    services_total: Decimal | None
    consumables_total: Decimal | None
    tangibles_total: Decimal | None
    totals_by_currency: tuple[tuple[str, Decimal], ...]
    currency: CurrencySetup
    warnings: tuple[str, ...]

    @property
    def total(self) -> Decimal | None:
        """Grand total in the standard currency, or None while a rate is missing."""

        if self.services_total is None or self.consumables_total is None or self.tangibles_total is None:
            return None
        return money(self.services_total + self.consumables_total + self.tangibles_total)


# ---------------------------------------------------------------------------
# Line pricing
# ---------------------------------------------------------------------------

ScopeKey = tuple[str | None, str | None]
_SECTION_WARNING = "Section is not in the well configuration"


def _section_text(section: SectionScope | None, phase: PhaseScope | None) -> str:
    return " · ".join(text for text in (section.label if section else "", phase.label if phase else "") if text) or "whole well"


def _day_component(
    category: str,
    days: Decimal,
    rate: Decimal,
    section: SectionScope | None,
    phase: PhaseScope | None,
    scope_label: str,
) -> Component:
    amount = money(days * rate)
    return Component(
        group=GROUP_SERVICES,
        category=category,
        description=f"{category} — {days} day(s) @ {_qty(rate)} · {scope_label}",
        amount=amount,
        section_id=section.section_id if section else None,
        phase_id=phase.phase_id if phase else None,
        quantity=days,
        rate=_qty(rate),
        unit="day",
    )


def _resolve_scope(
    well: WellScope,
    section_id: str | None,
    phase_id: str | None,
    warnings: list[str],
    category: str,
) -> tuple[SectionScope | None, PhaseScope | None] | None:
    """The configured section and phase, or None when the scope is not in the plan."""

    if section_id is None:
        return None, None
    section = well.section(section_id)
    if section is None:
        warnings.append(f"{category}: {_SECTION_WARNING.lower()}; the amount is shown as well-level")
        return None
    if phase_id is not None:
        phase = section.phase(phase_id)
        if phase is None:
            warnings.append(f"{category}: the phase is not planned under {section.label}; the amount is shown at section level")
            return section, None
        return section, phase
    return section, None


def _scope_rates(line: ServiceLine) -> dict[tuple[str, str | None, str | None], Decimal]:
    """Entered per-scope rates, keyed by (category, section, phase)."""

    rates: dict[tuple[str, str | None, str | None], Decimal] = {}
    for rate in line.service_rates:
        if rate.section_id is None:
            continue
        rates[(rate.category, rate.section_id, rate.phase_id)] = Decimal(rate.unit_rate)
    return rates


def _shared_rate(line: ServiceLine, category: str) -> Decimal | None:
    """One rate for every scope of the category: a shared row, else a legacy rate."""

    for rate in line.service_rates:
        if rate.category == category and rate.section_id is None:
            return Decimal(rate.unit_rate)
    if line.service_rates:
        # A scope-aware line prices only the categories it actually carries rates for.
        return None
    legacy = line.rate_for(category)
    return legacy if legacy != 0 or any(rate.category == category for rate in line.rates) else None


def _explicit_days(line: ServiceLine) -> tuple[dict[tuple[str, str | None, str | None], Decimal], dict[str, Decimal]]:
    """Explicit day quantities, split into scoped rows and whole-line rows."""

    scoped: dict[tuple[str, str | None, str | None], Decimal] = {}
    shared: dict[str, Decimal] = {}
    for row in line.scope_days:
        days = normalize_days(row.quantity, row.unit)
        if days == 0:
            continue
        if row.section_id is None:
            shared[row.category] = shared.get(row.category, Decimal("0")) + days
        else:
            key = (row.category, row.section_id, row.phase_id)
            scoped[key] = scoped.get(key, Decimal("0")) + days
    for charge in line.charges:
        if charge.category in ONE_TIME_CATEGORIES:
            continue
        days = normalize_days(charge.quantity, charge.unit)
        if days == 0:
            continue
        shared[charge.category] = shared.get(charge.category, Decimal("0")) + days
    return scoped, shared


def _covered_scopes(line: ServiceLine, well: WellScope) -> list[ScopeKey]:
    """Which (section, phase) pairs the service is used on.

    Scope rows entered in the dialog decide it when there are any; otherwise the
    line's own section (and phase); otherwise the whole well, which the caller
    splits across every configured section.
    """

    covered: list[ScopeKey] = []
    for rate in line.service_rates:
        if rate.section_id is None:
            continue
        key = (rate.section_id, rate.phase_id)
        if key not in covered:
            covered.append(key)
    for row in line.scope_days:
        if row.section_id is None:
            continue
        key = (row.section_id, row.phase_id)
        if key not in covered:
            covered.append(key)
    if not covered and line.section_id is not None:
        covered.append((line.section_id, line.phase_id))
    return covered


def _daily_components(line: ServiceLine, well: WellScope, warnings: list[str]) -> list[Component]:
    """Price every day-based category once per scope the service covers.

    A shared rate applies to every covered scope; a scope rate overrides it for
    that scope alone. Each category is therefore never priced twice for the same
    scope, and the line's amount is the sum of all the scopes it covers.
    """

    scope_rates = _scope_rates(line)
    scoped_days, shared_days = _explicit_days(line)
    covered = _covered_scopes(line, well)
    well_wide = not covered

    components: list[Component] = []
    for category in DAY_CATEGORIES:
        rate_scopes = [key for key in covered if (category, key[0], key[1]) in scope_rates]
        shared = _shared_rate(line, category)
        entries: list[tuple[Decimal, Decimal, str | None, str | None]] = []

        # 1. A scope rate prices its own scope with that scope's days. When one
        # phase of a section carries its own rate, a rate for the whole section
        # covers only the remaining phases, so a phase is never priced twice.
        phased_sections = {
            rate_section for rate_category, rate_section, rate_phase in scope_rates
            if rate_category == category and rate_phase is not None
        }
        for section_id, phase_id in rate_scopes:
            rate = scope_rates[(category, section_id, phase_id)]
            days = scoped_days.get((category, section_id, phase_id))
            if days is None and not (phase_id is None and section_id in phased_sections):
                days = shared_days.get(category)
            if days is None:
                days = _scope_days_or_free_phases(
                    well, category, section_id, phase_id, scope_rates, section_id in phased_sections
                )
            entries.append((days, rate, section_id, phase_id))

        if shared is not None:
            if rate_scopes:
                # The shared rate covers the remaining scopes of the line only
                # when the line itself names one section; a well-wide line with
                # some scoped rates has no other scope to fall back to.
                if line.section_id is not None and (line.section_id, line.phase_id) not in rate_scopes:
                    days = scoped_days.get((category, line.section_id, line.phase_id))
                    if days is None:
                        days = shared_days.get(category)
                    if days is None:
                        days = well.planned_days(line.section_id, line.phase_id)
                    entries.append((days, shared, line.section_id, line.phase_id))
            elif well_wide:
                explicit = shared_days.get(category)
                weighted = [section for section in well.sections if section.days > 0]
                total_weight = sum((section.days for section in weighted), Decimal("0"))
                if total_weight == 0:
                    warnings.append(
                        "Well-wide day rate has no planned days in the configuration to split across"
                    )
                    entries.append((explicit if explicit is not None else well.total_days, shared, None, None))
                elif explicit is None:
                    # Each section carries its own planned days.
                    entries.extend((section.days, shared, section.section_id, None) for section in weighted)
                else:
                    # An entered total is split across the sections by their planned days.
                    for section in weighted:
                        entries.append((_qty(explicit * section.days / total_weight), shared, section.section_id, None))
            else:
                for section_id, phase_id in covered:
                    if (category, section_id, phase_id) in scope_rates:
                        continue
                    days = scoped_days.get((category, section_id, phase_id))
                    if days is None:
                        days = shared_days.get(category)
                    if days is None:
                        days = well.planned_days(section_id, phase_id)
                    entries.append((days, shared, section_id, phase_id))

        for days, rate, section_id, phase_id in entries:
            if days == 0:
                continue
            if rate == 0:
                warnings.append(f"{category}: {days} day(s) entered without a unit rate, so not priced")
                continue
            resolved = _resolve_scope(well, section_id, phase_id, warnings, category)
            if resolved is None:
                section, phase = None, None
            else:
                section, phase = resolved
            components.append(
                _day_component(
                    category,
                    days,
                    rate,
                    section,
                    phase,
                    _section_text(section, phase) if (section or phase) else WELL_LEVEL_LABEL,
                )
            )

    # Explicit days entered without any rate are reported, never silently priced.
    for category, days in shared_days.items():
        if category in ONE_TIME_CATEGORIES:
            continue
        if _shared_rate(line, category) is None and not any(
            key[0] == category for key in scope_rates
        ):
            warnings.append(f"{category}: {days} day(s) entered without a unit rate, so not priced")
    return components


def _scope_days_or_free_phases(
    well: WellScope,
    category: str,
    section_id: str,
    phase_id: str | None,
    scope_rates: dict[tuple[str, str | None, str | None], Decimal],
    section_has_phase_rates: bool,
) -> Decimal:
    """Days for one scope rate row.

    A phase row uses its own phase days. A whole-section row whose section also
    has phase rates covers only the phases without a rate of their own, so the
    phase days are never counted twice.
    """

    if phase_id is not None:
        return well.planned_days(section_id, phase_id)
    if not section_has_phase_rates:
        return well.planned_days(section_id, None)
    section = well.section(section_id)
    if section is None:
        return Decimal("0")
    return sum(
        (
            phase.days for phase in section.phases
            if (category, section_id, phase.phase_id) not in scope_rates
        ),
        Decimal("0"),
    )


def _one_time_components(line: ServiceLine, well: WellScope, warnings: list[str]) -> list[Component]:
    """One-time charges: once for the line, or once for each scope rate entered."""

    scope_rates = _scope_rates(line)
    components: list[Component] = []
    for category in ONE_TIME_CATEGORIES:
        scoped = [
            (section_id, phase_id, amount)
            for (rate_category, section_id, phase_id), amount in scope_rates.items()
            if rate_category == category
        ]
        if scoped:
            for section_id, phase_id, amount in scoped:
                resolved = _resolve_scope(well, section_id, phase_id, warnings, category)
                section, phase = (None, None) if resolved is None else resolved
                components.append(
                    Component(
                        group=GROUP_SERVICES,
                        category=category,
                        description=f"{category} — charged once · {_section_text(section, phase) if (section or phase) else WELL_LEVEL_LABEL}",
                        amount=money(amount),
                        section_id=section.section_id if section else None,
                        phase_id=phase.phase_id if phase else None,
                        quantity=Decimal("1"),
                        rate=_qty(amount),
                        unit="lump sum",
                    )
                )
            continue
        rate = _shared_rate(line, category)
        if rate is None or rate == 0:
            continue
        section = well.section(line.section_id)
        phase = section.phase(line.phase_id) if section and line.phase_id else None
        components.append(
            Component(
                group=GROUP_SERVICES,
                category=category,
                description=f"{category} — charged once · {_section_text(section, phase)}",
                amount=money(rate),
                section_id=section.section_id if section else None,
                phase_id=phase.phase_id if phase else None,
                quantity=Decimal("1"),
                rate=_qty(rate),
                unit="lump sum",
            )
        )
    return components


def estimate_service(line: ServiceLine, well: WellScope) -> LineResult:
    warnings: list[str] = []
    section = well.section(line.section_id)
    phase = section.phase(line.phase_id) if section else None
    if line.section_id is not None and section is None:
        warnings.append("Section is not in the well configuration")
    if line.phase_id is not None:
        if section is None:
            warnings.append("Phase cannot be used without a section from the well configuration")
        elif phase is None:
            warnings.append("Phase is not planned under this section in the well configuration")
    for row in line.service_rates:
        if row.section_id is None:
            continue
        row_section = well.section(row.section_id)
        if row_section is None:
            if _SECTION_WARNING not in warnings:
                warnings.append(_SECTION_WARNING)
            continue
        if row.phase_id is not None and row_section.phase(row.phase_id) is None:
            warnings.append(f"{row.category}: the phase is not planned under {row_section.label}")

    components: list[Component] = []
    if line.charging_basis == BASIS_DAY_RATE:
        components.extend(_daily_components(line, well, warnings))
        components.extend(_one_time_components(line, well, warnings))
    elif line.charging_basis == BASIS_PER_SECTION:
        if not line.section_rates:
            warnings.append("Per Section Rate service has no section amount entered")
        for entry in line.section_rates:
            entry_section = well.section(entry.section_id)
            if entry_section is None:
                warnings.append("A section rate refers to a section that is not in the well configuration")
                continue
            entry_phase = None
            if entry.phase_id is not None:
                entry_phase = entry_section.phase(entry.phase_id)
                if entry_phase is None:
                    warnings.append(f"A section rate refers to a phase not planned under {entry_section.label}")
                    continue
            components.append(
                Component(
                    group=GROUP_SERVICES,
                    category="Per Section Rate",
                    description=f"Per section rate — {_section_text(entry_section, entry_phase)}",
                    amount=money(entry.amount),
                    section_id=entry_section.section_id,
                    phase_id=entry_phase.phase_id if entry_phase else None,
                    quantity=Decimal("1"),
                    rate=_qty(entry.amount),
                    unit="section",
                )
            )
    else:
        if line.service_amount == 0:
            warnings.append("Per Service Rate service has no price entered")
        components.append(
            Component(
                group=GROUP_SERVICES,
                category="Per Service Rate",
                description=f"Per service price — {_section_text(section, phase)}",
                amount=money(line.service_amount),
                section_id=section.section_id if section else None,
                phase_id=phase.phase_id if phase else None,
                quantity=Decimal("1"),
                rate=_qty(line.service_amount),
                unit="service",
            )
        )

    amount = money(sum((component.amount for component in components), Decimal("0")))
    return LineResult(
        key=line.key,
        group=GROUP_SERVICES,
        label=line.label,
        amount=amount,
        currency=line.currency,
        components=tuple(components),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def estimate_consumable(line: ConsumableLine, well: WellScope) -> LineResult:
    warnings: list[str] = []
    section = well.section(line.section_id)
    if section is None:
        warnings.append("Section is not in the well configuration; priced as well-level")
    phase = None
    if line.phase_id is not None:
        phase = section.phase(line.phase_id) if section else None
        if phase is None:
            warnings.append("Phase is not planned under this section in the well configuration")
    scope = _section_text(section, phase)

    if line.category == CONSUMABLE_DRILL_BITS:
        rate = effective_rate(line.captured_rate, line.override_rate)
        if rate == 0:
            warnings.append("Drill bit has no unit rate in master data and no override entered")
        amount = money(Decimal(line.quantity) * rate)
        component = Component(
            group=GROUP_CONSUMABLES,
            category=CONSUMABLE_DRILL_BITS,
            description=f"{line.label} — {line.quantity} bit(s) @ {money(rate)} · {scope}",
            amount=amount,
            section_id=section.section_id if section else None,
            phase_id=phase.phase_id if phase else None,
            quantity=Decimal(line.quantity),
            rate=_qty(rate),
            unit="bit",
        )
    else:
        estimate = Decimal(line.estimated_amount or 0)
        if estimate == 0:
            warnings.append(f"{line.category} has no estimated amount entered")
        amount = money(estimate)
        component = Component(
            group=GROUP_CONSUMABLES,
            category=line.category,
            description=f"{line.category} — lump-sum estimate · {scope}",
            amount=amount,
            section_id=section.section_id if section else None,
            phase_id=phase.phase_id if phase else None,
            unit="lump sum",
        )

    return LineResult(
        key=line.key,
        group=GROUP_CONSUMABLES,
        label=line.label,
        amount=amount,
        currency=line.currency,
        components=(component,),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def estimate_tangible(line: TangibleLine) -> LineResult:
    warnings: list[str] = []
    rate = effective_rate(line.captured_rate, line.override_rate)
    if rate == 0:
        warnings.append("No unit rate captured from master data and no override entered")
    amount = money(Decimal(line.quantity) * rate)
    overridden = line.override_rate is not None
    component = Component(
        group=GROUP_TANGIBLES,
        category="Override rate" if overridden else "Captured rate",
        description=f"{line.label} — {line.quantity} {line.uom or 'unit'} @ {money(rate)}",
        amount=amount,
        quantity=Decimal(line.quantity),
        rate=_qty(rate),
        unit=line.uom,
    )
    return LineResult(
        key=line.key,
        group=GROUP_TANGIBLES,
        label=line.label,
        amount=amount,
        currency=line.currency,
        components=(component,),
        warnings=tuple(dict.fromkeys(warnings)),
    )


# ---------------------------------------------------------------------------
# Estimate compilation
# ---------------------------------------------------------------------------


def compile_estimate(
    well: WellScope,
    services: Sequence[ServiceLine] = (),
    consumables: Sequence[ConsumableLine] = (),
    tangibles: Sequence[TangibleLine] = (),
    standard_currency: str = "",
    exchange_rates: Mapping[str, Decimal] | None = None,
) -> EstimateResult:
    service_results = tuple(estimate_service(line, well) for line in services)
    consumable_results = tuple(estimate_consumable(line, well) for line in consumables)
    tangible_results = tuple(estimate_tangible(line) for line in tangibles)
    all_results = (*service_results, *consumable_results, *tangible_results)

    setup = resolve_currency((result.currency for result in all_results), standard_currency, exchange_rates)
    converted = setup.converted

    configured = {section.section_id for section in well.sections}
    buckets: dict[str | None, dict[str, Decimal]] = {
        section.section_id: {GROUP_SERVICES: Decimal("0"), GROUP_CONSUMABLES: Decimal("0"), GROUP_TANGIBLES: Decimal("0")}
        for section in well.sections
    }
    buckets[None] = {GROUP_SERVICES: Decimal("0"), GROUP_CONSUMABLES: Decimal("0"), GROUP_TANGIBLES: Decimal("0")}
    group_totals = {GROUP_SERVICES: Decimal("0"), GROUP_CONSUMABLES: Decimal("0"), GROUP_TANGIBLES: Decimal("0")}
    for result in all_results:
        factor = setup.factor(result.currency)
        if factor is None:
            continue  # Missing rate: the converted figures are withheld below.
        for component in result.components:
            value = money(component.amount * factor)
            bucket_id = component.section_id if component.section_id in configured else None
            buckets[bucket_id][component.group] += value
            group_totals[component.group] += value

    def shown(value: Decimal) -> Decimal | None:
        return money(value) if converted else None

    by_section = [
        SectionSummary(
            section_id=section.section_id,
            label=section.label,
            planned_days=section.days,
            services=shown(buckets[section.section_id][GROUP_SERVICES]),
            consumables=shown(buckets[section.section_id][GROUP_CONSUMABLES]),
            tangibles=shown(buckets[section.section_id][GROUP_TANGIBLES]),
        )
        for section in well.sections
    ]
    well_level = buckets[None]
    if any(value != 0 for value in well_level.values()):
        by_section.append(
            SectionSummary(
                section_id=None,
                label=WELL_LEVEL_LABEL,
                planned_days=Decimal("0"),
                services=shown(well_level[GROUP_SERVICES]),
                consumables=shown(well_level[GROUP_CONSUMABLES]),
                tangibles=shown(well_level[GROUP_TANGIBLES]),
            )
        )

    services_total = shown(group_totals[GROUP_SERVICES])
    consumables_total = shown(group_totals[GROUP_CONSUMABLES])
    tangibles_total = shown(group_totals[GROUP_TANGIBLES])

    # Totals as entered, one per currency. These are never added together.
    currency_totals: dict[str, Decimal] = {}
    for result in all_results:
        currency_totals[result.currency] = currency_totals.get(result.currency, Decimal("0")) + result.amount
    totals_by_currency = tuple(
        (currency, money(amount)) for currency, amount in sorted(currency_totals.items(), key=lambda item: item[0])
    )

    warnings: list[str] = []
    for result in all_results:
        warnings.extend(f"{result.label}: {text}" for text in result.warnings)
    if setup.multi_currency:
        names = ", ".join(currency or "no currency" for currency in setup.currencies)
        if setup.standard_missing:
            warnings.append(
                f"Estimate mixes currencies ({names}); select the standard currency and enter the conversion rate for each other currency"
            )
        elif setup.missing_rates:
            missing = ", ".join(currency or "no currency" for currency in setup.missing_rates)
            warnings.append(f"Enter the conversion rate to {setup.standard_currency} for {missing}")

    return EstimateResult(
        services=service_results,
        consumables=consumable_results,
        tangibles=tangible_results,
        by_section=tuple(by_section),
        services_total=services_total,
        consumables_total=consumables_total,
        tangibles_total=tangibles_total,
        totals_by_currency=totals_by_currency,
        currency=setup,
        warnings=tuple(dict.fromkeys(warnings)),
    )
