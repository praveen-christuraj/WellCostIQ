#!/usr/bin/env python3
"""Measure what the daily-sheet entry checks catch, and what they flag by mistake.

The detection and correction figures quoted in ``docs/entry-checks.md`` come
from this script. Run it again after changing a threshold or a keying-slip rule
in ``backend/app/domain/entry_statistics.py`` and update the document with the
new tables; a change that raises the false-alarm columns needs a reason.

    python3 .agent/tools/entry-checks-simulation.py          # 4,000 trials per cell, about a minute
    python3 .agent/tools/entry-checks-simulation.py 500      # a quick look

Standard library only, seeded, so the same code always prints the same table.

How one trial works: an item is given a usual level (anywhere from 2 to 50,000)
and a day-to-day spread; ``n`` earlier values are drawn around that level and
rounded to three significant digits, the way a person keys a figure. Then a
fresh value is drawn the same way and judged (a finding here is a false alarm),
and the same value is judged again after each keying slip.

Columns:
    spread       standard deviation of ln(value): 0.1 is about +/-10% from day to
                 day, 0.6 is an item that routinely doubles or halves, 1.0 one
                 that varies by several times
    n            how many earlier values the item has
    false note   a correct value shown as a note
    false warn   a correct value shown as a warning
    per slip     four percentages of all trials:
                 warn   the slipped value is shown as a warning
                 note   it is shown as a note
                 right  a correction is offered and it is the value that was meant
                 other  a correction is offered and it is a different figure
                 (warn + note - right - other = flagged with no correction offered)

A second table follows, one row per spread with all history sizes together. It
answers "when a correction is offered, how good is it?":
    exact        the offered figure is the value that was meant
    close        it is the value that was meant or within 10% of it
"""
import math
import random
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.domain import entry_statistics as es  # noqa: E402 - needs the path above

SEED = 20261113
SPREADS = (0.0, 0.1, 0.3, 0.6, 1.0)
HISTORY_SIZES = (5, 6, 8, 12, 20, 45, 120)


def keyed(value: float) -> Decimal:
    """Round like a person keys a figure: three significant digits."""
    if value <= 0:
        return Decimal("1")
    return es.significant(Decimal(repr(value)), 3)


def history(level: float, spread: float, count: int) -> list[Decimal]:
    return [keyed(math.exp(random.gauss(level, spread))) for _ in range(count)]


def verdict(value: Decimal, values: list[Decimal]) -> tuple[str, es.Slip | None]:
    """The severity the quantity check would give, and the correction it would offer."""
    profile = es.build_profile(values)
    if profile is None or profile.count < es.MIN_HISTORY:
        return "", None
    deviation = es.measure(value, profile)
    if deviation is None or not deviation.noticeable:
        return "", None
    slip = es.explain_slip(value, profile, es.DECIMAL_FAMILIES)
    return ("warning" if ((slip and deviation.slip_grade) or deviation.strong) else "info"), slip


def doubled(value: Decimal) -> Decimal:
    text = format(es.tidy(value), "f")
    position = random.choice([index for index, char in enumerate(text) if char.isdigit()])
    return Decimal(text[:position] + text[position] + text[position:])


def swapped(value: Decimal) -> Decimal:
    text = format(es.tidy(value), "f")
    pairs = [
        index for index in range(len(text) - 1)
        if text[index].isdigit() and text[index + 1].isdigit() and text[index] != text[index + 1]
    ]
    if not pairs:
        return value
    position = random.choice(pairs)
    return Decimal(text[:position] + text[position + 1] + text[position] + text[position + 2:])


SLIPS = {
    "x10": lambda value: value * 10,
    "/10": lambda value: value / 10,
    "x100": lambda value: value * 100,
    "x1000": lambda value: value * 1000,
    "doubled": doubled,
    "swapped": swapped,
}


def main() -> None:
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    random.seed(SEED)
    print(f"trials per cell: {trials}")
    print(f"{'spread':>6} {'n':>4} | {'false note':>10} {'false warn':>10} | " + " ".join(f"{name:>22}" for name in SLIPS))
    print(" " * 13 + "|" + " " * 23 + "| " + " ".join(f"{'warn/note/right/other':>22}" for _ in SLIPS))
    # Per spread and slip: corrections offered, exactly right, right or within 10%.
    offered = {(spread, name): [0, 0, 0] for spread in SPREADS for name in SLIPS}
    for spread in SPREADS:
        for count in HISTORY_SIZES:
            false_info = false_warning = 0
            caught = {name: [0, 0, 0, 0] for name in SLIPS}
            for _ in range(trials):
                level = random.uniform(math.log(2), math.log(50000))
                earlier = history(level, spread, count)
                correct = keyed(math.exp(random.gauss(level, spread)))
                severity, _slip = verdict(correct, earlier)
                false_info += severity == "info"
                false_warning += severity == "warning"
                for name, mistype in SLIPS.items():
                    wrong = mistype(correct)
                    if wrong == correct:
                        continue
                    severity, slip = verdict(wrong, earlier)
                    caught[name][0] += severity == "warning"
                    caught[name][1] += severity == "info"
                    if severity and slip is not None:
                        exact = slip.corrected == es.tidy(correct)
                        caught[name][2 if exact else 3] += 1
                        tally = offered[(spread, name)]
                        tally[0] += 1
                        tally[1] += exact
                        tally[2] += exact or abs(float(slip.corrected) / float(correct) - 1) <= 0.10
            cells = " ".join(
                f"{100 * warned / trials:5.1f}/{100 * noted / trials:4.1f}/{100 * right / trials:5.1f}/{100 * other / trials:4.1f}"
                for warned, noted, right, other in caught.values()
            )
            print(f"{spread:>6} {count:>4} | {100 * false_info / trials:9.2f}% {100 * false_warning / trials:9.2f}% | {cells}")
    print()
    print("when a correction is offered: exact % / close % (the value meant, or within 10% of it)")
    print(f"{'spread':>6} | " + " ".join(f"{name:>13}" for name in SLIPS))
    for spread in SPREADS:
        cells = " ".join(
            f"{100 * exact / count:6.1f}/{100 * close / count:5.1f} " if count else f"{'-':>13}"
            for count, exact, close in (offered[(spread, name)] for name in SLIPS)
        )
        print(f"{spread:>6} | {cells}")


if __name__ == "__main__":
    main()
