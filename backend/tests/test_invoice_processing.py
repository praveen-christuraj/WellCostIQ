import os
import tempfile
from decimal import Decimal

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User

CAPABILITIES = [
    *(f"master-data:{action}" for action in ("read", "create", "update", "delete", "restore", "permanent-delete", "import", "export")),
    *(f"rig-well:{action}" for action in ("read", "create", "update", "delete", "restore", "permanent-delete", "import", "export")),
    *(f"invoice-processing:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
        "configure", "submit", "verify", "epicor", "approve", "payment",
        "document-upload", "document-download", "document-delete",
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
            permissions = [Permission(organization_id=organization.id, key=key, description=key) for key in CAPABILITIES]
            owner = Role(organization_id=organization.id, name="Owner", is_owner=True, permissions=permissions)
            db.add(User(
                organization_id=organization.id, email="owner@example.com", full_name="Test Owner",
                password_hash=hash_password("correct-password-123"), roles=[owner],
            ))
        db.commit()
    yield


def login(client: TestClient, organization: str = "north") -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={
        "organization": organization, "email": "owner@example.com", "password": "correct-password-123",
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_currency(client, headers, code="USD", default=False):
    response = client.post("/api/v1/master-data/currencies", headers=headers, json={
        "code": code, "name": "US Dollar" if code == "USD" else "Nigerian Naira",
        "symbol": "$" if code == "USD" else "₦", "description": "", "is_default": default,
    })
    assert response.status_code == 201, response.text
    return response.json()


def create_commercial_scope(client, headers):
    create_currency(client, headers, "USD", True)
    create_currency(client, headers, "NGN")
    vendor = client.post("/api/v1/master-data/vendors", headers=headers, json={
        "vendor_code": "VEND-01", "vendor_name": "Example Oilfield Services", "vendor_type": "Third party",
        "category": "Drilling", "status": "active", "credit_terms_days": 45, "description": "",
    })
    assert vendor.status_code == 201, vendor.text
    vendor = vendor.json()
    order = client.post("/api/v1/master-data/po-so-orders", headers=headers, json={
        "order_number": "PO-001", "order_type": "PO", "vendor_id": vendor["id"],
        "issue_date": "2026-01-01", "expiry_date": "2026-12-31", "status": "open", "description": "",
    })
    assert order.status_code == 201, order.text
    order = order.json()
    block = client.post("/api/v1/rig-well/blocks", headers=headers, json={
        "block_code": "OML-01", "block_name": "Example Block", "description": "",
    }).json()
    rig = client.post("/api/v1/rig-well/rigs", headers=headers, json={
        "rig_code": "RIG-01", "rig_name": "Example Rig", "remarks": "",
    }).json()
    well = client.post("/api/v1/rig-well/wells", headers=headers, json={
        "rig_id": rig["id"], "block_id": block["id"], "well_code": "WELL-01", "well_name": "Example Well",
        "well_location": "Example Location", "objective": "Production", "remarks": "",
    })
    assert well.status_code == 201, well.text
    return vendor, order, block, rig, well.json()


def create_configuration(client, headers, vendor, block):
    location = client.post("/api/v1/invoice-processing/config/locations", headers=headers, json={
        "name": "Port Harcourt", "description": "Main base", "is_active": True,
    })
    assert location.status_code == 201, location.text
    location = location.json()
    category = client.post("/api/v1/invoice-processing/config/categories", headers=headers, json={
        "name": "Completion Services", "description": "", "is_active": True,
    }).json()
    vat = client.post("/api/v1/invoice-processing/config/taxes", headers=headers, json={
        "tax_code": "VAT", "tax_name": "VAT", "rate_percent": "7.5", "direction": "addition",
        "is_common": True, "description": "", "is_active": True, "vendor_ids": [],
    })
    assert vat.status_code == 201, vat.text
    wht = client.post("/api/v1/invoice-processing/config/taxes", headers=headers, json={
        "tax_code": "WHT", "tax_name": "Withholding Tax", "rate_percent": "5", "direction": "deduction",
        "is_common": False, "description": "", "is_active": True, "vendor_ids": [vendor["id"]],
    })
    assert wht.status_code == 201, wht.text
    rate = client.post("/api/v1/invoice-processing/config/exchange-rates", headers=headers, json={
        "base_currency": "USD", "quote_currency": "NGN", "rate": "1600", "description": "Budget rate", "is_active": True,
    })
    assert rate.status_code == 201, rate.text
    term = client.post("/api/v1/invoice-processing/config/payment-terms", headers=headers, json={
        "term_code": "30-60-40", "term_name": "30 days · 60% USD / 40% NGN", "payment_days": 30,
        "description": "Standard split", "is_active": True,
        "splits": [{"currency_code": "USD", "percentage": "60"}, {"currency_code": "NGN", "percentage": "40"}],
        "vendor_ids": [vendor["id"]],
    })
    assert term.status_code == 201, term.text
    # Replacing unique child currencies/vendor links on configuration edit must
    # flush removals before reinserting the same keys.
    updated_wht = client.patch(f"/api/v1/invoice-processing/config/taxes/{wht.json()['id']}", headers=headers, json={
        "tax_code": "WHT", "tax_name": "Withholding Tax", "rate_percent": "5", "direction": "deduction",
        "is_common": False, "description": "", "is_active": True, "vendor_ids": [vendor["id"]],
    })
    assert updated_wht.status_code == 200, updated_wht.text
    updated_term = client.patch(f"/api/v1/invoice-processing/config/payment-terms/{term.json()['id']}", headers=headers, json={
        "term_code": "30-60-40", "term_name": "30 days · 60% USD / 40% NGN", "payment_days": 30,
        "description": "Standard split", "is_active": True,
        "splits": [{"currency_code": "USD", "percentage": "60"}, {"currency_code": "NGN", "percentage": "40"}],
        "vendor_ids": [vendor["id"]],
    })
    assert updated_term.status_code == 200, updated_term.text
    assert len(updated_term.json()["splits"]) == 2 and updated_term.json()["vendor_ids"] == [vendor["id"]]
    classified = client.put(f"/api/v1/invoice-processing/config/blocks/{block['id']}", headers=headers, json={"category": "jv"})
    assert classified.status_code == 200, classified.text
    return location, category, term.json()


def invoice_payload(vendor, order, block, rig, well, location, category, term):
    return {
        "idvs_date": "2026-01-03", "invoice_number": "INV-001", "invoice_date": "2026-01-01",
        "invoice_received_date": "2026-01-03", "vendor_id": vendor["id"], "order_id": order["id"],
        "block_id": block["id"], "rig_id": rig["id"], "well_id": well["id"], "location_id": location["id"],
        "field_name": "Example Field", "phase": "Completion", "description_category_id": category["id"],
        "service_description": "Completion equipment", "detailed_description": "Two verification lines",
        "concerned_person": "Cost Engineer", "service_from": "2025-12-01", "service_to": "2025-12-31",
        "currency_code": "USD", "payment_term_id": term["id"], "payment_tenure_days": None,
        "disallowed_amount": "4.5", "advance_amount": "10", "remarks": "Initial IDVS",
        "lines": [{
            "description": "Packers", "invoice_quantity": "2", "invoice_unit_price": "100",
            "verified_quantity": "2", "verified_unit_price": "90", "remarks": "Contract rate",
        }],
        "taxes": None, "payment_splits": None,
    }


def test_idvs_calculations_workflow_documents_dashboard_and_tenant_isolation():
    with TestClient(app) as client:
        north = login(client)
        south = login(client, "south")
        vendor, order, block, rig, well = create_commercial_scope(client, north)
        location, category, term = create_configuration(client, north, vendor, block)
        references = client.get("/api/v1/invoice-processing/reference", headers=north)
        assert references.status_code == 200, references.text
        assert references.json()["vendors"][0]["payment_term_id"] == term["id"]
        assert {item["currency_code"] for item in references.json()["currencies"]} == {"USD", "NGN"}
        configuration = client.get("/api/v1/invoice-processing/configuration", headers=north)
        assert configuration.status_code == 200
        assert configuration.json()["vendors"][0]["id"] == vendor["id"]
        payload = invoice_payload(vendor, order, block, rig, well, location, category, term)
        created = client.post("/api/v1/invoice-processing/invoices", headers=north, json=payload)
        assert created.status_code == 201, created.text
        row = created.json()
        assert row["idvs_number"] == "IDVS-2026-00001"
        assert row["due_date"] == "2026-01-31"
        assert Decimal(row["invoice_subtotal"]) == Decimal("200")
        assert Decimal(row["verified_subtotal"]) == Decimal("180")
        assert Decimal(row["invoice_tax_total"]) == Decimal("5")
        assert Decimal(row["verified_tax_total"]) == Decimal("4.5")
        assert Decimal(row["invoice_total"]) == Decimal("205")
        assert Decimal(row["verified_total"]) == Decimal("184.5")
        assert Decimal(row["adjusted_verified_amount"]) == Decimal("170")
        assert Decimal(row["difference_amount"]) == Decimal("20.5")
        assert {tax["source"] for tax in row["taxes"]} == {"common", "vendor"}
        splits = {split["currency_code"]: split for split in row["payment_splits"]}
        assert Decimal(splits["USD"]["amount"]) == Decimal("102")
        assert Decimal(splits["NGN"]["amount"]) == Decimal("108800")
        assert row["block_category"] == "jv"

        # A Draft remains editable, including replacement of its unique-per-invoice
        # payment split rows; the revision guard protects concurrent sessions.
        draft_update = {**payload, "service_description": "Corrected completion equipment", "expected_revision": row["revision"]}
        updated = client.put(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=north, json=draft_update)
        assert updated.status_code == 200, updated.text
        row = updated.json()
        assert row["revision"] == 1 and row["service_description"] == "Corrected completion equipment"
        assert len(row["payment_splits"]) == 2
        stale = client.put(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=north, json={**draft_update, "expected_revision": 0})
        assert stale.status_code == 409

        # Cross-tenant identifiers never resolve, and workflow order is server-enforced.
        assert client.get(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=south).status_code == 404
        wrong = client.post(f"/api/v1/invoice-processing/invoices/{row['id']}/workflow", headers=north, json={
            "action": "approve_epicor", "action_date": "2026-01-05", "remarks": "Too early",
        })
        assert wrong.status_code == 409
        for action, day, expected in (
            ("submit", "2026-01-04", "submitted"),
            ("send_to_accounts", "2026-01-06", "sent_to_accounts"),
            ("receive_epicor", "2026-01-08", "epicor_pending"),
            ("approve_epicor", "2026-01-10", "approved"),
        ):
            moved = client.post(f"/api/v1/invoice-processing/invoices/{row['id']}/workflow", headers=north, json={
                "action": action, "action_date": day, "remarks": f"{action} checked",
            })
            assert moved.status_code == 200, moved.text
            assert moved.json()["status"] == expected
        locked = client.put(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=north, json=payload)
        assert locked.status_code == 409
        paid = client.post(f"/api/v1/invoice-processing/invoices/{row['id']}/payment", headers=north, json={
            "paid_date": "2026-01-15", "payment_reference": "EPICOR-PAY-01", "remarks": "Settled",
        })
        assert paid.status_code == 200, paid.text
        assert paid.json()["display_status"] == "paid"
        assert len(paid.json()["history"]) == 5

        document = client.post(f"/api/v1/invoice-processing/invoices/{row['id']}/attachments", headers=north,
            files={"files": ("support.pdf", b"%PDF-1.4 supporting document", "application/pdf")},
            data={"label": "Signed field ticket", "notes": "Source document"},
        )
        assert document.status_code == 201, document.text
        attachment = document.json()[0]
        assert attachment["is_pdf"] is True and attachment["can_inline"] is True
        opened = client.get(f"/api/v1/invoice-processing/attachments/{attachment['id']}/content?inline=true", headers=north)
        assert opened.status_code == 200
        assert opened.headers["content-disposition"].startswith("inline")
        assert opened.content.startswith(b"%PDF")
        spreadsheet = client.post(f"/api/v1/invoice-processing/invoices/{row['id']}/attachments", headers=north,
            files={"files": ("support.xlsx", b"workbook bytes", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert spreadsheet.status_code == 201
        assert spreadsheet.json()[0]["is_pdf"] is False and spreadsheet.json()[0]["can_inline"] is False
        downloaded = client.get(f"/api/v1/invoice-processing/attachments/{spreadsheet.json()[0]['id']}/content?inline=true", headers=north)
        assert downloaded.headers["content-disposition"].startswith("attachment")
        oversized = client.post(
            f"/api/v1/invoice-processing/invoices/{row['id']}/attachments", headers=north,
            files={"files": ("too-large.pdf", b"x" * (25 * 1024 * 1024 + 1), "application/pdf")},
        )
        assert oversized.status_code == 413

        dashboard = client.get("/api/v1/invoice-processing/dashboard", headers=north)
        assert dashboard.status_code == 200, dashboard.text
        data = dashboard.json()
        assert data["total_invoices"] == 1 and data["paid_count"] == 1
        assert data["jv_block_count"] == 1 and data["attachment_count"] == 2
        assert data["currency_totals"][0]["currency_code"] == "USD"
        assert data["vendor_rows"][0]["verified_total"] == "184.5000000000"
        assert data["block_rows"][0]["block_code"] == "OML-01"
        assert len(data["ageing_rows"]) == 5
        assert {row["currency_code"] for row in data["ageing_rows"]} == {"USD"}
        assert data["recent_activity"][0]["action_label"] == "Paid date recorded"
        assert data["recent_activity"][0]["invoice_id"] == row["id"]
        assert client.post("/api/v1/invoice-processing/export-audit", headers=north, json={
            "module": "idvs", "format": "pdf", "record_count": 1, "detail": row["idvs_number"],
        }).status_code == 204
        with SessionLocal() as db:
            actions = {entry.action for entry in db.query(AuditLog).all()}
            assert {"create", "submit", "send_to_accounts", "receive_epicor", "approve_epicor", "payment", "document_upload", "document_download", "export"}.issubset(actions)
        assert client.post("/api/v1/invoice-processing/invoices/bulk-delete", headers=north, json={"ids": [row["id"]]}).status_code == 200
        deleted_detail = client.get(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=north)
        assert deleted_detail.status_code == 200 and deleted_detail.json()["is_deleted"] is True
        assert client.delete(f"/api/v1/invoice-processing/attachments/{spreadsheet.json()[0]['id']}", headers=north).status_code == 409
        assert client.post("/api/v1/invoice-processing/invoices/bulk-restore", headers=north, json={"ids": [row["id"]]}).status_code == 200


def test_multiline_import_lifecycle_and_row_errors():
    with TestClient(app) as client:
        headers = login(client)
        vendor, order, block, rig, well = create_commercial_scope(client, headers)
        location, category, term = create_configuration(client, headers, vendor, block)
        base = {
            "idvs_number": "IDVS-IMPORT-01", "idvs_date": "2026-02-03", "invoice_received_date": "2026-02-03",
            "vendor_code": "VEND-01", "order_number": "PO-001", "invoice_number": "INV-IMPORT",
            "invoice_date": "2026-02-01", "block_code": "OML-01", "rig_code": "RIG-01", "well_code": "WELL-01",
            "location": "Port Harcourt", "description_category": "Completion Services",
            "service_description": "Imported services", "detailed_description": "", "concerned_person": "",
            "field_name": "", "phase": "Drilling", "service_from": "", "service_to": "", "currency_code": "USD",
            "payment_term_code": "30-60-40", "payment_tenure_days": "", "disallowed_amount": 0,
            "advance_amount": 0, "line_remarks": "", "remarks": "",
        }
        rows = [
            {**base, "description": "Line one", "invoice_quantity": 2, "invoice_unit_price": 50, "verified_quantity": 2, "verified_unit_price": 50},
            {**base, "description": "Line two", "invoice_quantity": 1, "invoice_unit_price": 25, "verified_quantity": 1, "verified_unit_price": 20},
        ]
        imported = client.post("/api/v1/invoice-processing/import", headers=headers, json={"rows": rows})
        assert imported.status_code == 200, imported.text
        assert imported.json() == {"imported_count": 2, "invoice_count": 1, "errors": [], "success": True}
        listing = client.get("/api/v1/invoice-processing/invoices", headers=headers).json()
        assert len(listing) == 1 and listing[0]["line_count"] == 2
        invoice_id = listing[0]["id"]
        detail = client.get(f"/api/v1/invoice-processing/invoices/{invoice_id}", headers=headers).json()
        assert Decimal(detail["invoice_subtotal"]) == Decimal("125")
        assert Decimal(detail["verified_subtotal"]) == Decimal("120")

        bad = client.post("/api/v1/invoice-processing/import", headers=headers, json={"rows": [
            {**base, "invoice_number": "INV-BAD", "location": "Missing", "description": "Bad", "invoice_quantity": 1, "invoice_unit_price": 1},
        ]})
        assert bad.json()["success"] is False and "Row 2" in bad.json()["errors"][0]
        assert len(client.get("/api/v1/invoice-processing/invoices", headers=headers).json()) == 1

        assert client.post("/api/v1/invoice-processing/invoices/bulk-delete", headers=headers, json={"ids": [invoice_id]}).status_code == 200
        assert client.get("/api/v1/invoice-processing/invoices", headers=headers).json() == []
        assert len(client.get("/api/v1/invoice-processing/invoices/deleted", headers=headers).json()) == 1
        assert client.post("/api/v1/invoice-processing/invoices/bulk-restore", headers=headers, json={"ids": [invoice_id]}).status_code == 200
        assert client.post("/api/v1/invoice-processing/invoices/bulk-delete", headers=headers, json={"ids": [invoice_id]}).status_code == 200
        assert client.post("/api/v1/invoice-processing/invoices/bulk-permanent-delete", headers=headers, json={"ids": [invoice_id]}).status_code == 200
        assert client.get("/api/v1/invoice-processing/invoices/deleted", headers=headers).json() == []


def test_invoice_capabilities_are_independently_enforced():
    with SessionLocal() as db:
        organization = db.query(Organization).filter_by(slug="north").one()
        read = db.query(Permission).filter_by(organization_id=organization.id, key="invoice-processing:read").one()
        reviewer_role = Role(organization_id=organization.id, name="Invoice read only", permissions=[read])
        db.add(User(
            organization_id=organization.id, email="reviewer@example.com", full_name="Invoice Reviewer",
            password_hash=hash_password("correct-password-123"), roles=[reviewer_role],
        ))
        db.commit()
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={
            "organization": "north", "email": "reviewer@example.com", "password": "correct-password-123",
        })
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        assert client.get("/api/v1/invoice-processing/dashboard", headers=headers).status_code == 200
        assert client.get("/api/v1/invoice-processing/configuration", headers=headers).status_code == 403
        assert client.post("/api/v1/invoice-processing/invoices", headers=headers, json={}).status_code == 403
        assert client.post("/api/v1/invoice-processing/invoices/not-an-id/workflow", headers=headers, json={
            "action": "submit", "action_date": "2026-01-01", "remarks": "",
        }).status_code == 403
        assert client.post("/api/v1/invoice-processing/export-audit", headers=headers, json={
            "module": "idvs", "format": "csv", "record_count": 0, "detail": "",
        }).status_code == 403
        assert client.post("/api/v1/invoice-processing/invoices/bulk-delete", headers=headers, json={"ids": ["not-an-id"]}).status_code == 403


SIGNATORY_BASE = "/api/v1/invoice-processing/config/signatories"


def create_signatories(client, headers):
    people = {}
    for role, name, designation in (
        ("prepared", "Ada Okafor", "Cost Engineer"),
        ("checked", "Chidi Nwosu", "Senior Cost Analyst"),
        ("verified", "Ngozi Eze", "Finance Manager"),
        ("approved", "Tunde Bello", "Country Manager"),
    ):
        response = client.post(SIGNATORY_BASE, headers=headers, json={
            "signatory_role": role, "full_name": name, "designation": designation, "is_active": True,
        })
        assert response.status_code == 201, response.text
        people[role] = response.json()
    return people


def all_signatures(people):
    return [{"role": role, "signatory_id": people[role]["id"]} for role in ("prepared", "checked", "verified", "approved")]


def test_idvs_day_count_and_sign_off_signatories():
    with TestClient(app) as client:
        headers = login(client)
        vendor, order, block, rig, well = create_commercial_scope(client, headers)
        location, category, term = create_configuration(client, headers, vendor, block)
        people = create_signatories(client, headers)

        # Names are unique per role, case-insensitively; the same name may serve another role.
        duplicate = client.post(SIGNATORY_BASE, headers=headers, json={
            "signatory_role": "prepared", "full_name": "ada okafor", "designation": "", "is_active": True,
        })
        assert duplicate.status_code == 409, duplicate.text
        assert client.post(SIGNATORY_BASE, headers=headers, json={
            "signatory_role": "ceo", "full_name": "Nobody", "designation": "", "is_active": True,
        }).status_code == 422
        references = client.get("/api/v1/invoice-processing/reference", headers=headers).json()
        assert len(references["signatories"]) == 4
        assert references["signatories"][0]["label"] == "Ada Okafor — Cost Engineer"
        configuration = client.get("/api/v1/invoice-processing/configuration", headers=headers).json()
        assert len(configuration["signatories"]) == 4

        # Days are ignored (stored as 1) while the IDVS day count is off, so totals keep the qty × price pattern.
        payload = invoice_payload(vendor, order, block, rig, well, location, category, term)
        payload["lines"] = [{
            "description": "Packers", "invoice_quantity": "2", "invoice_days": "5", "invoice_unit_price": "100",
            "verified_quantity": "2", "verified_days": "3", "verified_unit_price": "90", "remarks": "",
        }]
        payload["signatures"] = all_signatures(people)
        created = client.post("/api/v1/invoice-processing/invoices", headers=headers, json=payload)
        assert created.status_code == 201, created.text
        row = created.json()
        assert row["day_count_enabled"] is False
        line = row["lines"][0]
        assert Decimal(line["invoice_days"]) == Decimal("1") and Decimal(line["verified_days"]) == Decimal("1")
        assert Decimal(row["invoice_subtotal"]) == Decimal("200") and Decimal(row["verified_subtotal"]) == Decimal("180")
        signatures = {item["role"]: item for item in row["signatures"]}
        assert signatures["prepared"]["name"] == "Ada Okafor" and signatures["prepared"]["designation"] == "Cost Engineer"
        assert signatures["approved"]["signatory_id"] == people["approved"]["id"]

        # With the day count on, total = qty × days × unit price on both sides.
        payload.update({"day_count_enabled": True, "expected_revision": row["revision"]})
        payload["lines"][0].update({"invoice_days": "3", "verified_days": "2"})
        updated = client.put(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=headers, json=payload)
        assert updated.status_code == 200, updated.text
        row = updated.json()
        assert row["day_count_enabled"] is True and row["revision"] == 1
        line = row["lines"][0]
        assert Decimal(line["invoice_total"]) == Decimal("600") and Decimal(line["verified_total"]) == Decimal("360")
        assert Decimal(row["invoice_subtotal"]) == Decimal("600") and Decimal(row["verified_subtotal"]) == Decimal("360")
        assert Decimal(line["difference_amount"]) == Decimal("240")

        # Verified days default to invoice days when omitted; zero invoice days is rejected.
        payload["lines"][0].pop("verified_days")
        defaulted = client.put(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=headers, json={**payload, "expected_revision": row["revision"]})
        assert defaulted.status_code == 200, defaulted.text
        assert Decimal(defaulted.json()["lines"][0]["verified_days"]) == Decimal("3")
        payload["lines"][0]["invoice_days"] = "0"
        assert client.put(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=headers, json={**payload, "expected_revision": row["revision"] + 1}).status_code == 422
        payload["lines"][0]["invoice_days"] = "3"

        # Selections must be active, role-matched and unique per role.
        wrong_role = {**payload, "expected_revision": row["revision"] + 1, "signatures": [
            {"role": "checked", "signatory_id": people["prepared"]["id"]},
        ]}
        assert client.put(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=headers, json=wrong_role).status_code == 422
        repeated = {**payload, "expected_revision": row["revision"] + 1, "signatures": [
            {"role": "prepared", "signatory_id": people["prepared"]["id"]},
            {"role": "prepared", "signatory_id": people["checked"]["id"]},
        ]}
        assert client.put(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=headers, json=repeated).status_code == 422

        # Renaming a signatory does not change the IDVS snapshot.
        renamed = client.patch(f"{SIGNATORY_BASE}/{people['prepared']['id']}", headers=headers, json={
            "signatory_role": "prepared", "full_name": "Ada O. Okafor", "designation": "Lead Cost Engineer", "is_active": True,
        })
        assert renamed.status_code == 200, renamed.text
        current = client.get(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=headers).json()
        assert {item["role"]: item["name"] for item in current["signatures"]}["prepared"] == "Ada Okafor"

        # Inactive signatories cannot be newly selected.
        client.patch(f"{SIGNATORY_BASE}/{people['approved']['id']}", headers=headers, json={
            "signatory_role": "approved", "full_name": "Tunde Bello", "designation": "Country Manager", "is_active": False,
        })
        assert len(client.get("/api/v1/invoice-processing/reference", headers=headers).json()["signatories"]) == 3
        inactive = {**payload, "expected_revision": row["revision"] + 1, "signatures": all_signatures(people)}
        assert client.put(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=headers, json=inactive).status_code == 422
        client.patch(f"{SIGNATORY_BASE}/{people['approved']['id']}", headers=headers, json={
            "signatory_role": "approved", "full_name": "Tunde Bello", "designation": "Country Manager", "is_active": True,
        })

        # Soft-deleted then permanently removed signatories keep snapshots on existing IDVS records.
        removed = client.post("/api/v1/invoice-processing/config/signatories/bulk-delete", headers=headers, json={"ids": [people["prepared"]["id"]]})
        assert removed.status_code == 200, removed.text
        purged = client.post("/api/v1/invoice-processing/config/signatories/bulk-permanent-delete", headers=headers, json={"ids": [people["prepared"]["id"]]})
        assert purged.status_code == 200, purged.text
        after_purge = client.get(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=headers).json()
        prepared = {item["role"]: item for item in after_purge["signatures"]}["prepared"]
        assert prepared["name"] == "Ada Okafor" and prepared["signatory_id"] is None
        restored = client.post("/api/v1/invoice-processing/config/signatories/bulk-restore", headers=headers, json={"ids": [people["checked"]["id"]]})
        assert restored.status_code == 200 and restored.json()["affected_count"] == 0

        with SessionLocal() as db:
            audited = {(entry.action, entry.entity_type) for entry in db.query(AuditLog).all()}
            assert {("create", "invoice_signatory"), ("update", "invoice_signatory"), ("delete", "invoice_configuration")}.issubset(audited)


def test_import_day_columns_and_signatory_refresh_keep_selections():
    with TestClient(app) as client:
        headers = login(client)
        vendor, order, block, rig, well = create_commercial_scope(client, headers)
        create_configuration(client, headers, vendor, block)
        people = create_signatories(client, headers)
        base = {
            "idvs_number": "IDVS-DAYS-01", "idvs_date": "2026-03-03", "invoice_received_date": "2026-03-03",
            "vendor_code": "VEND-01", "order_number": "PO-001", "invoice_number": "INV-DAYS",
            "invoice_date": "2026-03-01", "block_code": "OML-01", "rig_code": "RIG-01", "well_code": "WELL-01",
            "location": "Port Harcourt", "description_category": "Completion Services",
            "service_description": "Rental tools", "detailed_description": "", "concerned_person": "",
            "field_name": "", "phase": "Drilling", "service_from": "", "service_to": "", "currency_code": "USD",
            "payment_term_code": "30-60-40", "payment_tenure_days": "", "disallowed_amount": 0,
            "advance_amount": 0, "line_remarks": "", "remarks": "", "invoice_days": "", "verified_days": "",
        }
        rows = [
            {**base, "description": "Rig rental", "invoice_quantity": 2, "invoice_days": 3, "invoice_unit_price": 100,
             "verified_quantity": 2, "verified_days": 2, "verified_unit_price": 90},
            {**base, "description": "Crew hire", "invoice_quantity": 1, "invoice_unit_price": 50,
             "verified_quantity": 1, "verified_unit_price": 50},
        ]
        imported = client.post("/api/v1/invoice-processing/import", headers=headers, json={"rows": rows})
        assert imported.status_code == 200, imported.text
        assert imported.json()["success"] is True, imported.text
        invoice_id = client.get("/api/v1/invoice-processing/invoices", headers=headers).json()[0]["id"]
        detail = client.get(f"/api/v1/invoice-processing/invoices/{invoice_id}", headers=headers).json()
        assert detail["day_count_enabled"] is True
        lines = sorted(detail["lines"], key=lambda item: item["sort_order"])
        assert Decimal(lines[0]["invoice_total"]) == Decimal("600") and Decimal(lines[0]["verified_total"]) == Decimal("360")
        assert Decimal(lines[1]["invoice_days"]) == Decimal("1") and Decimal(lines[1]["verified_days"]) == Decimal("1")
        assert Decimal(detail["invoice_subtotal"]) == Decimal("650") and Decimal(detail["verified_subtotal"]) == Decimal("410")

        # Sign-off selections are set on the IDVS; a spreadsheet refresh (signatures omitted) must keep them.
        signed = client.put(f"/api/v1/invoice-processing/invoices/{invoice_id}", headers=headers, json={
            **{key: detail[key] for key in ("idvs_date", "invoice_number", "invoice_date", "invoice_received_date", "vendor_id",
                                             "location_id", "field_name", "phase", "service_description", "currency_code")},
            "expected_revision": detail["revision"], "idvs_number": detail["idvs_number"],
            "description_category_id": detail["description_category_id"], "detailed_description": "",
            "concerned_person": "", "remarks": "", "disallowed_amount": "0", "advance_amount": "0",
            "order_id": detail["order_id"], "block_id": detail["block_id"], "rig_id": detail["rig_id"],
            "well_id": detail["well_id"], "payment_term_id": detail["payment_term_id"], "payment_tenure_days": None,
            "lines": [{"description": "Rig rental", "invoice_quantity": "2", "invoice_days": "3", "invoice_unit_price": "100",
                       "verified_quantity": "2", "verified_days": "2", "verified_unit_price": "90", "remarks": ""}],
            "signatures": all_signatures(people),
        })
        assert signed.status_code == 200, signed.text
        assert len(signed.json()["signatures"]) == 4

        refreshed = client.post("/api/v1/invoice-processing/import", headers=headers, json={"rows": [
            {**base, "description": "Rig rental", "invoice_quantity": 2, "invoice_unit_price": 100,
             "verified_quantity": 2, "verified_unit_price": 100},
        ]})
        assert refreshed.status_code == 200 and refreshed.json()["success"] is True, refreshed.text
        after = client.get(f"/api/v1/invoice-processing/invoices/{invoice_id}", headers=headers).json()
        assert after["day_count_enabled"] is False and len(after["lines"]) == 1
        assert Decimal(after["invoice_subtotal"]) == Decimal("200")
        assert {item["role"] for item in after["signatures"]} == {"prepared", "checked", "verified", "approved"}


def test_register_only_taxes_and_net_payable_amount():
    """A tax may be printed on the IDVS, recorded on the register, both, or neither."""
    with TestClient(app) as client:
        headers = login(client)
        vendor, order, block, rig, well = create_commercial_scope(client, headers)
        location, category, term = create_configuration(client, headers, vendor, block)

        # Withholdings and levies that are deducted from the payable are often kept
        # off the printed IDVS but still recorded in the register.
        levy = client.post("/api/v1/invoice-processing/config/taxes", headers=headers, json={
            "tax_code": "LEVY", "tax_name": "NCDMB Levy", "rate_percent": "1", "direction": "deduction",
            "is_report_visible": False, "is_net_payable": True,
            "is_common": True, "description": "", "is_active": True, "vendor_ids": [],
        })
        assert levy.status_code == 201, levy.text
        assert levy.json()["is_report_visible"] is False and levy.json()["is_net_payable"] is True

        # A reference-only tax is stored on the IDVS but changes no amount anywhere.
        memo = client.post("/api/v1/invoice-processing/config/taxes", headers=headers, json={
            "tax_code": "MEMO", "tax_name": "Reference only", "rate_percent": "2", "direction": "addition",
            "is_report_visible": False, "is_net_payable": False,
            "is_common": True, "description": "", "is_active": True, "vendor_ids": [],
        })
        assert memo.status_code == 201, memo.text

        payload = invoice_payload(vendor, order, block, rig, well, location, category, term)
        # VAT 7.5% common (report + register), WHT 5% vendor-linked (report + register),
        # the 1% register-only levy and the 2% reference-only tax.
        created = client.post("/api/v1/invoice-processing/invoices", headers=headers, json=payload)
        assert created.status_code == 201, created.text
        row = created.json()
        taxes = {tax["tax_code"] if "tax_code" in tax else tax["tax_name"]: tax for tax in row["taxes"]}
        assert len(row["taxes"]) == 4
        assert taxes["VAT"]["is_report_visible"] is True and taxes["VAT"]["is_net_payable"] is True
        assert taxes["NCDMB Levy"]["is_report_visible"] is False and taxes["NCDMB Levy"]["is_net_payable"] is True
        assert taxes["Reference only"]["is_report_visible"] is False and taxes["Reference only"]["is_net_payable"] is False

        # IDVS report totals keep only the report-visible taxes: 180 + 13.5 - 9 = 184.5.
        assert Decimal(row["invoice_subtotal"]) == Decimal("200")
        assert Decimal(row["verified_subtotal"]) == Decimal("180")
        assert Decimal(row["verified_tax_total"]) == Decimal("4.5")
        assert Decimal(row["invoice_total"]) == Decimal("205")
        assert Decimal(row["verified_total"]) == Decimal("184.5")
        assert Decimal(row["adjusted_verified_amount"]) == Decimal("170")
        # The register adds the register-only levy (1% deducted) but not the reference-only tax.
        assert Decimal(row["net_payable_amount"]) == Decimal("168.2")
        # Payment splits follow the IDVS report amount, not the register amount.
        splits = {split["currency_code"]: split for split in row["payment_splits"]}
        assert Decimal(splits["USD"]["amount"]) == Decimal("102")
        assert Decimal(splits["NGN"]["amount"]) == Decimal("108800")

        # A manual tax line that overrides the configuration switches is stored as sent.
        manual = {**payload, "expected_revision": row["revision"], "invoice_number": "INV-MANUAL"}
        manual["taxes"] = [{
            "tax_configuration_id": None, "tax_name": "Manual levy", "rate_percent": "1",
            "direction": "deduction", "is_report_visible": False, "is_net_payable": True,
        }]
        manual_row = client.post("/api/v1/invoice-processing/invoices", headers=headers, json=manual)
        assert manual_row.status_code == 201, manual_row.text
        manual_row = manual_row.json()
        assert manual_row["taxes"][0]["is_report_visible"] is False
        assert Decimal(manual_row["verified_total"]) == Decimal("180")
        assert Decimal(manual_row["adjusted_verified_amount"]) == Decimal("165.5")
        assert Decimal(manual_row["net_payable_amount"]) == Decimal("163.7")

        # Making the levy report-visible re-enters the report total on the next save.
        patched = client.patch(f"/api/v1/invoice-processing/config/taxes/{levy.json()['id']}", headers=headers, json={
            "tax_code": "LEVY", "tax_name": "NCDMB Levy", "rate_percent": "1", "direction": "deduction",
            "is_report_visible": True, "is_net_payable": True,
            "is_common": True, "description": "", "is_active": True, "vendor_ids": [],
        })
        assert patched.status_code == 200, patched.text
        refreshed = client.put(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=headers, json={
            **payload, "expected_revision": row["revision"],
        })
        assert refreshed.status_code == 200, refreshed.text
        refreshed = refreshed.json()
        # Now the deduction is printed too: 180 + 13.5 - 9 - 1.8 = 182.7 verified.
        assert Decimal(refreshed["verified_total"]) == Decimal("182.7")
        assert Decimal(refreshed["adjusted_verified_amount"]) == Decimal("168.2")
        assert Decimal(refreshed["net_payable_amount"]) == Decimal("168.2")

        # The dashboard keeps both register amounts per currency.
        dashboard = client.get("/api/v1/invoice-processing/dashboard", headers=headers).json()
        totals = dashboard["currency_totals"][0]
        assert Decimal(totals["adjusted_verified_amount"]) == Decimal("333.7")
        assert Decimal(totals["net_payable_amount"]) == Decimal("331.9")
        assert all("net_payable_amount" in ageing for ageing in dashboard["ageing_rows"])


def test_signature_space_is_saved_and_validated():
    with TestClient(app) as client:
        headers = login(client)
        vendor, order, block, rig, well = create_commercial_scope(client, headers)
        location, category, term = create_configuration(client, headers, vendor, block)
        payload = invoice_payload(vendor, order, block, rig, well, location, category, term)

        # The default leaves a 15 mm signing gap between the role row and the names.
        created = client.post("/api/v1/invoice-processing/invoices", headers=headers, json=payload)
        assert created.status_code == 201, created.text
        row = created.json()
        assert row["signature_space_mm"] == 15

        for value, expected in ((25, 200), (0, 200), (61, 422), (-1, 422)):
            response = client.put(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=headers, json={
                **payload, "expected_revision": row["revision"], "signature_space_mm": value,
            })
            assert response.status_code == expected, (value, response.text)
            if expected == 200:
                row = response.json()
                assert row["signature_space_mm"] == value

        # A spreadsheet refresh that omits the field keeps the stored signing space.
        refreshed = client.post("/api/v1/invoice-processing/import", headers=headers, json={"rows": [{
            "idvs_number": row["idvs_number"], "idvs_date": "2026-01-03", "invoice_received_date": "2026-01-03",
            "vendor_code": "VEND-01", "order_number": "PO-001", "invoice_number": "INV-001",
            "invoice_date": "2026-01-01", "block_code": "OML-01", "rig_code": "RIG-01", "well_code": "WELL-01",
            "location": "Port Harcourt", "description_category": "Completion Services",
            "service_description": "Completion equipment", "currency_code": "USD", "payment_term_code": "30-60-40",
            "description": "Packers", "invoice_quantity": 2, "invoice_unit_price": 100,
            "verified_quantity": 2, "verified_unit_price": 90,
        }]})
        assert refreshed.status_code == 200 and refreshed.json()["success"] is True, refreshed.text
        after = client.get(f"/api/v1/invoice-processing/invoices/{row['id']}", headers=headers).json()
        assert after["signature_space_mm"] == 0

def test_bulk_configuration_is_atomic_and_tenant_scoped():
    with TestClient(app) as client:
        north, south = login(client), login(client, 'south')
        for kind in ('locations', 'categories', 'descriptions', 'signatories'):
            rows = [{"name": "Alpha", "description": "Reusable text", "signatory_role": "prepared" if kind == 'signatories' else None, "designation": "Cost Engineer" if kind == 'signatories' else ''},
                    {"name": "Beta", "description": "Second", "signatory_role": "prepared" if kind == 'signatories' else None, "designation": "Manager" if kind == 'signatories' else '', "is_active": False}]
            result = client.post(f'/api/v1/invoice-processing/config/{kind}/import', headers=north, json={"rows": rows})
            assert result.status_code == 200, result.text
            assert result.json()['affected_count'] == 2
            with SessionLocal() as db:
                audit_count = db.query(AuditLog).count()
            invalid = client.post(f'/api/v1/invoice-processing/config/{kind}/import', headers=north,
                                  json={"rows": [{**rows[0], "name": "New entry"}, rows[0]]})
            assert invalid.status_code == 409, invalid.text
            assert 'Row 3' in invalid.json()['detail']
            with SessionLocal() as db:
                assert db.query(AuditLog).count() == audit_count
            config = client.get('/api/v1/invoice-processing/configuration', headers=north).json()
            assert [item['full_name' if kind == 'signatories' else 'name'] for item in config[kind]] == ['Alpha', 'Beta']
            refs = client.get('/api/v1/invoice-processing/reference', headers=north).json()
            assert [item['full_name' if kind == 'signatories' else 'name'] for item in refs[kind]] == ['Alpha']
            assert client.get('/api/v1/invoice-processing/configuration', headers=south).json()[kind] == []
        invalid = client.post('/api/v1/invoice-processing/config/signatories/import', headers=north,
                              json={"rows": [{"name": "No designation"}]})
        assert invalid.status_code == 422
        assert client.post('/api/v1/invoice-processing/config/locations/import', json={"rows": [{"name": "Denied"}]}).status_code == 401
        with SessionLocal() as db:
            org = db.query(Organization).filter_by(slug='north').one()
            permission = db.query(Permission).filter_by(organization_id=org.id, key='invoice-processing:read').one()
            role = Role(organization_id=org.id, name='Invoice reader', permissions=[permission])
            db.add(User(organization_id=org.id, email='reader@example.com', full_name='Reader', password_hash=hash_password('reader-password-123'), roles=[role]))
            db.commit()
        auth = client.post('/api/v1/auth/login', json={"organization": "north", "email": "reader@example.com", "password": "reader-password-123"}).json()
        denied = client.post('/api/v1/invoice-processing/config/locations/import', headers={"Authorization": f"Bearer {auth['access_token']}"}, json={"rows": [{"name": "Denied"}]})
        assert denied.status_code == 403


def test_invoice_classification_filters_and_signoff_snapshots():
    with TestClient(app) as client:
        north, south = login(client), login(client, 'south')
        vendor, order, block, rig, well = create_commercial_scope(client, north)
        location, category, term = create_configuration(client, north, vendor, block)
        person = client.post('/api/v1/invoice-processing/config/signatories', headers=north,
                             json={"full_name": "Jane Doe", "signatory_role": "prepared", "designation": "Cost Engineer"}).json()
        payload = invoice_payload(vendor, order, block, rig, well, location, category, term)
        payload.update(block_category='jv', signatures=[{"role": "prepared", "signatory_id": person["id"]}])
        created = client.post('/api/v1/invoice-processing/invoices', headers=north, json=payload)
        assert created.status_code == 201, created.text
        invoice = created.json()
        assert invoice['block_category'] == 'jv'
        assert invoice['signatures'][0]['designation'] == 'Cost Engineer'
        for classification, expected in [('jv', 1), ('own', 0), ('common', 0), ('unclassified', 0)]:
            result = client.get(f'/api/v1/invoice-processing/invoices?block_category={classification}', headers=north)
            assert result.status_code == 200
            assert len(result.json()) == expected
        assert client.get('/api/v1/invoice-processing/invoices?block_category=jv', headers=south).json() == []
        assert client.get('/api/v1/invoice-processing/invoices?block_category=invalid', headers=north).status_code == 422
        client.patch(f"/api/v1/invoice-processing/config/signatories/{person['id']}", headers=north,
                     json={"full_name": "Jane Doe", "signatory_role": "prepared", "designation": "Senior Engineer"})
        assert client.get(f"/api/v1/invoice-processing/invoices/{invoice['id']}", headers=north).json()['signatures'][0]['designation'] == 'Cost Engineer'
        payload.update(expected_revision=invoice['revision'], block_category='own', signatures=[{"role": "prepared", "signatory_id": person["id"]}])
        updated = client.put(f"/api/v1/invoice-processing/invoices/{invoice['id']}", headers=north, json=payload)
        assert updated.status_code == 200, updated.text
        assert updated.json()['signatures'][0]['designation'] == 'Senior Engineer'
        assert updated.json()['block_category'] == 'own'
        payload.pop('expected_revision')
        payload.update(invoice_number='INV-SECOND', idvs_number='', block_category='jv')
        second = client.post('/api/v1/invoice-processing/invoices', headers=north, json=payload)
        assert second.status_code == 201, second.text
        dashboard = client.get('/api/v1/invoice-processing/dashboard', headers=north).json()
        assert dashboard['own_block_count'] == dashboard['jv_block_count'] == 1
        assert {row['block_category'] for row in dashboard['block_rows']} == {'own', 'jv'}
        deleted = client.post('/api/v1/invoice-processing/invoices/bulk-delete', headers=north, json={"ids": [invoice['id']]})
        assert deleted.status_code == 200
        assert len(client.get('/api/v1/invoice-processing/invoices/deleted?block_category=own', headers=north).json()) == 1
        assert client.get('/api/v1/invoice-processing/invoices/deleted?block_category=jv', headers=north).json() == []
