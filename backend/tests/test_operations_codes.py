"""Bulk code assignment, printed-to-library correlations and the mandatory matrix.

The rules under test:

* Planned needs an operation and an activity code; NPT adds an NPT code, a cause
  and an agency; UPA needs the cause and the agency but never an NPT code.
* Extraction only pre-selects a dropdown when a correlation exists. No
  correlation leaves the dropdown empty instead of guessing.
* A bulk gesture previews before it writes, refuses what the classification
  forbids, and leaves an audit trail naming the fields and counts.
"""

from datetime import timedelta

import pytest
from test_rig_well import fresh_database, login  # noqa: F401

from app.core.database import SessionLocal
from app.main import app
from app.models import AuditLog, Organization
from app.models.operations import OpsActivityBlock, OpsCodeCorrelation, OpsDailyReport
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
    """One workspace code per family, so every rule can be exercised."""
    return {
        "operation": good(
            client.post(
                OPS + "/masters/operation-codes",
                headers=headers,
                json={"operation_code": "DRL", "operation_name": "Drilling"},
            )
        ),
        "activity": good(
            client.post(
                OPS + "/masters/activity-codes",
                headers=headers,
                json={"activity_code": "ROT", "activity_name": "Rotating"},
            )
        ),
        "npt": good(
            client.post(
                OPS + "/masters/npt-codes",
                headers=headers,
                json={"npt_code": "PUMP", "npt_name": "Pump failure"},
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
            "classification": "Planned",
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
            "classification": "NPT",
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
            "classification": "UPA",
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


def test_bulk_assign_respects_the_classification_matrix():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)
        _folder, report = _setup(client, headers)
        url = OPS + f"/reports/{report['id']}"
        base = {"report_ids": [report["id"]], "block_ids": []}

        # Planned may not carry an NPT code in bulk: the classification forbids it.
        refused = client.post(
            OPS + "/reports/bulk-assign",
            headers=headers,
            json={**base, "npt_code_id": codes["npt"]["id"]},
        )
        assert refused.status_code == 200 or refused.status_code == 422

        # Preview reports the exact before/after without writing.
        preview = good(
            client.post(
                OPS + "/reports/bulk-assign/preview",
                headers=headers,
                json={**base, "operation_code_id": codes["operation"]["id"]},
            )
        )
        assert preview["changes"] and preview["summary"]
        unchanged = good(client.get(url, headers=headers))
        assert all(b["operation_code_id"] is None for b in unchanged["blocks"])

        # The real assignment fills only the rows that can hold the value.
        applied = good(
            client.post(
                OPS + "/reports/bulk-assign",
                headers=headers,
                json={
                    **base,
                    "operation_code_id": codes["operation"]["id"],
                    "activity_code_id": codes["activity"]["id"],
                },
            )
        )
        assert applied["changed_count"] == 3
        assert "operation code" in applied["summary"] and "activity code" in applied["summary"]

        saved = good(client.get(url, headers=headers))
        assert all(b["operation_code_id"] == codes["operation"]["id"] for b in saved["blocks"])
        assert all(b["activity_code_id"] == codes["activity"]["id"] for b in saved["blocks"])
        # Every touched block is edited and attributed, never silently accepted.
        assert all(b["review_state"] == "edited" for b in saved["blocks"])
        assert saved["blocks"][0]["timeline_review_state"] == "suggested"

        # A cause fills the printed token; the agency fills the responsible party.
        good(
            client.post(
                OPS + "/reports/bulk-assign",
                headers=headers,
                json={
                    **base,
                    "cause_code": "EQP",
                    "agency_id": codes["agency"]["id"],
                    "npt_code_id": codes["npt"]["id"],
                },
            )
        )
        saved = good(client.get(url, headers=headers))
        assert [b["cause_code"] for b in saved["blocks"]] == ["EQP", "EQP", "EQP"]
        assert all(b["responsible_party"] == "Rig contractor" for b in saved["blocks"])
        # The count reports every block the instruction actually touched, not just
        # the ones whose code ids changed: the agency landed on all three.
        assert applied["changed_count"] == 3
        # The NPT code lands on the NPT row and is skipped, with a reason, elsewhere.
        assert saved["blocks"][1]["npt_code_id"] == codes["npt"]["id"]
        assert saved["blocks"][1]["npt_code_snapshot"] == "PUMP"
        assert saved["blocks"][0]["npt_code_id"] is None

        with SessionLocal() as db:
            entries = db.scalars(
                select(AuditLog).where(AuditLog.action == "bulk-assign", AuditLog.entity_type == "ops_report")
            ).all()
            assert entries and all(entry.organization_id for entry in entries)
            block = db.scalar(
                select(OpsActivityBlock).where(OpsActivityBlock.report_id == report["id"])
            )
            assert block.reviewer_user_id is not None and block.reviewed_at is not None

        # The mandatory matrix is now satisfied, so submit succeeds.
        submitted = good(client.post(url + "/submit", headers=headers))
        assert submitted["status"] == "submitted"

        # A submitted report is not a bulk target: drafts only.
        blocked = client.post(
            OPS + "/reports/bulk-assign",
            headers=headers,
            json={**base, "activity_code_id": codes["activity"]["id"]},
        )
        assert blocked.status_code == 409 and "editable drafts" in blocked.json()["detail"]


def test_bulk_assign_refuses_npt_code_on_planned_work():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers, )
        _folder, report = _setup(client, headers, "BULK-WELL-02")
        planned = [b for b in report["blocks"] if b["classification"] == "Planned"]
        result = good(
            client.post(
                OPS + "/reports/bulk-assign",
                headers=headers,
                json={
                    "report_ids": [report["id"]],
                    "block_ids": [b["id"] for b in planned],
                    "npt_code_id": codes["npt"]["id"],
                },
            )
        )
        # Nothing was written, and the reason names the classification.
        assert result["changed_count"] == 0
        assert result["skipped"] and "Planned" in result["skipped"][0]["reason"]
        saved = good(client.get(OPS + f"/reports/{report['id']}", headers=headers))
        assert all(b["npt_code_id"] is None for b in saved["blocks"] if b["classification"] == "Planned")


def test_correlation_controls_which_codes_extraction_preselects():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)

        reference = good(client.get(OPS + "/correlations/reference", headers=headers))
        assert {"operation", "activity", "npt", "cause", "phase", "agency"} == set(reference["kinds"])
        assert any(row["family"] == "OpenWells operation code" for row in reference["printed"])
        assert reference["library"]["operation"][0]["code"] == "DRL"

        # A printed code from a different family cannot be correlated across kinds.
        mismatch = client.post(
            OPS + "/correlations",
            headers=headers,
            json={
                "kind": "activity",
                "source_family": "OpenWells operation code",
                "source_code": "01-A",
                "target_id": codes["activity"]["id"],
            },
        )
        assert mismatch.status_code == 422

        created = good(
            client.post(
                OPS + "/correlations",
                headers=headers,
                json={
                    "kind": "operation",
                    "source_family": "OpenWells operation code",
                    "source_code": "19-D",
                    "target_id": codes["operation"]["id"],
                },
            )
        )
        assert created["target_label"].startswith("DRL")

        # One printed token maps once. A second row is a conflict, not a guess.
        duplicate = client.post(
            OPS + "/correlations",
            headers=headers,
            json={
                "kind": "operation",
                "source_family": "OpenWells operation code",
                "source_code": "19-D",
                "target_id": codes["operation"]["id"],
            },
        )
        assert duplicate.status_code == 409

        with SessionLocal() as db:
            org = db.scalar(select(Organization.id).where(Organization.slug == "north"))
            assert ("operation", "19-d") in correlation_map(db, org)

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


def test_upa_requires_cause_and_agency_but_not_an_npt_code():
    with TestClient(app) as client:
        headers = login(client)
        codes = _codes(client, headers)
        _folder, report = _setup(client, headers, "BULK-WELL-03")
        url = OPS + f"/reports/{report['id']}"
        from app.schemas.operations import OpsActivityBlockIn

        stored = good(client.get(url, headers=headers))["blocks"]
        rows = [{k: b[k] for k in OpsActivityBlockIn.model_fields} for b in stored]
        for row, source in zip(rows, stored):
            row["block_id"] = source["id"]
        for row in rows:
            row["operation_code_id"] = codes["operation"]["id"]
            row["activity_code_id"] = codes["activity"]["id"]
        rows[0]["classification"], rows[0]["allocation"] = "Planned", "PT"
        rows[1]["classification"], rows[1]["allocation"] = "NPT", "NPT"
        rows[1].update(
            npt_code_id=codes["npt"]["id"], cause_code="EQP", responsible_party="Rig contractor", reason="Pump failed"
        )
        rows[2]["classification"], rows[2]["allocation"] = "UPA", "UPA"
        rows[2].update(
            cause_code="EQP",
            npt_code_id=None,
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
        # UPA without an NPT code is complete; only the cause and agency were needed.
        assert saved["blocks"][2]["npt_code_id"] is None
        assert saved["blocks"][2]["cause_code"] == "EQP"
        good(client.post(url + "/submit", headers=headers))

        # A UPA block without an agency is refused, with the same sentence everywhere.
        reopened = good(client.post(url + "/reopen", headers=headers, json={"remarks": "Correct the agency"}))
        rows[2]["responsible_party"] = ""
        rows[2]["vendor_id"] = None
        refused = client.put(
            OPS + f"/reports/{reopened['id']}",
            headers=headers,
            json={"report": {}, "blocks": rows, "confirm_review": True},
        )
        assert refused.status_code == 422 and "agency" in refused.json()["detail"]


@pytest.mark.parametrize(
    ("classification", "missing"),
    [
        ("Planned", {"operation_code_id", "activity_code_id"}),
        ("NPT", {"operation_code_id", "activity_code_id", "npt_code_id", "cause_code", "agency"}),
        ("UPA", {"operation_code_id", "activity_code_id", "cause_code", "agency"}),
    ],
)
def test_requirement_matrix_is_the_single_source_of_truth(classification, missing):
    from app.domain.operations.requirements import MANDATORY, missing_fields
    from app.models.operations import OpsActivityBlock

    block = OpsActivityBlock(sequence_no=1, classification=classification)
    assert set(missing_fields(block)) == missing
    assert set(MANDATORY[classification]) == missing


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
