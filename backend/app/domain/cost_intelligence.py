"""Cost Intelligence: deterministic analysis of a well's daily cost record.

Pure functions over plain numbers, standard library only (the hosted API runs
in 512 MB; see `.agent/memory/project.md`). Nothing here reads the database,
knows about HTTP, or changes a record. Every finding carries the figures it was
derived from and a plain statement of the rule, so a cost engineer can check it
by hand. The output is advice: it never blocks or rewrites an entry.

Methods
-------
* Robust centre and spread: median and MAD (scaled by 1.4826), so one bad day
  does not move the yardstick it is measured against.
* Spikes: modified z-score (Iglewicz & Hoaglin) of a day against the week on
  either side of it; flagged beyond 3.5, at least 25% from the local median,
  and only when no neighbouring day comes within 15% of it.
* Creeping drift: Page's two-sided CUSUM on standardised daily cost against the
  well's own opening baseline (slack k = 0.5, decision interval h = 4).
* Forecast: estimate at completion = spent + recent burn x remaining planned
  days, with a low/high range from the recent day-to-day spread.
* Record quality: missing cost dates, repeated identical totals, zero-cost
  days, sheets left in draft, sheets carrying entry-check warnings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from math import sqrt
from statistics import median

MAD_SCALE = 1.4826
SPIKE_Z = 3.5
SPIKE_MIN_RELATIVE = 0.25
SPIKE_MIN_HISTORY = 5
SPIKE_WINDOW = 7
SPIKE_ISOLATION = 0.15
CUSUM_SLACK = 0.5
CUSUM_LIMIT = 4.0
CUSUM_MIN_DAYS = 12
BASELINE_MIN_DAYS = 7
RECENT_DAYS = 7
NPT_WARNING_SHARE = 10.0
NPT_CRITICAL_SHARE = 20.0
OVERRUN_WARNING_PERCENT = 5.0
OVERRUN_CRITICAL_PERCENT = 15.0
STALE_DAYS = 3
REPEAT_RUN = 3
PENALTY = {"critical": 25, "warning": 10, "info": 3}
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class DayCost:
    cost_date: date
    actual: float
    npt: float = 0.0
    upa: float = 0.0


@dataclass(frozen=True)
class GroupCost:
    label: str
    planned: float | None
    actual: float


@dataclass(frozen=True)
class WellInput:
    """Everything the analysis may use about one well. ``None`` means "not known
    to this caller" (for example an AFE amount without ``afe:read``), and the
    checks that need the figure are skipped rather than guessed."""

    well_id: str
    well_code: str
    well_name: str = ""
    status: str = ""
    currency: str = ""
    afe_amount: float | None = None
    actual_amount: float | None = None
    planned_days: float | None = None
    actual_days: float | None = None
    npt_amount: float | None = None
    draft_sheets: int = 0
    sheet_count: int = 0
    warning_sheets: int = 0
    days: tuple[DayCost, ...] = ()
    groups: tuple[GroupCost, ...] = ()


@dataclass
class Finding:
    code: str
    severity: str
    category: str
    title: str
    detail: str
    basis: str
    suggestion: str
    well_id: str = ""
    well_code: str = ""
    cost_date: date | None = None
    amount: float | None = None
    evidence: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Forecast:
    available: bool = False
    reason: str = ""
    recent_daily: float = 0.0
    planned_daily: float | None = None
    remaining_days: float | None = None
    estimate: float | None = None
    low: float | None = None
    high: float | None = None
    variance: float | None = None
    variance_percent: float | None = None
    exhaustion_date: date | None = None
    days_to_exhaustion: float | None = None
    past_plan: bool = False


@dataclass
class Drift:
    available: bool = False
    baseline: float = 0.0
    spread: float = 0.0
    baseline_days: int = 0
    upper: list[float] = field(default_factory=list)
    lower: list[float] = field(default_factory=list)
    direction: str = ""
    alarm_index: int | None = None
    start_index: int | None = None
    recent_mean: float = 0.0
    change_percent: float = 0.0


@dataclass
class WellAnalysis:
    well: WellInput
    findings: list[Finding]
    forecast: Forecast
    drift: Drift
    spikes: list[int]
    missing_dates: list[date]
    score: int
    band: str
    summary: str


def money(value: float, currency: str = "") -> str:
    text = f"{value:,.0f}"
    return f"{currency} {text}".strip()


def robust_centre(values: list[float]) -> tuple[float, float]:
    """Median and a robust standard deviation (scaled MAD).

    When more than half the values are identical the MAD is zero; the mean
    absolute deviation (scaled to the same unit) is used instead so a flat
    record still has a usable spread.
    """
    if not values:
        return 0.0, 0.0
    centre = median(values)
    deviations = [abs(value - centre) for value in values]
    spread = MAD_SCALE * median(deviations)
    if spread <= 0:
        spread = 1.2533 * (sum(deviations) / len(deviations))
    return centre, spread


def find_spikes(values: list[float]) -> list[tuple[int, float, float]]:
    """Isolated days far from the days around them: (index, z, local median).

    Each day is compared with up to ``SPIKE_WINDOW`` days on either side. Using
    both sides matters: when a well moves to a new cost level (a new hole
    section, an added service) the days after the step agree with it, so the
    step is left to the drift check instead of being reported as a run of
    spikes. A day is flagged only when all three hold:

    * modified z-score beyond ``SPIKE_Z``;
    * at least ``SPIKE_MIN_RELATIVE`` away from the local median;
    * no other day in the window comes within ``SPIKE_ISOLATION`` of it, so a
      peak that recurs (a rig move every third day) is not an anomaly.
    """
    found: list[tuple[int, float, float]] = []
    for index, value in enumerate(values):
        around = values[max(0, index - SPIKE_WINDOW):index] + values[index + 1:index + 1 + SPIKE_WINDOW]
        if len(around) < SPIKE_MIN_HISTORY:
            continue
        centre, spread = robust_centre(around)
        if centre <= 0:
            continue
        if abs(value - centre) / centre < SPIKE_MIN_RELATIVE:
            continue
        # A spread under 5% of the level would make ordinary variation look extreme.
        z = (value - centre) / max(spread, 0.05 * centre)
        if abs(z) < SPIKE_Z:
            continue
        if value > centre and value < max(around) * (1 + SPIKE_ISOLATION):
            continue
        if value < centre and value > min(around) * (1 - SPIKE_ISOLATION):
            continue
        found.append((index, round(max(min(z, 99.0), -99.0), 2), centre))
    return found


def cusum(values: list[float], skip: set[int] | None = None) -> Drift:
    """Page's two-sided CUSUM against the well's own opening baseline.

    The baseline is the median of the first third of the record (at least
    ``BASELINE_MIN_DAYS`` days). Spike days are skipped so a single invoice
    does not register as a trend. ``start_index`` is the last day the statistic
    stood at zero before the alarm: the estimated day the level changed.
    """
    drift = Drift()
    if len(values) < CUSUM_MIN_DAYS:
        return drift
    skip = skip or set()
    baseline_days = max(BASELINE_MIN_DAYS, len(values) // 3)
    opening = [value for index, value in enumerate(values[:baseline_days]) if index not in skip]
    if len(opening) < SPIKE_MIN_HISTORY:
        return drift
    centre, spread = robust_centre(opening)
    if centre <= 0:
        return drift
    # A spread below 2% of the level would turn ordinary rounding into alarms.
    spread = max(spread, 0.02 * centre)
    drift.available, drift.baseline, drift.spread, drift.baseline_days = True, centre, spread, baseline_days
    up = down = 0.0
    up_zero = down_zero = -1
    for index, value in enumerate(values):
        if index not in skip:
            z = (value - centre) / spread
            up = max(0.0, up + z - CUSUM_SLACK)
            down = max(0.0, down - z - CUSUM_SLACK)
        if up == 0.0:
            up_zero = index
        if down == 0.0:
            down_zero = index
        drift.upper.append(round(up, 3))
        drift.lower.append(round(down, 3))
        if drift.alarm_index is None and index >= baseline_days:
            if up > CUSUM_LIMIT:
                drift.direction, drift.alarm_index, drift.start_index = "up", index, up_zero + 1
            elif down > CUSUM_LIMIT:
                drift.direction, drift.alarm_index, drift.start_index = "down", index, down_zero + 1
    if drift.alarm_index is not None:
        since = [value for index, value in enumerate(values) if index >= (drift.start_index or 0) and index not in skip]
        if since:
            drift.recent_mean = sum(since) / len(since)
            drift.change_percent = (drift.recent_mean - centre) / centre * 100
        # Still out of control at the end of the record? Otherwise it was a
        # passing excursion and is reported as information only.
        still = (drift.upper[-1] if drift.direction == "up" else drift.lower[-1]) > CUSUM_LIMIT
        if not still:
            drift.direction += "-recovered"
    return drift


def missing_dates(days: tuple[DayCost, ...]) -> list[date]:
    if len(days) < 2:
        return []
    present = {day.cost_date for day in days}
    first, last = min(present), max(present)
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)
            if first + timedelta(days=offset) not in present]


def _date_runs(dates: list[date]) -> list[tuple[date, date]]:
    runs: list[tuple[date, date]] = []
    for item in sorted(dates):
        if runs and (item - runs[-1][1]).days == 1:
            runs[-1] = (runs[-1][0], item)
        else:
            runs.append((item, item))
    return runs


def _span(first: date, last: date) -> str:
    return first.isoformat() if first == last else f"{first.isoformat()} to {last.isoformat()}"


def forecast(well: WellInput, values: list[float], skip: set[int]) -> Forecast:
    result = Forecast()
    usable = [value for index, value in enumerate(values) if index not in skip]
    if len(usable) < 3:
        result.reason = "At least three recorded cost days are needed for a forecast."
        return result
    recent = usable[-RECENT_DAYS:]
    burn = sum(recent) / len(recent)
    result.recent_daily = burn
    spent = well.actual_amount if well.actual_amount is not None else sum(values)
    if well.afe_amount and well.planned_days:
        result.planned_daily = well.afe_amount / well.planned_days
    if well.afe_amount and burn > 0:
        left = well.afe_amount - spent
        result.days_to_exhaustion = max(left, 0.0) / burn
        if well.days:
            result.exhaustion_date = well.days[-1].cost_date + timedelta(days=int(result.days_to_exhaustion))
    if not well.planned_days or well.actual_days is None:
        result.reason = "No planned days are configured for this well, so the remaining duration is unknown."
        return result
    remaining = well.planned_days - well.actual_days
    if well.status in ("completed", "closed"):
        remaining = 0.0
    result.past_plan = remaining <= 0 and well.status not in ("completed", "closed")
    remaining = max(remaining, 0.0)
    result.remaining_days = remaining
    result.estimate = spent + burn * remaining
    _, spread = robust_centre(recent)
    band = 1.2816 * spread * sqrt(remaining) if remaining > 0 else 0.0
    result.low, result.high = max(spent, result.estimate - band), result.estimate + band
    result.available = True
    if well.afe_amount:
        result.variance = result.estimate - well.afe_amount
        result.variance_percent = result.variance / well.afe_amount * 100
    return result


def analyse_well(well: WellInput, as_of: date | None = None) -> WellAnalysis:
    days = tuple(sorted(well.days, key=lambda item: item.cost_date))
    well = WellInput(**{**well.__dict__, "days": days})
    values = [day.actual for day in days]
    cur = well.currency
    findings: list[Finding] = []

    def add(code: str, severity: str, category: str, title: str, detail: str, basis: str, suggestion: str,
            cost_date: date | None = None, amount: float | None = None,
            evidence: list[tuple[str, str]] | None = None) -> None:
        findings.append(Finding(
            code=code, severity=severity, category=category, title=title, detail=detail, basis=basis,
            suggestion=suggestion, well_id=well.well_id, well_code=well.well_code, cost_date=cost_date,
            amount=amount, evidence=evidence or [],
        ))

    # --- Anomalies: single-day spikes -------------------------------------
    spikes = find_spikes(values)
    spike_index = {index for index, _, _ in spikes}
    for index, z, centre in spikes:
        day = days[index]
        higher = day.actual > centre
        add(
            "cost-spike" if higher else "cost-dip", "warning" if higher else "info", "anomaly",
            f"{'Unusually high' if higher else 'Unusually low'} daily cost on {day.cost_date.isoformat()}",
            f"{money(day.actual, cur)} was recorded against a typical {money(centre, cur)} for the surrounding days "
            f"({day.actual / centre:.1f}x).",
            f"Modified z-score {z:+.1f} against the median of up to {SPIKE_WINDOW} days either side (flagged beyond "
            f"{SPIKE_Z}, at least {SPIKE_MIN_RELATIVE:.0%} from that median, and no neighbouring day within "
            f"{SPIKE_ISOLATION:.0%} of it).",
            ("Open the sheet and confirm the large lines: a lump-sum, mobilisation or tangible delivery is legitimate; "
             "a quantity keyed with an extra digit or a cost booked on the wrong date is not."
             if higher else
             "Open the sheet and confirm no service line or day-rate item was left out."),
            cost_date=day.cost_date, amount=day.actual - centre,
            evidence=[("Recorded", money(day.actual, cur)), ("Typical day", money(centre, cur)),
                      ("Difference", money(day.actual - centre, cur))],
        )

    # --- Trend: creeping drift ---------------------------------------------
    drift = cusum(values, spike_index)
    if drift.alarm_index is not None and drift.start_index is not None:
        start = days[min(drift.start_index, len(days) - 1)].cost_date
        alarm = days[drift.alarm_index].cost_date
        rising = drift.direction.startswith("up")
        recovered = drift.direction.endswith("recovered")
        extra_days = len(days) - drift.start_index
        extra = (drift.recent_mean - drift.baseline) * extra_days
        if recovered:
            add(
                "drift-recovered", "info", "trend",
                f"Daily cost ran {'above' if rising else 'below'} its baseline from {start.isoformat()}, then settled",
                f"The daily cost level moved away from the opening {money(drift.baseline, cur)} per day and has since "
                f"returned inside the control limit.",
                f"Two-sided CUSUM (slack {CUSUM_SLACK}, limit {CUSUM_LIMIT:g}) against the median of the first "
                f"{drift.baseline_days} days; alarm on {alarm.isoformat()}, no longer in alarm on the last recorded day.",
                "No action is needed; note the cause in the well file if it was a planned change of operation.",
                cost_date=start,
            )
        elif rising:
            add(
                "drift-up", "critical" if drift.change_percent >= 25 else "warning", "trend",
                f"Daily cost has been creeping up since {start.isoformat()}",
                f"The daily level rose from about {money(drift.baseline, cur)} to {money(drift.recent_mean, cur)} "
                f"({drift.change_percent:+.0f}%). Over {extra_days} days that is about {money(extra, cur)} more than "
                f"the opening rate would have cost.",
                f"Two-sided CUSUM (slack {CUSUM_SLACK}, limit {CUSUM_LIMIT:g}) against the median of the first "
                f"{drift.baseline_days} days; alarm raised on {alarm.isoformat()} and still standing.",
                "Compare the service lines of a recent sheet with one from the opening period: look for added "
                "services, a rate revision, or standby and rental items that were meant to be released.",
                cost_date=start, amount=extra,
                evidence=[("Opening level", money(drift.baseline, cur) + " / day"),
                          ("Level since change", money(drift.recent_mean, cur) + " / day"),
                          ("Change", f"{drift.change_percent:+.1f}%")],
            )
        else:
            add(
                "drift-down", "info", "trend",
                f"Daily cost has been running lower since {start.isoformat()}",
                f"The daily level fell from about {money(drift.baseline, cur)} to {money(drift.recent_mean, cur)} "
                f"({drift.change_percent:+.0f}%).",
                f"Two-sided CUSUM (slack {CUSUM_SLACK}, limit {CUSUM_LIMIT:g}) against the median of the first "
                f"{drift.baseline_days} days; alarm raised on {alarm.isoformat()}.",
                "Confirm the saving is real (a released service or lower rate) and not costs that are still to be "
                "entered; accruals missing from the sheets understate the well.",
                cost_date=start, amount=extra,
            )

    # --- Budget: position and forecast --------------------------------------
    outlook = forecast(well, values, spike_index)
    spent = well.actual_amount
    if well.afe_amount and spent is not None:
        used = spent / well.afe_amount * 100
        if spent > well.afe_amount:
            over = spent - well.afe_amount
            add(
                "afe-exceeded", "critical", "budget",
                f"Actual cost is {used - 100:.0f}% over the AFE",
                f"{money(spent, cur)} has been recorded against an AFE of {money(well.afe_amount, cur)}: "
                f"{money(over, cur)} over.",
                "Recorded actual cost compared with the effective AFE amount (SOW adjustments included).",
                "Raise a supplementary AFE or an approved SOW adjustment for the overrun before further cost is "
                "committed, and record the cause against the well.",
                amount=over,
                evidence=[("AFE", money(well.afe_amount, cur)), ("Actual", money(spent, cur)), ("Over", money(over, cur))],
            )
        elif outlook.available and outlook.variance_percent is not None and outlook.variance_percent >= OVERRUN_WARNING_PERCENT:
            critical = outlook.variance_percent >= OVERRUN_CRITICAL_PERCENT
            add(
                "forecast-overrun", "critical" if critical else "warning", "budget",
                f"Forecast to finish {outlook.variance_percent:.0f}% over the AFE",
                f"At the recent {money(outlook.recent_daily, cur)} per day for the remaining "
                f"{outlook.remaining_days:.0f} planned days, the well would close near {money(outlook.estimate or 0, cur)} "
                f"against an AFE of {money(well.afe_amount, cur)}"
                + (f"; the AFE would be used up around {outlook.exhaustion_date.isoformat()}." if outlook.exhaustion_date else "."),
                f"Estimate at completion = recorded cost + mean of the last {RECENT_DAYS} recorded days (spikes excluded) "
                f"x remaining planned days. Range {money(outlook.low or 0, cur)} to {money(outlook.high or 0, cur)}.",
                "Review the remaining programme with operations now: confirm the days to go, and prepare a "
                "supplementary AFE or SOW adjustment if the forecast holds.",
                amount=outlook.variance,
                evidence=[("Estimate at completion", money(outlook.estimate or 0, cur)),
                          ("AFE", money(well.afe_amount, cur)), ("Forecast overrun", money(outlook.variance or 0, cur))],
            )
        elif well.planned_days and well.actual_days is not None and well.actual_days > 0:
            elapsed = well.actual_days / well.planned_days * 100
            if used - elapsed >= 15 and elapsed < 100:
                add(
                    "burn-ahead", "warning", "budget",
                    "Cost is running ahead of time",
                    f"{used:.0f}% of the AFE is spent with {elapsed:.0f}% of the planned days used.",
                    "Share of AFE spent minus share of planned days elapsed is 15 points or more.",
                    "Check whether front-loaded items (mobilisation, tangibles) explain the lead; if not, the daily "
                    "rate is above the AFE basis.",
                    evidence=[("AFE used", f"{used:.1f}%"), ("Planned days used", f"{elapsed:.1f}%")],
                )

    # --- Schedule ------------------------------------------------------------
    if well.planned_days and well.actual_days is not None and well.actual_days > well.planned_days:
        over_days = well.actual_days - well.planned_days
        percent = over_days / well.planned_days * 100
        cost_of_days = over_days * outlook.recent_daily if outlook.recent_daily else None
        add(
            "schedule-overrun", "critical" if percent >= 20 else "warning", "schedule",
            f"{over_days:.0f} day(s) beyond the planned duration",
            f"{well.actual_days:.0f} days recorded against {well.planned_days:.0f} planned"
            + (f"; each further day costs about {money(outlook.recent_daily, cur)}." if outlook.recent_daily else "."),
            "Recorded actual days compared with the configured planned days (plan adjustments included).",
            "Record a well plan SOW adjustment for the extra days so the plan, the AFE and the forecast agree.",
            amount=cost_of_days,
            evidence=[("Planned days", f"{well.planned_days:.0f}"), ("Actual days", f"{well.actual_days:.0f}")],
        )

    # --- Non-productive time -------------------------------------------------
    if well.npt_amount and spent:
        share = well.npt_amount / spent * 100
        if share >= NPT_WARNING_SHARE:
            add(
                "npt-share", "critical" if share >= NPT_CRITICAL_SHARE else "warning", "npt",
                f"Non-productive time is {share:.0f}% of the cost",
                f"{money(well.npt_amount, cur)} of {money(spent, cur)} was recorded against non-productive time.",
                f"NPT cost as a share of recorded cost; warning from {NPT_WARNING_SHARE:.0f}%, critical from "
                f"{NPT_CRITICAL_SHARE:.0f}%.",
                "Review the NPT events by activity and service company; where a contractor is accountable, check the "
                "contract for a reduced or zero rate and raise the back-charge.",
                amount=well.npt_amount,
                evidence=[("NPT cost", money(well.npt_amount, cur)), ("Share of cost", f"{share:.1f}%")],
            )

    # --- Cost groups ---------------------------------------------------------
    for group in well.groups:
        if group.planned and group.actual > group.planned * 1.05:
            over = group.actual - group.planned
            add(
                "group-overrun", "warning", "budget",
                f"{group.label} is over its AFE allowance",
                f"{money(group.actual, cur)} recorded against {money(group.planned, cur)} planned for {group.label}.",
                "Recorded cost of the cost group compared with its AFE estimate (more than 5% over).",
                f"Check which {group.label.lower()} lines exceed the estimate and whether another group is carrying "
                "a matching saving.",
                amount=over,
                evidence=[("Planned", money(group.planned, cur)), ("Actual", money(group.actual, cur))],
            )

    # --- Record quality ------------------------------------------------------
    gaps = missing_dates(days)
    if gaps:
        runs = _date_runs(gaps)
        typical = robust_centre(values)[0]
        add(
            "missing-sheets", "warning", "data-quality",
            f"{len(gaps)} cost date(s) have no daily sheet",
            "No cost is recorded for " + ", ".join(_span(first, last) for first, last in runs[:6])
            + (f" and {len(runs) - 6} more period(s)" if len(runs) > 6 else "")
            + f". At a typical {money(typical, cur)} per day that is about {money(typical * len(gaps), cur)} not yet in the record.",
            "Every calendar date between the first and last recorded cost date is expected to have a sheet.",
            "Enter the missing sheets, or record a zero-cost sheet with a remark if the rig was released for those days.",
            cost_date=runs[0][0], amount=typical * len(gaps),
            evidence=[("Missing dates", str(len(gaps))), ("Typical day", money(typical, cur))],
        )
    if as_of and days and well.status == "active":
        behind = (as_of - days[-1].cost_date).days
        if behind >= STALE_DAYS:
            add(
                "stale-record", "warning", "data-quality",
                f"No cost recorded for {behind} days",
                f"The last daily sheet is dated {days[-1].cost_date.isoformat()} and the well is still active.",
                f"Days between the last cost date and {as_of.isoformat()} on an active well ({STALE_DAYS} or more).",
                "Bring the daily sheets up to date; the dashboard and the forecast understate the well until then.",
                cost_date=days[-1].cost_date,
            )
    run_start = 0
    for index in range(1, len(values) + 1):
        if index == len(values) or values[index] != values[run_start]:
            length = index - run_start
            if length >= REPEAT_RUN and values[run_start] > 0:
                add(
                    "repeated-total", "info", "data-quality",
                    f"{length} consecutive days carry the identical total",
                    f"{money(values[run_start], cur)} is recorded for every day from "
                    f"{_span(days[run_start].cost_date, days[index - 1].cost_date)}.",
                    f"{REPEAT_RUN} or more consecutive cost dates with exactly the same daily total.",
                    "If the sheets were copied forward, confirm the consumables and variable services were updated "
                    "for each day.",
                    cost_date=days[run_start].cost_date,
                )
            run_start = index
    zero_days = [day.cost_date for day in days if day.actual <= 0]
    if zero_days:
        add(
            "zero-day", "info", "data-quality",
            f"{len(zero_days)} sheet(s) carry no cost",
            "A sheet exists with a zero or negative total on " + ", ".join(item.isoformat() for item in zero_days[:6])
            + ("…" if len(zero_days) > 6 else "") + ".",
            "Daily total of a recorded cost date is zero or below.",
            "Confirm the rig was off rate; otherwise complete the sheet.",
            cost_date=zero_days[0],
        )
    if well.warning_sheets:
        add(
            "entry-warnings", "info", "data-quality",
            f"{well.warning_sheets} sheet(s) carry entry-check warnings",
            "The entry checks raised a warning on these sheets when they were saved and it was kept as entered.",
            "Count of daily sheets whose saved entry checks include a warning.",
            "Open the sheets from Daily Cost Analysis and either correct the line or confirm it with a remark.",
        )
    if well.sheet_count and well.draft_sheets and well.draft_sheets == well.sheet_count and well.sheet_count >= 5:
        add(
            "all-draft", "info", "data-quality",
            "None of the daily sheets has been submitted",
            f"All {well.sheet_count} sheets are still in draft, so the figures can change without a reopen trail.",
            "Every recorded daily sheet has draft status.",
            "Submit the sheets that have been checked so the record is locked and later changes are traceable.",
        )
    elif well.draft_sheets and well.status in ("completed", "closed"):
        add(
            "draft-on-closed", "warning", "data-quality",
            f"{well.draft_sheets} draft sheet(s) on a completed well",
            "The well is completed but part of its cost record is still in draft.",
            "Draft daily sheets on a well whose status is completed.",
            "Submit or remove the draft sheets before the final cost report is issued.",
        )
    if well.status == "active" and not days and spent in (None, 0):
        add(
            "no-actuals", "warning", "data-quality",
            "Active well with no cost recorded",
            "The well is active but no daily sheet has been entered.",
            "Well status is active and the cost register holds no sheet for it.",
            "Start the daily cost sheets, or set the well back to upcoming if operations have not begun.",
        )

    findings.sort(key=lambda item: (SEVERITY_ORDER[item.severity], -(abs(item.amount) if item.amount else 0.0)))
    score = max(0, 100 - sum(PENALTY[item.severity] for item in findings))
    band = "good" if score >= 80 else "watch" if score >= 55 else "at-risk"
    return WellAnalysis(
        well=well, findings=findings, forecast=outlook, drift=drift, spikes=sorted(spike_index),
        missing_dates=gaps, score=score, band=band, summary=_summary(well, findings, outlook),
    )


def _summary(well: WellInput, findings: list[Finding], outlook: Forecast) -> str:
    """One paragraph a manager can read without the tables."""
    cur = well.currency
    parts: list[str] = []
    if well.afe_amount and well.actual_amount:
        used = well.actual_amount / well.afe_amount * 100
        parts.append(f"{well.well_code} has recorded {money(well.actual_amount, cur)} against an AFE of "
                     f"{money(well.afe_amount, cur)} ({used:.0f}%).")
    elif well.actual_amount:
        parts.append(f"{well.well_code} has recorded {money(well.actual_amount, cur)}.")
    else:
        parts.append(f"{well.well_code} has no recorded cost yet.")
    if outlook.available and outlook.estimate is not None and well.afe_amount and well.status not in ("completed", "closed"):
        if outlook.past_plan:
            parts.append(f"It is past its planned duration and is spending about {money(outlook.recent_daily, cur)} a day.")
        else:
            direction = "over" if (outlook.variance or 0) > 0 else "under"
            parts.append(f"At the current rate it is forecast to finish near {money(outlook.estimate, cur)}, "
                         f"{abs(outlook.variance_percent or 0):.0f}% {direction} the AFE.")
    serious = [item for item in findings if item.severity in ("critical", "warning")]
    if serious:
        parts.append("Main points: " + "; ".join(item.title.lower() for item in serious[:3]) + ".")
    elif findings:
        parts.append("No cost or schedule concern was found; there are record-keeping notes only.")
    else:
        parts.append("No concern was found.")
    return " ".join(parts)


def portfolio_score(analyses: list[WellAnalysis]) -> int:
    """AFE-weighted mean of the well scores (plain mean without AFE amounts)."""
    scored = [item for item in analyses if item.well.days or item.findings]
    if not scored:
        return 100
    weights = [item.well.afe_amount or 0.0 for item in scored]
    if sum(weights) <= 0:
        return round(sum(item.score for item in scored) / len(scored))
    return round(sum(item.score * weight for item, weight in zip(scored, weights)) / sum(weights))
