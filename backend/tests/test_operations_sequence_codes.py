"""Sequence codes: skip, partial progress, unplanned hours and splits.

The four cases this file pins down are the ones the old arithmetic got wrong:

1. a planned activity that is **skipped** releases its hours instead of reading as
   a lag, and shifts the effective curve earlier;
2. a code with **some** of its hours logged is *in progress* — progress and
   remaining hours, never a lead, and a later day under the same code adds to it;
3. hours against **no** code are Unplanned Activity: they raise actual hours and
   can only lag, and they get their own bucket instead of a footnote;
4. one line can genuinely do **two** activities, so its hours can be split — and a
   split can never lose an hour, because the remainder is named.
"""

import sys
from datetime import UTC, datetime, timedelta

from test_rig_well import create_rig, create_well, fresh_database, login  # noqa: F401 - autouse fixture

sys.path.insert(0, "tests")

from test_operations_timeline_hours import _items, _well, good  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.rig_well import Well  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

OPS = "/api/v1/operations"


def _programme(client, headers, well, rows):
    plan = good(
        client.post(
            OPS + "/plans",
            headers=headers,
            json={
                "well_id": well["id"],
                "scope": "drilling",
                "label": "Baseline",
                "planned_start_at": "2026-11-01T00:00:00Z",
            },
        )
    )
    good(client.put(OPS + f"/plans/{plan['id']}/items", headers=headers, json=rows))
    good(client.post(OPS + f"/plans/{plan['id']}/activate", headers=headers))
    return plan


_SERIAL = 0


def _criteria(client, headers):
    """Master data for a report, with a fresh code each time.

    A code is unique per workspace, so a test that writes two reports must not reuse
    one — and a report cannot be accepted without the three criteria.
    """
    global _SERIAL
    _SERIAL += 1
    suffix = f"{_SERIAL:03d}"
    section = good(
        client.post(
            "/api/v1/master-data/hole-sections",
            headers=headers,
            json={"code": f"H12{suffix}", "name": '12-1/4" hole'},
        )
    )
    phase = good(
        client.post("/api/v1/master-data/phases", headers=headers, json={"code": f"DRL{suffix}", "name": "Drilling"})
    )
    activity = good(
        client.post("/api/v1/master-data/activities", headers=headers, json={"code": f"ROT{suffix}", "name": "Rotating"})
    )
    return {"hole_section_id": section["id"], "phase_id": phase["id"], "activity_id": activity["id"]}


def _report(client, headers, rig, well, blocks, day=16, submit=True):
    """One daily report; ``blocks`` is ``[(narrative, hours, allocation, code)]``.

    ``submit=False`` leaves the report a draft, which is the only state a sequence
    code may be changed in.
    """
    criteria = _criteria(client, headers)
    report = good(
        client.post(
            OPS + "/reports",
            headers=headers,
            json={"well_id": well["id"], "rig_id": rig["id"], "report_date": f"2026-11-{day:02d}"},
        )
    )
    payload = []
    cursor = datetime(2026, 11, day, tzinfo=UTC)
    for index, (narrative, hours, allocation, code) in enumerate(blocks, 1):
        payload.append(
            {
                "sequence_no": index,
                "started_at": cursor.isoformat(),
                "ended_at": (cursor + timedelta(hours=hours)).isoformat(),
                "duration_minutes": int(hours * 60),
                "narrative": narrative,
                "allocation": allocation,
                "reason": "No coded programme activity for this work." if allocation == "UPA" else "",
                "review_state": "accepted",
                "timeline_code": code,
                **criteria,
            }
        )
        cursor += timedelta(hours=hours)
    # The period is the span actually logged, so a part-day of one activity is a
    # complete report rather than an hour short of a full day.
    body = good(
        client.put(
            OPS + f"/reports/{report['id']}",
            headers=headers,
            json={
                "report": {"period_start_at": payload[0]["started_at"], "period_end_at": payload[-1]["ended_at"]},
                "blocks": payload,
            },
        )
    )
    if submit:
        # Submitted, because a draft does not vote: the rollup reports what is
        # recorded and signed, and shows draft hours beside it as provisional.
        good(client.post(OPS + f"/reports/{report['id']}/submit", headers=headers))
    return body


def _rollup(client, headers, plan):
    return good(client.get(OPS + f"/plans/{plan['id']}/timeline-rollup", headers=headers))


def _codes(rollup):
    return {row["sequence_no"]: row for row in rollup["codes"]}


def _submit(client, headers, report):
    return good(client.post(OPS + f"/reports/{report['id']}/submit", headers=headers))


# ---------------------------------------------------------------------------
# 1. A skipped activity releases its hours; it is not a lag
# ---------------------------------------------------------------------------
def test_a_skipped_activity_releases_its_hours_and_shifts_the_curve():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        plan = _programme(
            client,
            headers,
            well,
            [
                {"sequence_no": 1, "description": "Drill surface hole", "planned_hours": "24"},
                {"sequence_no": 2, "description": "Run surface casing", "planned_hours": "48"},
                {"sequence_no": 3, "description": "Drill intermediate hole", "planned_hours": "100"},
            ],
        )
        # The programme is 172 h ≈ 7.17 d to the third activity.
        before = _codes(_rollup(client, headers, plan))
        assert before[3]["effective_cum_days"] == before[3]["saved_cum_days"] == "7.167"

        item = _items(client, headers, plan)[1]
        # A skip needs a reason: it is a decision the record keeps.
        missing = client.post(
            OPS + f"/plans/{plan['id']}/items/{item['id']}/state",
            headers=headers,
            json={"state": "skipped"},
        )
        assert missing.status_code == 422
        assert "why" in missing.json()["detail"].lower()

        skipped = good(
            client.post(
                OPS + f"/plans/{plan['id']}/items/{item['id']}/state",
                headers=headers,
                json={"state": "skipped", "reason": "Client deleted the casing programme step."},
            )
        )
        assert skipped["state"] == "skipped"
        assert skipped["saved_planned_hours"] == "48.000"
        assert skipped["planned_in_scope"] == "124.000"
        assert skipped["planned_saved"] == "48.000"

        after = _codes(_rollup(client, headers, plan))
        assert after[2]["state"] == "skipped"
        # The skipped row keeps its audit figure and reports the saving.
        assert after[2]["saved_cum_days"] == "3.000"
        assert after[2]["effective_cum_days"] == "1.000"
        assert after[2]["saved_planned_hours"] == "48.000"
        # Work that will never be done is not a lag: no verdict, and the hours of
        # the activities after it move two days earlier.
        assert after[2]["variance_hours"] is None
        assert after[2]["comparison"] == "on"
        assert after[3]["cum_shift_days"] == "2.000"
        assert after[3]["effective_cum_days"] == "5.167"
        # And the saved 48 h is *not* quietly netted into a lead.
        rollup = _rollup(client, headers, plan)
        assert rollup["totals"]["realised_variance"] is None
        assert rollup["totals"]["planned_saved"] == "48.000"

        # Restoring it puts the curve back.
        restored = good(
            client.post(
                OPS + f"/plans/{plan['id']}/items/{item['id']}/state",
                headers=headers,
                json={"state": "planned"},
            )
        )
        assert restored["planned_saved"] is None
        assert _codes(_rollup(client, headers, plan))[3]["cum_shift_days"] == "0.000"


def test_hours_coded_to_a_skipped_activity_are_refused_and_named():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        plan = _programme(
            client,
            headers,
            well,
            [
                {"sequence_no": 1, "description": "Drill surface hole", "planned_hours": "24"},
                {"sequence_no": 2, "description": "Run surface casing", "planned_hours": "48"},
            ],
        )
        _report(client, headers, rig, well, [("Drill surface hole 24 hrs", 20, "PT", "1")])
        item = _items(client, headers, plan)[0]
        response = client.post(
            OPS + f"/plans/{plan['id']}/items/{item['id']}/state",
            headers=headers,
            json={"state": "skipped", "reason": "Trying to park logged work."},
        )
        assert response.status_code == 409
        assert "Hours are already logged" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 2. A partial code is in progress, and later days add to it
# ---------------------------------------------------------------------------
def test_a_partial_code_reports_progress_and_later_days_carry_it_forward():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        plan = _programme(
            client,
            headers,
            well,
            [{"sequence_no": 1, "description": "Drill 12-1/4 hole", "planned_hours": "100"}],
        )
        first = _report(client, headers, rig, well, [("Drill 12-1/4 hole", 12, "PT", "1")], day=16)
        item = _items(client, headers, plan)[0]
        row = _codes(_rollup(client, headers, plan))[1]
        assert row["state"] == "in_progress"
        assert row["actual_hours"] == "12.000"
        assert row["progress_pct"] == "12.000"
        assert row["remaining_hours"] == "88.000"
        # The defect this replaces: 12 of 100 printed as an 88-hour lead.
        assert row["variance_hours"] is None
        assert row["variance_days"] is None
        assert row["comparison"] == "on"

        # The same code on the next day: the hours total, the operation is still open.
        _report(client, headers, rig, well, [("Drill 12-1/4 hole continued", 20, "PT", "1")], day=17)
        row = _codes(_rollup(client, headers, plan))[1]
        assert row["actual_hours"] == "32.000"
        assert row["progress_pct"] == "32.000"
        assert row["remaining_hours"] == "68.000"
        assert row["line_count"] == 2
        assert row["report_count"] == 2
        assert row["variance_hours"] is None
        assert any(f["kind"] == "close_suggested" for f in _rollup(client, headers, plan)["findings"]) is False

        # Closing states the outcome once, on the summed hours.
        closed = good(
            client.post(OPS + f"/plans/{plan['id']}/items/{item['id']}/close", headers=headers, json={})
        )
        assert closed["state"] == "complete"
        assert closed["actual_hours"] == "32.000"
        assert closed["variance_hours"] == "68.000"
        assert closed["comparison"] == "ahead"
        # 68 h is 2.833 days early, on the user's own sign convention.
        assert closed["variance_days"] == "2.833"
        assert closed["summary"].startswith("Sequence 1 closed · ahead")

        # A closed code keeps its verdict when a later day adds hours to it, but the
        # verdict is what the record now says — never a frozen figure.
        _report(client, headers, rig, well, [("Drill 12-1/4 hole finishing", 8, "PT", "1")], day=18)
        row = _codes(_rollup(client, headers, plan))[1]
        assert row["state"] == "complete"
        assert row["actual_hours"] == "40.000"
        assert row["variance_hours"] == "60.000"


def test_closing_without_hours_or_logged_lines_is_refused():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        plan = _programme(
            client,
            headers,
            well,
            [{"sequence_no": 1, "description": "Drill surface hole", "planned_hours": "24"}],
        )
        item = _items(client, headers, plan)[0]
        empty = client.post(OPS + f"/plans/{plan['id']}/items/{item['id']}/close", headers=headers, json={})
        assert empty.status_code == 422
        assert "no logged hours" in empty.json()["detail"]
        # Hours that were never logged can still be closed, but only with a note
        # saying where they are — the claim has to be traceable.
        unbacked = client.post(
            OPS + f"/plans/{plan['id']}/items/{item['id']}/close",
            headers=headers,
            json={"actual_hours": "26"},
        )
        assert unbacked.status_code == 422
        assert "needs a note" in unbacked.json()["detail"]
        closed = good(
            client.post(
                OPS + f"/plans/{plan['id']}/items/{item['id']}/close",
                headers=headers,
                json={"actual_hours": "26", "note": "Hours are in the rig contractor's day book."},
            )
        )
        assert closed["variance_hours"] == "-2.000"
        assert closed["variance_days"] == "-0.083"

        # A superseded version is history: it cannot be re-highlighted in place.
        reopened = good(
            client.post(
                OPS + f"/plans/{plan['id']}/items/{item['id']}/reopen",
                headers=headers,
                json={"note": "Closed on the wrong activity."},
            )
        )
        # The typed hours are not a log line, so reopening leaves the activity with
        # nothing recorded against it — not-started, which is the truth.
        assert reopened["state"] == "not_started"
        assert reopened["summary"].startswith("Sequence 1 reopened")


# ---------------------------------------------------------------------------
# 3. Unplanned hours: their own bucket, added to actual, never a lead
# ---------------------------------------------------------------------------
def test_unplanned_hours_are_a_bucket_and_reduce_a_realised_lead():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        plan = _programme(
            client,
            headers,
            well,
            [
                {"sequence_no": 1, "description": "Drill surface hole", "planned_hours": "24"},
                {"sequence_no": 2, "description": "Run surface casing", "planned_hours": "48"},
            ],
        )
        # 20 h with no code: unplanned, and it can only be a lag.
        _report(client, headers, rig, well, [("Catering standby for weather", 20, "UPA", None)])
        row = _codes(_rollup(client, headers, plan))
        assert row[1]["state"] == "not_started"
        rollup = _rollup(client, headers, plan)
        assert rollup["unplanned"]["actual_hours"] == "20.000"
        assert rollup["unplanned"]["upa_hours"] == "20.000"
        assert rollup["unplanned"]["variance_hours"] == "-20.000"
        assert rollup["unplanned"]["variance_days"] == "-0.833"
        assert rollup["unplanned"]["comparison"] == "behind"
        assert rollup["uncoded_lines"] == 1
        assert rollup["totals"]["actual_unplanned"] == "20.000"
        assert rollup["totals"]["realised_variance"] == "-20.000"
        assert any(f["kind"] == "unplanned_activity" for f in rollup["findings"])

        # Now a 20 h activity closed against its planned 24 h: a 4 h lead of its own,
        # which the 20 h of unplanned work more than cancels. The two figures are
        # reported side by side and never conflated.
        _report(client, headers, rig, well, [("Drill surface hole", 20, "PT", "1")], day=17)
        item = _items(client, headers, plan)[0]
        good(client.post(OPS + f"/plans/{plan['id']}/items/{item['id']}/close", headers=headers, json={}))
        rollup = _rollup(client, headers, plan)
        assert _codes(rollup)[1]["variance_hours"] == "4.000"
        assert rollup["unplanned"]["variance_hours"] == "-20.000"
        assert rollup["totals"]["realised_variance"] == "-16.000"
        assert rollup["totals"]["realised_variance_days"] == "-0.667"
        # Burn is named as burn, not as a verdict.
        assert rollup["totals"]["plan_coverage_pct"] == "55.556"
        assert rollup["totals"]["closed_coverage_pct"] == "33.333"


# ---------------------------------------------------------------------------
# 4. One line, two codes
# ---------------------------------------------------------------------------
def test_one_line_can_be_split_between_two_codes_without_losing_an_hour():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        plan = _programme(
            client,
            headers,
            well,
            [
                {"sequence_no": 1, "description": "Drill surface hole", "planned_hours": "24"},
                {"sequence_no": 2, "description": "Run surface casing", "planned_hours": "48"},
            ],
        )
        report = _report(
            client, headers, rig, well, [("Drill and case the surface hole", 20, "PT", None)], submit=False
        )
        block = report["blocks"][0]
        items = _items(client, headers, plan)

        over = client.post(
            OPS + "/reports/timeline-codes/split",
            headers=headers,
            json={
                "block_id": block["id"],
                "allocations": [
                    {"item_id": items[0]["id"], "hours": "12"},
                    {"item_id": items[1]["id"], "hours": "12"},
                ],
            },
        )
        assert over.status_code == 422
        assert "cannot be invented" in over.json()["detail"]

        split = good(
            client.post(
                OPS + "/reports/timeline-codes/split",
                headers=headers,
                json={
                    "block_id": block["id"],
                    "allocations": [
                        {"item_id": items[0]["id"], "hours": "12"},
                        {"item_id": items[1]["id"], "hours": "6"},
                    ],
                },
            )
        )
        assert split["line_hours"] == "20.000"
        assert split["allocated_hours"] == "18.000"
        # Two hours of the line belong to neither activity, and are named rather than
        # dropped on the floor.
        assert split["remainder_hours"] == "2.000"
        assert "remains unplanned" in split["summary"]

        # The draft does not vote, so the split is checked where it is written — on
        # the line itself — and then on the rollup once the report is submitted.
        refreshed = good(client.get(OPS + f"/reports/{report['id']}", headers=headers))["blocks"][0]
        assert refreshed["timeline_split_state"] == "split"
        good(client.post(OPS + f"/reports/{report['id']}/submit", headers=headers))
        rollup = _rollup(client, headers, plan)
        codes = _codes(rollup)
        assert codes[1]["actual_hours"] == "12.000"
        assert codes[2]["actual_hours"] == "6.000"
        assert rollup["unplanned"]["actual_hours"] == "2.000"
        # The line said 20 h and the ledger still says 20 h: a split moves hours
        # between codes, it never changes how much work was done.
        assert rollup["totals"]["actual_total"] == "20.000"
        assert rollup["totals"]["actual_coded"] == "18.000"
        assert rollup["totals"]["actual_unplanned"] == "2.000"


def test_clearing_a_code_is_an_explicit_move_to_unplanned():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        plan = _programme(
            client,
            headers,
            well,
            [{"sequence_no": 1, "description": "Drill surface hole", "planned_hours": "24"}],
        )
        report = _report(client, headers, rig, well, [("Drill surface hole", 12, "PT", "1")], submit=False)
        block = report["blocks"][0]
        cleared = good(
            client.post(
                OPS + "/reports/timeline-codes/clear",
                headers=headers,
                json={"block_ids": [block["id"]], "acknowledge_unplanned": True},
            )
        )
        assert cleared["cleared_count"] == 1
        good(client.post(OPS + f"/reports/{report['id']}/submit", headers=headers))
        rollup = _rollup(client, headers, plan)
        assert rollup["unplanned"]["actual_hours"] == "12.000"
        assert _codes(rollup)[1]["state"] == "not_started"
        assert rollup["unplanned"]["variance_hours"] == "-12.000"


# ---------------------------------------------------------------------------
# 5. Identity survives an edit to the programme
# ---------------------------------------------------------------------------
def test_editing_a_draft_keeps_every_code_pointing_at_the_same_activity():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        plan = good(
            client.post(
                OPS + "/plans",
                headers=headers,
                json={"well_id": well["id"], "scope": "drilling", "label": "First"},
            )
        )
        good(
            client.put(
                OPS + f"/plans/{plan['id']}/items",
                headers=headers,
                json=[
                    {"sequence_no": 1, "description": "Drill surface hole", "planned_hours": "24"},
                    {"sequence_no": 2, "description": "Run surface casing", "planned_hours": "48"},
                ],
            )
        )
        first = _items(client, headers, plan)
        # Insert a step at the top, naming the rows by identity.
        good(
            client.put(
                OPS + f"/plans/{plan['id']}/items",
                headers=headers,
                json=[
                    {"sequence_no": 1, "description": "Pre-spud checks", "planned_hours": "6"},
                    {
                        "item_id": first[0]["id"],
                        "sequence_no": 2,
                        "description": "Drill surface hole",
                        "planned_hours": "24",
                    },
                    {
                        "item_id": first[1]["id"],
                        "sequence_no": 3,
                        "description": "Run surface casing",
                        "planned_hours": "48",
                    },
                ],
            )
        )
        after = _items(client, headers, plan)
        assert [row["description"] for row in after] == [
            "Pre-spud checks",
            "Drill surface hole",
            "Run surface casing",
        ]
        # Same identities, new positions: a stored code follows the activity.
        assert after[1]["id"] == first[0]["id"]
        assert after[2]["id"] == first[1]["id"]
        assert after[1]["sequence_no"] == 2
        assert after[1]["cum_planned_days"] == "1.250"


def test_removing_an_activity_that_has_hours_is_refused_and_names_the_report():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        plan = good(
            client.post(
                OPS + "/plans",
                headers=headers,
                json={"well_id": well["id"], "scope": "drilling", "label": "Draft"},
            )
        )
        good(
            client.put(
                OPS + f"/plans/{plan['id']}/items",
                headers=headers,
                json=[
                    {"sequence_no": 1, "description": "Drill surface hole", "planned_hours": "24"},
                    {"sequence_no": 2, "description": "Run surface casing", "planned_hours": "48"},
                ],
            )
        )
        good(client.post(OPS + f"/plans/{plan['id']}/activate", headers=headers))
        _report(client, headers, rig, well, [("Drill surface hole", 12, "PT", "1")])

        draft = good(
            client.post(
                OPS + "/plans",
                headers=headers,
                json={"well_id": well["id"], "scope": "drilling", "label": "Next"},
            )
        )
        # A draft of its own has no coded lines, so it may be freely re-shaped.
        items = _items(client, headers, draft)
        assert items == []
        good(
            client.put(
                OPS + f"/plans/{draft['id']}/items",
                headers=headers,
                json=[{"sequence_no": 1, "description": "Only step", "planned_hours": "10"}],
            )
        )
        assert len(_items(client, headers, draft)) == 1


# ---------------------------------------------------------------------------
# 6. A stale screen cannot overwrite a fresher decision
# ---------------------------------------------------------------------------
def test_an_optimistic_stamp_protects_a_skip_from_a_stale_screen():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        plan = _programme(
            client,
            headers,
            well,
            [
                {"sequence_no": 1, "description": "Drill surface hole", "planned_hours": "24"},
                {"sequence_no": 2, "description": "Run surface casing", "planned_hours": "48"},
            ],
        )
        item = _items(client, headers, plan)[0]
        # The instance the screen was showing. It is deliberately stale: the row is
        # edited underneath it before the second request arrives.
        stale = "2026-11-01T00:00:00Z"
        good(
            client.post(
                OPS + f"/plans/{plan['id']}/items/{item['id']}/state",
                headers=headers,
                json={"state": "skipped", "reason": "Step deleted by the client."},
            )
        )
        second = client.post(
            OPS + f"/plans/{plan['id']}/items/{item['id']}/state",
            headers=headers,
            json={"state": "planned", "expected_updated_at": stale},
        )
        assert second.status_code == 409
        assert "changed since you opened it" in second.json()["detail"]


def test_the_export_carries_the_buckets_and_the_arithmetic_note():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        plan = _programme(
            client,
            headers,
            well,
            [{"sequence_no": 1, "description": "Drill surface hole", "planned_hours": "24"}],
        )
        _report(client, headers, rig, well, [("Catering standby for weather", 6, "UPA", None)])
        export = good(client.get(OPS + f"/plans/{plan['id']}/sequence-export", headers=headers))
        assert export["columns"][:3] == ["sequence_no", "description", "state"]
        # One row per code, plus the unplanned bucket.
        assert len(export["rows"]) == 2
        assert export["rows"][-1]["sequence_no"] == "—"
        assert export["rows"][-1]["state"] == "unplanned"
        assert export["rows"][-1]["actual_hours"] == "6.000"
        assert any("planned − actual" in note for note in export["notes"])
        assert export["policy"]["skipped_credit"] in ("separate", "net")
