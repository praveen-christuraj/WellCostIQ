"""Robust statistics behind the daily-sheet entry checks.

The entry checks answer two questions about a value somebody has just keyed:

* *Is it unusual?*  The value is compared with what the same item usually
  carries (:class:`Profile`), measured on a ratio scale so that "ten times too
  much" and "a tenth of the usual" are treated alike.
* *How could it have been mistyped?*  A short list of keying slips (an extra
  zero, a digit keyed twice, hours entered as days, feet entered as metres, a
  rate entered the other way round) is tried; when exactly that slip turns the
  value into a usual one, the corrected value is offered (:func:`explain_slip`).

There is no model, no training run and no random number here. A profile is a
median and a spread, so the same history always produces the same verdict and
every verdict can be explained with the figures it quotes. Only the Python
standard library is used.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence

# Fewer comparable values than this is not a pattern, so no opinion is given.
MIN_HISTORY = 5
# A short history is trusted less: the tolerance is multiplied by
# ``1 + SMALL_SAMPLE_WIDENING / (count - 3)`` -- twice as wide at five values,
# 1.4 times at eight, 1.1 times at twenty. This follows how much wider a
# Student-t interval is than a normal one when the spread itself is estimated.
SMALL_SAMPLE_WIDENING = 2.0
# Natural-log units. Day-to-day variation of about twelve per cent is treated as
# ordinary even when the history happens to repeat one value exactly.
SPREAD_FLOOR = 0.12
# Scales a median absolute deviation to a standard deviation for normal data.
MAD_TO_SIGMA = 1.4826
# One value in eight is set aside as a possible earlier mistake before the range
# of the history is measured (none below eight values, where each one counts).
RANGE_TRIM_EVERY = 8

# "Outside the usual range": far from the median for this item *and* at least
# two and a half times away from it, so ordinary busy or quiet days stay silent.
NOTICE_Z = 3.5
NOTICE_RATIO = 2.5
# "Probably a slip" needs either a keying slip that explains the value exactly
# (and a value at least this far out) ...
SLIP_Z = 4.0
# ... or a value five times away and far beyond the item's own variation.
STRONG_Z = 6.0
STRONG_RATIO = 5.0
# A corrected value "fits" when it lands within this many spreads of the usual value.
FIT_BAND = 1.5
# A digit-level correction (doubled or swapped digit) must land this close to the
# usual value, because such corrections are otherwise easy to find by accident.
DIGIT_FIT = 0.05
EXACT = 1e-9

FEET_PER_METRE = Decimal("3.281")
HOURS_PER_DAY = Decimal("24")

# Keying slips, most frequent first. Ties between equally good corrections are
# resolved in this order.
SCALE_10 = "scale10"
SCALE_100 = "scale100"
SCALE_1000 = "scale1000"
DOUBLED_DIGIT = "doubled-digit"
SWAPPED_DIGITS = "swapped-digits"
HOURS_DAYS = "hours-days"
FEET_METRES = "feet-metres"
INVERTED = "inverted"
DECIMAL_FAMILIES: tuple[str, ...] = (SCALE_10, DOUBLED_DIGIT, SCALE_100, SCALE_1000, SWAPPED_DIGITS)


@dataclass(frozen=True)
class Profile:
    """What an item usually carries: its middle value and how much it varies."""

    count: int
    median: float
    # Robust standard deviation of ln(value); 0 when the history never varies.
    # It is the larger of two estimates (see :func:`build_profile`).
    spread: float
    # Tenth and ninetieth percentile of the history, for the "usual range" shown.
    low: float
    high: float
    # The value that keeps recurring (for example 24 hours), when there is one.
    common: float | None = None

    @property
    def tolerance(self) -> float:
        """The spread actually applied: floored, and widened for a short history."""
        scale = max(self.spread, SPREAD_FLOOR)
        if self.count > 3:
            scale *= 1 + SMALL_SAMPLE_WIDENING / (self.count - 3)
        else:
            scale *= 1 + SMALL_SAMPLE_WIDENING
        return scale

    @property
    def usual(self) -> float:
        """The figure to quote as "usual": the recurring value, else the median."""
        return self.common if self.common is not None else self.median


@dataclass(frozen=True)
class Deviation:
    """How far a value sits from its profile."""

    ratio: float
    z: float
    # Outside the usual range (worth showing).
    noticeable: bool
    # Far enough out for a keying slip, when one fits, to be called probable.
    slip_grade: bool
    # So far out that it is called probable even without a recognised slip.
    strong: bool


@dataclass(frozen=True)
class Slip:
    """One keying slip that turns the entered value into a usual one."""

    kind: str
    corrected: Decimal
    phrase: str


def _positive(values: Iterable[Decimal | float | int | None]) -> list[float]:
    numbers: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, InvalidOperation):
            continue
        if number > 0 and math.isfinite(number):
            numbers.append(number)
    numbers.sort()
    return numbers


def _median(ordered: Sequence[float]) -> float:
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile: always a value that was actually recorded."""
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _same(left: float, right: float) -> bool:
    return abs(left - right) <= EXACT * max(abs(left), abs(right), 1.0)


# Expected range of ``n`` standard normal values (statistical table "d2").
_EXPECTED_RANGE = {
    2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078,
    11: 3.173, 12: 3.258, 13: 3.336, 14: 3.407, 15: 3.472, 16: 3.532, 17: 3.588, 18: 3.640,
    19: 3.689, 20: 3.735,
}


def _expected_range(count: int) -> float:
    if count in _EXPECTED_RANGE:
        return _EXPECTED_RANGE[count]
    return 3.735 + 0.865 * math.log(count / 20)


def _range_spread(logs: Sequence[float], centre: float) -> float:
    """Spread implied by how wide the history actually ranges.

    The median absolute deviation is blind to anything but the middle half of
    the values, so on a short history of a genuinely variable item it is often
    far too small. The observed range cannot be: if recorded values already
    span a factor of twenty, a value ten times the median is not a surprise.
    The values farthest from the median (one in eight) are set aside first, so
    an earlier mistake in the history does not hide the next one.
    """
    kept = sorted(logs, key=lambda value: abs(value - centre))
    trim = len(kept) // RANGE_TRIM_EVERY
    if trim:
        kept = kept[:-trim]
    if len(kept) < 2:
        return 0.0
    return (max(kept) - min(kept)) / _expected_range(len(kept))


def build_profile(values: Iterable[Decimal | float | int | None]) -> Profile | None:
    """Summarise a history of positive values. ``None`` when there are none."""
    numbers = _positive(values)
    if not numbers:
        return None
    centre = _median(numbers)
    log_centre = math.log(centre)
    logs = [math.log(number) for number in numbers]
    deviations = sorted(abs(value - log_centre) for value in logs)
    spread = max(MAD_TO_SIGMA * _median(deviations), _range_spread(logs, log_centre))
    # A recurring value needs to be seen at least twice and in three records out
    # of ten; anything rarer is just one of many values.
    common: float | None = None
    value, occurrences = Counter(round(number, 10) for number in numbers).most_common(1)[0]
    if occurrences >= 2 and occurrences * 10 >= len(numbers) * 3:
        common = value
    return Profile(
        count=len(numbers), median=centre, spread=spread,
        low=_percentile(numbers, 0.10), high=_percentile(numbers, 0.90), common=common,
    )


def far_from_median(value: Decimal | float | int, values: Sequence[float]) -> bool | None:
    """Whether ``value`` is at least :data:`NOTICE_RATIO` away from the middle of ``values``.

    ``None`` when there is nothing positive to compare with. This is the first
    half of :func:`measure` without the profile: a value that is not this far
    from the median can never be a finding, whatever the spread turns out to
    be, so most values are dismissed here for the price of one sort.
    """
    try:
        number = float(value)
        plain = all(0 < item < math.inf for item in values)
    except (TypeError, ValueError, InvalidOperation):
        return None
    ordered = sorted(values) if plain else _positive(values)
    if not ordered or number <= 0 or not math.isfinite(number):
        return None
    ratio = number / float(_median(ordered))
    return ratio >= NOTICE_RATIO or ratio <= 1 / NOTICE_RATIO


def measure(value: Decimal | float | int, profile: Profile) -> Deviation | None:
    """Compare one positive value with its profile on a ratio scale."""
    number = float(value)
    if number <= 0 or not math.isfinite(number) or profile.median <= 0:
        return None
    ratio = number / profile.median
    z = math.log(ratio) / profile.tolerance
    far = ratio >= NOTICE_RATIO or ratio <= 1 / NOTICE_RATIO
    very_far = ratio >= STRONG_RATIO or ratio <= 1 / STRONG_RATIO
    return Deviation(
        ratio=ratio, z=z,
        noticeable=abs(z) >= NOTICE_Z and far,
        slip_grade=abs(z) >= SLIP_Z and far,
        strong=abs(z) >= STRONG_Z and very_far,
    )


def tidy(value: Decimal, places: int = 10) -> Decimal:
    """A plain decimal without exponent or trailing zeros (``Decimal('24')``, not ``2.4E+1``)."""
    quantized = value.quantize(Decimal(1).scaleb(-places)) if value.as_tuple().exponent < -places else value
    text = format(quantized.normalize(), "f")
    return Decimal(text)


def significant(value: Decimal, digits: int = 6) -> Decimal:
    """Round to a number of significant digits, for derived suggestions such as 1/x."""
    if value == 0:
        return value
    exponent = value.adjusted()
    return tidy(value.quantize(Decimal(1).scaleb(exponent - digits + 1)))


def _digit_variants(value: Decimal) -> tuple[list[Decimal], list[Decimal]]:
    """Values obtained by removing one doubled digit, and by swapping two neighbours."""
    text = format(tidy(value), "f")
    doubled: list[Decimal] = []
    swapped: list[Decimal] = []
    seen: set[str] = {text}
    for index in range(len(text) - 1):
        left, right = text[index], text[index + 1]
        if not (left.isdigit() and right.isdigit()):
            continue
        candidate = text[:index] + text[index + 1:] if left == right else text[:index] + right + left + text[index + 2:]
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            number = Decimal(candidate)
        except InvalidOperation:
            continue
        if number <= 0:
            continue
        (doubled if left == right else swapped).append(number)
    return doubled, swapped


def _candidates(value: Decimal, families: Sequence[str]) -> list[tuple[int, str, Decimal, str]]:
    """Every (priority, kind, corrected value, explanation) the slip families allow."""
    found: list[tuple[int, str, Decimal, str]] = []
    doubled: list[Decimal] = []
    swapped: list[Decimal] = []
    if DOUBLED_DIGIT in families or SWAPPED_DIGITS in families:
        doubled, swapped = _digit_variants(value)
    for priority, family in enumerate(families):
        if family == SCALE_10:
            found.append((priority, family, value / 10, "one zero too many, or the decimal point one place too far right"))
            found.append((priority, family, value * 10, "one zero missing, or the decimal point one place too far left"))
        elif family == SCALE_100:
            found.append((priority, family, value / 100, "two zeros too many, or the decimal point two places too far right"))
            found.append((priority, family, value * 100, "two zeros missing, or the decimal point two places too far left"))
        elif family == SCALE_1000:
            found.append((priority, family, value / 1000, "a unit a thousand times smaller than usual (kilograms for tonnes, for example)"))
            found.append((priority, family, value * 1000, "a unit a thousand times larger than usual (tonnes for kilograms, for example)"))
        elif family == DOUBLED_DIGIT:
            found.extend((priority, family, number, "a digit keyed twice") for number in doubled)
        elif family == SWAPPED_DIGITS:
            found.extend((priority, family, number, "two neighbouring digits swapped") for number in swapped)
        elif family == HOURS_DAYS:
            found.append((priority, family, value / HOURS_PER_DAY, "hours entered where days are expected"))
            found.append((priority, family, value * HOURS_PER_DAY, "days entered where hours are expected"))
        elif family == FEET_METRES:
            found.append((priority, family, value / FEET_PER_METRE, "feet entered where metres are expected"))
            found.append((priority, family, value * FEET_PER_METRE, "metres entered where feet are expected"))
        elif family == INVERTED:
            found.append((priority, family, Decimal(1) / value, "the rate entered the other way round"))
    return found


def _best_slip(
    value: Decimal,
    profile: Profile,
    families: Sequence[str],
    *,
    offset: float = 0.0,
    factor: float = 1.0,
) -> tuple[tuple[int, int, float], Slip] | None:
    """The best correction of ``value`` and its rank (lower is better).

    The figure compared with the profile is ``offset + corrected * factor``:
    ``factor`` expresses the entered value in the profile's unit and ``offset``
    is whatever else adds to the same total.
    """
    if value <= 0 or profile.median <= 0:
        return None
    band = max(FIT_BAND * profile.tolerance, DIGIT_FIT)
    log_usual = math.log(profile.median)
    best: tuple[tuple[int, int, float], Slip] | None = None
    for priority, kind, corrected, phrase in _candidates(value, families):
        if corrected <= 0:
            continue
        number = offset + float(corrected) * factor
        if number <= 0:
            continue
        distance = abs(math.log(number) - log_usual)
        if distance > band:
            continue
        exact = profile.common is not None and _same(number, profile.common)
        if kind in (DOUBLED_DIGIT, SWAPPED_DIGITS) and not exact and distance > DIGIT_FIT:
            continue
        rank = (0 if exact else 1, priority, distance)
        if best is None or rank < best[0]:
            best = (rank, Slip(kind=kind, corrected=corrected, phrase=phrase))
    if best is None:
        return None
    rank, slip = best
    corrected = slip.corrected
    if slip.kind in (FEET_METRES, HOURS_DAYS):
        corrected = tidy(corrected, places=3)
    elif slip.kind == INVERTED:
        corrected = significant(corrected)
    else:
        corrected = tidy(corrected)
    return rank, Slip(kind=slip.kind, corrected=corrected, phrase=slip.phrase)


def explain_slip(
    value: Decimal,
    profile: Profile,
    families: Sequence[str] = DECIMAL_FAMILIES,
) -> Slip | None:
    """The keying slip that best turns ``value`` into a usual one, if any does.

    A correction is accepted only when it lands inside the item's usual range;
    a digit-level correction (a doubled or swapped digit) must also reproduce
    the item's recurring value or land within five per cent of the usual value,
    because such corrections are otherwise easy to find by accident. A
    correction that reproduces the recurring value wins; otherwise the more
    frequent kind of slip wins (the order of ``families``) and closeness breaks
    a tie.
    """
    found = _best_slip(value, profile, families)
    return found[1] if found else None


def explain_slip_in_sum(
    parts: Sequence[tuple[Decimal, float]],
    profile: Profile,
    families: Sequence[str] = DECIMAL_FAMILIES,
) -> tuple[int, Slip] | None:
    """The one part whose keying slip best explains an unusual total.

    ``parts`` are the entered values, each with the factor that expresses it in
    the profile's unit; what is compared with the profile is their total. One
    slip in one part is looked for, the largest part first, and the corrected
    value is returned in the unit that part was entered in.
    """
    amounts = [float(value) * factor for value, factor in parts]
    total = sum(amounts)
    best: tuple[tuple[int, int, float], int, Slip] | None = None
    for index in sorted(range(len(parts)), key=lambda position: -amounts[position]):
        value, factor = parts[index]
        if value <= 0 or factor <= 0:
            continue
        found = _best_slip(value, profile, families, offset=max(total - amounts[index], 0.0), factor=factor)
        if found is not None and (best is None or found[0] < best[0]):
            best = (found[0], index, found[1])
    if best is None:
        return None
    return best[1], best[2]


def power_of_ten(ratio: float, tolerance: float = 0.05) -> int:
    """``k`` when ``ratio`` is within ``tolerance`` (log units) of ``10**k``, ``k != 0``; else 0."""
    if ratio <= 0 or not math.isfinite(ratio):
        return 0
    exponent = math.log10(ratio)
    nearest = round(exponent)
    if nearest == 0 or abs(nearest) > 6:
        return 0
    return nearest if abs(exponent - nearest) * math.log(10) <= tolerance else 0


def times(ratio: float) -> str:
    """A ratio in words: ``10 times`` / ``2.4 times`` / ``one tenth of`` / ``38% of``."""
    if ratio >= 1:
        rounded = round(ratio, 1)
        text = f"{rounded:,.0f}" if rounded >= 10 or rounded == int(rounded) else f"{rounded:,.1f}"
        return f"{text} times"
    inverse = 1 / ratio
    if _same(round(inverse), inverse) or abs(round(inverse) - inverse) < 0.02 * inverse:
        names = {2: "half", 10: "one tenth", 100: "one hundredth", 1000: "one thousandth"}
        whole = int(round(inverse))
        if whole in names:
            return f"{names[whole]} of"
    percent = ratio * 100
    return f"{percent:.0f}% of" if percent >= 1 else f"{percent:.2g}% of"
