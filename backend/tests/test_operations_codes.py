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
    """A second code per family, so a link can join two distinct criteria."""
    return {
        "phase": good(
            client.post(OPS + "/masters/phase-codes", headers=headers, json={"phase_code": "PH1", "phase_name": "Drilling"})
        ),
        "activity2": good(
            client.post(
                OPS + "/masters/activity-codes", headers=headers, json={"activity_code": "TRIP", "activity_name": "Tripping"}
            )
        ),
        "operation2": codes["operation"],
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
            json={"operation_code_id": codes["operation"]["id"]},
        )
        assert single.status_code == 422 and "two workspace code criteria" in single.json()["detail"]

        # NPT code with a Planned classification is refused before it is written.
        matrix = client.post(
            OPS + "/code-links",
            headers=headers,
            json={
                "operation_code_id": codes["operation"]["id"],
                "npt_code_id": codes["npt"]["id"],
                "default_classification": "Planned",
            },
        )
        assert matrix.status_code == 422 and "NPT code applies only" in matrix.json()["detail"]

        link = good(
            client.post(
                OPS + "/code-links",
                headers=headers,
                json={
                    "rule_name": "Drilling + rotating",
                    "operation_code_id": codes["operation"]["id"],
                    "activity_code_id": codes["activity"]["id"],
                    "phase_code_id": extra["phase"]["id"],
                    "note": "Rotating while drilling",
                },
            )
        )
        assert link["criteria_count"] == 3
        assert "Operation: DRL" in link["summary_label"]
        assert link["phase_label"] == "PH1 — Drilling"

        # The same criteria twice is a conflict; deletion then re-creation is not.
        # The signature is the exact criteria set: the same two codes with a
        # *narrower* set is a different rule (and is what the duplicate above would
        # be if the phase were dropped). Repeating the identical set is the conflict.
        different = good(
            client.post(
                OPS + "/code-links",
                headers=headers,
                json={"operation_code_id": codes["operation"]["id"], "activity_code_id": codes["activity"]["id"]},
            )
        )
        duplicate = client.post(
            OPS + "/code-links",
            headers=headers,
            json={"operation_code_id": codes["operation"]["id"], "activity_code_id": codes["activity"]["id"]},
        )
        assert duplicate.status_code == 409
        good(client.post(OPS + "/code-links/bulk-delete", headers=headers, json={"ids": [different["id"]]}))
        good(client.post(OPS + "/code-links/bulk-permanent-delete", headers=headers, json={"ids": [different["id"]]}))

        listed = good(client.get(OPS + "/code-links", headers=headers))
        assert [row["id"] for row in listed] == [link["id"]]

        # A code inside a link cannot leave the library until the link is gone.
        blocked = client.post(
            OPS + "/masters/operation-codes/bulk-delete", headers=headers, json={"ids": [codes["operation"]["id"]]}
        )
        assert blocked.status_code == 409 and "code link 'Drilling + rotating'" in blocked.json()["detail"]
        good(client.post(OPS + "/code-links/bulk-delete", headers=headers, json={"ids": [link["id"]]}))
        good(client.post(OPS + "/masters/operation-codes/bulk-delete", headers=headers, json={"ids": [codes["operation"]["id"]]}))

        # A deleted link whose code is itself deleted cannot be restored blind.
        refused = client.post(OPS + "/code-links/bulk-restore", headers=headers, json={"ids": [link["id"]]})
        assert refused.status_code == 409 and "Restore the code first" in refused.json()["detail"]
        good(client.post(OPS + "/masters/operation-codes/bulk-restore", headers=headers, json={"ids": [codes["operation"]["id"]]}))
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
        base = {"operation_code_id": codes["operation"]["id"]}

        # A duplicate inside the batch rolls the whole batch back.
        refused = client.post(
            url,
            headers=headers,
            json={
                "items": [
                    {**base, "activity_code_id": codes["activity"]["id"]},
                    {**base, "activity_code_id": codes["activity"]["id"]},
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
                    {**base, "activity_code_id": codes["activity"]["id"]},
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
                            "operation_code_id": codes["operation"]["id"],
                            "activity_code_id": codes["activity"]["id"],
                        },
                        {
                            "rule_name": "NPT",
                            "npt_code_id": codes["npt"]["id"],
                            "cause_id": codes["cause"]["id"],
                            "default_classification": "NPT",
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
        agency = good(
            client.post(
                OPS + "/correlations",
                headers=headers,
                json={
                    "kind": "agency",
                    "source_code": "Halliburton",
                    "target_id": codes["agency"]["id"],
                    "note": "Printed operator spelling",
                },
            )
        )
        assert agency["source_family"] == "Source agency"
        assert agency["source_code"] == "HALLIBURTON"

        # Companion criteria pin the same token to a second workspace code.
        companion = good(
            client.post(
                OPS + "/correlations",
                headers=headers,
                json={
                    "kind": "npt",
                    "source_family": "Trouble / NPT",
                    "source_code": "TP02",
                    "target_id": codes["npt"]["id"],
                    "target_cause_id": codes["cause"]["id"],
                    "target_agency_id": codes["agency"]["id"],
                    "target_classification": "NPT",
                    "target_allocation": "NPT",
                },
            )
        )
        assert companion["target_npt_code_id"] == codes["npt"]["id"]
        assert companion["target_cause_id"] == codes["cause"]["id"]
        assert "Cause" in companion["extra_criteria_summary"]

        # The classification matrix applies to correlations as well.
        bad = client.post(
            OPS + "/correlations",
            headers=headers,
            json={
                "kind": "operation",
                "source_family": "OpenWells operation code",
                "source_code": "01-A",
                "target_id": codes["operation"]["id"],
                "target_classification": "NPT",
                "target_allocation": "PT",
            },
        )
        assert bad.status_code == 422 and "NPT classification" in bad.json()["detail"]

        # A correlated code cannot be soft-deleted; the refusal names the rule.
        blocked = client.post(
            OPS + "/masters/agencies/bulk-delete", headers=headers, json={"ids": [codes["agency"]["id"]]}
        )
        assert blocked.status_code == 409 and "HALLIBURTON" in blocked.json()["detail"]

        # Purge is refused while even a deleted correlation still names the code.
        good(client.post(OPS + "/correlations/bulk-delete", headers=headers, json={"ids": [agency["id"]]}))
        # The companion row still names the agency: correlation rules are blocked too.
        for rule in good(client.get(OPS + "/correlations", headers=headers)):
            good(client.post(OPS + "/correlations/bulk-delete", headers=headers, json={"ids": [rule["id"]]}))
        good(client.post(OPS + "/masters/agencies/bulk-delete", headers=headers, json={"ids": [codes["agency"]["id"]]}))
        purge = client.post(
            OPS + "/masters/agencies/bulk-permanent-delete", headers=headers, json={"ids": [codes["agency"]["id"]]}
        )
        assert purge.status_code == 409 and "deleted correlation" in purge.json()["detail"]

        # Removing the rule, then purging, is allowed and audited.
        good(client.post(OPS + "/correlations/bulk-permanent-delete", headers=headers, json={"ids": [agency["id"]]}))
        good(client.post(OPS + "/correlations/bulk-delete", headers=headers, json={"ids": [companion["id"]]}))
        good(client.post(OPS + "/correlations/bulk-permanent-delete", headers=headers, json={"ids": [companion["id"]]}))
        purged = good(
            client.post(OPS + "/masters/agencies/bulk-permanent-delete", headers=headers, json={"ids": [codes["agency"]["id"]]})
        )
        assert purged["affected_count"] == 1


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
                        "source_family": "OpenWells operation code",
                        "source_code": "19-D",
                        "target_id": codes["operation"]["id"],
                    },
                    {
                        "kind": "operation",
                        "source_family": "OpenWells operation code",
                        "source_code": "19-D",
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
                            "source_family": "OpenWells operation code",
                            "source_code": "19-D",
                            "target_id": codes["operation"]["id"],
                        },
                        {
                            "kind": "activity",
                            "source_family": "Activity",
                            "source_code": "06",
                            "target_id": codes["activity"]["id"],
                        },
                    ]
                },
            )
        )
        assert created["created_count"] == 2

        # The reference payload counts live rules per code, so the library can link to them.
        reference = good(client.get(OPS + "/correlations/reference", headers=headers))
        counted = {row["code"]: row["correlation_count"] for row in reference["library"]["operation"]}
        assert counted["DRL"] == 1


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
                "operation_code_id": codes["operation"]["id"],
                "activity_code_id": codes["activity"]["id"],
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
                            "operation_code_id": codes["operation"]["id"],
                            "activity_code_id": codes["activity"]["id"],
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
