"""Plan vs timeline: the engineer compares hours, corrects the actual, and it sticks.

The organisation's own "Input-lookahead" sheet compares the same job's planned
hours with the hours it actually took (variance = planned − actual, positive =
lead). These checks pin that behaviour down: the system proposes the comparison,
an engineer corrects an actual that the log got wrong, the variance recomputes
from the corrected value, the correction survives a later re-suggest, and a
reviewed day is never quietly overwritten.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from test_rig_well import create_rig, create_well, fresh_database, login  # noqa: F401 - autouse fixture

# The shared fixture must configure its disposable database before app.core.database is imported.
# isort: split

from app.core.database import SessionLocal
from app.main import app
from app.models.rig_well import Well
from fastapi.testclient import TestClient

OPS = "/api/v1/operations"


def good(response):
    assert response.is_success, response.text[:3000]
    return response.json() if response.content else None


def _well(client, headers, code="WELL-HOURS"):
    rig = create_rig(client, headers, code="RIG-H")
    well = create_well(client, headers, rig["id"], code=code)
    with SessionLocal() as db:
        db.get(Well, well["id"]).config_status = "configured"
        db.commit()
    return rig, well


def _programme(client, headers, rig, well):
    """Two activities with clearly different planned hours."""
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
    rows = [
        {
            "sequence_no": 1,
            "description": 'Drill 12-1/4" directional hole to section TD',
            "planned_hours": "12",
            "target_depth_m": "2800",
        },
        {
            "sequence_no": 2,
            "description": "Perform a wiper trip to shoe",
            "planned_hours": "6",
            "target_depth_m": None,
        },
    ]
    good(client.put(OPS + f"/plans/{plan['id']}/items", headers=headers, json=rows))
    good(client.post(OPS + f"/plans/{plan['id']}/activate", headers=headers))
    return plan


def _criteria(client, headers):
    """The Master Data the review needs so a block can be accepted, not just drafted."""
    section = good(
        client.post("/api/v1/master-data/hole-sections", headers=headers, json={"code": "H12", "name": '12-1/4" hole'})
    )
    phase = good(client.post("/api/v1/master-data/phases", headers=headers, json={"code": "DRL", "name": "Drilling"}))
    activity = good(
        client.post("/api/v1/master-data/activities", headers=headers, json={"code": "ROT", "name": "Rotating"})
    )
    return {"hole_section_id": section["id"], "phase_id": phase["id"], "activity_id": activity["id"]}


def _report_with_blocks(client, headers, rig, well, blocks):
    criteria = _criteria(client, headers)
    report = good(
        client.post(
            OPS + "/reports",
            headers=headers,
            json={"well_id": well["id"], "rig_id": rig["id"], "report_date": "2026-11-16"},
        )
    )
    start = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)
    payload = []
    cursor = start
    for narrative, hours in blocks:
        end = cursor + timedelta(hours=hours)
        payload.append(
            {
                "sequence_no": len(payload) + 1,
                "started_at": cursor.isoformat(),
                "ended_at": end.isoformat(),
                "duration_minutes": int(hours * 60),
                "narrative": narrative,
                "review_state": "accepted",
                **criteria,
            }
        )
        cursor = end
    body = good(
        client.put(
            OPS + f"/reports/{report['id']}",
            headers=headers,
            json={"report": {}, "blocks": payload},
        )
    )
    return body


def test_the_system_compares_the_matched_activity_in_hours_not_calendar_days():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        _programme(client, headers, rig, well)
        report = _report_with_blocks(
            client,
            headers,
            rig,
            well,
            [('Drill 12-1/4" directional hole to section TD', 15), ("Perform a wiper trip to shoe", 4)],
        )
        first, second = report["blocks"]
        # 'Drill … to section TD' planned 12 h, logged 15 h → 3 h over plan = a lag.
        assert first["timeline_plan_step_no"] == 1
        assert first["timeline_planned_hours"] == "12.000"
        assert first["timeline_actual_hours"] == "15.000"
        assert first["timeline_variance_hours"] == "-3.000"
        assert first["timeline_comparison"] == "behind"
        # The wiper trip planned 6 h and took 4 h → 2 h early = a lead.
        assert second["timeline_plan_step_no"] == 2
        assert second["timeline_variance_hours"] == "2.000"
        assert second["timeline_comparison"] == "ahead"
        # The block's own logged duration is preserved as the system's figure.
        assert second["timeline_system_actual_hours"] == "4.000"
        assert second["timeline_actual_edited"] is False


def test_an_engineer_correction_recomputes_the_variance_and_survives_a_resuggest():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        _programme(client, headers, rig, well)
        report = _report_with_blocks(
            client, headers, rig, well, [('Drill 12-1/4" directional hole to section TD', 15)]
        )
        block = report["blocks"][0]
        review = good(
            client.post(
                OPS + f"/reports/{report['id']}/timeline-review",
                headers=headers,
                json={
                    "review_state": "edited",
                    "note": "Two hours were rig repair, logged against the wrong activity.",
                    "hours": [{"block_id": block["id"], "actual_hours": "13"}],
                },
            )
        )
        assert review["corrected_blocks"] == 1
        assert review["variance_hours"] == "-1.000"
        refreshed = good(client.get(OPS + f"/reports/{report['id']}", headers=headers))["blocks"][0]
        assert refreshed["timeline_actual_hours"] == "13.000"
        assert refreshed["timeline_variance_hours"] == "-1.000"
        assert refreshed["timeline_comparison"] == "behind"
        assert refreshed["timeline_review_state"] == "edited"
        assert refreshed["timeline_actual_edited"] is True
        assert refreshed["timeline_edited_by"]

        # A later save re-runs the suggestion. The corrected hours are the record,
        # so the plan/variance must not snap back to the raw logged duration.
        keep = [
            {
                "block_id": refreshed["id"],
                "hole_section_id": refreshed["hole_section_id"],
                "phase_id": refreshed["phase_id"],
                "activity_id": refreshed["activity_id"],
                "sequence_no": 1,
                "started_at": refreshed["started_at"],
                "ended_at": refreshed["ended_at"],
                "duration_minutes": 900,
                "narrative": refreshed["narrative"],
                "review_state": "accepted",
            }
        ]
        after = good(
            client.put(
                OPS + f"/reports/{report['id']}",
                headers=headers,
                json={"report": {}, "blocks": keep},
            )
        )
        assert after["blocks"][0]["timeline_actual_hours"] == "13.000"
        assert after["blocks"][0]["timeline_variance_hours"] == "-1.000"
        assert after["blocks"][0]["timeline_review_state"] == "edited"


def test_accepting_and_clearing_a_correction_restores_the_logged_duration():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        _programme(client, headers, rig, well)
        report = _report_with_blocks(client, headers, rig, well, [("Perform a wiper trip to shoe", 4)])
        block = report["blocks"][0]
        good(
            client.post(
                OPS + f"/reports/{report['id']}/timeline-review",
                headers=headers,
                json={"review_state": "edited", "note": "x", "hours": [{"block_id": block["id"], "actual_hours": "5"}]},
            )
        )
        assert good(client.get(OPS + f"/reports/{report['id']}", headers=headers))["blocks"][0][
            "timeline_variance_hours"
        ] == "1.000"
        cleared = good(
            client.post(
                OPS + f"/reports/{report['id']}/timeline-review",
                headers=headers,
                json={
                    "review_state": "accepted",
                    "hours": [{"block_id": block["id"], "actual_hours": None}],
                },
            )
        )
        assert cleared["review_state"] == "accepted"
        restored = good(client.get(OPS + f"/reports/{report['id']}", headers=headers))["blocks"][0]
        assert restored["timeline_actual_hours"] == "4.000"
        assert restored["timeline_actual_edited"] is False
        assert restored["timeline_variance_hours"] == "2.000"


def test_a_correction_for_a_block_outside_the_report_is_refused_not_dropped():
    """A stale screen must not look like a saved correction.

    If the hours name a block the report no longer holds, applying the rest and
    answering 200 would leave the engineer believing a figure was stored.
    """
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        _programme(client, headers, rig, well)
        report = _report_with_blocks(client, headers, rig, well, [("Perform a wiper trip to shoe", 4)])
        response = client.post(
            OPS + f"/reports/{report['id']}/timeline-review",
            headers=headers,
            json={
                "review_state": "edited",
                "note": "Typed on a screen that has since reloaded.",
                "hours": [
                    {"block_id": "00000000-0000-0000-0000-000000000000", "actual_hours": "5"},
                ],
            },
        )
        assert response.status_code == 422, response.text
        assert "no longer in this report" in response.json()["detail"]


def test_rejecting_removes_the_comparison_instead_of_zeroing_it():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        _programme(client, headers, rig, well)
        report = _report_with_blocks(client, headers, rig, well, [("Perform a wiper trip to shoe", 4)])
        good(
            client.post(
                OPS + f"/reports/{report['id']}/timeline-review",
                headers=headers,
                json={"review_state": "rejected", "note": "Programme row was superseded yesterday."},
            )
        )
        block = good(client.get(OPS + f"/reports/{report['id']}", headers=headers))["blocks"][0]
        assert block["timeline_review_state"] == "rejected"
        assert block["timeline_comparison"] == "on"
        assert block["timeline_variance_hours"] is None


def test_an_unmatched_block_reports_no_comparison_rather_than_a_wrong_activity():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        _programme(client, headers, rig, well)
        report = _report_with_blocks(
            client, headers, rig, well, [("Catering standby for weather", 3)]
        )
        block = report["blocks"][0]
        assert block["timeline_planned_hours"] is None
        assert block["timeline_variance_hours"] is None
        assert block["timeline_comparison"] == "on"
        assert block["timeline_basis"] == "no matching programme activity"


def test_a_report_without_an_active_programme_says_so():
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        report = _report_with_blocks(client, headers, rig, well, [("Perform a wiper trip to shoe", 4)])
        assert report["blocks"][0]["timeline_basis"] == "no active programme"
        assert report["blocks"][0]["timeline_variance_hours"] is None


# ---------------------------------------------------------------------------
# Code Library import follows the create form, including the sub-phase phase
# ---------------------------------------------------------------------------
def test_sub_phase_import_accepts_the_phase_column_the_page_shows():
    with TestClient(app) as client:
        headers = login(client)
        phase = good(
            client.post(
                "/api/v1/master-data/phases", headers=headers, json={"code": "DRLPRO", "name": "Drilling programme"}
            )
        )
        template = good(client.get(OPS + "/masters/sub-phases/import-template", headers=headers))
        assert template["required"] == ["sub_phase_code", "sub_phase_name", "phase_code"]
        assert "phase_code" in template["columns"]
        imported = good(
            client.post(
                OPS + "/masters/sub-phases/import",
                headers=headers,
                json=[
                    {
                        "sub_phase_code": "SP1",
                        "sub_phase_name": "Drill surface hole",
                        "Phase": "DRLPRO",
                        "Description": "Imported with its phase.",
                        "Active": "yes",
                    }
                ],
            )
        )
        assert imported["errors"] == [], imported["errors"]
        rows = good(client.get(OPS + "/masters/sub-phases", headers=headers))
        assert rows[0]["phase_id"] == phase["id"]
        assert rows[0]["phase_code_snapshot"] == "DRLPRO"
        assert rows[0]["is_active"] is True


def test_sub_phase_import_names_the_available_phases_when_one_is_unknown():
    with TestClient(app) as client:
        headers = login(client)
        good(
            client.post(
                "/api/v1/master-data/phases", headers=headers, json={"code": "DRLPRO", "name": "Drilling programme"}
            )
        )
        result = good(
            client.post(
                OPS + "/masters/sub-phases/import",
                headers=headers,
                json=[{"sub_phase_code": "SP9", "sub_phase_name": "Orphan", "phase_code": "NOPE"}],
            )
        )
        assert result["created_count"] == 0
        assert "DRLPRO" in result["errors"][0]


def test_operation_import_accepts_every_published_column_and_reads_booleans():
    with TestClient(app) as client:
        headers = login(client)
        template = good(client.get(OPS + "/masters/operations/import-template", headers=headers))
        assert template["required"] == ["operation_code", "operation_name"]
        assert "is_contractor_caused" in template["optional"]
        imported = good(
            client.post(
                OPS + "/masters/operations/import",
                headers=headers,
                json=[
                    {
                        "operation_code": "TP99",
                        "operation_name": "Stuck pipe — mechanically stuck",
                        "Family": "trouble",
                        "Category": "downhole",
                        "Responsible party": "Drilling contractor",
                        "Chargeable": "no",
                        "Company caused": "yes",
                        "Contractor caused": "no",
                        "Description": "Mechanical sticking after a long static period.",
                        "Active": "yes",
                    }
                ],
            )
        )
        assert imported["errors"] == [], imported["errors"]
        row = good(client.get(OPS + "/masters/operations", headers=headers))[0]
        assert row["operation_code"] == "TP99"
        assert row["family"] == "trouble"
        assert row["category"] == "downhole"
        assert row["is_company_caused"] is True
        assert row["is_contractor_caused"] is False
        assert row["is_chargeable"] is False
        assert row["default_responsible_party"] == "Drilling contractor"


def test_a_blank_optional_cell_keeps_the_default_and_a_bad_boolean_is_reported():
    with TestClient(app) as client:
        headers = login(client)
        imported = good(
            client.post(
                OPS + "/masters/causes/import",
                headers=headers,
                json=[
                    {"cause_code": "C1", "cause_name": "Weather", "description": ""},
                    {"cause_code": "C2", "cause_name": "Equipment", "active": "perhaps"},
                ],
            )
        )
        assert imported["created_count"] == 1
        assert "Row 3" in imported["errors"][0] and "yes or no" in imported["errors"][0]
        row = good(client.get(OPS + "/masters/causes", headers=headers))[0]
        assert row["description"] == ""
        assert row["is_active"] is True


def test_an_engineer_can_state_the_comparison_when_the_hours_say_otherwise():
    """A stated mark is a judgement the hours cannot overrule, and it persists.

    The rig can move late while the printed programme days still look healthy.
    The engineer's "behind" must survive the save and stay visible beside the
    computed variance, so a reader sees both the figure and the call.
    """
    with TestClient(app) as client:
        headers = login(client)
        rig, well = _well(client, headers)
        _programme(client, headers, rig, well)
        report = _report_with_blocks(client, headers, rig, well, [("Perform a wiper trip to shoe", 4)])
        block = report["blocks"][0]
        edited = client.post(
            OPS + f"/reports/{report['id']}/timeline-review",
            headers=headers,
            json={
                "review_state": "edited",
                "comparison": "behind",
                "note": "Rig moved late; the printed hours understate the delay.",
                "block_ids": [block["id"]],
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["comparison"] == "behind"
        saved = good(client.get(OPS + f"/reports/{report['id']}", headers=headers))["blocks"][0]
        assert saved["timeline_comparison"] == "behind"
        assert "Rig moved late" in saved["timeline_note"]
        # The figure is still reported honestly beside the stated mark.
        assert saved["timeline_variance_hours"] == "2.000"
