"""Exercise the Operations boundary through its public API, including real source files."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from test_rig_well import create_rig, create_well, fresh_database, login  # noqa: F401

# The shared fixture must configure its disposable database before app.core.database is imported.
# isort: split

from app.core.database import Base, SessionLocal
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User
from app.models.rig_well import Well
from app.models.vendor_master import Vendor
from app.schemas.operations import OpsActivityBlockIn, OpsSettingsIn
from app.services.operations.analytics import planned_at_depth
from app.services.operations.openwells import parse_pdf
from app.services.operations.workbooks import daily_workbook, timeline_preview
from fastapi.testclient import TestClient
from sqlalchemy import select

OPS = "/api/v1/operations"
MODELS = Path(__file__).resolve().parents[2] / "MODEL REPORTS/operation reports"


def good(response):
    assert response.is_success, response.text[:3000]
    return response.json() if response.content else None


def configured_well(client, headers, code="ACHARA-EAST-4PH"):
    rig = create_rig(client, headers)
    well = create_well(client, headers, rig["id"], code)
    assert good(client.get(OPS + "/scope-reference", headers=headers))["wells"] == []
    payload = {"well_id": well["id"], "scope": "drilling"}
    assert (
        client.post(OPS + "/plans", headers=headers, json=dict(**payload, label="Not configured")).status_code
        == 422
    )
    with SessionLocal() as db:
        db.get(Well, well["id"]).config_status = "configured"
        db.commit()
    return payload


def scoped_login(client, name, keys):
    with SessionLocal() as db:
        org = db.scalar(select(Organization.id).where(Organization.slug == "north"))
        owner = db.scalar(select(User).where(User.organization_id == org, User.email == "owner@example.com"))
        permissions = []
        for key in keys:
            perm = db.scalar(select(Permission).where(Permission.organization_id == org, Permission.key == key))
            permissions.append(perm or Permission(organization_id=org, key=key, description=key))
        role = Role(organization_id=org, name=name, permissions=permissions)
        db.add(
            User(
                organization_id=org,
                full_name=name,
                email=f"{name}@example.com",
                password_hash=owner.password_hash,
                roles=[role],
            )
        )
        db.commit()
    result = good(
        client.post(
            "/api/v1/auth/login",
            json={"organization": "north", "email": f"{name}@example.com", "password": "correct-password-123"},
        )
    )
    return {"Authorization": "Bearer " + result["access_token"]}


def test_real_programme_to_reviewed_daily_kpis():
    with TestClient(app) as c:
        h = login(c)
        south = login(c, "south")
        folder = configured_well(c, h)

        def get(path, **kwargs):
            return good(c.get(OPS + path, headers=h, **kwargs))

        def post(path, **kwargs):
            return good(c.post(OPS + path, headers=h, **kwargs))

        def put(path, **kwargs):
            return good(c.put(OPS + path, headers=h, **kwargs))

        settings = get("/settings")
        put(
            "/settings",
            json={
                **{k: settings[k] for k in OpsSettingsIn.model_fields},
                "require_npt_agency": True,
                "document_types": ["Field log", "Mud sheet"],
            },
        )
        assert get("/scope-reference")["document_types"] == ["Field log", "Mud sheet"]
        assert "Field log" not in good(c.get(OPS + "/scope-reference", headers=south))["document_types"]
        assert (
            c.post(
                OPS + "/plans", headers=h, json={**folder, "scope": "completion", "label": "Wrong scope"}
            ).status_code
            == 422
        )
        plan = post("/plans", json=dict(**folder, label="Programme A"))
        base = "/plans/" + plan["id"]
        xlsx = next(MODELS.glob("ACHARA EAST*.xlsx"))
        preview = post(base + "/import-preview", files={"file": (xlsx.name, xlsx.read_bytes())})
        assert len(preview["items"]) == 118
        assert sum(Decimal(str(r["planned_hours"])) for r in preview["items"]) / 24 == pytest.approx(Decimal(104))
        assert get("/plans")[0]["items"] == []  # Preview is not a write.
        rows = [
            {k: r[k] for k in ("sequence_no", "description", "target_depth_m", "planned_hours")}
            for r in preview["items"]
        ]
        rows[0]["planned_hours"] = str(Decimal(str(rows[0]["planned_hours"])) + 24)
        put(base + "/items", json=rows)
        active = post(base + "/activate")
        assert Decimal(active["planned_days"]) == pytest.approx(Decimal(105))
        assert c.put(OPS + base + "/items", headers=h, json=rows).status_code == 409
        pdf = next(MODELS.glob("DDR- 55*.pdf"))
        raw = pdf.read_bytes()
        files = {"file": (pdf.name, raw, "application/pdf")}
        doc = post("/documents/upload", data=dict(**folder, document_type="Field log"), files=files)
        assert doc["status"] == "uploaded" and get("/reports") == []
        assert (
            post("/documents/upload", data=dict(**folder, document_type="Field log"), files=files)["id"]
            == doc["id"]
        )
        assert c.get(OPS + f"/documents/{doc['id']}/download", headers=h).content == raw
        assert c.get(OPS + f"/documents/{doc['id']}/download", headers=south).status_code == 404
        assert c.get(OPS + f"/documents/{doc['id']}/download").status_code == 401
        assert (
            c.post(OPS + "/reports/from-document", headers=south, json={"document_id": doc["id"]}).status_code
            == 404
        )
        source = {"document_id": doc["id"]}
        draft = post("/reports/from-document", json=source)
        address = "/reports/" + draft["id"]
        assert draft["extraction_status"] == "needs_review" and draft["status"] == "draft"
        assert len(draft["blocks"]) == 3 and draft["total_block_minutes"] == 1439
        assert [b["classification"] for b in draft["blocks"]] == ["Planned", "NPT", "Planned"]
        assert all(b["review_state"] == "suggested" and b["source_page"] for b in draft["blocks"])
        assert "Programme A" in draft["blocks"][0]["classification_evidence"]
        assert draft["sources"] == [{"id": doc["id"], "file_name": pdf.name}]
        assert Decimal(draft["depth_end_m"]) == 4127 and draft["surveys"][0]["azi_deg"] is not None
        assert get("/dashboard")["kpis"]["total_logged_hours"] == 0
        assert c.post(OPS + address + "/submit", headers=h).status_code == 422
        blocks = [{k: b[k] for k in OpsActivityBlockIn.model_fields} for b in draft["blocks"]]
        for b, source_block in zip(blocks, draft["blocks"]):
            b.update(review_state="accepted", block_id=source_block["id"])
        # A Planned block cannot be accepted without its operation and activity code.
        refused = c.put(
            OPS + address,
            headers=h,
            json={
                "confirm_review": False,
                "report": {"operation_summary": draft["operation_summary"]},
                "blocks": blocks,
                "surveys": draft["surveys"],
            },
        )
        assert refused.status_code == 422 and "operation code" in refused.json()["detail"]
        operation = post("/masters/operation-codes", json={"operation_code": "DRILL", "operation_name": "Drilling"})
        activity = post("/masters/activity-codes", json={"activity_code": "ROT", "activity_name": "Rotating"})
        for b in blocks:
            b.update(operation_code_id=operation["id"], activity_code_id=activity["id"])
        code = post("/masters/npt-codes", json={"npt_code": "ENGINE", "npt_name": "Engine shutdown"})
        with SessionLocal() as db:
            org = db.scalar(select(Organization.id).where(Organization.slug == "north"))
            db.add(Vendor(organization_id=org, vendor_name="Rig contractor", vendor_code="RC", status="active"))
            db.commit()
        vendor = get("/reference")["vendors"][0]
        assert vendor["vendor_name"] == "Rig contractor"
        cause = post("/masters/causes", json={"cause_code": "EQP", "cause_name": "Equipment failure"})
        block = blocks[1]
        block.update(npt_code_id=code["id"], cause_code="EQP", reason="Engine shutdown", review_state="edited")
        checkpoint = active["items"][30]
        edited = {
            "confirm_review": True,
            "report": {
                "operation_summary": "Engineer verified the engine downtime.",
                "completed_plan_item_id": checkpoint["id"],
            },
            "blocks": blocks,
            "surveys": draft["surveys"],
        }
        # An NPT block without an agency is refused before it ever reaches submit.
        blocked = c.put(OPS + address, headers=h, json=edited)
        assert blocked.status_code == 422 and "agency" in blocked.json()["detail"]
        assert c.post(OPS + address + "/submit", headers=h).status_code == 422
        block.update(vendor_id=vendor["id"], responsible_party="Untrusted client label")
        reviewed = put(address, json=edited)
        assert (
            reviewed["blocks"][1]["id"] == draft["blocks"][1]["id"]
            and reviewed["blocks"][1]["source_page"] == draft["blocks"][1]["source_page"]
        )
        assert Decimal(reviewed["surveys"][0]["md_m"]) == Decimal("3960.69")
        # The length columns are metric, but the printed 1.60 dogleg is degrees/100 ft.
        assert Decimal(reviewed["surveys"][0]["dls_deg_per_30m"]) == Decimal("1.575")
        assert reviewed["extraction_status"] == "reviewed"
        assert reviewed["blocks"][1]["responsible_party"] == "Rig contractor"
        assert post(address + "/extract", json=source)["operation_summary"] == edited["report"]["operation_summary"]
        assert c.put(OPS + address, headers=h, json={**edited, "blocks": [blocks[0], blocks[0]]}).status_code == 409
        assert post(address + "/submit")["status"] == "submitted"
        assert "Engineer verified" in get(address + "/brief")["summary"]
        dash = get("/dashboard", params=folder)
        k = dash["kpis"]
        assert k["total_logged_hours"] == 23.983 and k["npt_hours"] == round(block["duration_minutes"] / 60, 3)
        assert k["avg_rop"] == round(135 / 13.42, 3) and dash["npt_by_agency"][0]["agency"] == "Rig contractor"
        curve = get("/analytics/time-depth", params=folder)
        assert curve["actual"][0]["cum_days"] == 54 and curve["actual"][0]["depth_m"] == 4127
        # Lead is positive, lag negative: the curve reports planned minus actual.
        assert curve["lag_series"][0]["lag_days"] == round(float(checkpoint["cum_planned_days"]) - 54, 3)
        replacement = post("/plans", json=dict(**folder, label="Programme B"))
        path = "/plans/" + replacement["id"]
        put(
            path + "/items",
            json=[
                {"sequence_no": 1, "description": "Revised objective", "target_depth_m": 4300, "planned_hours": 24}
            ],
        )
        post(path + "/activate")
        revised = get("/analytics/time-depth", params=folder)
        assert revised["plan"] != curve["plan"] and revised["lag_series"] == curve["lag_series"]
        assert get("/dashboard", params={"from": "2027-01-01"})["kpis"]["total_reports"] == 0
        assert c.post(OPS + "/reports/bulk-delete", headers=h, json={"ids": [draft["id"]]}).status_code == 409
        assert c.put(OPS + address, headers=h, json=edited).status_code == 409
        assert post(address + "/approve")["status"] == "approved"


def test_register_lifecycle_permissions_and_exports():
    with TestClient(app) as c:
        h = login(c)
        folder = configured_well(c, h)
        headers = {
            "rows": [
                {"well_code": "ACHARA-EAST-4PH", "report_date": d, "report_type": "DDR", "scope": "drilling"}
                for d in ["2026-11-15", "2026-11-16"]
            ]
        }
        assert good(c.post(OPS + "/reports/import", headers=h, json=headers))["created_count"] == 2
        ids = {"ids": [r["id"] for r in good(c.get(OPS + "/reports", headers=h))]}
        assert (
            good(c.post(OPS + "/reports/bulk-edit", headers=h, json={**ids, "remarks": "Shift handover"}))[
                "affected_count"
            ]
            == 2
        )
        for register in ("reports", "plans", "documents", "analytics", "library"):
            for fmt in ("pdf", "csv", "xlsx"):
                assert (
                    c.post(
                        OPS + f"/{register}/export-audit", headers=h, json={"format": fmt, "record_count": 2}
                    ).status_code
                    == 204
                )
        assert good(c.post(OPS + "/reports/bulk-delete", headers=h, json=ids))["affected_count"] == 2
        assert good(c.get(OPS + "/reports", headers=h)) == []
        assert len(good(c.get(OPS + "/reports/deleted", headers=h))) == 2
        report_path = OPS + f"/reports/{ids['ids'][0]}"
        trash = {"include_deleted": True}
        assert c.get(report_path, headers=h).status_code == 404
        assert good(c.get(report_path, headers=h, params=trash))["is_deleted"]
        assert good(c.get(report_path + "/brief", headers=h, params=trash))["summary"]
        assert c.post(report_path + "/print-audit", headers=h, params=trash).status_code == 204
        assert c.post(report_path + "/submit", headers=h, params=trash).status_code == 404
        assert c.get(report_path, headers=login(c, "south"), params=trash).status_code == 404
        assert c.post(OPS + "/reports", headers=h, json=dict(**folder, report_date="2026-11-15")).status_code == 409
        assert good(c.post(OPS + "/reports/bulk-restore", headers=h, json=ids))["affected_count"] == 2
        c.post(OPS + "/reports/bulk-delete", headers=h, json=ids).raise_for_status()
        assert good(c.post(OPS + "/reports/bulk-permanent-delete", headers=h, json=ids))["affected_count"] == 2
        with SessionLocal() as db:
            org = db.scalar(select(Organization.id).where(Organization.slug == "north"))
            assert (
                len(
                    db.scalars(
                        select(AuditLog).where(AuditLog.action == "export", AuditLog.organization_id == org)
                    ).all()
                )
                == 15
            )
        restricted = scoped_login(c, "monitor", ["ops-doc:read", "ops-dashboard:read"])
        for path in ["/documents", "/scope-reference", "/dashboard"]:
            assert c.get(OPS + path, headers=restricted).status_code == 200
        for path in ["/reference", "/reports", "/plans", "/settings", "/masters/causes"]:
            assert c.get(OPS + path, headers=restricted).status_code == 403
        assert (
            c.post(
                OPS + "/reports/from-document", headers=restricted, json={"document_id": "unavailable"}
            ).status_code
            == 403
        )
        assert (
            c.post(OPS + "/documents/export-audit", headers=restricted, json={"record_count": 0}).status_code == 403
        )
        assert c.get("/api/v1/daily-cost/entries", headers=restricted).status_code == 403
        costing = scoped_login(c, "costing", ["daily-cost:read"])
        assert c.get("/api/v1/daily-cost/entries", headers=costing).is_success
        for path in ["/scope-reference", "/reports", "/documents", "/dashboard", "/plans"]:
            assert c.get(OPS + path, headers=costing).status_code == 403


def test_no_cross_module_foreign_keys():
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if table.name.startswith("ops_"):
                assert not fk.column.table.name.startswith(
                    ("afe", "daily_cost", "invoice", "fuel_cost", "mud_cost")
                )
            if fk.column.table.name.startswith("ops_"):
                assert table.name.startswith("ops_")


def test_parser_edge_cases_and_ambiguous_depth():
    for pattern, expected in [
        ("ACHARA EAST*.xlsx", 104),
        ("ACHARA-8*.xlsx", 64),
        ("ACHARA-SOUTH*.xlsx", 21.00121),
        ("SAKA*.xlsx", 82),
    ]:
        path = next(MODELS.glob(pattern))
        source = path.read_bytes()
        p = timeline_preview(path.name, source)
        assert float(sum(r["planned_hours"] for r in p["items"]) / 24) == pytest.approx(expected, abs=0.0001)
        day = daily_workbook(source, date(2026, 11, 16))
        assert all(b["start"].day == 16 and b["end"].date() <= date(2026, 11, 17) for b in day["blocks"])
    mud = daily_workbook(next(MODELS.glob("DMR-65*.xlsx")).read_bytes(), None)
    assert mud["blocks"] == [] and mud["report_date"] == date(2026, 11, 16) and mud["depth_end_m"] == 3885
    rmr = parse_pdf(next(MODELS.glob("RMR*.pdf")).read_bytes())
    assert sum((b["end"] - b["start"]).total_seconds() for b in rmr["blocks"]) / 3600 == 8.5
    ogini = parse_pdf(next(MODELS.glob("DDR_41*.pdf")).read_bytes())
    assert ogini["rotating_hours"] is None and ogini["depth_end_m"] == Decimal("944.834")
    assert planned_at_depth([{"depth_m": 0, "cum_days": 0}, {"depth_m": 500, "cum_days": 10}], 250) == 5
    assert planned_at_depth([{"depth_m": 500, "cum_days": 8}, {"depth_m": 500, "cum_days": 10}], 500) is None


def test_measurement_only_mud_report_and_draft_restore():
    with TestClient(app) as c:
        h = login(c)
        folder = configured_well(c, h)
        mud = next(MODELS.glob("DMR-4*.xlsx"))
        doc = good(
            c.post(
                OPS + "/documents/upload",
                headers=h,
                data=dict(**folder, document_type="DMR"),
                files={"file": (mud.name, mud.read_bytes())},
            )
        )
        r = good(c.post(OPS + "/reports/from-document", headers=h, json={"document_id": doc["id"]}))
        url = OPS + "/reports/" + r["id"]
        assert (
            r["report_type"] == "DMR"
            and r["blocks"] == []
            and len(r["surveys"]) == 1
            and r["extraction_status"] == "needs_review"
        )
        assert c.post(url + "/submit", headers=h).status_code == 422
        editor = scoped_login(c, "editor", ["ops-report:read", "ops-report:update"])
        assert (
            c.put(url, headers=editor, json={"report": {}, "blocks": [], "confirm_review": True}).status_code == 403
        )
        # Saving corrections is not acceptance, including a measurement-only report.
        good(c.put(url, headers=h, json={"report": {}, "blocks": [], "surveys": r["surveys"]}))
        assert c.post(url + "/submit", headers=h).status_code == 422
        assert (
            c.put(
                url, headers=h, json={"expected_updated_at": r["updated_at"], "report": {}, "blocks": []}
            ).status_code
            == 409
        )
        good(c.put(url, headers=h, json={"report": {}, "blocks": [], "confirm_review": True}))
        submitted = good(c.post(url + "/submit", headers=h))
        assert submitted["status"] == "submitted" and submitted["unaccounted_minutes"] == 0
        k = good(c.get(OPS + "/dashboard", headers=h))["kpis"]
        assert k["total_logged_hours"] == k["unaccounted_hours"] == 0
        assert c.post(url + "/print-audit", headers=h).status_code == 204
        draft = good(c.post(OPS + "/plans", headers=h, json=dict(**folder, label="Unused programme")))
        base = OPS + "/plans/" + draft["id"]
        good(c.delete(base, headers=h))
        assert good(c.get(OPS + "/plans?deleted=true", headers=h))[0]["id"] == draft["id"]
        good(c.post(base + "/restore", headers=h))
        assert good(c.get(OPS + "/plans", headers=h))[0]["status"] == "draft"
        ids = {"ids": [doc["id"]]}
        good(c.post(OPS + "/documents/bulk-delete", headers=h, json=ids))
        assert c.get(OPS + f"/documents/{doc['id']}/download", headers=h).status_code == 404
        assert c.post(OPS + "/documents/bulk-permanent-delete", headers=h, json=ids).status_code == 409
        good(c.post(OPS + "/documents/bulk-restore", headers=h, json=ids))
        assert c.get(OPS + f"/documents/{doc['id']}/download", headers=h).content == mud.read_bytes()


def test_custom_rules_and_tabular_workbook():
    from datetime import time
    from io import BytesIO

    from openpyxl import Workbook

    with TestClient(app) as c:
        h = login(c)
        folder = configured_well(c, h, "IKAKI-SOUTH-14")
        rules = OPS + "/masters/source-marks"
        assert (
            good(
                c.post(
                    rules + "/import",
                    headers=h,
                    json=[
                        {
                            "mark_code": "X",
                            "mark_name": "Unscheduled trip",
                            "default_classification": "UPA",
                            "default_allocation": "PT",
                        }
                    ],
                )
            )["created_count"]
            == 1
        )
        wb = Workbook()
        ws = wb.active
        ws.append(["From", "To", "Activity", "Class", "Depth (ft)"])
        ws.append([time(4), time(6), "Additional wiper trip", "X", 3281])
        f = BytesIO()
        wb.save(f)
        wb.close()
        doc = good(
            c.post(
                OPS + "/documents/upload",
                headers=h,
                data=dict(**folder, document_type="Other"),
                files={"file": ("tour.xlsx", f.getvalue())},
            )
        )
        r = good(
            c.post(
                OPS + "/reports/from-document",
                headers=h,
                json={"document_id": doc["id"], "report_date": "2026-11-16"},
            )
        )
        b = r["blocks"][0]
        assert (
            b["classification"] == "UPA"
            and b["classification_source"] == "workspace"
            and b["review_state"] == "suggested"
        )
        assert b["allocation"] == "PT" and b["is_productive"]
        assert b["duration_minutes"] == 120 and Decimal(b["depth_to_m"]) == 1000
        assert c.post(OPS + f"/reports/{r['id']}/submit", headers=h).status_code == 422
        mud = next(MODELS.glob("DMR-65*.xlsx"))
        source = good(
            c.post(
                OPS + "/documents/upload",
                headers=h,
                data=dict(**folder, document_type="DMR"),
                files={"file": (mud.name, mud.read_bytes())},
            )
        )
        url = OPS + "/reports/" + r["id"] + "/extract"
        addition = {"document_id": source["id"]}
        supplemented = good(c.post(url, headers=h, json=addition))
        assert supplemented["id"] == r["id"] and supplemented["report_type"] == "DDR"
        assert (
            len(supplemented["sources"]) == 2
            and supplemented["blocks"] == r["blocks"]
            and len(supplemented["surveys"]) == 1
        )
        assert len(good(c.post(url, headers=h, json=addition))["surveys"]) == 1


def test_dated_checkpoint_without_depth_and_closed_day_gaps():
    with TestClient(app) as c:
        h = login(c)
        folder = configured_well(c, h)
        plan = good(
            c.post(
                OPS + "/plans",
                headers=h,
                json=dict(**folder, label="Dated programme", planned_start_at="2020-01-01T00:00:00+01:00"),
            )
        )
        base = OPS + "/plans/" + plan["id"]
        items = [{"sequence_no": 1, "description": "Mobilise", "planned_hours": 72}]
        good(c.put(base + "/items", headers=h, json=items))
        active = good(c.post(base + "/activate", headers=h))
        draft = good(c.post(OPS + "/reports", headers=h, json=dict(**folder, report_date="2020-01-02")))
        url = OPS + "/reports/" + draft["id"]
        operation = good(
            c.post(OPS + "/masters/operation-codes", headers=h,
                   json={"operation_code": "MOB", "operation_name": "Mobilisation"})
        )
        activity = good(
            c.post(OPS + "/masters/activity-codes", headers=h,
                   json={"activity_code": "MOB", "activity_name": "Move in"})
        )
        b = {
            "sequence_no": 1,
            "started_at": draft["period_start_at"],
            "ended_at": draft["period_end_at"],
            "duration_minutes": 1440,
            "review_state": "accepted",
            "narrative": "Mobilisation complete",
            "operation_code_id": operation["id"],
            "activity_code_id": activity["id"],
        }
        good(
            c.put(
                url, headers=h, json={"report": {"completed_plan_item_id": active["items"][0]["id"]}, "blocks": [b]}
            )
        )
        good(c.post(url + "/submit", headers=h))
        curve = good(c.get(OPS + "/analytics/time-depth", headers=h, params=folder))
        assert curve["actual"][0]["depth_m"] is None and curve["actual"][0]["cum_days"] == 2
        # Two days elapsed against a three-day programme item is one day ahead:
        # lead positive, lag negative, so +1.
        assert (
            curve["lag_series"][0]["lag_days"] == 1
            and curve["lag_series"][0]["basis"] == "confirmed programme activity"
        )
        dash = good(
            c.get(OPS + "/dashboard", headers=h, params={**folder, "from": "2020-01-01", "to": "2020-01-05"})
        )
        assert {g["date"] for g in dash["missing_reports"]} == {"2020-01-01", "2020-01-03"}


def test_rop_uses_matched_measurements():
    from types import SimpleNamespace as Row

    from app.domain.operations.metrics import penetration

    report = Row(progress_m=Decimal(100), depth_start_m=None, depth_end_m=None, rotating_hours=None)
    blocks = [
        Row(footage_m=Decimal(8), rotating_hours=Decimal(2)),
        Row(footage_m=None, rotating_hours=Decimal(10)),
        Row(footage_m=Decimal(30), rotating_hours=None),
    ]
    assert penetration(report, blocks) == (8, 2)
    report.rotating_hours = Decimal(10)
    assert penetration(report, blocks) == (100, 10)
    report.rotating_hours = None
    assert penetration(report, blocks[1:]) == (100, None)
