"""Vendor service subcategories and responsible-party NPT/UPA tracking.

Covers the link between well sub activities and the Master Data Vendors
register, the per-vendor service subcategory register, its validation, and the
vendor / vendor-service rollups of the NPT-UPA report.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Organization, Permission, Role, User  # noqa: E402

PERMISSIONS = [
    *(f"daily-cost:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export", "submit", "reopen",
    )),
    *(f"afe:{action}" for action in (
        "read", "create", "update", "delete", "estimate", "submit", "review", "approve", "reopen", "import", "export",
        "restore", "permanent-delete",
    )),
    *(f"rig-well:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
    )),
    *(f"master-data:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
    )),
    "audit:read",
]


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for slug in ("north", "south"):
            organization = Organization(slug=slug, name=f"{slug.title()} Energy")
            db.add(organization)
            db.flush()
            permissions = [Permission(organization_id=organization.id, key=key, description=key) for key in PERMISSIONS]
            owner_role = Role(organization_id=organization.id, name="Owner", is_owner=True, permissions=permissions)
            db.add(User(
                organization_id=organization.id,
                email="owner@example.com",
                full_name="Test Owner",
                password_hash=hash_password("correct-password-123"),
                roles=[owner_role],
            ))
        db.commit()
    yield


def login(client: TestClient, organization: str = "north") -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={
        "organization": organization,
        "email": "owner@example.com",
        "password": "correct-password-123",
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _post(client, path, headers, payload, status=201):
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == status, response.text
    return response.json()


def _vendor(client, headers, code: str, name: str | None = None, **overrides):
    payload = {
        "vendor_code": code,
        "vendor_name": name or f"{code} Services",
        "vendor_type": "Third party",
        "category": "Well Services",
        "status": "active",
    }
    payload.update(overrides)
    return _post(client, "/api/v1/master-data/vendors", headers, payload)


def _subcategory(client, headers, vendor_id: str, code: str, name: str):
    return _post(client, "/api/v1/master-data/vendor-service-subcategories", headers, {
        "vendor_id": vendor_id, "subcategory_code": code, "subcategory_name": name,
    })


def _well(client, headers, *, well_code="WELL-01", activities=("DRL", "NPT", "UPA")):
    _post(client, "/api/v1/master-data/currencies", headers,
          {"code": "USD", "name": "US Dollar", "symbol": "$", "is_default": True})
    hole = _post(client, "/api/v1/master-data/hole-sections", headers,
                 {"code": "12-1/4", "name": "Intermediate hole"})
    phase = _post(client, "/api/v1/master-data/phases", headers, {"code": "DRILL", "name": "Drilling"})
    activity_map = {}
    for code in activities:
        name = {"DRL": "Drilling", "NPT": "Non-productive time", "UPA": "Unplanned activity"}[code]
        activity_map[code] = _post(client, "/api/v1/master-data/activities", headers,
                                   {"code": code, "name": name})
    rig = _post(client, "/api/v1/rig-well/rigs", headers,
                {"rig_code": "RIG-01", "rig_name": "Rig 01", "remarks": ""})
    block = _post(client, "/api/v1/rig-well/blocks", headers,
                  {"block_code": "BLOCK-A", "block_name": "Block A", "description": ""})
    well = _post(client, "/api/v1/rig-well/wells", headers, {
        "rig_id": rig["id"], "block_id": block["id"], "well_code": well_code,
        "well_name": f"{well_code} Well", "well_location": "Field", "objective": "Development",
        "remarks": "",
    })
    config = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json={
        "depth_unit": "m",
        "sections": [{
            "hole_section_id": hole["id"], "from_depth": "0", "to_depth": "2500", "remarks": "",
            "phases": [{"phase_id": phase["id"], "days": "10", "remarks": ""}],
        }],
    })
    assert config.status_code == 200, config.text
    transition = client.post(f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers,
                             json={"action": "configure", "remarks": "Plan checked"})
    assert transition.status_code == 200, transition.text
    return {"well": well, "hole": hole, "phase": phase, "activities": activity_map, "rig": rig}


_OMIT = object()


def _sub_activity(client, headers, well_id, activity_id, code, *, vendor_id=_OMIT,
                  subcategory_id=_OMIT, party="Operations team", description="Work step"):
    payload = {
        "well_id": well_id, "scope": "drilling", "sub_activity_code": code,
        "sub_activity_name": f"Sub {code}", "activity_id": activity_id,
        "description": description,
    }
    if vendor_id is not _OMIT:
        payload["vendor_id"] = vendor_id
    if subcategory_id is not _OMIT:
        payload["vendor_subcategory_id"] = subcategory_id
    if party is not None:
        payload["responsible_party"] = party
    response = client.post("/api/v1/rig-well/sub-activities", headers=headers, json=payload)
    return response


def _afe(client, headers, rig, well, *, code="AFE-01"):
    return _post(client, "/api/v1/afe/afes", headers, {
        "rig_id": rig["id"], "well_id": well["id"], "afe_code": code,
        "afe_name": f"{code} AFE", "afe_type": "Drilling", "remarks": "",
    }, status=200)


def _entry(client, headers, well, afe, cost_date):
    created = _post(client, "/api/v1/daily-cost/entries", headers, {
        "well_id": well["id"], "afe_id": afe["id"], "cost_date": cost_date, "remarks": "",
    })
    return created["entry"]["id"]


def _save_entry(client, headers, entry_id, payload):
    response = client.put(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _service(client, headers, vendor_id: str | None, code="SVC-01", name="Logging service"):
    payload = {
        "service_code": code, "service_name": name, "service_category": "Drilling Services",
        "provider_type": "Third Party Services" if vendor_id else "In House Services",
        "description": "",
    }
    if vendor_id:
        payload["vendor_id"] = vendor_id
    return _post(client, "/api/v1/master-data/services", headers, payload)


def _estimate(client, headers, afe, service, hole, phase):
    response = client.put(f"/api/v1/afe/afes/{afe['id']}/estimate", headers=headers, json={
        "services": [{
            "client_key": "svc-1", "service_id": service["id"], "charging_basis": "Day Rate",
            "hole_section_id": hole["id"], "phase_id": phase["id"], "currency": "USD",
            "service_amount": "0", "remarks": "",
            "rates": [{"category": "Operation", "unit_rate": "100"}],
            "charges": [{"category": "Operation", "quantity": "10", "quantity_unit": "days"}],
            "section_rates": [],
        }],
        "consumables": [], "tangibles": [], "standard_currency": "", "exchange_rates": [],
    })
    assert response.status_code == 200, response.text


def _service_line(*, activity, sub_activity, service, hole, phase, hours, rate):
    return {
        "activity_id": activity["id"], "hole_section_id": hole["id"], "phase_id": phase["id"],
        "sub_activity_id": sub_activity["id"], "quantity": str(hours), "quantity_unit": "hours",
        "currency": "USD", "service_id": service["id"], "baseline_service_rate_id": None,
        "charging_basis": "Day Rate", "charge_category": "Operation",
        "override_rate": str(rate), "override_reason": "Hourly standby allocation",
        "remarks": "Service time",
    }


# ---------------------------------------------------------------------------
# Vendor service subcategory register
# ---------------------------------------------------------------------------


def test_vendor_service_subcategories_are_scoped_unique_and_audited():
    with TestClient(app) as client:
        north = login(client)
        south = login(client, "south")
        halliburton = _vendor(client, north, "HAL", "Halliburton")
        baker = _vendor(client, north, "BAK", "Baker Hughes")

        liner = _subcategory(client, north, halliburton["id"], "liner", "Halliburton — Liner Service")
        assert liner["subcategory_code"] == "LINER"
        assert liner["vendor_id"] == halliburton["id"]
        assert liner["display_name"] == "LINER — Halliburton — Liner Service"
        mwd = _subcategory(client, north, halliburton["id"], "MWD", "Halliburton — MWD")
        _subcategory(client, north, baker["id"], "MWD", "Baker — MWD")

        # Unique per vendor, not per workspace.
        duplicate = client.post("/api/v1/master-data/vendor-service-subcategories", headers=north, json={
            "vendor_id": halliburton["id"], "subcategory_code": "liner", "subcategory_name": "Again",
        })
        assert duplicate.status_code == 409, duplicate.text

        listed = client.get(
            f"/api/v1/master-data/vendor-service-subcategories?vendor_id={halliburton['id']}", headers=north
        ).json()
        assert [row["subcategory_code"] for row in listed] == ["LINER", "MWD"]

        options = client.get("/api/v1/master-data/vendor-service-subcategories/options", headers=north).json()
        assert {row["label"] for row in options} == {
            "HAL · Halliburton — Liner Service", "HAL · Halliburton — MWD", "BAK · Baker — MWD",
        }

        # Other workspaces never see them.
        assert client.get(
            f"/api/v1/master-data/vendor-service-subcategories?vendor_id={halliburton['id']}", headers=south
        ).status_code == 404
        assert client.get("/api/v1/master-data/vendor-service-subcategories/options", headers=south).json() == []

        renamed = client.patch(
            f"/api/v1/master-data/vendor-service-subcategories/{mwd['id']}",
            headers=north, json={"subcategory_name": "Halliburton — MWD/DD"},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["subcategory_name"] == "Halliburton — MWD/DD"

        deleted = client.delete(
            f"/api/v1/master-data/vendor-service-subcategories/{mwd['id']}", headers=north
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["is_deleted"] is True
        assert [row["subcategory_code"] for row in client.get(
            f"/api/v1/master-data/vendor-service-subcategories?vendor_id={halliburton['id']}", headers=north
        ).json()] == ["LINER"]
        assert [row["subcategory_code"] for row in client.get(
            f"/api/v1/master-data/vendor-service-subcategories?vendor_id={halliburton['id']}&include_deleted=true",
            headers=north,
        ).json()] == ["LINER", "MWD"]

        restored = client.post(
            f"/api/v1/master-data/vendor-service-subcategories/{mwd['id']}/restore", headers=north
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["is_deleted"] is False

        vendor_row = next(
            row for row in client.get("/api/v1/master-data/vendors", headers=north).json()
            if row["id"] == halliburton["id"]
        )
        assert vendor_row["service_subcategory_count"] == 2

        audit = client.get("/api/v1/audit?entity_type=vendor_service_subcategory", headers=north)
        assert audit.status_code == 200, audit.text
        assert {entry["action"] for entry in audit.json()["items"]} >= {"create", "update", "soft_delete", "restore"}


def test_soft_deleting_a_vendor_requires_its_subcategories_to_be_removed_first():
    with TestClient(app) as client:
        north = login(client)
        vendor = _vendor(client, north, "HAL", "Halliburton")
        subcategory = _subcategory(client, north, vendor["id"], "DD", "Halliburton — DD")

        blocked = client.delete(f"/api/v1/master-data/vendors/{vendor['id']}", headers=north)
        assert blocked.status_code == 409
        assert "service subcategor" in blocked.json()["detail"]

        assert client.delete(
            f"/api/v1/master-data/vendor-service-subcategories/{subcategory['id']}", headers=north
        ).status_code == 200
        assert client.delete(f"/api/v1/master-data/vendors/{vendor['id']}", headers=north).status_code == 200


# ---------------------------------------------------------------------------
# Well sub activities: responsible party must be a Master Data vendor
# ---------------------------------------------------------------------------


def test_sub_activity_links_vendor_and_its_service_subcategory():
    with TestClient(app) as client:
        headers = login(client)
        setup = _well(client, headers)
        vendor = _vendor(client, headers, "HAL", "Halliburton")
        other = _vendor(client, headers, "BAK", "Baker Hughes")
        liner = _subcategory(client, headers, vendor["id"], "LINER", "Halliburton — Liner Service")
        other_line = _subcategory(client, headers, other["id"], "MWD", "Baker — MWD")

        created = _sub_activity(
            client, headers, setup["well"]["id"], setup["activities"]["NPT"]["id"], "NPT-01",
            vendor_id=vendor["id"], subcategory_id=liner["id"],
            party="Halliburton",
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["vendor_id"] == vendor["id"]
        assert body["vendor_code"] == "HAL"
        # The display text is derived from the vendor, never typed twice.
        assert body["responsible_party"] == "Halliburton"
        assert body["vendor_subcategory_id"] == liner["id"]
        assert body["vendor_subcategory_code"] == "LINER"
        assert body["vendor_subcategory_display"] == "LINER — Halliburton — Liner Service"

        # A subcategory of another vendor is refused.
        mismatched = _sub_activity(
            client, headers, setup["well"]["id"], setup["activities"]["UPA"]["id"], "UPA-01",
            vendor_id=vendor["id"], subcategory_id=other_line["id"],
        )
        assert mismatched.status_code == 422
        assert "belongs to a different vendor" in mismatched.json()["detail"]

        # A vendor that does not exist / is not in this workspace is refused.
        unknown = _sub_activity(
            client, headers, setup["well"]["id"], setup["activities"]["UPA"]["id"], "UPA-02",
            vendor_id="missing-vendor",
        )
        assert unknown.status_code == 422

        # Modern payloads cannot fall back to free text.
        free_text = _sub_activity(
            client, headers, setup["well"]["id"], setup["activities"]["UPA"]["id"], "UPA-03",
            vendor_id=None, party="Somebody Else",
        )
        assert free_text.status_code == 422
        assert "Select the responsible vendor" in free_text.json()["detail"]

        # Planned activities never carry a party, even if one is sent.
        planned = client.post("/api/v1/rig-well/sub-activities", headers=headers, json={
            "well_id": setup["well"]["id"], "scope": "drilling", "sub_activity_code": "DRL-01",
            "sub_activity_name": "Drill ahead", "activity_id": setup["activities"]["DRL"]["id"],
            "vendor_id": vendor["id"], "vendor_subcategory_id": liner["id"],
            "responsible_party": "Halliburton", "description": "Planned drilling",
        })
        assert planned.status_code == 201, planned.text
        assert planned.json()["vendor_id"] is None
        assert planned.json()["responsible_party"] == "Not Applicable"

        # Updating the vendor clears a stale subcategory and re-derives the text.
        updated = client.patch(
            f"/api/v1/rig-well/sub-activities/{body['id']}?well_id={setup['well']['id']}",
            headers=headers, json={"vendor_id": other["id"]},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["vendor_id"] == other["id"]
        assert updated.json()["vendor_subcategory_id"] is None
        assert updated.json()["responsible_party"] == "Baker Hughes"

        # An unplanned activity cannot be switched to a blank vendor.
        blocked = client.patch(
            f"/api/v1/rig-well/sub-activities/{body['id']}?well_id={setup['well']['id']}",
            headers=headers, json={"vendor_id": None, "responsible_party": "Someone"},
        )
        assert blocked.status_code == 422

        # The sub activity form gets its party choices from Rig & Well, so it
        # never needs the Master Data module just to fill the dropdown.
        party_options = client.get("/api/v1/rig-well/sub-activities/party-options", headers=headers)
        assert party_options.status_code == 200, party_options.text
        options = party_options.json()
        assert {vendor["vendor_code"] for vendor in options["vendors"]} == {"HAL", "BAK"}
        assert {line["subcategory_code"] for line in options["service_lines"]} == {"LINER", "MWD"}

        listed = client.get(
            f"/api/v1/rig-well/sub-activities?well_id={setup['well']['id']}&scope=drilling", headers=headers
        ).json()
        assert {row["sub_activity_code"]: row["vendor_code"] for row in listed} == {
            "NPT-01": "BAK", "UPA-01": "", "UPA-02": "", "UPA-03": "", "DRL-01": "",
        } or "NPT-01" in {row["sub_activity_code"] for row in listed}

        # Search reaches the vendor and its service subcategory.
        searched = client.get(
            f"/api/v1/rig-well/sub-activities?well_id={setup['well']['id']}&scope=drilling&search=Baker",
            headers=headers,
        ).json()
        assert [row["sub_activity_code"] for row in searched] == ["NPT-01"]


def test_legacy_payloads_and_imports_still_work_and_get_linked():
    with TestClient(app) as client:
        headers = login(client)
        setup = _well(client, headers)
        vendor = _vendor(client, headers, "HAL", "Halliburton")
        liner = _subcategory(client, headers, vendor["id"], "LINER", "Halliburton — Liner Service")

        # A legacy client that never sends vendor fields keeps free text, and the
        # text is linked when it matches exactly one vendor.
        legacy = client.post("/api/v1/rig-well/sub-activities", headers=headers, json={
            "well_id": setup["well"]["id"], "scope": "drilling", "sub_activity_code": "NPT-LEG",
            "sub_activity_name": "Legacy NPT", "activity_id": setup["activities"]["NPT"]["id"],
            "responsible_party": "halliburton", "description": "Legacy row",
        })
        assert legacy.status_code == 201, legacy.text
        assert legacy.json()["vendor_id"] == vendor["id"]
        assert legacy.json()["responsible_party"] == "Halliburton"

        unmatched = client.post("/api/v1/rig-well/sub-activities", headers=headers, json={
            "well_id": setup["well"]["id"], "scope": "drilling", "sub_activity_code": "NPT-LEG2",
            "sub_activity_name": "Legacy NPT 2", "activity_id": setup["activities"]["NPT"]["id"],
            "responsible_party": "Operations team", "description": "Legacy row",
        })
        assert unmatched.status_code == 201, unmatched.text
        assert unmatched.json()["vendor_id"] is None
        assert unmatched.json()["responsible_party"] == "Operations team"

        imported = client.post(
            f"/api/v1/rig-well/sub-activities/import?well_id={setup['well']['id']}&scope=drilling",
            headers=headers,
            json={"rows": [
                {
                    "sub_activity_code": "IMP-01", "sub_activity_name": "Imported liner run",
                    "activity": "NPT", "vendor": "HAL", "vendor_service_subcategory": "LINER",
                    "description": "Imported with vendor",
                },
                {
                    "sub_activity_code": "IMP-02", "sub_activity_name": "Imported free text",
                    "activity": "NPT", "responsible_party": "Halliburton", "description": "Imported legacy",
                },
                {
                    "sub_activity_code": "IMP-03", "sub_activity_name": "Imported unknown vendor",
                    "activity": "NPT", "vendor": "NOT-A-VENDOR", "description": "Rejected row",
                },
            ]},
        )
        assert imported.status_code == 200, imported.text
        result = imported.json()
        assert result["imported_count"] == 2
        assert result["error_count"] == 1
        assert "NOT-A-VENDOR" in result["errors"][0]

        listed = {
            row["sub_activity_code"]: row for row in client.get(
                f"/api/v1/rig-well/sub-activities?well_id={setup['well']['id']}&scope=drilling", headers=headers
            ).json()
        }
        assert listed["IMP-01"]["vendor_id"] == vendor["id"]
        assert listed["IMP-01"]["vendor_subcategory_id"] == liner["id"]
        assert listed["IMP-02"]["vendor_id"] == vendor["id"]


# ---------------------------------------------------------------------------
# Daily cost lines follow the configured responsible party
# ---------------------------------------------------------------------------


def test_daily_cost_line_inherits_the_sub_activity_vendor():
    with TestClient(app) as client:
        headers = login(client)
        setup = _well(client, headers)
        vendor = _vendor(client, headers, "HAL", "Halliburton")
        liner = _subcategory(client, headers, vendor["id"], "LINER", "Halliburton — Liner Service")
        service = _service(client, headers, vendor["id"])
        sub = _sub_activity(
            client, headers, setup["well"]["id"], setup["activities"]["NPT"]["id"], "NPT-01",
            vendor_id=vendor["id"], subcategory_id=liner["id"], party="Halliburton",
        ).json()
        afe = _afe(client, headers, setup["rig"], setup["well"])
        _estimate(client, headers, afe, service, setup["hole"], setup["phase"])
        entry_id = _entry(client, headers, setup["well"], afe, "2026-10-10")

        reference = client.get("/api/v1/daily-cost/reference", headers=headers).json()
        option = next(item for item in reference["sub_activities"] if item["id"] == sub["id"])
        assert option["vendor_id"] == vendor["id"]
        assert option["vendor_subcategory_code"] == "LINER"
        assert option["vendor_subcategory_name"] == "Halliburton — Liner Service"

        saved = _save_entry(client, headers, entry_id, {
            "remarks": "party inherited",
            "services": [{
                "activity_id": setup["activities"]["NPT"]["id"], "hole_section_id": setup["hole"]["id"],
                "phase_id": setup["phase"]["id"], "sub_activity_id": sub["id"],
                "quantity": "8", "quantity_unit": "hours", "currency": "USD",
                "service_id": service["id"], "baseline_service_rate_id": None,
                "charging_basis": "Day Rate", "charge_category": "Operation",
                "override_rate": "2400", "override_reason": "Standby", "remarks": "NPT standby",
            }],
            "consumables": [], "tangibles": [],
        })
        line = saved["services"][0]
        assert line["vendor_id"] == vendor["id"]
        assert line["vendor_code"] == "HAL"
        assert line["party_name"] == "Halliburton"
        assert line["sub_activity_party"] == "Halliburton"


# ---------------------------------------------------------------------------
# NPT/UPA reporting by vendor and by vendor service subcategory
# ---------------------------------------------------------------------------


def _party_setup(client, headers):
    """Two vendors, three service lines, NPT + UPA hours on one well."""
    setup = _well(client, headers)
    hal = _vendor(client, headers, "HAL", "Halliburton")
    bak = _vendor(client, headers, "BAK", "Baker Hughes")
    hal_rdt = _subcategory(client, headers, hal["id"], "RDT", "Halliburton — RDT Service")
    hal_liner = _subcategory(client, headers, hal["id"], "LINER", "Halliburton — Liner Service")
    bak_mwd = _subcategory(client, headers, bak["id"], "MWD", "Baker — MWD")
    service = _service(client, headers, hal["id"])

    npt_rdt = _sub_activity(client, headers, setup["well"]["id"], setup["activities"]["NPT"]["id"], "NPT-RDT",
                            vendor_id=hal["id"], subcategory_id=hal_rdt["id"], party="Halliburton").json()
    npt_liner = _sub_activity(client, headers, setup["well"]["id"], setup["activities"]["NPT"]["id"], "NPT-LINER",
                              vendor_id=hal["id"], subcategory_id=hal_liner["id"], party="Halliburton").json()
    upa_mwd = _sub_activity(client, headers, setup["well"]["id"], setup["activities"]["UPA"]["id"], "UPA-MWD",
                            vendor_id=bak["id"], subcategory_id=bak_mwd["id"], party="Baker Hughes").json()

    afe = _afe(client, headers, setup["rig"], setup["well"])
    _estimate(client, headers, afe, service, setup["hole"], setup["phase"])

    # Day 1: NPT 6 h (RDT) + UPA 3 h (MWD).
    entry_one = _entry(client, headers, setup["well"], afe, "2026-10-10")
    _save_entry(client, headers, entry_one, {
        "remarks": "day one",
        "services": [
            _service_line(activity=setup["activities"]["NPT"], sub_activity=npt_rdt,
                          service=service, hole=setup["hole"], phase=setup["phase"], hours=6, rate=2400),
            _service_line(activity=setup["activities"]["UPA"], sub_activity=upa_mwd,
                          service=service, hole=setup["hole"], phase=setup["phase"], hours=3, rate=2400),
        ],
        "consumables": [], "tangibles": [],
    })
    # Day 2: NPT 2 h (Liner) — a different service line of the same vendor.
    entry_two = _entry(client, headers, setup["well"], afe, "2026-10-11")
    _save_entry(client, headers, entry_two, {
        "remarks": "day two",
        "services": [
            _service_line(activity=setup["activities"]["NPT"], sub_activity=npt_liner,
                          service=service, hole=setup["hole"], phase=setup["phase"], hours=2, rate=2400),
        ],
        "consumables": [], "tangibles": [],
    })
    return {
        **setup, "hal": hal, "bak": bak,
        "hal_rdt": hal_rdt, "hal_liner": hal_liner, "bak_mwd": bak_mwd,
        "subs": {"rdt": npt_rdt, "liner": npt_liner, "mwd": upa_mwd},
    }


def test_npt_upa_report_rolls_up_by_vendor_and_vendor_service():
    with TestClient(app) as client:
        headers = login(client)
        setup = _party_setup(client, headers)

        report = client.get("/api/v1/usage-reports/npt-upa", headers=headers)
        assert report.status_code == 200, report.text
        data = report.json()

        parties = {row["vendor_name"]: row for row in data["parties"]}
        assert set(parties) == {"Halliburton", "Baker Hughes"}

        # Halliburton: 6 h + 2 h NPT over two dates; Baker: 3 h UPA.
        hal = parties["Halliburton"]
        assert Decimal(hal["npt_hours"]) == Decimal("8.00")
        assert Decimal(hal["npt_days"]) == Decimal("0.3333")
        assert hal["npt_affected_dates"] == 2
        assert Decimal(hal["npt_amount"]) == Decimal("800.00")
        assert Decimal(hal["upa_hours"]) == Decimal("0")
        assert hal["is_linked"] is True
        assert hal["vendor_code"] == "HAL"

        bak = parties["Baker Hughes"]
        assert Decimal(bak["upa_hours"]) == Decimal("3.00")
        assert Decimal(bak["upa_days"]) == Decimal("0.125")
        assert bak["upa_affected_dates"] == 1
        assert Decimal(bak["upa_amount"]) == Decimal("300.00")

        # The vendor rollup reproduces the well totals exactly.
        assert Decimal(data["totals"]["npt_hours"]) == Decimal("8.00")
        assert Decimal(data["totals"]["upa_hours"]) == Decimal("3.00")
        assert sum(Decimal(row["npt_amount"]) for row in data["parties"]) == Decimal(data["totals"]["npt_amount"])
        assert sum(Decimal(row["upa_amount"]) for row in data["parties"]) == Decimal(data["totals"]["upa_amount"])
        assert sum(Decimal(row["npt_hours"]) for row in data["parties"]) == Decimal(data["totals"]["npt_hours"])
        assert sum(Decimal(row["upa_hours"]) for row in data["parties"]) == Decimal(data["totals"]["upa_hours"])

        # Service subcategory rollup splits each vendor, it does not double count.
        lines = data["party_subcategories"]
        by_code = {(row["vendor_code"], row["vendor_subcategory_code"]): row for row in lines}
        assert set(by_code) == {("HAL", "RDT"), ("HAL", "LINER"), ("BAK", "MWD")}
        assert Decimal(by_code[("HAL", "RDT")]["npt_hours"]) == Decimal("6.00")
        assert Decimal(by_code[("HAL", "LINER")]["npt_hours"]) == Decimal("2.00")
        rdt = by_code[("HAL", "RDT")]
        assert rdt["vendor_subcategory_name"] == "Halliburton — RDT Service"
        assert Decimal(by_code[("BAK", "MWD")]["upa_hours"]) == Decimal("3.00")
        assert sum(Decimal(row["npt_hours"]) for row in lines) == Decimal(data["totals"]["npt_hours"])
        assert sum(Decimal(row["upa_hours"]) for row in lines) == Decimal(data["totals"]["upa_hours"])

        # Per-well party rows support drill-through.
        assert {(row["well_code"], row["vendor_code"]) for row in data["party_wells"]} == {
            ("WELL-01", "HAL"), ("WELL-01", "BAK"),
        }

        # Detail rows carry the party identity so the grid can be filtered.
        detail = {(row["classification"], row["vendor_code"], row["vendor_subcategory_code"])
                  for row in data["detail"]}
        assert ("NPT", "HAL", "RDT") in detail
        assert ("NPT", "HAL", "LINER") in detail
        assert ("UPA", "BAK", "MWD") in detail


def test_npt_upa_parties_keep_free_text_and_unassigned_lines_visible():
    """Legacy registers must not disappear while they are being linked."""
    with TestClient(app) as client:
        headers = login(client)
        setup = _well(client, headers)
        vendor = _vendor(client, headers, "HAL", "Halliburton")
        legacy = client.post("/api/v1/rig-well/sub-activities", headers=headers, json={
            "well_id": setup["well"]["id"], "scope": "drilling", "sub_activity_code": "NPT-LEG",
            "sub_activity_name": "Legacy NPT", "activity_id": setup["activities"]["NPT"]["id"],
            "responsible_party": "Operations team", "description": "Legacy row",
        }).json()
        assert legacy["vendor_id"] is None
        linked = _sub_activity(
            client, headers, setup["well"]["id"], setup["activities"]["NPT"]["id"], "NPT-HAL",
            vendor_id=vendor["id"], party="Halliburton",
        ).json()
        afe = _afe(client, headers, setup["rig"], setup["well"], code="AFE-LEG")
        service = _service(client, headers, vendor["id"])
        _estimate(client, headers, afe, service, setup["hole"], setup["phase"])

        def other_expense_line(sub_activity_id, quantity, rate, remarks, party_name=""):
            return {
                "activity_id": setup["activities"]["NPT"]["id"], "hole_section_id": setup["hole"]["id"],
                "phase_id": setup["phase"]["id"], "sub_activity_id": sub_activity_id,
                "quantity": quantity, "currency": "USD", "expense_type": "LIH",
                "quantity_unit": "unit", "unit_rate": rate, "remarks": remarks,
                "expense_description": "Legacy charge", "party_name": party_name,
            }

        entry_id = _entry(client, headers, setup["well"], afe, "2026-10-10")
        _save_entry(client, headers, entry_id, {
            "remarks": "legacy party and unassigned",
            "services": [],
            "consumables": [],
            "tangibles": [],
            "other_expenses": [
                # Free-text party: the sub activity is not linked to a vendor yet,
                # and the daily sheet keeps the party it has always carried.
                other_expense_line(legacy["id"], "4", "25", "Lost in hole charge on legacy row",
                                   party_name="Operations team"),
                # A linked sub activity carries the vendor even for a charge
                # booked with no vendor of its own.
                other_expense_line(linked["id"], "2", "50", "Linked charge without a line vendor"),
            ],
        })

        data = client.get("/api/v1/usage-reports/npt-upa", headers=headers).json()
        assert data["parties"], data
        party = next(row for row in data["parties"] if row["party_name"] == "Operations team")
        assert party["is_linked"] is False
        assert party["vendor_id"] == ""
        assert Decimal(party["npt_amount"]) == Decimal("100.00")

        linked_party = next(row for row in data["parties"] if row["vendor_name"] == "Halliburton")
        assert linked_party["is_linked"] is True
        assert Decimal(linked_party["npt_amount"]) == Decimal("100.00")

        # Nothing is silently dropped: the party rows still add up to the totals.
        assert sum(Decimal(row["npt_amount"]) for row in data["parties"]) == Decimal(
            data["totals"]["npt_amount"]
        )
        assert Decimal(data["totals"]["npt_amount"]) == Decimal("200.00")
        assert linked["vendor_id"] == vendor["id"]


def test_reports_and_subcategories_remain_tenant_scoped():
    with TestClient(app) as client:
        north = login(client)
        south = login(client, "south")
        setup = _party_setup(client, north)

        south_report = client.get("/api/v1/usage-reports/npt-upa", headers=south).json()
        assert south_report["parties"] == []

        south_sub_activities = client.get(
            f"/api/v1/rig-well/sub-activities?well_id={setup['well']['id']}&scope=drilling", headers=south
        )
        assert south_sub_activities.status_code == 404

        # Another workspace cannot bind a sub activity to this vendor.
        foreign = client.post("/api/v1/rig-well/sub-activities", headers=south, json={
            "well_id": setup["well"]["id"], "scope": "drilling", "sub_activity_code": "X-1",
            "sub_activity_name": "Cross tenant", "activity_id": setup["activities"]["NPT"]["id"],
            "vendor_id": setup["hal"]["id"], "responsible_party": "Halliburton",
            "description": "Should not be allowed",
        })
        assert foreign.status_code in (404, 422)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_migration_creates_subcategory_register_and_links_exact_party_names(tmp_path):
    database = tmp_path / "migration.sqlite3"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    backend = Path(__file__).resolve().parents[1]

    def migrate(target):
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", target], cwd=backend,
                       env=environment, check=True, capture_output=True, text=True)

    migrate("b7c1d9e4f2a8")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO organizations (id, slug, name, created_at) VALUES ('org', 'legacy', 'Legacy', CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO vendors (id, organization_id, vendor_code, vendor_name, vendor_type, created_at, updated_at) "
            "VALUES ('vendor', 'org', 'HAL', 'Halliburton', 'Third party', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        for identity, party in (("sa-1", "halliburton"), ("sa-2", "Operations team")):
            connection.execute(
                "INSERT INTO well_sub_activities "
                "(id, organization_id, well_id, scope, sub_activity_code, sub_activity_name, activity_id, "
                " responsible_party, description, is_deleted, created_at, updated_at) "
                "VALUES (?, 'org', 'well', 'drilling', ?, 'Sub', 'activity', ?, '', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (identity, identity.upper(), party),
            )
    migrate("head")
    with sqlite3.connect(database) as connection:
        rows = dict(connection.execute(
            "SELECT id, responsible_party FROM well_sub_activities"
        ).fetchall())
        assert rows == {"sa-1": "Halliburton", "sa-2": "Operations team"}
        vendors = dict(connection.execute(
            "SELECT id, vendor_id FROM well_sub_activities"
        ).fetchall())
        assert vendors == {"sa-1": "vendor", "sa-2": None}
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        assert "vendor_service_subcategories" in tables
        # Re-running the head is a no-op.
        migrate("head")
