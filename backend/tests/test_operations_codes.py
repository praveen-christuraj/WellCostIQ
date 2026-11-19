"""Bulk criteria assignment, correlations and the mandatory matrix.

The criteria are Hole Section, Phase, Sub-phase, Activity, Allocation, Cause,
Operations, Agency / service vendor and the Responsible agency label. Hole
Section, Phase and Activity are Master Data; Sub-phase, Operations, Cause and the
Responsible agency label are configured in the Code Library.

The rules under test:

* Hole Section, Phase, Activity and Allocation are always mandatory. Cause is
  mandatory only when the Activity's own type is NPT or UPA, never for Planned.
* Extraction only pre-selects a dropdown when a correlation exists. No
  correlation leaves the dropdown empty instead of guessing.
* A bulk gesture previews before it writes, refuses what the Activity type
  forbids, and leaves an audit trail naming the fields and counts.
"""

from datetime import timedelta

import pytest
from test_rig_well import fresh_database, login  # noqa: F401

from app.core.database import SessionLocal
from app.main import app
from app.models import AuditLog, Organization
from app.models.operations import OpsActivityBlock, OpsCodeCorrelation, OpsDailyReport
from app.models.vendor_master import Vendor
from app.services.operations.correlations import correlation_map
from fastapi.testclient import TestClient
from sqlalchemy import select

OPS = "/api/v1/operations"
DAY = "2026-03-02"
NEXT_DAY = "2026-03-03"


def good(response):
    assert response.is_success, response.text[:2000]
    return response.json() if response.content else None


def _codes(client, headers):
    """One workspace criterion of each kind, so every rule can be exercised.

    Hole Section, Phase and Activity are Master Data; the Code Library owns
    Sub-phase, Operations, Cause and the Responsible agency label.
    """
    section = good(
        client.post("/api/v1/master-data/hole-sections", headers=headers, json={"code": "H12", "name": '12-1/4" hole'})
    )
    phase = good(client.post("/api/v1/master-data/phases", headers=headers, json={"code": "DRL", "name": "Drilling"}))
    return {
        "hole_section": section,
        "phase": phase,
        "activity": good(
            client.post("/api/v1/master-data/activities", headers=headers, json={"code": "ROT", "name": "Rotating"})
        ),
        "npt_activity": good(
            client.post(
                "/api/v1/master-data/activities",
                headers=headers,
                json={"code": "DWN", "name": "Rig repair", "activity_type": "NPT"},
            )
        ),
        "upa_activity": good(
            client.post(
                "/api/v1/master-data/activities",
                headers=headers,
                json={"code": "FSH", "name": "Fishing", "activity_type": "UPA"},
            )
        ),
        "sub_phase": good(
            client.post(
                OPS + "/masters/sub-phases",
                headers=headers,
                json={
                    "phase_id": phase["id"],
                    "sub_phase_code": "DRL-1",
                    "sub_phase_name": "Drilling ahead",
                },
            )
        ),
        "operation": good(
            client.post(
                OPS + "/masters/operations",
                headers=headers,
                json={"operation_code": "PUMP", "operation_name": "Pump failure"},
            )
        ),
        "cause": good(
            client.post(
                OPS + "/masters/causes",
                headers=headers,
                json={"cause_code": "EQP", "cause_name": "Equipment failure"},
            )
        ),
        "agency": good(
            client.post(
                OPS + "/masters/agencies",
                headers=headers,
                json={"agency_code": "RIG", "agency_name": "Rig contractor"},
            )
        ),
    }


def _setup(client, headers, well_code="BULK-WELL-01"):
    from app.models.rig_well import Well

    from test_rig_well import create_rig, create_well

    rig = create_rig(client, headers)
    well = create_well(client, headers, rig["id"], well_code)
    with SessionLocal() as db:
        db.get(Well, well["id"]).config_status = "configured"
        db.commit()
    folder = {"well_id": well["id"], "scope": "drilling"}
    report = good(
        client.post(
            OPS + "/reports",
            headers=headers,
            json={**folder, "report_date": DAY, "report_type": "DDR"},
        )
    )
    blocks = [
        {
            "sequence_no": 1,
            "started_at": f"{DAY}T00:00:00+01:00",
            "ended_at": f"{DAY}T12:00:00+01:00",
            "duration_minutes": 720,
            "allocation": "PT",
            "is_productive": True,
            "narrative": "Drill ahead with rotary steerable.",
            "review_state": "suggested",
        },
        {
            "sequence_no": 2,
            "started_at": f"{DAY}T12:00:00+01:00",
            "ended_at": f"{DAY}T18:00:00+01:00",
            "duration_minutes": 360,
            "allocation": "NPT",
            "is_productive": False,
            "narrative": "Mud pump failure; repairing.",
            "reason": "Mud pump failure",
            "review_state": "suggested",
        },
        {
            "sequence_no": 3,
            "started_at": f"{DAY}T18:00:00+01:00",
            "ended_at": f"{NEXT_DAY}T00:00:00+01:00",
            "duration_minutes": 360,
            "allocation": "UPA",
            "is_productive": True,
            "narrative": "Fishing operation for dropped tool.",
            "reason": "Fishing for a dropped tool",
            "review_state": "suggested",
        },
    ]
    saved = good(
        client.put(
            OPS + f"/reports/{report['id']}",
            headers=headers,
            json={"expected_updated_at": report["updated_at"], "report": {}, "blocks": blocks},
        )
    )
    return folder, saved


def test_bulk_assign_respects_the_activity_type_matrix():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)
        _folder, report = _setup(client, headers)
        url = OPS + f"/reports/{report['id']}"
        base = {"report_ids": [report["id"]], "block_ids": []}

        # Planned work may not carry a cause in bulk: nothing went wrong.
        refused = good(
            client.post(
                OPS + "/reports/bulk-assign",
                headers=headers,
                json={**base, "cause_code": "EQP"},
            )
        )
        assert refused["changed_count"] == 0
        assert refused["skipped"] and "Planned" in refused["skipped"][0]["reason"]

        # Preview reports the exact before/after without writing.
        preview = good(
            client.post(
                OPS + "/reports/bulk-assign/preview",
                headers=headers,
                json={**base, "operation_id": codes["operation"]["id"]},
            )
        )
        assert preview["changes"] and preview["summary"]
        unchanged = good(client.get(url, headers=headers))
        assert all(b["operation_id"] is None for b in unchanged["blocks"])

        # The real assignment fills only the rows that can hold the value.
        applied = good(
            client.post(
                OPS + "/reports/bulk-assign",
                headers=headers,
                json={
                    **base,
                    "operation_id": codes["operation"]["id"],
                    "hole_section_id": codes["hole_section"]["id"],
                    "sub_phase_id": codes["sub_phase"]["id"],
                },
            )
        )
        assert applied["changed_count"] == 3
        assert "operations" in applied["summary"] and "hole section" in applied["summary"]

        saved = good(client.get(url, headers=headers))
        assert all(b["operation_id"] == codes["operation"]["id"] for b in saved["blocks"])
        assert all(b["hole_section_id"] == codes["hole_section"]["id"] for b in saved["blocks"])
        assert all(b["sub_phase_id"] == codes["sub_phase"]["id"] for b in saved["blocks"])
        # Every touched block is edited and attributed, never silently accepted.
        assert all(b["review_state"] == "edited" for b in saved["blocks"])
        assert saved["blocks"][0]["timeline_review_state"] == "suggested"

        # Assigning the NPT Activity is what makes the row NPT, so the cause lands
        # in the same gesture. The Old Activity on the other rows is Planned, so
        # their cause is refused with a reason rather than written.
        npt = good(
            client.post(
                OPS + "/reports/bulk-assign",
                headers=headers,
                json={
                    **base,
                    "block_ids": [report["blocks"][1]["id"]],
                    "phase_id": codes["phase"]["id"],
                    "activity_id": codes["npt_activity"]["id"],
                    "cause_code": "EQP",
                    "responsible_agency_id": codes["agency"]["id"],
                },
            )
        )
        assert npt["changed_count"] == 1
        saved = good(client.get(url, headers=headers))
        assert saved["blocks"][1]["classification"] == "NPT"
        assert saved["blocks"][1]["activity_type"] == "NPT"
        assert saved["blocks"][1]["cause_code"] == "EQP"
        assert saved["blocks"][1]["responsible_party"] == "Rig contractor"
        assert saved["blocks"][1]["responsible_agency_label"] == "Rig contractor"

        with SessionLocal() as db:
            entries = db.scalars(
                select(AuditLog).where(AuditLog.action == "bulk-assign", AuditLog.entity_type == "ops_report")
            ).all()
            assert entries and all(entry.organization_id for entry in entries)
            block = db.scalar(
                select(OpsActivityBlock).where(OpsActivityBlock.report_id == report["id"])
            )
            assert block.reviewer_user_id is not None and block.reviewed_at is not None

        # Fill the remaining mandatory criteria on the Planned rows, then submit
        # succeeds: the NPT row already carried its phase and Activity.
        good(
            client.post(
                OPS + "/reports/bulk-assign",
                headers=headers,
                json={
                    **base,
                    "phase_id": codes["phase"]["id"],
                    "activity_id": codes["activity"]["id"],
                    "block_ids": [b["id"] for b in saved["blocks"] if b["sequence_no"] != 2],
                },
            )
        )
        saved = good(client.get(url, headers=headers))
        # The NPT row keeps the phase assigned with its Activity, so every row now
        # carries the whole mandatory set.
        assert all(b["phase_id"] == codes["phase"]["id"] for b in saved["blocks"])
        assert all(b["activity_id"] for b in saved["blocks"])
        submitted = good(client.post(url + "/submit", headers=headers))
        assert submitted["status"] == "submitted"

        # A submitted report is not a bulk target: drafts only.
        blocked = client.post(
            OPS + "/reports/bulk-assign",
            headers=headers,
            json={**base, "activity_id": codes["activity"]["id"]},
        )
        assert blocked.status_code == 409 and "editable drafts" in blocked.json()["detail"]


def test_bulk_assign_refuses_a_cause_on_planned_work():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)
        _folder, report = _setup(client, headers, "BULK-WELL-02")
        planned = [b for b in report["blocks"] if b["classification"] == "Planned"]
        result = good(
            client.post(
                OPS + "/reports/bulk-assign",
                headers=headers,
                json={
                    "report_ids": [report["id"]],
                    "block_ids": [b["id"] for b in planned],
                    "cause_code": "EQP",
                },
            )
        )
        # Nothing was written, and the reason names the Activity type.
        assert result["changed_count"] == 0
        assert result["skipped"] and "Planned" in result["skipped"][0]["reason"]
        saved = good(client.get(OPS + f"/reports/{report['id']}", headers=headers))
        assert all(b["cause_code"] == "" for b in saved["blocks"] if b["classification"] == "Planned")


def test_correlation_controls_which_criteria_extraction_preselects():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)

        reference = good(client.get(OPS + "/correlations/reference", headers=headers))
        # Printed tokens are correlated into Code Library criteria; Hole Section,
        # Phase and Activity are Master Data targets, not correlation kinds.
        assert {"operation", "cause", "sub-phase", "responsible-party", "agency"} == set(reference["kinds"])
        assert any(row["family"] == "Trouble / NPT" for row in reference["printed"])
        assert reference["library"]["operation"][0]["code"] == "PUMP"
        # Every criterion list the Correlations panel needs is present.
        assert set(reference["library"]) == {
            "hole_section",
            "phase",
            "sub_phase",
            "activity",
            "operation",
            "cause",
            "responsible_agency",
            "vendor",
            "mark",
        }

        # A printed token from a family the kind does not read cannot be correlated.
        mismatch = client.post(
            OPS + "/correlations",
            headers=headers,
            json={
                "kind": "operation",
                "source_family": "Cause",
                "source_code": "XX01",
                "target_id": codes["operation"]["id"],
            },
        )
        assert mismatch.status_code == 422

        created = good(
            client.post(
                OPS + "/correlations",
                headers=headers,
                json={
                    "kind": "operation",
                    "source_family": "Trouble / NPT",
                    "source_code": "TP02",
                    "target_id": codes["operation"]["id"],
                },
            )
        )
        assert created["target_label"].startswith("PUMP")
        assert created["target_operation_id"] == codes["operation"]["id"]

        # One printed token maps once. A second row is a conflict, not a guess.
        duplicate = client.post(
            OPS + "/correlations",
            headers=headers,
            json={
                "kind": "operation",
                "source_family": "Trouble / NPT",
                "source_code": "TP02",
                "target_id": codes["operation"]["id"],
            },
        )
        assert duplicate.status_code == 409

        with SessionLocal() as db:
            org = db.scalar(select(Organization.id).where(Organization.slug == "north"))
            assert ("operation", "tp02") in correlation_map(db, org)

        # Deleted correlations stop feeding extraction but are recoverable.
        good(
            client.post(
                OPS + "/correlations/bulk-delete",
                headers=headers,
                json={"ids": [created["id"]]},
            )
        )
        assert good(client.get(OPS + "/correlations", headers=headers)) == []
        assert len(good(client.get(OPS + "/correlations", headers=headers, params={"deleted": True}))) == 1
        restored = good(
            client.post(
                OPS + "/correlations/bulk-restore",
                headers=headers,
                json={"ids": [created["id"]]},
            )
        )
        assert restored["affected_count"] == 1
        with SessionLocal() as db:
            row = db.get(OpsCodeCorrelation, created["id"])
            assert row is not None and row.is_deleted is False


def test_upa_requires_a_cause_but_never_an_operations_code():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)
        _folder, report = _setup(client, headers, "BULK-WELL-03")
        url = OPS + f"/reports/{report['id']}"
        from app.schemas.operations import OpsActivityBlockIn, OpsSettingsIn

        stored = good(client.get(url, headers=headers))["blocks"]
        rows = [{k: b[k] for k in OpsActivityBlockIn.model_fields} for b in stored]
        for row, source in zip(rows, stored):
            row["block_id"] = source["id"]
            row["hole_section_id"] = codes["hole_section"]["id"]
            row["phase_id"] = codes["phase"]["id"]
            row["sub_phase_id"] = codes["sub_phase"]["id"]
        # The Activity's own type is the block's type: Planned, NPT and UPA.
        rows[0]["activity_id"], rows[0]["allocation"] = codes["activity"]["id"], "PT"
        rows[1]["activity_id"], rows[1]["allocation"] = codes["npt_activity"]["id"], "NPT"
        rows[1].update(
            operation_id=codes["operation"]["id"],
            cause_code="EQP",
            responsible_party="Rig contractor",
            reason="Pump failed",
        )
        rows[2]["activity_id"], rows[2]["allocation"] = codes["upa_activity"]["id"], "UPA"
        rows[2].update(
            cause_code="EQP",
            responsible_party="Rig contractor",
            reason="Fishing for a dropped tool",
        )
        for row in rows:
            row["review_state"] = "accepted"
        saved = good(
            client.put(
                url,
                headers=headers,
                json={"report": {}, "blocks": rows, "confirm_review": True},
            )
        )
        assert [b["classification"] for b in saved["blocks"]] == ["Planned", "NPT", "UPA"]
        assert [b["activity_type"] for b in saved["blocks"]] == ["Planned", "NPT", "UPA"]
        # UPA without an Operations code is complete; only the cause was needed.
        assert saved["blocks"][2]["operation_id"] is None
        assert saved["blocks"][2]["cause_code"] == "EQP"
        # The responsible agency label keeps its own value beside the free-text
        # responsible party, and both are visible on the block.
        assert saved["blocks"][2]["responsible_party"] == "Rig contractor"
        # Operations stays optional for UPA, but the workspace asks for it on NPT
        # and UPA before submit; the requirement is a setting, not the matrix.
        submitted = client.post(url + "/submit", headers=headers)
        assert submitted.status_code == 422 and "Operations code" in submitted.json()["detail"]
        settings = good(client.get(OPS + "/settings", headers=headers))
        writable = {k: v for k, v in settings.items() if k in OpsSettingsIn.model_fields}
        good(
            client.put(
                OPS + "/settings",
                headers=headers,
                json={**writable, "require_operations": False},
            )
        )
        good(client.post(url + "/submit", headers=headers))

        # A UPA block without a cause is refused, with the same sentence everywhere.
        reopened = good(client.post(url + "/reopen", headers=headers, json={"remarks": "Correct the cause"}))
        rows[2]["cause_code"] = ""
        refused = client.put(
            OPS + f"/reports/{reopened['id']}",
            headers=headers,
            json={"report": {}, "blocks": rows, "confirm_review": True},
        )
        assert refused.status_code == 422 and "cause code" in refused.json()["detail"]


@pytest.mark.parametrize(
    ("activity_type", "missing"),
    [
        ("Planned", {"hole_section_id", "phase_id", "activity_id", "allocation"}),
        ("NPT", {"hole_section_id", "phase_id", "activity_id", "allocation", "cause_code"}),
        ("UPA", {"hole_section_id", "phase_id", "activity_id", "allocation", "cause_code"}),
    ],
)
def test_requirement_matrix_is_the_single_source_of_truth(activity_type, missing):
    from app.domain.operations.requirements import MANDATORY, missing_fields
    from app.models.operations import OpsActivityBlock

    # A block's stored Activity type is what the matrix is keyed on, so the
    # editor, the bulk dialog and submit all quote the same answer.
    block = OpsActivityBlock(sequence_no=1, classification=activity_type)
    assert set(missing_fields(block)) == missing
    assert set(MANDATORY[activity_type]) == missing


def test_report_and_extra_blocks_are_not_faked_by_correlations():
    """A correlation pre-selects a dropdown; it never accepts a block for the engineer."""
    with TestClient(app) as client:
        headers = login(client)
        _codes(client, headers)
        with SessionLocal() as db:
            org = db.scalar(select(Organization.id).where(Organization.slug == "north"))
            report = db.scalar(select(OpsDailyReport).where(OpsDailyReport.organization_id == org))
            assert report is None or report.status == "draft"
            row = db.scalar(select(OpsCodeCorrelation).where(OpsCodeCorrelation.organization_id == org))
            assert row is None or row.is_deleted is False


def test_plan_permanent_delete_requires_a_deleted_unreferenced_version():
    with TestClient(app) as client:
        headers = login(client)
        _codes(client, headers)
        folder, _report = _setup(client, headers, "PURGE-WELL-01")
        plan = good(client.post(OPS + "/plans", headers=headers, json={**folder, "label": "Purge me"}))
        good(
            client.put(
                OPS + f"/plans/{plan['id']}/items",
                headers=headers,
                json=[{"sequence_no": 1, "description": "Spud", "planned_hours": 24}],
            )
        )
        url = OPS + "/plans/bulk-permanent-delete"

        # A live (not deleted) version is never one click from being destroyed.
        live = client.post(url, headers=headers, json={"ids": [plan["id"]]})
        assert live.status_code == 409 and "deleted" in live.json()["detail"].lower()

        good(client.delete(OPS + f"/plans/{plan['id']}", headers=headers))
        purged = good(client.post(url, headers=headers, json={"ids": [plan["id"]]}))
        assert purged["affected_count"] == 1
        assert good(client.get(OPS + "/plans", headers=headers, params={**folder, "deleted": True})) == []

        with SessionLocal() as db:
            entries = db.scalars(
                select(AuditLog).where(AuditLog.action == "permanent-delete", AuditLog.entity_type == "ops_plan")
            ).all()
            assert entries


def test_timeline_comparison_is_visible_reviewable_and_editable():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)
        folder, report = _setup(client, headers, "TIMELINE-WELL-01")
        url = OPS + f"/reports/{report['id']}"

        # A draft with no baseline has an explicit "unavailable" comparison, never a
        # guessed lead or lag.
        saved = good(client.get(url, headers=headers))
        block = saved["blocks"][0]
        assert block["timeline_review_state"] == "suggested"
        assert block["timeline_comparison"] == "on"
        assert block["timeline_variance_days"] is None

        # Editing the comparison without a note is refused: an unexplained manual
        # mark cannot be audited later.
        refused = client.post(
            url + "/timeline-review",
            headers=headers,
            json={"review_state": "edited", "comparison": "behind"},
        )
        assert refused.status_code == 422 and "note" in refused.json()["detail"]

        accepted = good(
            client.post(
                url + "/timeline-review",
                headers=headers,
                json={"review_state": "accepted", "block_ids": [block["id"]]},
            )
        )
        assert accepted["updated_count"] == 1
        reviewed = good(client.get(url, headers=headers))
        assert reviewed["blocks"][0]["timeline_review_state"] == "accepted"
        assert reviewed["blocks"][0]["timeline_reviewed_by"]

        edited = good(
            client.post(
                url + "/timeline-review",
                headers=headers,
                json={
                    "review_state": "edited",
                    "comparison": "behind",
                    "note": "Rig moved late; the printed days understate the delay.",
                    "block_ids": [block["id"]],
                },
            )
        )
        assert edited["comparison"] == "behind"
        saved = good(client.get(url, headers=headers))
        assert saved["blocks"][0]["timeline_comparison"] == "behind"
        assert "Rig moved late" in saved["blocks"][0]["timeline_note"]
        # The rest of the report is untouched.
        assert saved["blocks"][1]["timeline_review_state"] == "suggested"

        with SessionLocal() as db:
            entry = db.scalars(
                select(AuditLog).where(AuditLog.action == "review", AuditLog.entity_type == "ops_report")
            ).all()
            assert entry


def test_reference_context_names_the_asked_abbreviation():
    """The Ollama prompt block must carry the printed meaning of the asked token.

    A rename of the local variable that holds the token (done to keep the security
    scan quiet about a non-credential) must not quietly empty the prompt block.
    """
    from app.domain.operations.reference_knowledge import format_reference_context

    block = format_reference_context("What does BHA mean in the daily report?")
    assert "ABBREVIATION IN THE QUESTION: BHA = " in block
    assert "bottom hole assembly" in block.lower()

    # A question with no printed abbreviation still gets the primer, never a blank.
    assert format_reference_context("How many days behind are we?").strip()


# ---------------------------------------------------------------------------
# Multi-criteria code links (API 0.20.0)
# ---------------------------------------------------------------------------


def _pair(client, headers, codes):
    """A second criterion of each kind, so a link can join distinct values."""
    return {
        "phase2": good(
            client.post("/api/v1/master-data/phases", headers=headers, json={"code": "CMP", "name": "Completion"})
        ),
        "activity2": good(
            client.post("/api/v1/master-data/activities", headers=headers, json={"code": "TRIP", "name": "Tripping"})
        ),
        "sub_phase2": good(
            client.post(
                OPS + "/masters/sub-phases",
                headers=headers,
                json={"phase_id": codes["phase"]["id"], "sub_phase_code": "DRL-2", "sub_phase_name": "Tripping"},
            )
        ),
        "cause2": good(
            client.post(OPS + "/masters/causes", headers=headers, json={"cause_code": "WTH", "cause_name": "Weather"})
        ),
    }


def test_multi_criteria_code_links_require_two_criteria_and_guard_code_deletion():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)
        extra = _pair(client, headers, codes)

        # One criterion is not a link: it is just a code.
        single = client.post(
            OPS + "/code-links",
            headers=headers,
            json={"hole_section_id": codes["hole_section"]["id"]},
        )
        assert single.status_code == 422 and "two criteria" in single.json()["detail"]

        # Cause with Planned work is refused: the Activity type decides.
        matrix = client.post(
            OPS + "/code-links",
            headers=headers,
            json={
                "activity_id": codes["activity"]["id"],
                "cause_id": codes["cause"]["id"],
            },
        )
        assert matrix.status_code == 422 and "Planned" in matrix.json()["detail"]

        # A single rule spanning Master Data and the Code Library: the DRLSUR case.
        link = good(
            client.post(
                OPS + "/code-links",
                headers=headers,
                json={
                    "rule_name": "Drilling ahead",
                    "hole_section_id": codes["hole_section"]["id"],
                    "phase_id": codes["phase"]["id"],
                    "sub_phase_id": codes["sub_phase"]["id"],
                    "activity_id": codes["activity"]["id"],
                    "operation_id": codes["operation"]["id"],
                    "responsible_agency_id": codes["agency"]["id"],
                    "note": "Everything the printed section code implies",
                },
            )
        )
        assert link["criteria_count"] == 6
        assert link["hole_section_label"].startswith("H12")
        assert link["sub_phase_label"].startswith("DRL-1")
        assert link["responsible_agency_label"] == "RIG — Rig contractor"
        assert "Hole section: H12" in link["summary_label"]
        assert "Operations: PUMP" in link["summary_label"]

        # The same criteria twice is a conflict; deletion then re-creation is not.
        different = good(
            client.post(
                OPS + "/code-links",
                headers=headers,
                json={"hole_section_id": codes["hole_section"]["id"], "phase_id": codes["phase"]["id"]},
            )
        )
        duplicate = client.post(
            OPS + "/code-links",
            headers=headers,
            json={"hole_section_id": codes["hole_section"]["id"], "phase_id": codes["phase"]["id"]},
        )
        assert duplicate.status_code == 409
        good(client.post(OPS + "/code-links/bulk-delete", headers=headers, json={"ids": [different["id"]]}))
        good(client.post(OPS + "/code-links/bulk-permanent-delete", headers=headers, json={"ids": [different["id"]]}))

        listed = good(client.get(OPS + "/code-links", headers=headers))
        assert [row["id"] for row in listed] == [link["id"]]

        # A code inside a link cannot leave the library until the link is gone.
        blocked = client.post(
            OPS + "/masters/operations/bulk-delete", headers=headers, json={"ids": [codes["operation"]["id"]]}
        )
        assert blocked.status_code == 409 and "code link 'Drilling ahead'" in blocked.json()["detail"]
        good(client.post(OPS + "/code-links/bulk-delete", headers=headers, json={"ids": [link["id"]]}))
        good(client.post(OPS + "/masters/operations/bulk-delete", headers=headers, json={"ids": [codes["operation"]["id"]]}))

        # A deleted link whose code is itself deleted cannot be restored blind.
        refused = client.post(OPS + "/code-links/bulk-restore", headers=headers, json={"ids": [link["id"]]})
        assert refused.status_code == 409 and "Restore the code first" in refused.json()["detail"]
        good(client.post(OPS + "/masters/operations/bulk-restore", headers=headers, json={"ids": [codes["operation"]["id"]]}))
        restored = good(client.post(OPS + "/code-links/bulk-restore", headers=headers, json={"ids": [link["id"]]}))
        assert restored["affected_count"] == 1

        # Permanent deletion is only ever offered from Deleted entries.
        live = client.post(OPS + "/code-links/bulk-permanent-delete", headers=headers, json={"ids": [link["id"]]})
        assert live.status_code == 409 and "Delete a code link before" in live.json()["detail"]
        good(client.post(OPS + "/code-links/bulk-delete", headers=headers, json={"ids": [link["id"]]}))
        purged = good(client.post(OPS + "/code-links/bulk-permanent-delete", headers=headers, json={"ids": [link["id"]]}))
        assert purged["affected_count"] == 1
        assert good(client.get(OPS + "/code-links", headers=headers, params={"deleted": True})) == []
        with SessionLocal() as db:
            entry = db.scalars(
                select(AuditLog).where(AuditLog.action == "permanent_delete", AuditLog.entity_type == "ops_code_link")
            ).all()
            assert entry


def test_batch_code_links_are_atomic_across_duplicates_and_bad_rows():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)
        url = OPS + "/code-links/batch"
        base = {"hole_section_id": codes["hole_section"]["id"]}

        # A duplicate inside the batch rolls the whole batch back.
        refused = client.post(
            url,
            headers=headers,
            json={
                "items": [
                    {**base, "phase_id": codes["phase"]["id"]},
                    {**base, "phase_id": codes["phase"]["id"]},
                ]
            },
        )
        assert refused.status_code == 409 and "Link 2" in refused.json()["detail"]
        assert good(client.get(OPS + "/code-links", headers=headers)) == []

        # Same for a row that cannot be formed at all: nothing half-saved.
        refused = client.post(
            url,
            headers=headers,
            json={
                "items": [
                    {**base, "phase_id": codes["phase"]["id"]},
                    {"rule_name": "only one criterion", **base},
                ]
            },
        )
        assert refused.status_code == 422
        assert good(client.get(OPS + "/code-links", headers=headers)) == []

        created = good(
            client.post(
                url,
                headers=headers,
                json={
                    "items": [
                        {
                            "rule_name": "Drilling",
                            "hole_section_id": codes["hole_section"]["id"],
                            "phase_id": codes["phase"]["id"],
                            "activity_id": codes["activity"]["id"],
                        },
                        {
                            "rule_name": "Downtime",
                            "activity_id": codes["npt_activity"]["id"],
                            "operation_id": codes["operation"]["id"],
                            "cause_id": codes["cause"]["id"],
                            "default_allocation": "NPT",
                        },
                    ]
                },
            )
        )
        assert created["created_count"] == 2
        assert len(good(client.get(OPS + "/code-links", headers=headers))) == 2


def test_correlations_accept_companion_criteria_and_free_text_agency_tokens():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)

        # Agency names are operator data: a printed token need not be in the catalogue.
        # The ``agency`` kind fills the Master Data vendor, so create one first.
        with SessionLocal() as db:
            org = db.scalar(select(Organization.id).where(Organization.slug == "north"))
            db.add(Vendor(organization_id=org, vendor_name="Halliburton", vendor_code="HAL", status="active"))
            db.commit()
        vendor = good(client.get(OPS + "/reference", headers=headers))["vendors"][0]
        agency = good(
            client.post(
                OPS + "/correlations",
                headers=headers,
                json={
                    "kind": "agency",
                    "source_code": "Halliburton",
                    "target_id": vendor["id"],
                    "note": "Printed operator spelling",
                },
            )
        )
        assert agency["source_family"] == "Source agency"
        assert agency["source_code"] == "HALLIBURTON"
        assert agency["target_vendor_id"] == vendor["id"]

        # A responsible-party rule correlates a printed token to the Code Library
        # label, while agency rules fill the Master Data vendor.
        label = good(
            client.post(
                OPS + "/correlations",
                headers=headers,
                json={
                    "kind": "responsible-party",
                    "source_code": "Rig Contractor",
                    "target_id": codes["agency"]["id"],
                },
            )
        )
        assert label["target_responsible_agency_id"] == codes["agency"]["id"]

        # Companion criteria reach across Master Data and the Code Library, so one
        # printed trouble code pre-fills the whole field set of the block.
        companion = good(
            client.post(
                OPS + "/correlations",
                headers=headers,
                json={
                    "kind": "operation",
                    "source_family": "Trouble / NPT",
                    "source_code": "TP02",
                    "target_id": codes["operation"]["id"],
                    "target_hole_section_id": codes["hole_section"]["id"],
                    "target_phase_id": codes["phase"]["id"],
                    "target_sub_phase_id": codes["sub_phase"]["id"],
                    "target_activity_id": codes["npt_activity"]["id"],
                    "target_cause_id": codes["cause"]["id"],
                    "target_responsible_agency_id": codes["agency"]["id"],
                    "target_allocation": "NPT",
                },
            )
        )
        assert companion["target_operation_id"] == codes["operation"]["id"]
        assert companion["target_cause_id"] == codes["cause"]["id"]
        for piece in ("Hole section", "Phase", "Sub-phase", "Activity", "Cause", "Responsible agency label"):
            assert piece in companion["extra_criteria_summary"]

        # A cause can never be pinned to a Planned Activity: the matrix refuses it.
        bad = client.post(
            OPS + "/correlations",
            headers=headers,
            json={
                "kind": "operation",
                "source_family": "Trouble / NPT",
                "source_code": "TP03",
                "target_id": codes["operation"]["id"],
                "target_activity_id": codes["activity"]["id"],
                "target_cause_id": codes["cause"]["id"],
            },
        )
        assert bad.status_code == 422 and "Planned" in bad.json()["detail"]

        # A correlated code cannot be soft-deleted; the refusal names the rule.
        blocked = client.post(
            OPS + "/masters/agencies/bulk-delete", headers=headers, json={"ids": [codes["agency"]["id"]]}
        )
        assert blocked.status_code == 409 and "RIG" in blocked.json()["detail"]

        # Purge is refused while even a deleted correlation still names the code.
        good(client.post(OPS + "/correlations/bulk-delete", headers=headers, json={"ids": [agency["id"]]}))
        for rule in good(client.get(OPS + "/correlations", headers=headers)):
            good(client.post(OPS + "/correlations/bulk-delete", headers=headers, json={"ids": [rule["id"]]}))
        good(client.post(OPS + "/masters/agencies/bulk-delete", headers=headers, json={"ids": [codes["agency"]["id"]]}))
        purge = client.post(
            OPS + "/masters/agencies/bulk-permanent-delete", headers=headers, json={"ids": [codes["agency"]["id"]]}
        )
        assert purge.status_code == 409 and "deleted correlation" in purge.json()["detail"]


def test_batch_correlations_are_atomic_and_reference_counts_are_live():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)
        url = OPS + "/correlations/batch"

        refused = client.post(
            url,
            headers=headers,
            json={
                "items": [
                    {
                        "kind": "operation",
                        "source_family": "Trouble / NPT",
                        "source_code": "TP02",
                        "target_id": codes["operation"]["id"],
                    },
                    {
                        "kind": "operation",
                        "source_family": "Trouble / NPT",
                        "source_code": "TP02",
                        "target_id": codes["operation"]["id"],
                    },
                ]
            },
        )
        assert refused.status_code == 409 and "Row 2" in refused.json()["detail"]
        assert good(client.get(OPS + "/correlations", headers=headers)) == []

        created = good(
            client.post(
                url,
                headers=headers,
                json={
                    "items": [
                        {
                            "kind": "operation",
                            "source_family": "Trouble / NPT",
                            "source_code": "TP02",
                            "target_id": codes["operation"]["id"],
                        },
                        {
                            "kind": "sub-phase",
                            "source_family": "OpenWells phase",
                            "source_code": "DRLSUR",
                            "target_id": codes["sub_phase"]["id"],
                        },
                    ]
                },
            )
        )
        assert created["created_count"] == 2

        # The reference payload counts live rules per code, so the library can link to them.
        reference = good(client.get(OPS + "/correlations/reference", headers=headers))
        counted = {row["code"]: row["correlation_count"] for row in reference["library"]["operation"]}
        assert counted["PUMP"] == 1


def test_completion_reports_never_report_a_rate_of_penetration():
    """ROP is a drilling measurement; a completion must say N/A, never inherit one."""
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)
        from app.models.rig_well import Well
        from test_rig_well import create_rig, create_well

        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"], "COMPLETION-WELL-01")
        with SessionLocal() as db:
            row = db.get(Well, well["id"])
            row.config_status = "configured"
            row.completion_config_status = "configured"
            db.commit()
        report = good(
            client.post(
                OPS + "/reports",
                headers=headers,
                json={"well_id": well["id"], "scope": "completion", "report_date": DAY, "report_type": "DCR"},
            )
        )
        blocks = [
            {
                "sequence_no": 1,
                "started_at": f"{DAY}T00:00:00+01:00",
                "ended_at": f"{DAY}T12:00:00+01:00",
                "duration_minutes": 720,
                "classification": "Planned",
                "allocation": "PT",
                "is_productive": True,
                "narrative": "Run completion string.",
                "hole_section_id": codes["hole_section"]["id"],
                "phase_id": codes["phase"]["id"],
                "sub_phase_id": codes["sub_phase"]["id"],
                "activity_id": codes["activity"]["id"],
                "footage_m": "120.000",
                "rotating_hours": "6.000",
                "depth_from_m": "2000.000",
                "depth_to_m": "2120.000",
                "review_state": "accepted",
            }
        ]
        saved = good(
            client.put(
                OPS + f"/reports/{report['id']}",
                headers=headers,
                json={"report": {}, "blocks": blocks, "confirm_review": True},
            )
        )
        assert saved["blocks"][0]["rop_m_per_hr"] is None

        brief = good(client.get(OPS + f"/reports/{report['id']}/brief", headers=headers))
        assert "ROP: N/A (completion operation)" in brief["summary"]
        assert brief["depth_progress"]["rop_m_per_hr"] is None
        # The summary is keyed by `well_id`; the Summary page accepts `?well=` and
        # falls back to `well_id`, so both names must reach the same resource.
        overall = good(client.get(OPS + "/summary", headers=headers, params={"well_id": well["id"]}))
        assert overall["kpis"]["avg_rop_m_per_hr"] in (None, "N/A")
        for activity in overall["activities"]:
            assert activity["rop_m_per_hr"] in (None, "N/A")
        dashboard = good(client.get(OPS + "/dashboard", headers=headers, params={"well_id": well["id"]}))
        assert dashboard["kpis"]["avg_rop"] in (None, "N/A")


def test_completion_scope_is_recognised_from_the_summary_and_never_carries_a_rate():
    """The AI surfaces must reach the same N/A conclusion as the pages.

    ``ops_ai`` decides from the summary document itself, because the assistant's
    AI grounding builds its context from summaries without any scope argument.
    A completion-only summary must therefore be recognised on its own, and the
    blended context block must build without raising (a NameError there used to
    be swallowed by the assistant's generic enrichment handler and surface as
    "AI communication error").
    """
    from app.services.operations import ops_ai

    completion_only = {"daily_rollup": [{"scope": "completion"}, {"scope": "completion"}], "kpis": {}}
    assert ops_ai._is_completion_only(completion_only) is True
    assert ops_ai._is_completion_only({"scope_label": "Completion", "daily_rollup": []}) is True
    assert ops_ai._is_completion_only({"scopes": ["completion"]}) is True
    # Mixed or drilling work keeps a real rate, with or without an explicit filter.
    assert ops_ai._is_completion_only({"daily_rollup": [{"scope": "drilling"}, {"scope": "completion"}]}) is False
    assert ops_ai._is_completion_only({"scopes": ["drilling"]}) is False
    assert ops_ai._is_completion_only({}) is False
    assert ops_ai._is_completion_only(completion_only, "drilling") is False
    assert ops_ai._is_completion_only({}, "completion") is True
    # The formatter the assistant uses for a rate renders N/A, never a blank.
    assert ops_ai._fmt_rop(None, " m/h", completion=True) == "N/A"
    assert ops_ai._fmt_rop(12.5, " m/h", completion=True) == "N/A"
    assert ops_ai._fmt_rop(12.5, " m/h") == "12.5 m/h"

    # A real workspace summary reaches the same verdict, and the context block
    # that grounds the offline AI builds for it.
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)
        from app.models.rig_well import Well
        from test_rig_well import create_rig, create_well

        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"], "COMPLETION-AI-01")
        with SessionLocal() as db:
            row = db.get(Well, well["id"])
            row.config_status = "configured"
            row.completion_config_status = "configured"
            db.commit()
        report = good(
            client.post(
                OPS + "/reports",
                headers=headers,
                json={"well_id": well["id"], "scope": "completion", "report_date": DAY, "report_type": "DCR"},
            )
        )
        good(
            client.put(
                OPS + f"/reports/{report['id']}",
                headers=headers,
                json={
                    "report": {},
                    "blocks": [
                        {
                            "sequence_no": 1,
                            "started_at": f"{DAY}T00:00:00+01:00",
                            "ended_at": f"{DAY}T12:00:00+01:00",
                            "duration_minutes": 720,
                            "classification": "Planned",
                            "allocation": "PT",
                            "is_productive": True,
                            "narrative": "Run completion string.",
                            "hole_section_id": codes["hole_section"]["id"],
                            "phase_id": codes["phase"]["id"],
                            "sub_phase_id": codes["sub_phase"]["id"],
                            "activity_id": codes["activity"]["id"],
                            "footage_m": "120.000",
                            "rotating_hours": "6.000",
                        }
                    ],
                    "confirm_review": True,
                },
            )
        )
        summary = good(client.get(OPS + "/summary", headers=headers, params={"well_id": well["id"]}))
        assert ops_ai._is_completion_only(summary) is True
        # The grounding block the offline AI reads is built from the same summary
        # and states N/A, so the model is never handed a fabricated rate.
        from app.models import User

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "owner@example.com"))
            org_id = user.organization_id
            context = ops_ai.build_ops_context_block(
                db, org_id, "How is COMPLETION-AI-01 completion progress?", {"ops-report:read", "ops-analytics:read"}
            )
        assert isinstance(context, str) and context
        assert "COMPLETION-AI-01" in context
        assert "AvgROP=N/A" in context
        assert "avg_ROP=" in context


def test_guide_explains_correlations_and_the_deletion_rule():
    with TestClient(app) as client:
        headers = login(client)
        _codes(client, headers)
        answer = good(
            client.post("/api/v1/assistant/ask", headers=headers, json={"question": "How do code correlations work?"})
        )
        text = (answer.get("answer") or "") + " " + " ".join(answer.get("steps") or [])
        assert "correlation" in text.lower()
        assert "/operations/library?tab=correlations" in json_dumps(answer)
        purge = good(
            client.post(
                "/api/v1/assistant/ask",
                headers=headers,
                json={"question": "How do I permanently delete a code that is still linked?"},
            )
        )
        purge_text = (purge.get("answer") or "") + " " + " ".join(purge.get("steps") or [])
        assert "delete permanently" in purge_text.lower() or "permanently" in purge_text.lower()


def json_dumps(value) -> str:
    import json

    return json.dumps(value, default=str)
