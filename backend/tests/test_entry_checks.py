"""Entry checks on daily cost sheets.

Three layers are covered: the statistics (pure), the rules (pure), and the
service behind the API -- including the promises the feature makes about
itself: a finding never blocks a save, a failure inside the checks never
breaks the sheet, reviews are audited and tied to the exact value, and
nothing is read across a workspace boundary.
"""

import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
from sqlalchemy import func, select

# Importing the Daily Cost suite first configures the throwaway database and
# provides its workspace fixture and sheet builder.
from test_daily_cost import _other_line, _post, _setup_daily_sheet, fresh_database, login  # noqa: F401 - pytest fixture

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.domain import entry_rules as rules
from app.domain import entry_statistics as stats
from app.main import app
from app.models import AuditLog, DailyCostCheckReview, DailyCostItemProfile, Organization, Role, User
from app.services import entry_checks

API = "/api/v1/daily-cost"
PREVIOUS_HEAD = "a2c5d8f14b30"  # pragma: allowlist secret - Alembic parent revision ID.
REVISION = "b7d3e9f25a41"  # pragma: allowlist secret - Alembic revision ID.


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def test_profile_is_a_median_and_a_spread_and_needs_no_history_to_exist():
    assert stats.build_profile([]) is None
    assert stats.build_profile([0, -3, None]) is None
    profile = stats.build_profile([1200, 1150, 1300, 1250, 1100, 1220, 1280])
    assert profile is not None and profile.count == 7
    assert profile.median == 1220
    assert profile.low == 1100 and profile.high == 1300
    assert profile.common is None
    steady = stats.build_profile([24, 24, 24, 24, 12, 24])
    assert steady is not None and steady.common == 24 and steady.usual == 24


def test_ordinary_variation_stays_silent_and_a_short_history_is_trusted_less():
    profile = stats.build_profile([1200, 1150, 1300, 1250, 1100, 1220, 1280])
    for value in (600, 900, 1500, 2400, 2900):
        deviation = stats.measure(value, profile)
        assert deviation is not None and not deviation.noticeable, value
    far = stats.measure(12000, profile)
    assert far is not None and far.noticeable and far.slip_grade and far.strong
    # The same history, shorter: the tolerance is wider.
    short = stats.build_profile([1200, 1150, 1300, 1250, 1100])
    assert short is not None and short.tolerance > profile.tolerance
    # A genuinely variable item is not flagged for being variable.
    wide = stats.build_profile([10, 400, 35, 900, 60, 150, 20, 700])
    busy = stats.measure(2500, wide)
    assert busy is not None and not busy.strong


def test_keying_slips_are_recognised_and_the_correction_is_offered():
    diesel = stats.build_profile([1200, 1150, 1300, 1250, 1100, 1220, 1280])
    extra_zero = stats.explain_slip(Decimal("12000"), diesel)
    assert extra_zero is not None and extra_zero.kind == stats.SCALE_10 and extra_zero.corrected == Decimal("1200")
    missing_zero = stats.explain_slip(Decimal("120"), diesel)
    assert missing_zero is not None and missing_zero.corrected == Decimal("1200")
    # A value that no single slip explains gets no suggestion.
    assert stats.explain_slip(Decimal("3900"), diesel) is None

    rig_days = stats.build_profile([1, 1, 1, 1, 1, 1])
    hours = stats.explain_slip(Decimal("24"), rig_days, (stats.SCALE_10, stats.HOURS_DAYS))
    assert hours is not None and hours.kind == stats.HOURS_DAYS and hours.corrected == Decimal("1")

    naira = stats.Profile(count=1, median=1 / 1540, spread=0.0, low=1 / 1540, high=1 / 1540, common=1 / 1540)
    inverted = stats.explain_slip(Decimal("1540"), naira, (stats.SCALE_10, stats.INVERTED))
    assert inverted is not None and inverted.kind == stats.INVERTED
    assert abs(float(inverted.corrected) - 1 / 1540) < 1e-9

    # A digit-level correction must reproduce the recurring value or land very
    # close to the usual one; otherwise such corrections are found by accident.
    steady = stats.build_profile([1200] * 6)
    doubled = stats.explain_slip(Decimal("11200"), steady)
    assert doubled is not None and doubled.kind == stats.DOUBLED_DIGIT and doubled.corrected == Decimal("1200")


def test_a_slip_in_one_of_several_lines_is_found_in_the_right_line():
    diesel = stats.build_profile([1200, 1150, 1300, 1250, 1100, 1220, 1280])
    found = stats.explain_slip_in_sum([(Decimal("600"), 1.0), (Decimal("6000"), 1.0)], diesel)
    assert found is not None
    index, slip = found
    assert index == 1 and slip.corrected == Decimal("600")
    # Hours and days mixed on one service: the line entered in days is the slip.
    rig_days = stats.build_profile([1, 1, 1, 1, 1, 1])
    found = stats.explain_slip_in_sum(
        [(Decimal("18"), 1 / 24), (Decimal("6"), 1.0)], rig_days, (stats.SCALE_10, stats.HOURS_DAYS),
    )
    assert found is not None and found[0] == 1 and found[1].kind == stats.HOURS_DAYS


def test_ratios_and_figures_read_like_a_sentence():
    assert stats.times(10) == "10 times"
    assert stats.times(2.44) == "2.4 times"
    assert stats.times(0.1) == "one tenth of"
    assert stats.times(0.38) == "38% of"
    assert rules.number(Decimal("12000")) == "12,000"
    assert rules.number(Decimal("0.5000")) == "0.5"
    assert rules.quantity_text(Decimal("1"), "days") == "1 day"
    assert rules.quantity_text(Decimal("24"), "hours") == "24 hours"
    assert rules.plain(Decimal("24.0000000000")) == "24"


def test_the_early_dismissal_never_disagrees_with_the_full_measurement():
    """Most values are dismissed before a profile is built; that must change no verdict."""
    histories = [
        [1200, 1150, 1300, 1250, 1100, 1220, 1280],
        [24, 24, 24, 24, 12, 24],
        [3, 60, 9, 150, 22, 5, 480, 31],
        [10, 10, 10, 10, 10, 100],
        [0.00065, 0.00066, 0.00064, 0.00065, 0.0007],
        [7],
    ]
    factors = (0.01, 0.1, 0.39, 0.4, 0.41, 0.5, 1, 2, 2.49, 2.5, 2.51, 5, 10, 100, 1000)
    for history in histories:
        profile = stats.build_profile(history)
        assert profile is not None
        for factor in factors:
            value = profile.median * factor
            deviation = stats.measure(value, profile)
            assert deviation is not None
            far = stats.far_from_median(value, history)
            assert far == (deviation.ratio >= stats.NOTICE_RATIO or deviation.ratio <= 1 / stats.NOTICE_RATIO), (history, factor)
            # Dismissed early means the full measurement would have stayed silent too.
            assert far or not deviation.noticeable, (history, factor)
    # Nothing to compare with is not a dismissal; the caller then takes the full path.
    assert stats.far_from_median(5, []) is None
    assert stats.far_from_median(0, [1, 2, 3]) is None
    assert stats.far_from_median("many", [1, 2, 3]) is None
    assert stats.far_from_median(10, [1, None, 2]) is None
    # Unusable figures in a history are ignored, exactly as a profile ignores them.
    assert stats.far_from_median(Decimal("3"), [1.0, float("nan"), 2.0, -1.0]) is False
    assert stats.far_from_median(Decimal("30"), [1.0, float("inf"), 2.0, 0]) is True
    # A history kept as decimals is judged like the same history kept as floats.
    assert stats.far_from_median(8, [Decimal("6"), Decimal("6.5"), Decimal("7")]) is False
    assert stats.far_from_median(Decimal("65"), [Decimal("6"), Decimal("6.5"), Decimal("7"), Decimal("5")]) is True
    # The rule-level test needs a long-enough history of the AFE itself.
    assert rules.unremarkable([6, 6, 7, 5, 6], Decimal("8")) is True
    assert rules.unremarkable([6, 6, 7, 5, 6], Decimal("60")) is False
    assert rules.unremarkable([6, 6, 7, 5], Decimal("6")) is False
    assert rules.unremarkable([], Decimal("6")) is False


# ---------------------------------------------------------------------------
# Rules (pure): one sheet against a small history
# ---------------------------------------------------------------------------


def _service_fact(index, quantity, *, unit="hours", override=None, currency="USD", usd_fx="1", depth=None,
                  depth_unit="m", sequence=1, sub_activity="sa1"):
    depth_m = None
    if depth is not None:
        depth_m = Decimal(str(depth)) / (rules.FEET_PER_METRE if depth_unit == "ft" else Decimal("1"))
    return rules.line_fact(
        group="services", index=index, kind="service", subject_id="rig", variant_a="Day Rate", variant_b="Operation",
        unit=unit, code="RIG", name="Rig", quantity=quantity, captured_rate="25000", captured_currency="USD",
        override_rate=override, currency=currency, usd_fx=usd_fx, amount="25000", depth_m=depth_m,
        depth_input=depth, depth_unit=depth_unit, depth_seq=sequence, section_id="S1", phase_id=None,
        sub_activity_id=sub_activity, itemised=False,
    )


def _diesel_fact(index, quantity, *, override=None, currency="USD", usd_fx="1", sub_activity="sa1", amount="1300"):
    return rules.line_fact(
        group="consumables", index=index, kind="consumable", subject_id="diesel", variant_a="fuel", variant_b="",
        unit="L", code="DIESEL", name="Diesel", quantity=quantity, captured_rate="1.1", captured_currency="USD",
        override_rate=override, currency=currency, usd_fx=usd_fx, amount=amount, depth_m=None, depth_input=None,
        depth_unit="m", depth_seq=0, section_id="S1", phase_id=None, sub_activity_id=sub_activity, itemised=False,
    )


def _sheet(day, lines, *, total="26300"):
    return rules.SheetFacts(
        entry_id=f"entry-{day}", code=f"DC-WELL-{day:02d}", cost_date=date(2026, 10, 1) + timedelta(days=day),
        status="draft", afe_id="afe", baseline_id="baseline", total=Decimal(total), usd_fx=Decimal("1"),
        standard_currency="USD", lines=list(lines),
    )


PLAN = rules.Plan(
    scope="drilling", standard_currency="USD",
    sections={"S1": rules.SectionPlan("S1", "12-1/4 — Intermediate", 500.0, 2000.0)},
    estimate_usd_fx={"NGN": 1 / 1540}, current_usd_fx={"NGN": 1 / 1540},
)


def _history():
    return rules.History([
        _sheet(day, [_service_fact(0, 24, depth=600 + 50 * day), _diesel_fact(0, 1150 + 20 * (day % 5))])
        for day in range(8)
    ])


def _evaluate(lines, *, day=8, history=None, plan=PLAN, total="26300"):
    return rules.evaluate(_sheet(day, lines, total=total), history if history is not None else _history(), plan)


def test_a_clean_day_has_no_findings():
    assert _evaluate([_service_fact(0, 24, depth=1000), _diesel_fact(0, 1200)]) == []


def test_hours_booked_as_days_offers_the_unit_not_a_new_figure():
    [finding] = _evaluate([_service_fact(0, 24, unit="days", depth=1000), _diesel_fact(0, 1200)])
    assert finding.code == "unusual-quantity" and finding.severity == "warning"
    assert finding.field_name == "quantity_unit" and finding.suggested_value == "hours"
    assert finding.apply_to == [("services", 0)]
    assert "24 days" in finding.message and "24 hours would be usual" in finding.message
    # The same slip the other way round: one "hour" where one day was meant.
    [finding] = _evaluate([_service_fact(0, 1, unit="hours", depth=1000), _diesel_fact(0, 1200)])
    assert finding.field_name == "quantity_unit" and finding.suggested_value == "days"


def test_more_than_a_day_is_remarked_even_before_there_is_any_history():
    [finding] = _evaluate([_service_fact(0, 24, unit="days", depth=600)], day=0, history=rules.History([]))
    assert finding.code == "more-than-a-day" and finding.severity == "warning"
    assert finding.suggested_value == "hours" and finding.scope == "sheet"
    [finding] = _evaluate([_service_fact(0, 3, unit="days", depth=600)], day=0, history=rules.History([]))
    assert finding.severity == "info"
    assert _evaluate([_service_fact(0, 1, unit="days", depth=600)], day=0, history=rules.History([])) == []


def test_an_extra_zero_on_a_quantity_is_a_warning_with_the_corrected_value():
    [finding] = _evaluate([_service_fact(0, 24, depth=1000), _diesel_fact(0, 12000)])
    assert finding.code == "unusual-quantity" and finding.severity == "warning"
    assert finding.suggested_value == "1200" and finding.apply_to == [("consumables", 0)]
    assert finding.lines == [("consumables", 0)]
    assert "10 times the usual" in finding.message
    assert finding.basis.startswith("The 8 nearest sheets of this AFE usually carry")
    # Unusual, but not something one slip explains: a notice without a suggestion.
    [finding] = _evaluate([_service_fact(0, 24, depth=1000), _diesel_fact(0, 3900)])
    assert finding.severity == "info" and finding.suggested_value is None and finding.apply_to == []


def test_a_slip_on_one_of_two_lines_names_that_line():
    [finding] = _evaluate([
        _service_fact(0, 24, depth=1000), _diesel_fact(0, 600), _diesel_fact(1, 6000, sub_activity="sa2"),
    ])
    assert finding.lines == [("consumables", 0), ("consumables", 1)]
    assert finding.apply_to == [("consumables", 1)] and finding.suggested_value == "600"
    assert "would bring the day to 1,200 L" in finding.message


def test_an_override_is_compared_with_the_locked_rate_in_the_same_money():
    [finding] = _evaluate([_service_fact(0, 24, override="250000", depth=1000), _diesel_fact(0, 1200)])
    assert finding.code == "unusual-rate" and finding.severity == "warning"
    assert finding.suggested_value == "25000" and finding.scope == "baseline"
    # A modest override is what overrides are for.
    assert _evaluate([_service_fact(0, 24, override="30000", depth=1000), _diesel_fact(0, 1200)]) == []
    # An override in another currency is converted before it is compared ...
    naira = dict(currency="NGN", usd_fx="0.00064935")
    assert _evaluate([_service_fact(0, 24, override="38500000", depth=1000, **naira), _diesel_fact(0, 1200)]) == []
    # ... and a slip is still a slip.
    [finding] = _evaluate([_service_fact(0, 24, override="385000000", depth=1000, **naira), _diesel_fact(0, 1200)])
    assert finding.code == "unusual-rate" and finding.suggested_value == "38500000"


def test_an_exchange_rate_entered_the_other_way_round_is_recognised_once():
    findings = _evaluate([
        _service_fact(0, 24, depth=1000), _diesel_fact(0, 1200, override="1700", currency="NGN", usd_fx="1540"),
    ])
    # The rate override on that line is not reported as well: a comparison
    # through an exchange rate that is itself in doubt says nothing.
    assert [finding.code for finding in findings] == ["unusual-fx"]
    finding = findings[0]
    assert finding.severity == "warning" and finding.field_name == "exchange_rate"
    assert "the other way round" in finding.message
    assert abs(Decimal(finding.suggested_value) - Decimal(1) / Decimal(1540)) < Decimal("0.0000001")
    assert finding.apply_to == [("consumables", 0)]


def test_an_exchange_rate_that_agrees_with_the_estimate_or_the_other_sheets_is_silent():
    assert rules.judge_exchange_rate(Decimal("0.00065"), "NGN", [], 1 / 1540) is None
    # The currency has moved since the estimate, and the other sheets agree.
    moved = [1 / 4700] * 4
    assert rules.judge_exchange_rate(Decimal("0.00021"), "NGN", moved, 1 / 1540) is None
    # A sheet that returns to the estimate after earlier mistakes is not blamed.
    assert rules.judge_exchange_rate(Decimal("0.00065"), "NGN", [1540.0] * 4, 1 / 1540) is None
    verdict = rules.judge_exchange_rate(Decimal("0.0065"), "NGN", [1 / 1540] * 4, None)
    assert verdict is not None and verdict.severity == "warning" and verdict.scope == "afe"
    assert verdict.slip is not None and verdict.slip.kind == stats.SCALE_10
    # Nothing to compare with means nothing to say.
    assert rules.judge_exchange_rate(Decimal("1540"), "NGN", [], None) is None


def test_depth_in_the_wrong_unit_backwards_or_outside_the_plan():
    [finding] = _evaluate([_service_fact(0, 24, depth=3281), _diesel_fact(0, 1200)])
    assert finding.code == "depth-outside-plan" and finding.severity == "warning"
    assert finding.field_name == "actual_depth_unit" and finding.suggested_value == "ft"

    [finding] = _evaluate([_service_fact(0, 24, depth=1000, depth_unit="ft"), _diesel_fact(0, 1200)])
    assert finding.code == "depth-decreased" and finding.suggested_value == "m"

    [finding] = _evaluate([_service_fact(0, 24, depth=700), _diesel_fact(0, 1200)])
    assert finding.code == "depth-decreased" and finding.severity == "warning" and finding.suggested_value is None
    assert "DC-WELL-07" in finding.message

    [finding] = _evaluate([_service_fact(0, 24, depth=10000), _diesel_fact(0, 1200)])
    assert finding.field_name == "actual_depth" and finding.suggested_value == "1000"


def test_a_well_drilled_deeper_than_planned_is_progress_not_a_slip():
    history = rules.History([
        _sheet(day, [_service_fact(0, 24, depth=1700 + 40 * day), _diesel_fact(0, 1200)]) for day in range(9)
    ])
    # 2,020 m yesterday, 2,100 m today: outside the plan, consistent with the well.
    assert _evaluate([_service_fact(0, 24, depth=2100), _diesel_fact(0, 1200)], day=9, history=history) == []


def test_completion_work_may_visit_depths_in_any_order():
    completion = rules.Plan(scope="completion", standard_currency="USD", sections=PLAN.sections)
    assert _evaluate([_service_fact(0, 24, depth=700), _diesel_fact(0, 1200)], plan=completion) == []


def test_a_repeated_line_a_missing_usual_line_and_an_unusual_day():
    [finding] = _evaluate([_service_fact(0, 24, depth=1000), _diesel_fact(0, 600), _diesel_fact(1, 600)])
    assert finding.code == "duplicate-line" and finding.lines == [("consumables", 0), ("consumables", 1)]

    [finding] = _evaluate([_service_fact(0, 24, depth=1000)])
    assert finding.code == "usual-line-missing" and finding.severity == "info"
    assert "DIESEL — Diesel" in finding.message and finding.lines == []

    [finding] = _evaluate(
        [_service_fact(0, 24, depth=1000), _diesel_fact(0, 1200, amount="900000")], total="925000",
    )
    assert finding.code == "unusual-day-total" and finding.lines == [("consumables", 0)]
    assert "The largest line is DIESEL — Diesel" in finding.message


def test_findings_are_stable_and_ordered_warnings_first():
    lines = [_service_fact(0, 24, unit="days", depth=3281), _diesel_fact(0, 3900)]
    first = _evaluate(lines)
    second = _evaluate(lines)
    assert [(item.key, item.fingerprint) for item in first] == [(item.key, item.fingerprint) for item in second]
    severities = [item.severity for item in first]
    assert severities == sorted(severities, key=lambda value: 0 if value == "warning" else 1)
    assert len({item.key for item in first}) == len(first)
    assert all(len(item.key) <= 240 and len(item.fingerprint) <= 80 for item in first)


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


def _service_line(setup, rate, *, quantity="24", unit="hours", depth=None, **overrides):
    line = {
        "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
        "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub1"]["id"],
        "vendor_id": setup["vendor"]["id"], "quantity": quantity, "quantity_unit": unit,
        "currency": "USD", "remarks": "Drilling day", "service_id": setup["service"]["id"],
        "baseline_service_rate_id": rate["id"], "charging_basis": "Day Rate", "charge_category": "Operation",
    }
    if depth is not None:
        line.update({"actual_depth": str(depth), "actual_depth_unit": "m"})
    line.update(overrides)
    return line


def _barite_line(setup, *, quantity="10", **overrides):
    line = {
        "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
        "phase_id": setup["phase"]["id"], "sub_activity_id": setup["sub1"]["id"], "vendor_id": None,
        "quantity": quantity, "currency": "USD", "override_rate": None, "override_reason": "",
        "remarks": "Barite usage", "category": "Mud Chemicals", "item_kind": "mud_chemical",
        "item_id": setup["chemical"]["id"],
    }
    line.update(overrides)
    return line


def _payload(services=(), consumables=(), other=()):
    return {
        "remarks": "", "services": list(services), "consumables": list(consumables), "tangibles": [],
        "other_expenses": list(other),
    }


def _new_sheet(client, headers, setup, cost_date, afe_id=None):
    created = _post(client, f"{API}/entries", headers, {
        "well_id": setup["well"]["id"], "afe_id": afe_id or setup["afe"]["id"], "cost_date": cost_date, "remarks": "",
    })
    return created["entry"]["id"]


def _save(client, headers, entry_id, payload):
    response = client.put(f"{API}/entries/{entry_id}", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _preview(client, headers, entry_id, payload):
    response = client.put(f"{API}/entries/{entry_id}/preview", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _checks(client, headers, entry_id):
    response = client.get(f"{API}/entries/{entry_id}/checks", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _steady_history(client, headers, setup, days=6):
    """Six ordinary days: the service for 24 hours, 10 MT of barite, 50 m deeper each day."""
    rate = setup["baseline"]["service_rates"][0]
    entry_ids = [setup["entry"]["id"]]
    for offset in range(1, days):
        entry_ids.append(_new_sheet(client, headers, setup, f"2026-10-{10 + offset:02d}"))
    for offset, entry_id in enumerate(entry_ids):
        _save(client, headers, entry_id, _payload(
            [_service_line(setup, rate, depth=100 + 50 * offset)], [_barite_line(setup)],
        ))
    return rate, entry_ids


def _by_subject(checks, text):
    return next(item for item in checks if text in item["subject_label"])


def test_preview_points_out_slips_and_a_finding_never_blocks_the_save():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        rate, _history_ids = _steady_history(client, headers, setup)
        entry_id = _new_sheet(client, headers, setup, "2026-10-16")

        clean = _preview(client, headers, entry_id, _payload(
            [_service_line(setup, rate, depth=400)], [_barite_line(setup)],
        ))
        assert clean["entry_checks"] == []
        # Everything the preview returned before is still there, untouched.
        assert Decimal(clean["total_cost"]) == Decimal("200.00")
        assert Decimal(clean["services_total"]) == Decimal("100.00")
        assert {"warnings", "section_depths", "total_cost_usd"} <= set(clean)

        slipped = _payload(
            [_service_line(setup, rate, quantity="24", unit="days", depth=400)], [_barite_line(setup, quantity="100")],
        )
        preview = _preview(client, headers, entry_id, slipped)
        assert Decimal(preview["total_cost"]) == Decimal("3400.00")
        checks = preview["entry_checks"]
        assert [item["severity"] for item in checks] == ["warning", "warning"]
        service = _by_subject(checks, "MUD-LOG")
        assert service["code"] == "unusual-quantity" and service["field"] == "quantity_unit"
        assert service["suggested_value"] == "hours" and service["apply_to"] == [{"group": "services", "index": 0}]
        assert service["scope"] == "afe" and service["history_count"] == 6
        barite = _by_subject(checks, "BARITE")
        assert barite["field"] == "quantity" and barite["current_value"] == "100" and barite["suggested_value"] == "10"
        assert barite["lines"] == [{"group": "consumables", "index": 0}]
        assert "10 times the usual 10 MT" in barite["message"]
        assert not barite["reviewed"]

        # Advice only: the same payload saves, with exactly the previewed total.
        saved = _save(client, headers, entry_id, slipped)
        assert Decimal(saved["entry"]["total_cost"]) == Decimal("3400.00")

        result = _checks(client, headers, entry_id)
        assert result["open_warnings"] == 2 and result["open_notices"] == 0 and result["reviewed"] == 0
        assert result["history_sheets"] == 6
        assert {item["key"] for item in result["checks"]} == {item["key"] for item in checks}


def test_keeping_a_value_as_entered_is_audited_and_lapses_when_the_value_changes():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        rate, _history_ids = _steady_history(client, headers, setup)
        entry_id = _new_sheet(client, headers, setup, "2026-10-16")
        payload = _payload([_service_line(setup, rate, depth=400)], [_barite_line(setup, quantity="100")])
        _save(client, headers, entry_id, payload)
        [barite] = _checks(client, headers, entry_id)["checks"]

        reviewed = client.post(f"{API}/entries/{entry_id}/checks/review", headers=headers, json={
            "items": [{"key": barite["key"], "fingerprint": barite["fingerprint"]}], "note": "Bulk delivery for the section",
        })
        assert reviewed.status_code == 200, reviewed.text
        body = reviewed.json()
        assert body["open_warnings"] == 0 and body["reviewed"] == 1
        [check] = body["checks"]
        assert check["reviewed"] and check["reviewed_by"] == "Test Owner"
        assert check["review_note"] == "Bulk delivery for the section" and check["reviewed_at"]
        # The preview of the same lines shows the same decision.
        [previewed] = _preview(client, headers, entry_id, payload)["entry_checks"]
        assert previewed["reviewed"]

        with SessionLocal() as db:
            summaries = db.scalars(select(AuditLog.summary).where(AuditLog.entity_id == entry_id)).all()
            assert any("kept 1 value(s) as entered" in text and "BARITE" in text and "Bulk delivery" in text
                       for text in summaries)
            assert db.scalar(select(func.count(DailyCostCheckReview.id))) == 1

        # Reviewing the same finding again changes nothing and is not audited twice.
        again = client.post(f"{API}/entries/{entry_id}/checks/review", headers=headers, json={
            "items": [{"key": barite["key"], "fingerprint": barite["fingerprint"]}], "note": "Bulk delivery for the section",
        })
        assert again.status_code == 200
        with SessionLocal() as db:
            assert sum("kept 1 value" in text for text in db.scalars(
                select(AuditLog.summary).where(AuditLog.entity_id == entry_id)).all()) == 1

        # A different value is a different finding: the review does not cover it.
        _save(client, headers, entry_id, _payload(
            [_service_line(setup, rate, depth=400)], [_barite_line(setup, quantity="200")],
        ))
        [changed] = _checks(client, headers, entry_id)["checks"]
        assert not changed["reviewed"] and changed["current_value"] == "200"

        # A review of what is no longer on the sheet is refused, and nothing is stored.
        stale = client.post(f"{API}/entries/{entry_id}/checks/review", headers=headers, json={
            "items": [{"key": barite["key"], "fingerprint": barite["fingerprint"]}],
        })
        assert stale.status_code == 409 and "changed after they were shown" in stale.json()["detail"]
        unknown = client.post(f"{API}/entries/{entry_id}/checks/review", headers=headers, json={
            "items": [{"key": "unusual-quantity|made-up", "fingerprint": "q|1"}],
        })
        assert unknown.status_code == 409

        # Review the new value, then withdraw the review: it is open again and audited.
        assert client.post(f"{API}/entries/{entry_id}/checks/review", headers=headers, json={
            "items": [{"key": changed["key"], "fingerprint": changed["fingerprint"]}],
        }).json()["reviewed"] == 1
        reopened = client.post(f"{API}/entries/{entry_id}/checks/reopen", headers=headers, json={"keys": [changed["key"]]})
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["reviewed"] == 0 and reopened.json()["open_warnings"] == 1
        with SessionLocal() as db:
            assert any("reopened 1 reviewed check(s)" in text for text in db.scalars(
                select(AuditLog.summary).where(AuditLog.entity_id == entry_id)).all())
            assert db.scalar(select(func.count(DailyCostCheckReview.id))) == 0


def test_entry_checks_follow_tenant_permission_and_draft_rules():
    with TestClient(app) as client:
        north = login(client, "north")
        south = login(client, "south")
        setup = _setup_daily_sheet(client, north)
        entry_id = setup["entry"]["id"]
        rate = setup["baseline"]["service_rates"][0]
        # No history is needed for this one: 24 days on a one-day sheet.
        _save(client, north, entry_id, _payload([_service_line(setup, rate, quantity="24", unit="days")]))
        [finding] = _checks(client, north, entry_id)["checks"]
        assert finding["code"] == "more-than-a-day" and finding["severity"] == "warning"
        review = {"items": [{"key": finding["key"], "fingerprint": finding["fingerprint"]}]}

        # Another workspace sees nothing and can change nothing.
        assert client.get(f"{API}/entries/{entry_id}/checks", headers=south).status_code == 404
        assert client.post(f"{API}/entries/{entry_id}/checks/review", headers=south, json=review).status_code == 404
        assert client.post(f"{API}/entries/{entry_id}/checks/reopen", headers=south,
                           json={"keys": [finding["key"]]}).status_code == 404
        assert client.get(f"{API}/wells/{setup['well']['id']}/checks", headers=south).status_code == 404
        with SessionLocal() as db:
            assert db.scalar(select(func.count(DailyCostCheckReview.id))) == 0

        # The request contract is strict.
        assert client.post(f"{API}/entries/{entry_id}/checks/review", headers=north,
                           json={**review, "severity": "info"}).status_code == 422
        assert client.post(f"{API}/entries/{entry_id}/checks/review", headers=north, json={"items": []}).status_code == 422
        assert client.post(f"{API}/entries/{entry_id}/checks/reopen", headers=north, json={"keys": ["x"]}).status_code == 422

        # A viewer reads the checks and cannot review them.
        def set_permissions(keys, *, owner=False):
            with SessionLocal() as db:
                north_id = select(Organization.id).where(Organization.slug == "north").scalar_subquery()
                user = db.scalar(select(User).where(User.email == "owner@example.com", User.organization_id == north_id))
                role = user.roles[0]
                role.is_owner = owner
                if keys is not None:
                    role.permissions = [permission for permission in role.permissions if permission.key in keys]
                db.commit()

        set_permissions(("daily-cost:read", "daily-cost:submit", "audit:read"))
        assert client.get(f"{API}/entries/{entry_id}/checks", headers=north).status_code == 200
        assert client.get(f"{API}/wells/{setup['well']['id']}/checks", headers=north).status_code == 200
        assert client.post(f"{API}/entries/{entry_id}/checks/review", headers=north, json=review).status_code == 403
        assert client.post(f"{API}/entries/{entry_id}/checks/reopen", headers=north,
                           json={"keys": [finding["key"]]}).status_code == 403
        set_permissions(("audit:read",))
        assert client.get(f"{API}/entries/{entry_id}/checks", headers=north).status_code == 403
        assert client.get(f"{API}/wells/{setup['well']['id']}/checks", headers=north).status_code == 403
        set_permissions(None, owner=True)

        # A submitted sheet is read-only, and so are its reviews.
        assert client.post(f"{API}/entries/{entry_id}/submit", headers=north, json={"remarks": "Checked"}).status_code == 200
        frozen = client.post(f"{API}/entries/{entry_id}/checks/review", headers=north, json=review)
        assert frozen.status_code == 409 and "Draft sheet only" in frozen.json()["detail"]
        assert client.post(f"{API}/entries/{entry_id}/checks/reopen", headers=north,
                           json={"keys": [finding["key"]]}).status_code == 409
        assert _checks(client, north, entry_id)["open_warnings"] == 1


def test_exchange_rate_and_depth_checks_on_saved_sheets():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        rate = setup["baseline"]["service_rates"][0]
        first = setup["entry"]["id"]
        naira = dict(currency="NGN", exchange_rate="0.00065", unit_rate="1500000", quantity="1")
        _save(client, headers, first, _payload(
            [_service_line(setup, rate, depth=300)], other=[_other_line(setup, **naira)],
        ))
        assert _checks(client, headers, first)["checks"] == []

        second = _new_sheet(client, headers, setup, "2026-10-11")
        wrong_way = _payload(
            [_service_line(setup, rate, depth=350)],
            other=[_other_line(setup, **{**naira, "exchange_rate": "1540"})],
        )
        preview = _preview(client, headers, second, wrong_way)
        [fx] = [item for item in preview["entry_checks"] if item["code"] == "unusual-fx"]
        assert fx["severity"] == "warning" and fx["field"] == "exchange_rate"
        assert "the other way round" in fx["message"]
        assert fx["lines"] == [{"group": "other_expenses", "index": 0}] == fx["apply_to"]
        assert abs(Decimal(fx["suggested_value"]) - Decimal(1) / Decimal(1540)) < Decimal("0.0000001")
        # Saving the slip overwrites the AFE's working rate; the other sheet still remembers.
        _save(client, headers, second, wrong_way)
        [saved_fx] = [item for item in _checks(client, headers, second)["checks"] if item["code"] == "unusual-fx"]
        assert saved_fx["key"] == fx["key"] and saved_fx["fingerprint"] == fx["fingerprint"]

        # Feet typed with the unit left on metres: 2,000 "m" in a section planned to 1,000 m.
        third = _new_sheet(client, headers, setup, "2026-10-12")
        preview = _preview(client, headers, third, _payload([_service_line(setup, rate, depth=2000)]))
        [depth] = [item for item in preview["entry_checks"] if item["code"].startswith("depth")]
        assert depth["code"] == "depth-outside-plan" and depth["severity"] == "warning"
        assert depth["field"] == "actual_depth_unit" and depth["suggested_value"] == "ft"
        # A depth shallower than the sheet before it.
        preview = _preview(client, headers, third, _payload([_service_line(setup, rate, depth=120)]))
        [depth] = [item for item in preview["entry_checks"] if item["code"].startswith("depth")]
        assert depth["code"] == "depth-decreased" and "2026-10-11" in depth["message"]


def test_a_new_afe_is_judged_by_its_own_workspace_and_no_other():
    with TestClient(app) as client:
        north = login(client, "north")
        south = login(client, "south")
        setup = _setup_daily_sheet(client, north)
        _steady_history(client, north, setup)

        # A second AFE on the same well has no sheets of its own yet.
        afe = _post(client, "/api/v1/afe/afes", north, {
            "rig_id": setup["rig"]["id"], "well_id": setup["well"]["id"], "afe_code": "AFE-02",
            "afe_name": "Second drilling AFE", "afe_type": "Drilling", "remarks": "",
        }, status=200)
        estimate = client.put(f"/api/v1/afe/afes/{afe['id']}/estimate", headers=north, json={
            "services": [], "tangibles": [], "standard_currency": "", "exchange_rates": [],
            "consumables": [{
                "client_key": "bulk-mud", "category": "Mud Chemicals", "hole_section_id": setup["hole"]["id"],
                "phase_id": setup["phase"]["id"], "drill_bit_id": None, "quantity": "1", "override_rate": None,
                "estimated_amount": "5000", "currency": "USD", "remarks": "Bulk chemicals allowance",
            }],
        })
        assert estimate.status_code == 200, estimate.text
        entry_id = _new_sheet(client, north, setup, "2026-10-20", afe_id=afe["id"])
        payload = _payload(consumables=[_barite_line(setup, quantity="100")])

        entry_checks.forget_pending_refreshes()
        with SessionLocal() as db:
            assert db.scalar(select(func.count(DailyCostItemProfile.id))) == 0
        # The first preview has nothing to compare with; it asks for the profile,
        # which is built after the response has been sent.
        assert _preview(client, north, entry_id, payload)["entry_checks"] == []
        with SessionLocal() as db:
            north_id = db.scalar(select(Organization.id).where(Organization.slug == "north"))
            profiles = db.scalars(select(DailyCostItemProfile)).all()
            assert profiles and {row.organization_id for row in profiles} == {north_id}
            quantity = next(row for row in profiles if row.metric == "quantity" and row.subject_id == setup["chemical"]["id"])
            assert quantity.sample_count == 6 and quantity.well_count == 1
            assert quantity.median_value == Decimal("10") and quantity.unit == "MT"
        [finding] = _preview(client, north, entry_id, payload)["entry_checks"]
        assert finding["scope"] == "workspace" and finding["suggested_value"] == "10"
        assert finding["basis"].startswith("Across this workspace a sheet usually carries 10 MT")

        # The same item codes in another workspace learn nothing from this one.
        other = _setup_daily_sheet(client, south)
        entry_checks.forget_pending_refreshes()
        south_payload = _payload(consumables=[_barite_line(other, quantity="100")])
        assert _preview(client, south, other["entry"]["id"], south_payload)["entry_checks"] == []
        assert _preview(client, south, other["entry"]["id"], south_payload)["entry_checks"] == []
        with SessionLocal() as db:
            south_id = db.scalar(select(Organization.id).where(Organization.slug == "south"))
            south_rows = db.scalars(select(DailyCostItemProfile).where(DailyCostItemProfile.organization_id == south_id)).all()
            # Only the "looked for, nothing recorded yet" marker.
            assert south_rows and all(row.sample_count == 0 for row in south_rows)


def test_the_well_review_lists_the_sheets_that_need_a_look():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        rate, entry_ids = _steady_history(client, headers, setup)
        # One mistake in the middle of the history.
        _save(client, headers, entry_ids[2], _payload(
            [_service_line(setup, rate, depth=200)], [_barite_line(setup, quantity="100")],
        ))
        response = client.get(f"{API}/wells/{setup['well']['id']}/checks", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["sheets_checked"] == 6 and body["sheets_with_findings"] == 1 and not body["truncated"]
        assert body["open_warnings"] == 1 and body["reviewed"] == 0
        [sheet] = body["sheets"]
        assert sheet["entry_id"] == entry_ids[2] and sheet["cost_date"] == "2026-10-12" and sheet["afe_code"] == "AFE-01"
        assert sheet["checks"][0]["suggested_value"] == "10"
        # One wrong day in the history does not make the right days look wrong.
        assert _checks(client, headers, entry_ids[4])["checks"] == []
        filtered = client.get(f"{API}/wells/{setup['well']['id']}/checks?afe_id={setup['afe']['id']}", headers=headers)
        assert filtered.status_code == 200 and filtered.json()["sheets_with_findings"] == 1
        unknown = client.get(f"{API}/wells/{setup['well']['id']}/checks?afe_id=none", headers=headers)
        assert unknown.status_code == 200 and unknown.json()["sheets_checked"] == 0


def test_a_failure_inside_the_checks_never_breaks_the_sheet(monkeypatch):
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        rate = setup["baseline"]["service_rates"][0]
        entry_id = setup["entry"]["id"]
        payload = _payload([_service_line(setup, rate, quantity="24", unit="days")])
        assert len(_preview(client, headers, entry_id, payload)["entry_checks"]) == 1
        assert _checks(client, headers, entry_id)["enabled"] is True

        def broken(*_args, **_kwargs):
            raise RuntimeError("the checks are broken")

        monkeypatch.setattr(entry_checks.rules, "evaluate", broken)
        preview = _preview(client, headers, entry_id, payload)
        assert preview["entry_checks"] == []
        assert Decimal(preview["total_cost"]) == Decimal("2400.00")
        assert Decimal(_save(client, headers, entry_id, payload)["entry"]["total_cost"]) == Decimal("2400.00")
        monkeypatch.undo()

        # Turned off, the checks say nothing and take no reviews.
        monkeypatch.setattr(get_settings(), "entry_checks_enabled", False)
        assert _preview(client, headers, entry_id, payload)["entry_checks"] == []
        off = _checks(client, headers, entry_id)
        assert off["checks"] == [] and off["enabled"] is False
        well_off = client.get(f"{API}/wells/{setup['well']['id']}/checks", headers=headers).json()
        assert well_off["enabled"] is False and well_off["sheets"] == []
        refused = client.post(f"{API}/entries/{entry_id}/checks/review", headers=headers, json={
            "items": [{"key": "unusual-quantity|any", "fingerprint": "q|24"}],
        })
        assert refused.status_code == 409 and "turned off" in refused.json()["detail"]


def test_reviews_are_removed_with_their_sheet():
    with TestClient(app) as client:
        headers = login(client)
        setup = _setup_daily_sheet(client, headers)
        rate = setup["baseline"]["service_rates"][0]
        entry_id = setup["entry"]["id"]
        _save(client, headers, entry_id, _payload([_service_line(setup, rate, quantity="24", unit="days")]))
        [finding] = _checks(client, headers, entry_id)["checks"]
        assert client.post(f"{API}/entries/{entry_id}/checks/review", headers=headers, json={
            "items": [{"key": finding["key"], "fingerprint": finding["fingerprint"]}],
        }).status_code == 200
        assert client.delete(f"{API}/entries/{entry_id}", headers=headers).status_code == 200
        # A deleted sheet has no checks to read; restoring it brings the review back with it.
        assert client.get(f"{API}/entries/{entry_id}/checks", headers=headers).status_code == 404
        assert client.post(f"{API}/entries/{entry_id}/restore", headers=headers).status_code == 200
        assert _checks(client, headers, entry_id)["reviewed"] == 1
        assert client.delete(f"{API}/entries/{entry_id}", headers=headers).status_code == 200
        assert client.delete(f"{API}/entries/{entry_id}/permanent", headers=headers).status_code == 204
        with SessionLocal() as db:
            assert db.scalar(select(func.count(DailyCostCheckReview.id))) == 0


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_the_entry_check_tables_are_added_and_removed_by_their_own_revision(tmp_path):
    database = tmp_path / "entry-checks.sqlite3"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    backend = Path(__file__).resolve().parents[1]

    def migrate(operation: str, target: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", operation, target],
            cwd=backend, env=environment, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    def tables() -> set[str]:
        with sqlite3.connect(database) as connection:
            return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    migrate("upgrade", PREVIOUS_HEAD)
    before = tables()
    assert not {"daily_cost_check_reviews", "daily_cost_item_profiles"} & before

    migrate("upgrade", REVISION)
    assert tables() - before == {"daily_cost_check_reviews", "daily_cost_item_profiles"}
    with sqlite3.connect(database) as connection:
        review_columns = {row[1] for row in connection.execute("PRAGMA table_info(daily_cost_check_reviews)")}
        assert {"organization_id", "entry_id", "check_key", "fingerprint", "reviewed_by", "reviewed_at"} <= review_columns
        profile_columns = {row[1] for row in connection.execute("PRAGMA table_info(daily_cost_item_profiles)")}
        assert {"organization_id", "subject_id", "metric", "median_value", "spread", "refreshed_at"} <= profile_columns
        foreign_keys = {(row[2], row[3], row[6]) for row in connection.execute(
            "PRAGMA foreign_key_list(daily_cost_check_reviews)")}
        assert ("daily_cost_entries", "entry_id", "CASCADE") in foreign_keys
        assert ("organizations", "organization_id", "CASCADE") in foreign_keys

    migrate("downgrade", PREVIOUS_HEAD)
    assert tables() == before
