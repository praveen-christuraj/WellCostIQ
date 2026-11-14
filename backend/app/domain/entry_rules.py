"""The rules behind the daily-sheet entry checks.

A daily sheet is keyed by hand, every day, under time pressure. The rules here
read a sheet the way a careful colleague would and point out what looks
mistyped or inconsistent:

* a quantity far from what the same item usually carries (ten times the usual
  diesel, a rig day booked as 24 days instead of 24 hours);
* a daily rate override far from the locked rate, or from the rates the item
  was priced at before;
* an exchange rate that disagrees with the other sheets and with the AFE
  estimate, including a rate entered the other way round;
* a depth in the wrong unit, a depth outside its planned section, or a depth
  shallower than an earlier sheet recorded;
* the same line entered twice, a line that is usually present and is missing,
  and a day costing several times the usual.

Everything in this module is a pure function of the facts it is given: no
database, no clock, no randomness. The same sheet and history always produce
the same findings, and each finding quotes the figures it was derived from.
"""

from __future__ import annotations

import hashlib
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Sequence

from app.domain import entry_statistics as stats

# These Day Rate categories are priced once whatever quantity is recorded, so
# their quantity is not a cost driver and is not compared.
ONE_TIME_CATEGORIES = frozenset({"Mobilization", "Demobilization", "Fixed Charge"})
GROUPS = ("services", "consumables", "tangibles", "other_expenses")
GROUP_ORDER = {name: position for position, name in enumerate(GROUPS)}
HOURS_PER_DAY = Decimal("24")
FEET_PER_METRE = stats.FEET_PER_METRE

# A line that was on each of this many preceding sheets is "usually present".
USUAL_LINE_SHEETS = 5
# Exchange rates barely move from one sheet to the next, so three other sheets
# are already a pattern; one or two are still a reference.
MIN_FX_HISTORY = 3
# Against a single reference figure there is no spread to measure, so plain
# ratios decide: three times away is worth a look, twenty times is not a rate.
REFERENCE_NOTICE_RATIO = 3.0
REFERENCE_STRONG_RATIO = 20.0
# Two exchange rates for one currency agree when they are within this factor.
FX_AGREEMENT_RATIO = 2.5
FX_SAME_SHEET_TOLERANCE = 0.02
# A planned section may be drilled a little past its plan before it is worth a
# remark: five per cent of its length, and never less than fifteen metres.
DEPTH_TOLERANCE_FRACTION = 0.05
DEPTH_TOLERANCE_MIN = 15.0
DEPTH_BACKWARDS_TOLERANCE = 1.0
# A depth within this fraction of a neighbouring sheet's depth is progress, not
# a slip, even when it is outside the plan (a well drilled deeper than planned).
DEPTH_CONSISTENT_FRACTION = 0.15
DAY_TOTAL_RATIO = 4.0
DAY_TOTAL_LINE_SHARE = Decimal("0.5")
MAX_FINDINGS = 60
MAX_LISTED_NAMES = 6
MAX_KEY_LENGTH = 160

FAMILIES_QUANTITY = stats.DECIMAL_FAMILIES
FAMILIES_DAY_RATE = (
    stats.SCALE_10, stats.HOURS_DAYS, stats.DOUBLED_DIGIT, stats.SCALE_100, stats.SCALE_1000, stats.SWAPPED_DIGITS,
)
FAMILIES_RATE = stats.DECIMAL_FAMILIES
# Through a currency conversion only the order of magnitude can be trusted.
FAMILIES_SCALE = (stats.SCALE_10, stats.SCALE_100, stats.SCALE_1000)
FAMILIES_FX = (
    stats.SCALE_10, stats.INVERTED, stats.SCALE_100, stats.SCALE_1000, stats.DOUBLED_DIGIT, stats.SWAPPED_DIGITS,
)

LineRef = tuple[str, int]  # payload group, position inside the group
ProfileKey = tuple[str, str, str, str, str]  # kind, subject id, variant, metric, unit


# ---------------------------------------------------------------------------
# Facts: the few columns of a sheet the rules read
# ---------------------------------------------------------------------------


@dataclass
class LineFact:
    group: str
    index: int
    # service | consumable | tangible | other
    kind: str
    subject_id: str
    # What distinguishes one way of charging the item from another.
    variant: str
    label: str
    # Unit the quantity was entered in, and how to express it in the unit the
    # item is profiled in (Day Rate hours and days are both profiled as days).
    unit: str
    quantity: Decimal
    norm_factor: Decimal
    norm_unit: str
    captured_rate: Decimal
    # Currency of ``captured_rate``; "" when it is not known.
    captured_currency: str
    override_rate: Decimal | None
    currency: str
    # One unit of ``currency`` in USD.
    usd_fx: Decimal
    # The line's cost in the sheet's standard currency.
    amount: Decimal
    depth_m: Decimal | None
    depth_input: Decimal | None
    depth_unit: str
    depth_seq: int
    section_id: str | None
    phase_id: str | None
    sub_activity_id: str | None
    one_time: bool = False
    # Priced from itemised amounts, so its quantity and rate do not price it.
    itemised: bool = False
    # Free text that tells two otherwise identical lines apart.
    detail: str = ""

    @property
    def ref(self) -> LineRef:
        return (self.group, self.index)

    @property
    def subject_key(self) -> str:
        return f"{self.kind}:{self.subject_id}:{self.variant}"

    @property
    def quantity_key(self) -> str:
        return f"{self.subject_key}@{self.norm_unit}"

    @property
    def norm_quantity(self) -> Decimal:
        return self.quantity * self.norm_factor

    @property
    def effective_rate(self) -> Decimal | None:
        if self.override_rate is not None:
            return self.override_rate
        return self.captured_rate if self.captured_rate and self.captured_rate > 0 else None


@dataclass
class SheetSummary:
    """One sheet reduced to the figures a neighbouring sheet is compared with."""

    # Item and unit -> quantity recorded that day, in the unit it is profiled in.
    quantity: dict[str, float] = field(default_factory=dict)
    # (item, currency) -> unit rates the item was priced at.
    rates: dict[tuple[str, str], list[float]] = field(default_factory=dict)
    # Currency -> USD rates used on the sheet.
    fx: dict[str, list[float]] = field(default_factory=dict)
    # Section -> the depth that governs it on this sheet.
    depths: dict[str | None, float] = field(default_factory=dict)
    # Item -> label, for every priced item on the sheet.
    subjects: dict[str, str] = field(default_factory=dict)


@dataclass
class SheetFacts:
    entry_id: str
    code: str
    cost_date: date
    status: str
    afe_id: str
    baseline_id: str
    total: Decimal
    # One unit of the sheet's standard currency in USD.
    usd_fx: Decimal
    standard_currency: str
    lines: list[LineFact] = field(default_factory=list)
    _summary: SheetSummary | None = field(default=None, repr=False, compare=False)

    @property
    def summary(self) -> SheetSummary:
        """Computed once per sheet; a well review reads each sheet many times."""
        if self._summary is None:
            self._summary = summarise(self.lines)
        return self._summary


@dataclass
class SectionPlan:
    section_id: str
    label: str
    top: float
    bottom: float


@dataclass
class Plan:
    """The locked plan a sheet is read against."""

    # "drilling" or "completion".
    scope: str = ""
    standard_currency: str = "USD"
    sections: dict[str, SectionPlan] = field(default_factory=dict)
    # Currency -> USD per unit, from the AFE estimate. No daily sheet can change it.
    estimate_usd_fx: dict[str, float] = field(default_factory=dict)
    # Currency -> USD per unit, as the AFE's daily costs convert it today.
    current_usd_fx: dict[str, float] = field(default_factory=dict)

    def usd_per(self, currency: str) -> float | None:
        code = (currency or "").upper()
        if code == "USD":
            return 1.0
        value = self.current_usd_fx.get(code) or self.estimate_usd_fx.get(code)
        return value if value and value > 0 else None


@dataclass
class WorkspaceProfile:
    profile: stats.Profile
    wells: int


@dataclass
class Finding:
    key: str
    code: str
    severity: str
    title: str
    message: str
    basis: str = ""
    scope: str = "afe"
    subject_label: str = ""
    lines: list[LineRef] = field(default_factory=list)
    field_name: str = ""
    current_value: str | None = None
    current_display: str = ""
    suggested_value: str | None = None
    suggested_display: str = ""
    apply_to: list[LineRef] = field(default_factory=list)
    usual_display: str = ""
    history_count: int = 0
    fingerprint: str = ""


# ---------------------------------------------------------------------------
# Building facts
# ---------------------------------------------------------------------------


def to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def join_label(code: str, name: str) -> str:
    return " — ".join(part for part in (code, name) if part)


def service_normalisation(basis: str, unit: str) -> tuple[Decimal, str]:
    """Day Rate hours and days are one measure: both are compared as days."""
    if basis == "Day Rate" and unit in ("days", "hours"):
        return (Decimal("1") / HOURS_PER_DAY if unit == "hours" else Decimal("1")), "days"
    return Decimal("1"), unit


def line_fact(
    *, group: str, index: int, kind: str, subject_id: Any, variant_a: str, variant_b: str, unit: str,
    code: str, name: str, quantity: Any, captured_rate: Any, captured_currency: str, override_rate: Any,
    currency: str, usd_fx: Any, amount: Any, depth_m: Any, depth_input: Any, depth_unit: str, depth_seq: Any,
    section_id: str | None, phase_id: str | None, sub_activity_id: str | None, itemised: bool, detail: str = "",
) -> LineFact:
    """One line as the rules read it, from stored or previewed column values."""
    unit = unit or ""
    if kind == "service":
        factor, norm_unit = service_normalisation(variant_a or "", unit)
        variant = f"{variant_a or ''}|{variant_b or ''}"
        one_time = variant_a == "Day Rate" and variant_b in ONE_TIME_CATEGORIES
    else:
        factor, norm_unit, variant, one_time = Decimal("1"), unit, variant_a or "", False
    return LineFact(
        group=group, index=index, kind=kind, subject_id=str(subject_id or ""), variant=variant,
        label=join_label(code or "", name or ""), unit=unit, quantity=to_decimal(quantity),
        norm_factor=factor, norm_unit=norm_unit,
        captured_rate=to_decimal(captured_rate), captured_currency=(captured_currency or "").upper(),
        override_rate=to_decimal(override_rate) if override_rate is not None else None,
        currency=(currency or "").upper(), usd_fx=to_decimal(usd_fx), amount=to_decimal(amount),
        depth_m=to_decimal(depth_m) if depth_m is not None else None,
        depth_input=to_decimal(depth_input) if depth_input is not None else None,
        depth_unit=depth_unit or "m", depth_seq=int(depth_seq or 0),
        section_id=section_id or None, phase_id=phase_id or None, sub_activity_id=sub_activity_id or None,
        one_time=one_time, itemised=bool(itemised), detail=detail or "",
    )


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------


def plain(value: Any) -> str:
    """Canonical decimal text: no exponent, no trailing zeros (``24``, ``0.5``)."""
    return format(stats.tidy(to_decimal(value)), "f")


def number(value: Any) -> str:
    """A figure as it reads on a sheet: grouped thousands, no noise decimals."""
    amount = to_decimal(value)
    magnitude = abs(amount)
    if magnitude == 0:
        return "0"
    if magnitude >= 1000:
        places = 2
    elif magnitude >= 1:
        places = 3
    else:
        places = max(4, 3 - magnitude.adjusted())
    text = f"{amount.quantize(Decimal(1).scaleb(-places)):,f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def quantity_text(value: Any, unit: str) -> str:
    amount = to_decimal(value)
    label = (unit or "").strip()
    if label in ("days", "hours") and amount == 1:
        label = label[:-1]
    elif label in ("unit", "service", "section") and amount != 1:
        label += "s"
    return f"{number(amount)} {label}".strip()


def money_text(value: Any, currency: str) -> str:
    return f"{currency} {number(value)}".strip()


def fx_text(value: Any, currency: str) -> str:
    return f"1 {currency} = {number(value)} USD"


def metres_text(value: Any) -> str:
    return f"{number(to_decimal(value).quantize(Decimal('0.01')))} m"


def listed(labels: Sequence[str]) -> str:
    shown = list(labels[:MAX_LISTED_NAMES])
    text = "; ".join(shown)
    if len(labels) > len(shown):
        text += f"; and {len(labels) - len(shown)} more"
    return text


def sheets_text(count: int) -> str:
    return "1 sheet" if count == 1 else f"{count} sheets"


def lines_text(count: int) -> str:
    return "1 line" if count == 1 else f"{count} lines"


def make_key(code: str, *parts: Any) -> str:
    """Identity of a finding on its sheet; long identities are shortened to a digest."""
    text = "|".join([code, *[str(part) for part in parts]])
    if len(text) <= MAX_KEY_LENGTH:
        return text
    return f"{code}|{hashlib.sha256(text.encode('utf-8')).hexdigest()[:40]}"


def make_fingerprint(*parts: Any) -> str:
    text = "|".join(str(part) for part in parts)
    if len(text) <= 80:
        return text
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:40]


def ordered_refs(lines: Sequence[LineFact]) -> list[LineRef]:
    return sorted({line.ref for line in lines}, key=lambda ref: (GROUP_ORDER.get(ref[0], 9), ref[1]))


# ---------------------------------------------------------------------------
# History: what the neighbouring sheets carry
# ---------------------------------------------------------------------------


def governing_depths(lines: Sequence[LineFact]) -> dict[str | None, LineFact]:
    """The depth that governs each section of a sheet: the last one entered."""
    chosen: dict[str | None, tuple[tuple[int, int, int], LineFact]] = {}
    for line in lines:
        if line.depth_m is None:
            continue
        order = (line.depth_seq, GROUP_ORDER.get(line.group, 9), line.index)
        current = chosen.get(line.section_id)
        if current is None or order > current[0]:
            chosen[line.section_id] = (order, line)
    return {section_id: item[1] for section_id, item in chosen.items()}


def summarise(lines: Sequence[LineFact]) -> SheetSummary:
    summary = SheetSummary()
    sums: dict[str, Decimal] = defaultdict(Decimal)
    currencies: dict[str, set[float]] = defaultdict(set)
    for line in lines:
        key = line.subject_key
        if line.kind != "other":
            summary.subjects.setdefault(key, line.label)
            if not line.one_time:
                sums[line.quantity_key] += line.norm_quantity
            rate = line.effective_rate
            if rate is not None and rate > 0 and not line.itemised:
                summary.rates.setdefault((key, line.currency), []).append(float(rate))
        if line.currency and line.currency != "USD" and line.usd_fx > 0:
            currencies[line.currency].add(float(line.usd_fx))
    summary.quantity = {key: float(total) for key, total in sums.items() if total > 0}
    summary.fx = {currency: sorted(values) for currency, values in currencies.items()}
    summary.depths = {
        section_id: float(line.depth_m or 0) for section_id, line in governing_depths(lines).items()
    }
    return summary


class History:
    """Per-item figures of the neighbouring sheets, one figure per sheet."""

    def __init__(self, neighbours: Sequence[SheetFacts]):
        self.sheets = sorted(neighbours, key=lambda sheet: (sheet.cost_date, sheet.code))
        self.quantity: dict[str, list[float]] = defaultdict(list)
        self.rates: dict[tuple[str, str], list[float]] = defaultdict(list)
        self.fx: dict[str, list[float]] = defaultdict(list)
        self.depths: dict[str | None, list[tuple[date, float, str]]] = defaultdict(list)
        self.presence: dict[str, set[str]] = defaultdict(set)
        self.labels: dict[str, str] = {}
        self.totals = [float(sheet.total) for sheet in self.sheets if sheet.total > 0]
        self.sheet_fx = [float(sheet.usd_fx) for sheet in self.sheets if sheet.usd_fx > 0]
        for sheet in self.sheets:
            summary = sheet.summary
            for key, label in summary.subjects.items():
                self.presence[key].add(sheet.entry_id)
                self.labels.setdefault(key, label)
            for key, total in summary.quantity.items():
                self.quantity[key].append(total)
            for rate_key, values in summary.rates.items():
                self.rates[rate_key].extend(values)
            for currency, values in summary.fx.items():
                self.fx[currency].extend(values)
            for section_id, depth in summary.depths.items():
                self.depths[section_id].append((sheet.cost_date, depth, sheet.code))


def choose_profile(
    values: Sequence[float], workspace: WorkspaceProfile | None, *, minimum: int = stats.MIN_HISTORY,
) -> tuple[stats.Profile, str, int] | None:
    """The AFE's own history when it is long enough, else the workspace profile."""
    if len(values) >= minimum:
        profile = stats.build_profile(values)
        if profile is not None:
            return profile, "afe", 0
    if workspace is not None and workspace.profile.count >= stats.MIN_HISTORY:
        return workspace.profile, "workspace", workspace.wells
    return None


def unremarkable(values: Sequence[float], value: Any, *, minimum: int = stats.MIN_HISTORY) -> bool:
    """A value near the middle of a long-enough history of its own AFE.

    Such a value cannot become a finding, so the caller skips it without
    building the item's profile. It is exactly the test :func:`stats.measure`
    applies first; nothing is judged differently, only sooner.
    """
    return len(values) >= minimum and stats.far_from_median(value, values) is False


def _most_between(low: str, high: str) -> str:
    return f" (most between {low} and {high})" if low != high else ""


def quantity_basis(profile: stats.Profile, scope: str, wells: int, usual: str, low: str, high: str) -> str:
    """The evidence behind a quantity finding: what was compared, and with how much history."""
    spread = _most_between(low, high)
    if scope == "workspace":
        on = f" on {wells} wells" if wells > 1 else ""
        return f"Across this workspace a sheet usually carries {usual}{spread}: {sheets_text(profile.count)}{on}."
    return f"The {profile.count} nearest sheets of this AFE usually carry {usual} each{spread}."


def rate_basis(profile: stats.Profile, scope: str, wells: int, usual: str, low: str, high: str) -> str:
    """The evidence behind a rate finding."""
    spread = _most_between(low, high)
    if scope == "workspace":
        on = f" on {wells} wells" if wells > 1 else ""
        return f"Across this workspace it is usually priced at {usual}{spread}: {lines_text(profile.count)}{on}."
    return f"The nearest sheets of this AFE usually price it at {usual}{spread}: {lines_text(profile.count)}."


def severity_of(deviation: stats.Deviation, slip: stats.Slip | None) -> str:
    return "warning" if deviation.strong or (slip is not None and deviation.slip_grade) else "info"


def reference_profile(value: float) -> stats.Profile:
    """A single reference figure (a locked rate) as a profile with no spread."""
    return stats.Profile(count=1, median=value, spread=0.0, low=value, high=value, common=value)


# ---------------------------------------------------------------------------
# Quantities
# ---------------------------------------------------------------------------


def _more_than_a_day(key: str, lines: Sequence[LineFact], total: Decimal, findings: list[Finding]) -> None:
    """Without any history: more than one day on a sheet that covers one day."""
    first = lines[0]
    if not (first.kind == "service" and first.norm_unit == "days") or total <= 1:
        return
    in_days = [line for line in lines if line.unit == "days" and line.quantity > 1]
    if not in_days:
        return
    target = max(in_days, key=lambda line: line.quantity)
    finding = Finding(
        key=make_key("unusual-quantity", key),
        code="more-than-a-day",
        severity="warning" if target.quantity == HOURS_PER_DAY else "info",
        title=f"{first.label}: more than one day on a daily sheet",
        message=f"{quantity_text(target.quantity, 'days')} is recorded on a sheet that covers one day.",
        basis="A Day Rate line normally carries at most one day (24 hours) on a daily sheet.",
        scope="sheet", subject_label=first.label, lines=ordered_refs(lines), field_name="quantity_unit",
        current_value=target.unit, current_display=quantity_text(target.quantity, target.unit),
        usual_display="1 day", history_count=0, fingerprint=make_fingerprint("q", plain(total)),
    )
    if target.quantity <= HOURS_PER_DAY:
        finding.suggested_value = "hours"
        finding.suggested_display = quantity_text(target.quantity, "hours")
        finding.apply_to = [target.ref]
        finding.message += f" If {finding.suggested_display} was meant, change the unit to hours."
    findings.append(finding)


def check_quantities(
    sheet: SheetFacts, history: History, profiles: dict[ProfileKey, WorkspaceProfile], findings: list[Finding],
) -> None:
    grouped: dict[str, list[LineFact]] = defaultdict(list)
    for line in sheet.lines:
        if line.kind == "other" or line.one_time or line.quantity <= 0:
            continue
        grouped[line.quantity_key].append(line)
    for key, lines in grouped.items():
        first = lines[0]
        total = sum((line.norm_quantity for line in lines), Decimal("0"))
        recorded = history.quantity.get(key, ())
        if unremarkable(recorded, total):
            continue
        chosen = choose_profile(
            recorded, profiles.get((first.kind, first.subject_id, first.variant, "quantity", first.norm_unit)),
        )
        if chosen is None:
            _more_than_a_day(key, lines, total, findings)
            continue
        profile, scope, wells = chosen
        deviation = stats.measure(total, profile)
        if deviation is None or not deviation.noticeable:
            continue
        day_rate = first.kind == "service" and first.norm_unit == "days"
        found = None
        if deviation.slip_grade:
            found = stats.explain_slip_in_sum(
                [(line.quantity, float(line.norm_factor)) for line in lines], profile,
                FAMILIES_DAY_RATE if day_rate else FAMILIES_QUANTITY,
            )
        slip = found[1] if found else None
        target = lines[found[0]] if found else max(lines, key=lambda line: line.norm_quantity)
        # Figures are quoted in the unit the lines were entered in.
        display_unit = first.unit if all(line.unit == first.unit for line in lines) else first.norm_unit
        to_display = HOURS_PER_DAY if (day_rate and display_unit == "hours") else Decimal("1")

        def shown(value: float | Decimal, unit: str = display_unit, scale: Decimal = to_display) -> str:
            return quantity_text(stats.tidy(to_decimal(value) * scale, places=3), unit)

        usual = shown(profile.usual)
        across = f" across {len(lines)} lines" if len(lines) > 1 else ""
        finding = Finding(
            key=make_key("unusual-quantity", key),
            code="unusual-quantity",
            severity=severity_of(deviation, slip),
            title=f"{first.label}: quantity looks too {'high' if deviation.ratio > 1 else 'low'}",
            message=(
                f"{quantity_text(total * to_display, display_unit)} is recorded for today{across}, "
                f"{stats.times(deviation.ratio)} the usual {usual}."
            ),
            basis=quantity_basis(profile, scope, wells, usual, shown(profile.low), shown(profile.high)),
            scope=scope, subject_label=first.label, lines=ordered_refs(lines), field_name="quantity",
            current_value=plain(target.quantity), current_display=quantity_text(target.quantity, target.unit),
            usual_display=usual, history_count=profile.count, fingerprint=make_fingerprint("q", plain(total)),
        )
        if slip is not None:
            finding.apply_to = [target.ref]
            other_unit = {"days": "hours", "hours": "days"}.get(target.unit)
            if slip.kind == stats.HOURS_DAYS and other_unit and (other_unit == "days" or target.quantity <= HOURS_PER_DAY):
                # The figure is right and the unit is wrong: offer the unit.
                finding.field_name = "quantity_unit"
                finding.current_value = target.unit
                finding.suggested_value = other_unit
                finding.suggested_display = quantity_text(target.quantity, other_unit)
            else:
                finding.suggested_value = plain(slip.corrected)
                finding.suggested_display = quantity_text(slip.corrected, target.unit)
            if len(lines) > 1:
                corrected_quantity = target.quantity if finding.field_name == "quantity_unit" else slip.corrected
                corrected_factor = (
                    service_normalisation("Day Rate", other_unit or target.unit)[0]
                    if finding.field_name == "quantity_unit" else target.norm_factor
                )
                corrected_total = total - target.norm_quantity + corrected_quantity * corrected_factor
                finding.message += (
                    f" This matches {slip.phrase} on one line: {finding.suggested_display} there would bring "
                    f"the day to {quantity_text(stats.tidy(corrected_total * to_display, places=3), display_unit)}."
                )
            else:
                finding.message += f" This matches {slip.phrase}: {finding.suggested_display} would be usual."
        findings.append(finding)


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------


def _against_locked_rate(
    line: LineFact, plan: Plan, base: dict[str, Any], suspect_fx: set[tuple[str, Decimal]],
) -> tuple[bool, Finding | None]:
    """Compare an override with the line's locked rate.

    Returns ``(comparable, finding)``. ``comparable`` is false when the line has
    no locked rate, or when the two are in different currencies and no
    conversion is known; the caller then falls back to the item's history.
    """
    rate = line.override_rate
    if rate is None or not line.captured_rate or line.captured_rate <= 0 or not line.captured_currency:
        return False, None
    locked = money_text(line.captured_rate, line.captured_currency)
    entered = money_text(rate, line.currency)
    if line.captured_currency == line.currency:
        ratio = float(rate / line.captured_rate)
        if not (ratio >= REFERENCE_NOTICE_RATIO or ratio <= 1 / REFERENCE_NOTICE_RATIO):
            return True, None
        slip = stats.explain_slip(rate, reference_profile(float(line.captured_rate)), FAMILIES_RATE)
        strong = slip is not None or ratio >= REFERENCE_STRONG_RATIO or ratio <= 1 / REFERENCE_STRONG_RATIO
        finding = Finding(
            **base, severity="warning" if strong else "info",
            title=f"{line.label}: rate override far from the locked rate",
            message=f"The daily rate override {entered} is {stats.times(ratio)} the locked rate {locked}.",
            basis="Compared with the rate locked for this line when tracking of the well began.",
            scope="baseline", usual_display=locked, history_count=1,
        )
        if slip is not None:
            finding.suggested_value = plain(slip.corrected)
            finding.suggested_display = money_text(slip.corrected, line.currency)
            finding.apply_to = [line.ref]
            finding.message += f" This matches {slip.phrase}: {finding.suggested_display} would be close to it."
        return True, finding
    # The override is in another currency: compare what both are worth in USD.
    locked_usd = plan.usd_per(line.captured_currency)
    if locked_usd is None or line.usd_fx <= 0 or (line.currency, stats.tidy(line.usd_fx)) in suspect_fx:
        # A comparison through an exchange rate that is itself in doubt says nothing.
        return False, None
    worth = rate * line.usd_fx
    locked_in_line_currency = float(line.captured_rate) * locked_usd / float(line.usd_fx)
    ratio = float(rate) / locked_in_line_currency
    if not (ratio >= REFERENCE_NOTICE_RATIO or ratio <= 1 / REFERENCE_NOTICE_RATIO):
        return True, None
    slip = stats.explain_slip(rate, reference_profile(locked_in_line_currency), FAMILIES_SCALE)
    strong = slip is not None or ratio >= REFERENCE_STRONG_RATIO or ratio <= 1 / REFERENCE_STRONG_RATIO
    finding = Finding(
        **base, severity="warning" if strong else "info",
        title=f"{line.label}: rate override far from the locked rate",
        message=(
            f"The daily rate override {entered} is worth about {money_text(worth, 'USD')} at this line's "
            f"exchange rate, {stats.times(ratio)} the locked rate {locked}."
        ),
        basis=(
            "Compared with the rate locked for this line when tracking of the well began, "
            "both converted to USD at the rates this sheet uses."
        ),
        scope="baseline", usual_display=locked, history_count=1,
    )
    if slip is not None:
        finding.suggested_value = plain(slip.corrected)
        finding.suggested_display = money_text(slip.corrected, line.currency)
        finding.apply_to = [line.ref]
        finding.message += f" This matches {slip.phrase}: {finding.suggested_display} would be close to it."
    return True, finding


def check_rates(
    sheet: SheetFacts, history: History, plan: Plan, profiles: dict[ProfileKey, WorkspaceProfile],
    findings: list[Finding], suspect_fx: set[tuple[str, Decimal]],
) -> None:
    for line in sheet.lines:
        rate = line.override_rate
        if line.kind == "other" or rate is None or rate <= 0 or line.itemised:
            continue
        base: dict[str, Any] = dict(
            key=make_key(
                "unusual-rate", line.subject_key, line.sub_activity_id or "", line.section_id or "",
                line.phase_id or "", line.currency, plain(rate),
            ),
            code="unusual-rate", subject_label=line.label, lines=[line.ref], field_name="override_rate",
            current_value=plain(rate), current_display=money_text(rate, line.currency),
            fingerprint=make_fingerprint("r", line.currency, plain(rate)),
        )
        comparable, against_locked = _against_locked_rate(line, plan, base, suspect_fx)
        if comparable:
            if against_locked is not None:
                findings.append(against_locked)
            continue
        # No comparable locked rate (an unplanned line): compare with the rates
        # this item was priced at before, in the same currency.
        priced = history.rates.get((line.subject_key, line.currency), ())
        if unremarkable(priced, rate):
            continue
        chosen = choose_profile(priced, profiles.get((line.kind, line.subject_id, line.variant, "rate", line.currency)))
        if chosen is None:
            continue
        profile, scope, wells = chosen
        deviation = stats.measure(rate, profile)
        if deviation is None or not deviation.noticeable:
            continue
        slip = stats.explain_slip(rate, profile, FAMILIES_RATE) if deviation.slip_grade else None
        usual = money_text(to_decimal(profile.usual), line.currency)
        finding = Finding(
            **base, severity=severity_of(deviation, slip),
            title=f"{line.label}: entered rate looks too {'high' if deviation.ratio > 1 else 'low'}",
            message=(
                f"The entered rate {money_text(rate, line.currency)} is {stats.times(deviation.ratio)} "
                f"the usual {usual} for this item."
            ),
            basis=rate_basis(
                profile, scope, wells, usual,
                money_text(to_decimal(profile.low), line.currency), money_text(to_decimal(profile.high), line.currency),
            ),
            scope=scope, usual_display=usual, history_count=profile.count,
        )
        if slip is not None:
            finding.suggested_value = plain(slip.corrected)
            finding.suggested_display = money_text(slip.corrected, line.currency)
            finding.apply_to = [line.ref]
            finding.message += f" This matches {slip.phrase}: {finding.suggested_display} would be usual."
        findings.append(finding)


# ---------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------


@dataclass
class _FxVerdict:
    severity: str
    scope: str
    basis: str
    usual: str
    count: int
    slip: stats.Slip | None
    ratio: float


def judge_exchange_rate(
    rate: Decimal, currency: str, history_values: Sequence[float], estimate: float | None,
) -> _FxVerdict | None:
    """Compare one exchange rate with the AFE estimate and the other sheets.

    Agreeing with either is enough: a currency that has moved since the
    estimate was made, and a sheet that returns to the estimate after an
    earlier mistake, both stay silent.
    """
    if rate <= 0:
        return None
    value = float(rate)

    def agrees(reference: float) -> bool:
        return reference > 0 and 1 / FX_AGREEMENT_RATIO < value / reference < FX_AGREEMENT_RATIO

    if estimate is not None and agrees(estimate):
        return None
    if len(history_values) >= MIN_FX_HISTORY:
        if stats.far_from_median(rate, history_values) is False:
            return None
        profile = stats.build_profile(history_values)
        if profile is None:
            return None
        deviation = stats.measure(rate, profile)
        if deviation is None or not deviation.noticeable:
            return None
        slip = stats.explain_slip(rate, profile, FAMILIES_FX) if deviation.slip_grade else None
        usual = fx_text(to_decimal(profile.usual), currency)
        return _FxVerdict(
            severity=severity_of(deviation, slip), scope="afe",
            basis=f"The other sheets of this AFE convert it at about {usual} ({sheets_text(profile.count)}).",
            usual=usual, count=profile.count, slip=slip, ratio=deviation.ratio,
        )
    middle = statistics.median(history_values) if history_values else None
    if middle is not None and agrees(middle):
        return None
    if estimate is not None and estimate > 0:
        reference, scope, count = estimate, "baseline", 1
        usual = fx_text(to_decimal(estimate), currency)
        basis = f"The AFE estimate converts it at {usual}."
    elif middle is not None and middle > 0:
        reference, scope, count = middle, "afe", len(history_values)
        usual = fx_text(to_decimal(middle), currency)
        basis = f"The other {sheets_text(count)} of this AFE that use {currency} convert it at {usual}."
    else:
        return None
    ratio = value / reference
    slip = stats.explain_slip(rate, reference_profile(reference), FAMILIES_FX)
    strong = slip is not None or ratio >= REFERENCE_STRONG_RATIO or ratio <= 1 / REFERENCE_STRONG_RATIO
    return _FxVerdict(
        severity="warning" if strong else "info", scope=scope, basis=basis, usual=usual, count=count,
        slip=slip, ratio=ratio,
    )


def check_exchange_rates(
    sheet: SheetFacts, history: History, plan: Plan, findings: list[Finding],
) -> set[tuple[str, Decimal]]:
    """Exchange-rate findings; returns the (currency, rate) pairs that are in doubt."""
    suspect: set[tuple[str, Decimal]] = set()
    by_currency: dict[str, list[LineFact]] = defaultdict(list)
    for line in sheet.lines:
        if line.currency and line.currency != "USD" and line.usd_fx > 0:
            by_currency[line.currency].append(line)
    for currency, lines in by_currency.items():
        by_rate: dict[Decimal, list[LineFact]] = defaultdict(list)
        for line in lines:
            by_rate[stats.tidy(line.usd_fx)].append(line)
        flagged = False
        for rate, same in by_rate.items():
            verdict = judge_exchange_rate(rate, currency, history.fx.get(currency, ()), plan.estimate_usd_fx.get(currency))
            if verdict is None:
                continue
            flagged = True
            suspect.add((currency, rate))
            refs = ordered_refs(same)
            finding = Finding(
                key=make_key("unusual-fx", currency, plain(rate)),
                code="unusual-fx", severity=verdict.severity,
                title=f"{currency}: exchange rate looks wrong",
                message=(
                    f"{fx_text(rate, currency)} is used on {lines_text(len(refs))}, "
                    f"{stats.times(verdict.ratio)} the usual {verdict.usual}."
                ),
                basis=verdict.basis, scope=verdict.scope, subject_label=currency, lines=refs,
                field_name="exchange_rate", current_value=plain(rate), current_display=fx_text(rate, currency),
                usual_display=verdict.usual, history_count=verdict.count,
                fingerprint=make_fingerprint("fx", currency, plain(rate)),
            )
            if verdict.slip is not None:
                finding.suggested_value = plain(verdict.slip.corrected)
                finding.suggested_display = fx_text(verdict.slip.corrected, currency)
                finding.apply_to = refs
                finding.message += f" This matches {verdict.slip.phrase}: {finding.suggested_display} would be usual."
            findings.append(finding)
        if flagged or len(by_rate) < 2:
            continue
        low, high = min(by_rate), max(by_rate)
        if float(high / low) - 1 <= FX_SAME_SHEET_TOLERANCE:
            continue
        # Nothing else disagrees, but the sheet disagrees with itself.
        majority = max(by_rate.items(), key=lambda item: (len(item[1]), -min(GROUP_ORDER.get(line.group, 9) for line in item[1])))[0]
        odd = ordered_refs([line for rate, same in by_rate.items() if rate != majority for line in same])
        odd_rate = next(rate for rate in by_rate if rate != majority)
        suspect.update((currency, rate) for rate in by_rate if rate != majority)
        findings.append(Finding(
            key=make_key("fx-inconsistent", currency),
            code="fx-inconsistent",
            severity="warning" if float(high / low) >= stats.STRONG_RATIO else "info",
            title=f"{currency}: {len(by_rate)} exchange rates on one sheet",
            message=(
                f"{currency} is converted at {len(by_rate)} different rates on this sheet, from "
                f"{number(low)} to {number(high)} USD. One day normally uses one rate."
            ),
            basis=f"Most {currency} lines of this sheet use {fx_text(majority, currency)}.",
            scope="sheet", subject_label=currency, lines=ordered_refs(lines), field_name="exchange_rate",
            current_value=plain(odd_rate), current_display=fx_text(odd_rate, currency),
            suggested_value=plain(majority), suggested_display=fx_text(majority, currency), apply_to=odd,
            usual_display=fx_text(majority, currency), history_count=len(lines),
            fingerprint=make_fingerprint("fx", currency, *sorted(plain(rate) for rate in by_rate)),
        ))
    # The sheet's own conversion from its standard currency to USD.
    standard = (plan.standard_currency or "USD").upper()
    if standard != "USD" and sheet.usd_fx > 0:
        verdict = judge_exchange_rate(sheet.usd_fx, standard, history.sheet_fx, plan.estimate_usd_fx.get(standard))
        if verdict is not None:
            finding = Finding(
                key=make_key("unusual-sheet-fx", standard),
                code="unusual-sheet-fx", severity=verdict.severity,
                title=f"{standard} to USD conversion rate looks wrong",
                message=(
                    f"This sheet converts at {fx_text(sheet.usd_fx, standard)}, "
                    f"{stats.times(verdict.ratio)} the usual {verdict.usual}."
                ),
                basis=verdict.basis, scope=verdict.scope, subject_label=f"{standard} to USD",
                field_name="usd_exchange_rate", current_value=plain(sheet.usd_fx),
                current_display=fx_text(sheet.usd_fx, standard), usual_display=verdict.usual,
                history_count=verdict.count, fingerprint=make_fingerprint("fx", standard, plain(sheet.usd_fx)),
            )
            if verdict.slip is not None:
                finding.suggested_value = plain(verdict.slip.corrected)
                finding.suggested_display = fx_text(verdict.slip.corrected, standard)
                finding.message += f" This matches {verdict.slip.phrase}: {finding.suggested_display} would be usual."
            findings.append(finding)
    return suspect


# ---------------------------------------------------------------------------
# Depths
# ---------------------------------------------------------------------------


def _depth_fix(
    line: LineFact, entered: Decimal, plausible: Callable[[float], bool],
) -> tuple[str, str, str, str] | None:
    """A unit or decimal slip that puts the depth where it belongs.

    Returns (field, value, how it would read, what kind of slip it is).
    """
    depth = float(line.depth_m or 0)
    feet = float(FEET_PER_METRE)
    if line.depth_unit == "m" and plausible(depth / feet):
        return "actual_depth_unit", "ft", f"{number(entered)} ft", "feet entered as metres"
    if line.depth_unit == "ft" and plausible(depth * feet):
        return "actual_depth_unit", "m", f"{number(entered)} m", "metres entered as feet"
    for factor, phrase in (
        (Decimal("0.1"), "one zero too many, or the decimal point one place too far right"),
        (Decimal("10"), "one zero missing, or the decimal point one place too far left"),
    ):
        if plausible(depth * float(factor)):
            corrected = stats.tidy(entered * factor)
            return "actual_depth", plain(corrected), f"{number(corrected)} {line.depth_unit}", phrase
    return None


def check_depths(sheet: SheetFacts, history: History, plan: Plan, findings: list[Finding]) -> None:
    # Depth only moves one way while a hole is drilled; completion work visits
    # depths in any order, so progress is not judged there.
    progression = plan.scope != "completion"
    governing = {id(line) for line in governing_depths(sheet.lines).values()}
    well_bounds: tuple[float, float] | None = None
    if plan.sections:
        well_bounds = (
            min(section.top for section in plan.sections.values()),
            max(section.bottom for section in plan.sections.values()),
        )
    grouped: dict[tuple[str | None, str, str], list[LineFact]] = defaultdict(list)
    for line in sheet.lines:
        if line.depth_m is not None and line.depth_m > 0:
            grouped[(line.section_id, plain(line.depth_m), line.depth_unit)].append(line)
    for (section_id, depth_text, _unit), lines in grouped.items():
        line = lines[0]
        depth = float(line.depth_m or 0)
        entered = line.depth_input if line.depth_input is not None else (line.depth_m or Decimal("0"))
        section = plan.sections.get(section_id or "")
        bounds = (section.top, section.bottom) if section else well_bounds
        if bounds is not None and bounds[1] <= bounds[0]:
            bounds = None
        tolerance = max(DEPTH_TOLERANCE_FRACTION * (bounds[1] - bounds[0]), DEPTH_TOLERANCE_MIN) if bounds else 0.0
        where = f"section {section.label}" if section else "the planned well"
        records = history.depths.get(section_id, ())
        earlier = [item for item in records if item[0] < sheet.cost_date]
        later = [item for item in records if item[0] > sheet.cost_date]
        previous = max(earlier, key=lambda item: item[0]) if earlier else None
        following = min(later, key=lambda item: item[0]) if later else None
        governs = any(id(item) in governing for item in lines)
        backwards = progression and governs and previous is not None and depth < previous[1] - DEPTH_BACKWARDS_TOLERANCE
        ahead = progression and governs and following is not None and depth > following[1] + DEPTH_BACKWARDS_TOLERANCE
        inside = bounds is None or bounds[0] - tolerance <= depth <= bounds[1] + tolerance
        consistent = any(
            abs(depth - neighbour[1]) <= DEPTH_CONSISTENT_FRACTION * max(neighbour[1], 1.0)
            for neighbour in (previous, following) if neighbour is not None
        )
        outside = not inside and not consistent
        if not (backwards or ahead or outside):
            continue

        def plausible(
            candidate: float, *, limits: tuple[float, float] | None = bounds, slack: float = tolerance,
            before: tuple[date, float, str] | None = previous, after: tuple[date, float, str] | None = following,
        ) -> bool:
            if limits is not None and not limits[0] - slack <= candidate <= limits[1] + slack:
                return False
            if progression and before is not None and candidate < before[1] - DEPTH_BACKWARDS_TOLERANCE:
                return False
            if progression and after is not None and candidate > after[1] + DEPTH_BACKWARDS_TOLERANCE:
                return False
            # With nothing to hold a figure against, any figure would "fit".
            return limits is not None or (progression and (before is not None or after is not None))

        fix = _depth_fix(line, entered, plausible)
        entered_text = f"{number(entered)} {line.depth_unit}"
        if line.depth_unit != "m":
            entered_text += f" ({metres_text(line.depth_m)})"
        if backwards and previous is not None:
            code, severity = "depth-decreased", "warning"
            title = f"{line.label}: depth shallower than an earlier sheet"
            message = (
                f"The actual depth {entered_text} is shallower than {metres_text(previous[1])} recorded for "
                f"the same section on {previous[0].isoformat()} ({previous[2]})."
            )
            basis = "Compared with the last depth entered for this section on the nearest earlier sheet of this AFE."
            scope, usual, count = "afe", metres_text(previous[1]), len(earlier)
        elif ahead and following is not None:
            code, severity = "depth-ahead", "warning" if fix else "info"
            title = f"{line.label}: depth deeper than a later sheet"
            message = (
                f"The actual depth {entered_text} is deeper than {metres_text(following[1])} recorded for "
                f"the same section on {following[0].isoformat()} ({following[2]})."
            )
            basis = "Compared with the last depth entered for this section on the nearest later sheet of this AFE."
            scope, usual, count = "afe", metres_text(following[1]), len(later)
        else:
            planned = f"{metres_text(bounds[0])} to {metres_text(bounds[1])}" if bounds else ""
            code, severity = "depth-outside-plan", "warning" if fix else "info"
            title = f"{line.label}: depth outside {where}"
            message = f"The actual depth {entered_text} is outside {where}, planned from {planned}."
            basis = "Compared with the section depths of the well plan locked with this AFE."
            scope, usual, count = "plan", planned, 1
        refs = ordered_refs(lines)
        finding = Finding(
            key=make_key(code, "section", section_id or "", depth_text, line.depth_unit),
            code=code, severity=severity, title=title, message=message, basis=basis, scope=scope,
            subject_label=line.label, lines=refs, field_name="actual_depth",
            current_value=plain(entered), current_display=entered_text, usual_display=usual, history_count=count,
            fingerprint=make_fingerprint("d", depth_text, line.depth_unit),
        )
        if fix is not None:
            finding.field_name, finding.suggested_value, finding.suggested_display, phrase = fix
            if finding.field_name == "actual_depth_unit":
                finding.current_value = line.depth_unit
            finding.apply_to = refs
            finding.message += f" This matches {phrase}: {finding.suggested_display} would fit."
        findings.append(finding)


# ---------------------------------------------------------------------------
# Whole-sheet checks
# ---------------------------------------------------------------------------


def check_duplicates(sheet: SheetFacts, findings: list[Finding]) -> None:
    """The same item, scope, quantity and rate on two lines: a likely double entry."""
    grouped: dict[tuple[Any, ...], list[LineFact]] = defaultdict(list)
    for line in sheet.lines:
        if line.kind == "service":
            # The sheet itself refuses a repeated service under one sub activity.
            continue
        grouped[(
            line.group, line.subject_key, line.section_id, line.phase_id, line.sub_activity_id,
            plain(line.quantity), plain(line.effective_rate or 0), line.currency, line.detail,
        )].append(line)
    for lines in grouped.values():
        if len(lines) < 2:
            continue
        first = lines[0]
        findings.append(Finding(
            key=make_key(
                "duplicate-line", first.subject_key, first.sub_activity_id or "", first.section_id or "",
                first.phase_id or "", plain(first.quantity), plain(first.effective_rate or 0), first.detail,
            ),
            code="duplicate-line", severity="warning",
            title=f"{first.label}: the same line appears {len(lines)} times",
            message=(
                f"{len(lines)} lines carry {first.label} with the same scope, quantity "
                f"({quantity_text(first.quantity, first.unit)}) and rate. If it was entered or copied twice, "
                "remove the extra line."
            ),
            basis="Compared with the other lines of this sheet.",
            scope="sheet", subject_label=first.label, lines=ordered_refs(lines), field_name="quantity",
            current_value=plain(first.quantity), current_display=quantity_text(first.quantity, first.unit),
            history_count=len(lines), fingerprint=make_fingerprint("dup", len(lines), plain(first.quantity)),
        ))


def check_usual_lines(sheet: SheetFacts, history: History, findings: list[Finding]) -> None:
    """Lines recorded on each of the preceding sheets and absent from this one."""
    if not sheet.lines:
        return
    earlier = [item for item in history.sheets if item.cost_date < sheet.cost_date]
    if len(earlier) < USUAL_LINE_SHEETS:
        return
    recent = {item.entry_id for item in earlier[-USUAL_LINE_SHEETS:]}
    present = {line.subject_key for line in sheet.lines}
    # A service recorded under another charge category is still that service.
    present_subjects = {(line.kind, line.subject_id) for line in sheet.lines}
    missing = sorted(
        (history.labels.get(key, key), key)
        for key, entries in history.presence.items()
        if recent <= entries and key not in present and tuple(key.split(":", 2)[:2]) not in present_subjects
    )
    if not missing:
        return
    labels = [label for label, _key in missing]
    several = len(missing) != 1
    findings.append(Finding(
        key=make_key("usual-line-missing", "sheet"),
        code="usual-line-missing", severity="info",
        title=f"{len(missing)} usual line{'s' if several else ''} not on this sheet",
        message=(
            f"{'These lines were' if several else 'This line was'} recorded on each of the last "
            f"{USUAL_LINE_SHEETS} sheets and {'are' if several else 'is'} not on this one: {listed(labels)}."
        ),
        basis=f"Compared with the {USUAL_LINE_SHEETS} sheets of this AFE before {sheet.cost_date.isoformat()}.",
        scope="afe", history_count=USUAL_LINE_SHEETS,
        fingerprint=make_fingerprint("missing", *[key for _label, key in missing]),
    ))


_LINE_LEVEL_EXPLANATIONS = frozenset({"unusual-quantity", "more-than-a-day", "unusual-rate", "unusual-fx", "duplicate-line"})


def check_day_total(sheet: SheetFacts, history: History, findings: list[Finding]) -> None:
    """A day costing several times the usual, when no single line explains it."""
    if sheet.total <= 0 or len(history.totals) < stats.MIN_HISTORY:
        return
    if any(item.severity == "warning" and item.code in _LINE_LEVEL_EXPLANATIONS for item in findings):
        return
    if stats.far_from_median(sheet.total, history.totals) is False:
        return
    profile = stats.build_profile(history.totals)
    if profile is None:
        return
    deviation = stats.measure(sheet.total, profile)
    if deviation is None or not deviation.noticeable or deviation.ratio < DAY_TOTAL_RATIO:
        return
    currency = sheet.standard_currency

    def money(value: Any) -> str:
        return money_text(to_decimal(value).quantize(Decimal("0.01")), currency)

    usual = money(profile.median)
    finding = Finding(
        key=make_key("unusual-day-total", "sheet"),
        code="unusual-day-total", severity="info",
        title="Day total several times the usual",
        message=f"This sheet totals {money(sheet.total)}, {stats.times(deviation.ratio)} the usual {usual} a day on this AFE.",
        basis=(
            f"The {profile.count} nearest sheets of this AFE total about {usual} a day"
            f"{_most_between(money(profile.low), money(profile.high))}."
        ),
        scope="afe", usual_display=usual, history_count=profile.count,
        fingerprint=make_fingerprint("total", plain(sheet.total.quantize(Decimal("0.01")))),
    )
    largest = max(sheet.lines, key=lambda line: line.amount, default=None)
    if largest is not None and largest.amount >= sheet.total * DAY_TOTAL_LINE_SHARE:
        share = int((largest.amount / sheet.total * 100).to_integral_value())
        finding.lines = [largest.ref]
        finding.subject_label = largest.label
        finding.message += f" The largest line is {largest.label}: {money(largest.amount)}, {share}% of the day."
    findings.append(finding)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def evaluate(
    sheet: SheetFacts,
    history: History,
    plan: Plan,
    profiles: dict[ProfileKey, WorkspaceProfile] | None = None,
) -> list[Finding]:
    """Every finding on one sheet, warnings first, then in sheet order."""
    workspace = profiles or {}
    findings: list[Finding] = []
    check_quantities(sheet, history, workspace, findings)
    suspect_fx = check_exchange_rates(sheet, history, plan, findings)
    check_rates(sheet, history, plan, workspace, findings, suspect_fx)
    check_depths(sheet, history, plan, findings)
    check_duplicates(sheet, findings)
    check_usual_lines(sheet, history, findings)
    check_day_total(sheet, history, findings)
    unique: dict[str, Finding] = {}
    for finding in findings:
        unique.setdefault(finding.key, finding)

    def position(item: Finding) -> tuple[int, int, int, str]:
        first = item.lines[0] if item.lines else ("", 10**6)
        return (0 if item.severity == "warning" else 1, GROUP_ORDER.get(first[0], 9), first[1], item.key)

    return sorted(unique.values(), key=position)[:MAX_FINDINGS]


def thin_subjects(sheet: SheetFacts, history: History) -> set[tuple[str, str]]:
    """Items on the sheet whose own AFE history is too short to judge them."""
    thin: set[tuple[str, str]] = set()
    for line in sheet.lines:
        if line.kind == "other":
            continue
        short_quantity = not line.one_time and len(history.quantity.get(line.quantity_key, ())) < stats.MIN_HISTORY
        short_rate = (
            line.override_rate is not None and not (line.captured_rate and line.captured_rate > 0)
            and len(history.rates.get((line.subject_key, line.currency), ())) < stats.MIN_HISTORY
        )
        if short_quantity or short_rate:
            thin.add((line.kind, line.subject_id))
    return thin
