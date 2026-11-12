import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import Afe, AuditLog, Organization, Permission, Role, User


PERMISSIONS = [
    *(f"template:{action}" for action in ("read", "create", "update", "delete", "export")),
    *(f"master-data:{action}" for action in ("read", "create", "update", "delete", "export")),
    *(f"rig-well:{action}" for action in ("read", "create", "update", "delete", "export")),
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
            role = Role(organization_id=organization.id, name="Owner", is_owner=True, permissions=permissions)
            db.add(User(
                organization_id=organization.id, email="owner@example.com", full_name="Test Owner",
                password_hash=hash_password("correct-password-123"), roles=[role],
            ))
        db.commit()
    yield


def login(client: TestClient, organization: str = "north", email: str = "owner@example.com") -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={
        "organization": organization, "email": email, "password": "correct-password-123",
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _post(client, path, headers, payload, status=201):
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == status, response.text
    return response.json()


def _seed(client, headers):
    assert client.post("/api/v1/master-data/currencies", headers=headers, json={
        "code": "USD", "name": "US Dollar", "symbol": "$",
    }).status_code == 201
    assert client.post("/api/v1/master-data/uom", headers=headers, json={
        "code": "MT", "name": "Metric tonne", "symbol": "MT",
    }).status_code == 201
    hole = _post(client, "/api/v1/master-data/hole-sections", headers, {"code": "17-1/2", "name": "Surface hole"})
    phase = _post(client, "/api/v1/master-data/phases", headers, {"code": "DRILL", "name": "Drilling"})
    vendor = _post(client, "/api/v1/master-data/vendors", headers, {
        "vendor_code": "VEND-01", "vendor_name": "Acme Services", "category": "Drilling", "status": "active",
    })
    service = _post(client, "/api/v1/master-data/services", headers, {
        "service_code": "MUD-LOG", "service_name": "Mud logging", "service_category": "Drilling Services",
        "service_group": "Formation Evaluation", "provider_type": "Third Party Services",
        "vendor_id": vendor["id"], "description": "Wellsite logging crew",
    })
    category = _post(client, "/api/v1/master-data/catalogue-options", headers, {
        "list_key": "tangible_category", "value": "Casing Accessories",
    })
    subcategory = _post(client, "/api/v1/master-data/catalogue-options", headers, {
        "list_key": "tangible_subcategory", "value": "Centralisers", "parent_id": category["id"],
    })
    manufacturer = _post(client, "/api/v1/master-data/catalogue-options", headers, {
        "list_key": "manufacturer", "value": "Weatherford",
    })
    tangible = _post(client, "/api/v1/master-data/tangibles", headers, {
        "tangible_code": "TNG-0001", "tangible_name": "Casing centraliser", "scope": "Drilling",
        "category_id": category["id"], "subcategory_id": subcategory["id"], "manufacturer_id": manufacturer["id"],
        "uom": "MT", "po_number": "PO-1", "unit_rate": "100", "cost_uplift": "100", "currency": "USD",
        "effective_date": "2026-01-31", "description": "", "remarks": "",
    })
    group = _post(client, "/api/v1/master-data/catalogue-options", headers, {
        "list_key": "mud_chemical_group", "value": "Weighting agent",
    })
    chemical = _post(client, "/api/v1/master-data/mud-chemicals", headers, {
        "chemical_code": "BARITE", "chemical_name": "Barite", "group_id": group["id"], "uom": "MT",
        "unit_rate": "10", "currency": "USD", "effective_date": "2026-01-15",
    })
    return {"hole": hole, "phase": phase, "service": service, "tangible": tangible, "chemical": chemical}


def _afe_payload(seed, **overrides):
    payload = {
        "template_kind": "afe",
        "name": "Standard 17-1/2 drilling AFE",
        "description": "Standard surface hole estimate",
        "scope": "Drilling",
        "afe_type": "Drilling",
        "standard_currency": "usd",
        "is_shared": False,
        "services": [{
            "service_id": seed["service"]["id"], "charging_basis": "Day Rate",
            "section_code": "17-1/2", "phase_code": "DRILL", "currency": "USD", "service_amount": "0",
            "operation_rate": "100", "operation_days": "10", "standby_rate": "50", "standby_days": "1",
            "quantity_unit": "days", "remarks": "",
        }],
        "consumables": [{
            "category": "Mud Chemicals", "section_code": "17-1/2", "phase_code": "DRILL",
            "quantity": "1", "estimated_amount": "5000", "currency": "USD", "remarks": "Bulk allowance",
        }],
        "tangibles": [{"tangible_id": seed["tangible"]["id"], "quantity": "2", "remarks": ""}],
    }
    payload.update(overrides)
    return payload


def _well_payload(seed, **overrides):
    payload = {
        "template_kind": "well",
        "name": "Development well plan",
        "description": "Three-section development plan",
        "scope": "Drilling",
        "standard_currency": "",
        "is_shared": True,
        "sections": [{
            "hole_section_id": seed["hole"]["id"], "from_depth": "0", "to_depth": "1000",
            "remarks": "",
            "phases": [{"phase_id": seed["phase"]["id"], "days": "10", "remarks": ""}],
        }],
    }
    payload.update(overrides)
    return payload


def test_afe_estimate_template_saves_the_structure_and_is_readable_afterwards():
    with TestClient(app) as client:
        headers = login(client)
        seed = _seed(client, headers)

        created = _post(client, "/api/v1/record-templates", headers, _afe_payload(seed))
        assert created["template_kind"] == "afe"
        assert created["standard_currency"] == "USD"
        assert created["scope"] == "Drilling"
        assert created["is_owner"] is True and created["is_shared"] is False
        assert created["line_count"] == 3
        assert created["unavailable_count"] == 0
        # Scope codes are matched and shown readable, not as raw ids.
        assert created["services"][0]["section_label"] == "17-1/2 · Surface hole"
        assert created["services"][0]["phase_label"] == "DRILL · Drilling"
        assert created["services"][0]["service_code"] == "MUD-LOG"
        assert created["tangibles"][0]["tangible_code"] == "TNG-0001"

        listing = client.get("/api/v1/record-templates?kind=afe", headers=headers)
        assert listing.status_code == 200, listing.text
        assert [row["name"] for row in listing.json()] == ["Standard 17-1/2 drilling AFE"]
        assert listing.json()[0]["line_count"] == 3
        assert client.get("/api/v1/record-templates?kind=well", headers=headers).json() == []

        # A template can be edited in place, keeping the same record.
        updated = client.put(f"/api/v1/record-templates/{created['id']}", headers=headers, json=_afe_payload(
            seed, name="Standard 17-1/2 drilling AFE v2", services=[],
        ))
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Standard 17-1/2 drilling AFE v2"
        assert updated.json()["line_count"] == 2

        with SessionLocal() as db:
            actions = [row.action for row in db.query(AuditLog).all()]
        assert "create" in actions and "update" in actions


def test_well_plan_template_saves_sections_and_previews_against_a_well():
    with TestClient(app) as client:
        headers = login(client)
        seed = _seed(client, headers)
        template = _post(client, "/api/v1/record-templates", headers, _well_payload(seed))
        assert template["template_kind"] == "well"
        assert template["line_count"] == 1  # one phase
        assert template["sections"][0]["section_code"] == "17-1/2"
        assert template["sections"][0]["phases"][0]["phase_code"] == "DRILL"
        # Decimals leave the API as operator-readable text, never 1E+1 or 10.0000000000.
        assert template["sections"][0]["phases"][0]["days"] == "10"
        assert template["sections"][0]["from_depth"] == "0"
        assert template["sections"][0]["to_depth"] == "1000"

        # A well whose plan does not use the section is told so before applying.
        rig = _post(client, "/api/v1/rig-well/rigs", headers, {"rig_code": "RIG-01", "rig_name": "Rig One", "remarks": ""})
        block = _post(client, "/api/v1/rig-well/blocks", headers, {"block_code": "BLK-A", "block_name": "Block A", "description": ""})
        well = _post(client, "/api/v1/rig-well/wells", headers, {
            "rig_id": rig["id"], "block_id": block["id"], "well_code": "WELL-01", "well_name": "Well One",
            "well_location": "North", "objective": "Development", "remarks": "",
        })
        preview = client.post(f"/api/v1/record-templates/{template['id']}/preview", headers=headers, json={"well_id": well["id"]})
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["can_apply"] is True
        assert body["sections"][0]["is_available"] is True
        assert any("does not use 17-1/2" in warning for warning in body["warnings"])
        # The preview describes the section in readable numbers, never raw decimals.
        assert body["sections"][0]["note"].startswith("0–1000 m")

        # Applying only counts the use: it never writes a well plan.
        applied = client.post(f"/api/v1/record-templates/{template['id']}/apply", headers=headers)
        assert applied.status_code == 200, applied.text
        assert applied.json()["use_count"] == 1
        assert applied.json()["last_used_at"] is not None
        config = client.get(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers)
        assert config.status_code in (200, 404)
        if config.status_code == 200:
            assert config.json().get("sections", []) == []


def test_template_rules_reject_mixed_kinds_duplicates_and_missing_lines():
    with TestClient(app) as client:
        headers = login(client)
        seed = _seed(client, headers)

        mixed = client.post("/api/v1/record-templates", headers=headers, json=_well_payload(seed, services=[{
            "service_id": seed["service"]["id"],
        }]))
        assert mixed.status_code == 422
        assert "hole sections and phases only" in mixed.json()["detail"]

        empty = client.post("/api/v1/record-templates", headers=headers, json=_afe_payload(seed, services=[], consumables=[], tangibles=[]))
        assert empty.status_code == 422

        no_sections = client.post("/api/v1/record-templates", headers=headers, json=_well_payload(seed, sections=[]))
        assert no_sections.status_code == 422

        duplicated = client.post("/api/v1/record-templates", headers=headers, json=_afe_payload(seed, services=[
            {"service_id": seed["service"]["id"], "section_code": "17-1/2", "phase_code": "DRILL"},
            {"service_id": seed["service"]["id"], "section_code": "17-1/2", "phase_code": "DRILL"},
        ]))
        assert duplicated.status_code == 422
        assert "appears twice" in duplicated.json()["detail"]

        # One name per kind per user.
        _post(client, "/api/v1/record-templates", headers, _afe_payload(seed))
        clash = client.post("/api/v1/record-templates", headers=headers, json=_afe_payload(seed, name="  standard 17-1/2 DRILLING afe  "))
        assert clash.status_code == 409

        # A kind cannot be changed under an existing template.
        created = client.get("/api/v1/record-templates?kind=afe", headers=headers).json()[0]
        changed = client.put(f"/api/v1/record-templates/{created['id']}", headers=headers, json=_well_payload(seed))
        assert changed.status_code == 422
        assert "cannot become" in changed.json()["detail"]


def test_shared_templates_are_read_only_and_can_be_copied():
    with TestClient(app) as client:
        headers = login(client)
        seed = _seed(client, headers)
        shared = _post(client, "/api/v1/record-templates", headers, _well_payload(seed, is_shared=True))

        with SessionLocal() as db:
            organization = db.query(Organization).filter(Organization.slug == "north").one()
            owner_role = db.query(Role).filter(Role.organization_id == organization.id).one()
            db.add(User(
                organization_id=organization.id, email="second@example.com", full_name="Second User",
                password_hash=hash_password("correct-password-123"), roles=[owner_role],
            ))
            db.commit()
        second = login(client, email="second@example.com")

        visible = client.get("/api/v1/record-templates?kind=well", headers=second)
        assert visible.status_code == 200
        assert [row["name"] for row in visible.json()] == ["Development well plan"]
        assert visible.json()[0]["is_shared"] is True

        # Editing or deleting somebody else's shared template is refused.
        assert client.put(f"/api/v1/record-templates/{shared['id']}", headers=second, json=_well_payload(seed)).status_code == 403
        assert client.delete(f"/api/v1/record-templates/{shared['id']}", headers=second).status_code == 403

        # Copying gives the second user an editable copy of their own.
        copied = client.post(f"/api/v1/record-templates/{shared['id']}/duplicate", headers=second)
        assert copied.status_code == 201, copied.text
        assert copied.json()["name"] == "Development well plan (copy)"
        assert copied.json()["is_owner"] is True and copied.json()["is_shared"] is False
        assert copied.json()["sections"][0]["section_code"] == "17-1/2"
        assert client.get("/api/v1/record-templates?kind=well", headers=second).json()[0]["is_owner"] is True


def test_templates_are_tenant_scoped_soft_deleted_and_exported():
    with TestClient(app) as client:
        headers = login(client)
        seed = _seed(client, headers)
        template = _post(client, "/api/v1/record-templates", headers, _afe_payload(seed))

        other = login(client, "south")
        assert client.get("/api/v1/record-templates", headers=other).json() == []
        assert client.get(f"/api/v1/record-templates/{template['id']}", headers=other).status_code == 404

        exported = client.get("/api/v1/record-templates/export?kind=afe", headers=headers)
        assert exported.status_code == 200
        assert "text/csv" in exported.headers["content-type"]
        text = exported.content.decode("utf-8-sig")
        header = text.splitlines()[0].split(",")
        # Every row stands on its own: what kind of line it is, the item it names,
        # its money and its quantity all travel in named columns.
        assert {"line_type", "item_code", "item_name", "quantity", "currency", "amount"} <= set(header)
        service_row = next(line for line in text.splitlines() if line.startswith("Standard 17-1/2 drilling AFE"))
        fields = dict(zip(header, service_row.split(",")))
        assert fields["line_type"] == "Service"
        assert fields["item_code"] == "MUD-LOG"
        assert fields["amount"] and fields["currency"] == "USD"
        assert "MUD-LOG" in text and "Standard 17-1/2 drilling AFE" in text
        assert client.post("/api/v1/record-templates/export-audit", headers=headers, json={
            "format": "csv", "record_count": 3,
        }).status_code == 204

        # Deleting a referenced master-data record makes the line show as unavailable
        # instead of breaking the template.
        assert client.delete(f"/api/v1/master-data/services/{seed['service']['id']}", headers=headers).status_code == 200
        after = client.get(f"/api/v1/record-templates/{template['id']}", headers=headers).json()
        assert after["services"][0]["is_available"] is False
        assert after["unavailable_count"] == 1
        preview = client.post(f"/api/v1/record-templates/{template['id']}/preview", headers=headers, json={}).json()
        assert preview["can_apply"] is True
        assert any("no longer in Master Data" in warning for warning in preview["warnings"])

        assert client.delete(f"/api/v1/record-templates/{template['id']}", headers=headers).status_code == 204
        assert client.get("/api/v1/record-templates", headers=headers).json() == []
        assert client.get(f"/api/v1/record-templates/{template['id']}", headers=headers).status_code == 404
        with SessionLocal() as db:
            assert any(row.action == "soft_delete" for row in db.query(AuditLog).all())


def test_apply_is_audited_counts_one_use_and_never_writes_a_record():
    """Applying a template is a starting point, not a record.

    It bumps use_count/last_used_at and writes an `apply` audit entry, and it
    leaves the AFE register untouched — the page's own save creates the record.
    """
    with TestClient(app) as client:
        headers = login(client)
        seed = _seed(client, headers)
        template = _post(client, "/api/v1/record-templates", headers, _afe_payload(seed))
        assert template["use_count"] == 0 and template["last_used_at"] is None

        applied = client.post(f"/api/v1/record-templates/{template['id']}/apply", headers=headers)
        assert applied.status_code == 200
        body = applied.json()
        assert body["use_count"] == 1
        assert body["last_used_at"] is not None

        again = client.post(f"/api/v1/record-templates/{template['id']}/apply", headers=headers).json()
        assert again["use_count"] == 2

        with SessionLocal() as db:
            applies = [row for row in db.query(AuditLog).all() if row.action == "apply"]
            assert len(applies) == 2
            assert all(row.entity_type == "record_template" for row in applies)

        # Nothing was created: the template is a starting point for a record the
        # estimator saves themselves. Count rows directly, because this workspace's
        # role holds only the template and master-data capabilities.
        with SessionLocal() as db:
            assert db.query(Afe).count() == 0
