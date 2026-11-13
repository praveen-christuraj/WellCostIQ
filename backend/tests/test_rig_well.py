import os
import tempfile
from decimal import Decimal

# Set the database before importing app modules (the engine is constructed at import).
_db_path = tempfile.mktemp(suffix=".sqlite3")
# Set TEST_DATABASE_URL (a PostgreSQL URL, as CI does) to run this suite against
# a real server instead of the throwaway SQLite file.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User


RIG_WELL_PERMISSIONS = [
    "rig-well:read",
    "rig-well:create",
    "rig-well:update",
    "rig-well:delete",
    "rig-well:restore",
    "rig-well:permanent-delete",
    "rig-well:import",
    "rig-well:export",
    "rig-well:rollback",
]
MASTER_DATA_PERMISSIONS = [
    "master-data:read",
    "master-data:create",
    "master-data:update",
    "master-data:delete",
    "master-data:restore",
    "master-data:permanent-delete",
    "master-data:import",
    "master-data:export",
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
            permission_keys = RIG_WELL_PERMISSIONS + MASTER_DATA_PERMISSIONS + ["audit:read"]
            permissions = [
                Permission(organization_id=organization.id, key=key, description=key)
                for key in permission_keys
            ]
            owner_role = Role(
                organization_id=organization.id,
                name="Owner",
                is_owner=True,
                permissions=permissions,
            )
            db.add(
                User(
                    organization_id=organization.id,
                    email="owner@example.com",
                    full_name="Test Owner",
                    password_hash=hash_password("correct-password-123"),
                    roles=[owner_role],
                )
            )
        db.commit()
    yield


def login(client: TestClient, organization: str = "north") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "organization": organization,
            "email": "owner@example.com",
            "password": "correct-password-123",
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_rig(client: TestClient, headers: dict[str, str], code: str = "RIG-01") -> dict:
    response = client.post(
        "/api/v1/rig-well/rigs",
        headers=headers,
        json={"rig_code": code, "rig_name": f"Rig {code}", "remarks": ""},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_block(
    client: TestClient, headers: dict[str, str], code: str = "BLOCK-A", name: str = "Block A"
) -> dict:
    response = client.post(
        "/api/v1/rig-well/blocks",
        headers=headers,
        json={"block_code": code, "block_name": name, "description": ""},
    )
    if response.status_code == 409:
        existing = client.get("/api/v1/rig-well/blocks", headers=headers).json()
        return next(block for block in existing if block["block_code"] == code)
    assert response.status_code == 201, response.text
    return response.json()


def create_well(client: TestClient, headers: dict[str, str], rig_id: str, code: str = "WELL-01") -> dict:
    block = create_block(client, headers)
    response = client.post(
        "/api/v1/rig-well/wells",
        headers=headers,
        json={
            "rig_id": rig_id,
            "block_id": block["id"],
            "well_code": code,
            "well_name": f"Well {code}",
            "well_location": "North field",
            "objective": "Production appraisal",
            "remarks": "",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_activity(client: TestClient, headers: dict[str, str], code: str = "DRILL") -> dict:
    response = client.post(
        "/api/v1/master-data/activities",
        headers=headers,
        json={"code": code, "name": f"{code.title()} operations"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_sub_activity(
    client: TestClient,
    headers: dict[str, str],
    well_id: str,
    activity_id: str,
    code: str = "SA-01",
) -> dict:
    response = client.post(
        "/api/v1/rig-well/sub-activities",
        headers=headers,
        json={
            "well_id": well_id,
            "sub_activity_code": code,
            "sub_activity_name": f"Sub activity {code}",
            "activity_id": activity_id,
            "responsible_party": "Operations team",
            "description": "Execute the planned work step.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_rigs_and_rig_scoped_wells_are_tenant_scoped_and_audited():
    with TestClient(app) as client:
        north = login(client, "north")
        south = login(client, "south")
        rig = create_rig(client, north, "rig-a")
        assert rig["rig_code"] == "RIG-A"
        assert client.get("/api/v1/rig-well/rigs", headers=north).json()[0]["id"] == rig["id"]
        assert client.get("/api/v1/rig-well/rigs", headers=south).json() == []
        assert client.post(
            "/api/v1/rig-well/rigs",
            headers=north,
            json={"rig_code": "RIG-A", "rig_name": "Duplicate"},
        ).status_code == 409

        well = create_well(client, north, rig["id"])
        assert well["rig_code"] == "RIG-A"
        assert well["rig_name"] == "Rig rig-a"
        # A newly created well is *upcoming*: planned and budgetable, not yet started.
        assert well["status"] == "upcoming"
        assert well["completion_status"] == "upcoming"
        assert well["tracking_status"] == "upcoming"
        assert well["upcoming_scope_count"] == 2
        assert well["active_scope_count"] == 0
        assert client.get("/api/v1/rig-well/wells", headers=north).json()[0]["id"] == well["id"]
        assert client.get("/api/v1/rig-well/wells", headers=south).json() == []
        assert client.post(
            "/api/v1/rig-well/wells",
            headers=south,
            json={
                "rig_id": rig["id"], "well_code": "FOREIGN", "well_name": "Foreign",
                "well_location": "Elsewhere", "block_id": "00000000-0000-0000-0000-000000000000",
                "objective": "Y",
            },
        ).status_code == 404
        assert client.patch(
            f"/api/v1/rig-well/wells/{well['id']}",
            headers=south,
            json={"well_name": "Cross-tenant edit"},
        ).status_code == 404

        dashboard = client.get("/api/v1/rig-well/overview", headers=north)
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["active_rigs"] == 1
        # Segregated by tracking status: the new well is upcoming, not active.
        assert dashboard.json()["upcoming_wells"] == 1
        assert dashboard.json()["active_wells"] == 0
        # An upcoming well still occupies its rig and block.
        assert client.get("/api/v1/rig-well/rigs", headers=north).json()[0]["well_count"] == 1
        assert client.get("/api/v1/rig-well/blocks", headers=north).json()[0]["well_count"] == 1
        assert client.get("/api/v1/rig-well/wells?status=upcoming", headers=north).json()[0]["id"] == well["id"]
        assert client.get("/api/v1/rig-well/wells?status=active", headers=north).json() == []
        assert client.get("/api/v1/rig-well/wells?status=completed", headers=south).json() == []
        assert client.post(
            "/api/v1/rig-well/export-audit",
            headers=north,
            json={"module": "wells", "format": "csv", "record_count": 1},
        ).status_code == 204
        with SessionLocal() as db:
            entity_types = {entry.entity_type for entry in db.query(AuditLog).all()}
            assert {"rig", "well", "rig_well_export"}.issubset(entity_types)


def test_configuration_uses_workspace_master_data_and_enforces_lifecycle_and_depth_order():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        hole = client.post(
            "/api/v1/master-data/hole-sections", headers=headers,
            json={"code": "17-1/2", "name": "Surface hole"},
        ).json()
        second_hole = client.post(
            "/api/v1/master-data/hole-sections", headers=headers,
            json={"code": "12-1/4", "name": "Intermediate hole"},
        ).json()
        phase = client.post(
            "/api/v1/master-data/phases", headers=headers,
            json={"code": "DRILL", "name": "Drilling"},
        ).json()
        options = client.get("/api/v1/rig-well/configuration-options", headers=headers)
        assert options.status_code == 200
        assert {item["id"] for item in options.json()["hole_sections"]} == {hole["id"], second_hole["id"]}
        assert options.json()["phases"][0]["id"] == phase["id"]

        def section(hole_id: str, start: str, end: str, days: str) -> dict:
            return {
                "hole_section_id": hole_id,
                "from_depth": start,
                "to_depth": end,
                "remarks": "",
                "phases": [{"phase_id": phase["id"], "days": days, "remarks": ""}],
            }

        payload = {"depth_unit": "m", "sections": [section(hole["id"], "0", "100", "2.5"), section(second_hole["id"], "100", "500", "4")]}
        saved = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        assert saved.json()["total_depth"] == "500"
        assert Decimal(saved.json()["total_days"]) == Decimal("6.50")
        assert [item["section_code"] for item in saved.json()["sections"]] == ["17-1/2", "12-1/4"]

        overlapping = {"depth_unit": "m", "sections": [section(hole["id"], "0", "100", "2"), section(second_hole["id"], "99", "500", "4")]}
        invalid = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json=overlapping)
        assert invalid.status_code == 422
        assert "previous section" in invalid.json()["detail"]
        assert client.post(
            f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers,
            json={"action": "configure", "remarks": "Plan checked"},
        ).status_code == 200
        transition_url = f"/api/v1/rig-well/wells/{well['id']}/transition"

        def move(action: str, remarks: str):
            return client.post(
                transition_url, headers=headers,
                json={"action": action, "scope": "drilling", "remarks": remarks},
            )

        # Final review is a *well* status that follows Active, so an upcoming scope
        # cannot skip to it, and nothing can be completed without passing through it.
        skipped = move("final_review", "Too early")
        assert skipped.status_code == 409
        assert "Upcoming" in skipped.json()["detail"]
        assert move("complete", "Too early").status_code == 409
        started = move("start", "Rig on location")
        assert started.status_code == 200, started.text
        assert (started.json()["status"], started.json()["config_status"]) == ("active", "configured")
        marked = move("final_review", "Operations ended")
        assert marked.status_code == 200, marked.text
        # Leaving operations closes the plan: the two ladders meet here.
        assert (marked.json()["status"], marked.json()["config_status"]) == ("final_review", "completed")
        assert marked.json()["final_review_scope_count"] == 1
        review = client.get("/api/v1/rig-well/overview", headers=headers).json()
        # Completion is still upcoming, so the well as a whole is still active.
        assert (review["active_wells"], review["final_review_wells"]) == (1, 0)
        completed = move("complete", "Costs reviewed")
        assert completed.status_code == 200, completed.text
        assert (completed.json()["status"], completed.json()["config_status"]) == ("completed", "completed")
        # Only the Drilling scope has finished. The live Completion scope keeps the
        # well itself active: the flag is per scope, and the well rolls up.
        assert completed.json()["tracking_status"] == "active"
        assert completed.json()["completed_scope_count"] == 1
        mixed = client.get("/api/v1/rig-well/overview", headers=headers).json()
        assert mixed["active_wells"] == 1
        assert mixed["completed_wells"] == 0
        assert mixed["upcoming_wells"] == 0
        # With the never-planned Completion scope removed, Drilling alone decides
        # the well, so it becomes a completed well for MIS reporting.
        assert client.delete(
            f"/api/v1/rig-well/wells/{well['id']}?scope=completion", headers=headers
        ).status_code == 200
        lifecycle = client.get("/api/v1/rig-well/overview", headers=headers).json()
        assert lifecycle["active_wells"] == 0
        assert lifecycle["configured_wells"] == 0
        assert lifecycle["draft_wells"] == 0
        assert lifecycle["final_review_wells"] == 0
        assert lifecycle["completed_wells"] == 1
        locked = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json=payload)
        assert locked.status_code == 409
        # A closed plan cannot be reopened directly: the scope walks back one step
        # at a time, and each step lands on exactly the previous status.
        assert move("draft", "Update plan").status_code == 409
        assert move("reactivate", "Skip a step").status_code == 409
        reopened = move("reopen", "Late invoice found")
        assert reopened.status_code == 200, reopened.text
        assert (reopened.json()["status"], reopened.json()["config_status"]) == ("final_review", "completed")
        assert client.get("/api/v1/rig-well/overview", headers=headers).json()["final_review_wells"] == 1
        assert [
            item["tracking_status"]
            for item in client.get("/api/v1/rig-well/wells?status=final_review", headers=headers).json()
        ] == ["final_review"]
        reactivated = move("reactivate", "Restart well")
        assert reactivated.status_code == 200, reactivated.text
        assert (reactivated.json()["status"], reactivated.json()["config_status"]) == ("active", "configured")
        drafted = move("draft", "Update plan")
        assert drafted.status_code == 200, drafted.text
        assert (drafted.json()["status"], drafted.json()["config_status"]) == ("active", "draft")
        assert client.put(
            f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json=payload
        ).status_code == 200
        with SessionLocal() as db:
            actions = [
                (entry.action, entry.summary)
                for entry in db.query(AuditLog).filter(AuditLog.entity_type == "well").order_by(AuditLog.created_at)
            ]
        rollbacks = [summary for action, summary in actions if action == "rollback"]
        assert len(rollbacks) == 3
        assert any("Completed → Final review" in summary and "Late invoice found" in summary for summary in rollbacks)
        assert any("Final review → Active" in summary for summary in rollbacks)
        assert any("Configured → Draft" in summary for summary in rollbacks)


def test_deletion_dependencies_block_rig_children_and_preserve_master_data_references():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        activity = create_activity(client, headers, "DEPENDENT-ACTIVITY")
        sub_activity = create_sub_activity(client, headers, well["id"], activity["id"], "DEPENDENT-SUB")
        hole = client.post(
            "/api/v1/master-data/hole-sections", headers=headers,
            json={"code": "DEPENDENT-HOLE", "name": "Dependent hole"},
        ).json()
        phase = client.post(
            "/api/v1/master-data/phases", headers=headers,
            json={"code": "DEPENDENT-PHASE", "name": "Dependent phase"},
        ).json()
        configuration = client.put(
            f"/api/v1/rig-well/wells/{well['id']}/configuration",
            headers=headers,
            json={"depth_unit": "m", "sections": [{
                "hole_section_id": hole["id"], "from_depth": "0", "to_depth": "100",
                "phases": [{"phase_id": phase["id"], "days": "2"}],
            }]},
        )
        assert configuration.status_code == 200, configuration.text

        blocked_rig = client.delete(f"/api/v1/rig-well/rigs/{rig['id']}", headers=headers)
        assert blocked_rig.status_code == 409
        assert "active well" in blocked_rig.json()["detail"]

        # Soft removal retains the old IDs for audit history; permanent purge is
        # refused with a clear reference count and a lifecycle path.
        for module, record in (("activities", activity), ("hole-sections", hole), ("phases", phase)):
            moved = client.delete(f"/api/v1/master-data/{module}/{record['id']}", headers=headers)
            assert moved.status_code == 200, moved.text
            blocked = client.delete(
                f"/api/v1/master-data/{module}/{record['id']}/permanent", headers=headers
            )
            assert blocked.status_code == 409, blocked.text
            assert "still referenced by" in blocked.json()["detail"]
            assert "Deleted Entries" in blocked.json()["detail"]
        assert "well sub activity" in client.delete(
            f"/api/v1/master-data/activities/{activity['id']}/permanent", headers=headers
        ).json()["detail"]
        assert sub_activity["id"]
        assert "well configuration section" in client.delete(
            f"/api/v1/master-data/hole-sections/{hole['id']}/permanent", headers=headers
        ).json()["detail"]
        assert "well configuration phase" in client.delete(
            f"/api/v1/master-data/phases/{phase['id']}/permanent", headers=headers
        ).json()["detail"]


def test_sub_activities_are_well_scoped_activity_categorized_and_hierarchical():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        first = create_well(client, headers, rig["id"], "WELL-01")
        second = create_well(client, headers, rig["id"], "WELL-02")
        activity = create_activity(client, headers)
        first_item = create_sub_activity(client, headers, first["id"], activity["id"], "SHARED-CODE")
        second_item = create_sub_activity(client, headers, second["id"], activity["id"], "SHARED-CODE")
        assert first_item["well_code"] == "WELL-01"
        assert first_item["activity_display"].startswith("DRILL")
        assert first_item["id"] != second_item["id"]
        duplicate = client.post(
            "/api/v1/rig-well/sub-activities", headers=headers,
            json={
                "well_id": first["id"], "sub_activity_code": "SHARED-CODE", "sub_activity_name": "Duplicate",
                "activity_id": activity["id"], "responsible_party": "Team", "description": "Details",
            },
        )
        assert duplicate.status_code == 409
        listing = client.get(f"/api/v1/rig-well/sub-activities?well_id={first['id']}", headers=headers)
        assert [item["id"] for item in listing.json()] == [first_item["id"]]
        cross_scope_patch = client.patch(
            f"/api/v1/rig-well/sub-activities/{first_item['id']}?well_id={second['id']}",
            headers=headers, json={"sub_activity_name": "Cross-well edit"},
        )
        assert cross_scope_patch.status_code == 404

        active_child_block = client.delete(f"/api/v1/rig-well/wells/{first['id']}", headers=headers)
        assert active_child_block.status_code == 409
        assert client.delete(
            f"/api/v1/rig-well/sub-activities/{first_item['id']}?well_id={first['id']}", headers=headers
        ).status_code == 200
        assert client.post(
            f"/api/v1/rig-well/sub-activities/{first_item['id']}/restore", headers=headers
        ).status_code == 200
        assert client.delete(
            f"/api/v1/rig-well/sub-activities/{first_item['id']}/permanent", headers=headers
        ).status_code == 409


def test_import_deleted_entries_bulk_restore_and_permanent_purge_are_atomic():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        create_block(client, headers, "BLOCK-A", "Block A")
        imported_wells = client.post(
            "/api/v1/rig-well/wells/import", headers=headers,
            json={"rows": [
                {"rig_code": rig["rig_code"], "well_code": "IMPORTED-01", "well_name": "Imported well", "well_location": "North", "block_code": "BLOCK-A", "objective": "Production"},
                {"rig_code": "MISSING", "well_code": "IMPORTED-02", "well_name": "Bad well", "well_location": "North", "block_code": "BLOCK-A", "objective": "Production"},
            ]},
        )
        assert imported_wells.status_code == 200, imported_wells.text
        assert imported_wells.json()["imported_count"] == 1
        assert imported_wells.json()["error_count"] == 1
        well = client.get("/api/v1/rig-well/wells", headers=headers).json()[0]
        activity = create_activity(client, headers)
        imported_subs = client.post(
            f"/api/v1/rig-well/sub-activities/import?well_id={well['id']}", headers=headers,
            json={"rows": [{
                "sub_activity_code": "IMPORT-01", "sub_activity_name": "Imported task", "activity": "DRILL",
                "responsible_party": "Team", "description": "Imported details",
            }]},
        )
        assert imported_subs.status_code == 200, imported_subs.text
        assert imported_subs.json()["imported_count"] == 1
        item = client.get(f"/api/v1/rig-well/sub-activities?well_id={well['id']}", headers=headers).json()[0]
        assert item["activity_id"] == activity["id"]

        assert client.delete(
            f"/api/v1/rig-well/sub-activities/{item['id']}?well_id={well['id']}", headers=headers
        ).status_code == 200
        assert client.delete(f"/api/v1/rig-well/wells/{well['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/rig-well/rigs/{rig['id']}", headers=headers).status_code == 200
        deleted = client.get("/api/v1/rig-well/deleted", headers=headers)
        assert deleted.status_code == 200
        assert {row["entity_type"] for row in deleted.json()} == {"rig", "well", "well_sub_activity"}
        assert client.delete(f"/api/v1/rig-well/rigs/{rig['id']}/permanent", headers=headers).status_code == 409

        records = [
            {"entity_type": "rig", "id": rig["id"]},
            {"entity_type": "well", "id": well["id"]},
            {"entity_type": "well_sub_activity", "id": item["id"]},
        ]
        restored = client.post("/api/v1/rig-well/deleted/bulk-restore", headers=headers, json={"records": records})
        assert restored.status_code == 200, restored.text
        assert restored.json()["affected_count"] == 3
        assert client.get("/api/v1/rig-well/deleted", headers=headers).json() == []

        assert client.delete(
            f"/api/v1/rig-well/sub-activities/{item['id']}?well_id={well['id']}", headers=headers
        ).status_code == 200
        assert client.delete(f"/api/v1/rig-well/wells/{well['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/rig-well/rigs/{rig['id']}", headers=headers).status_code == 200
        purged = client.post(
            "/api/v1/rig-well/deleted/bulk-permanent-delete", headers=headers, json={"records": records}
        )
        assert purged.status_code == 200, purged.text
        assert purged.json()["affected_count"] == 3
        assert client.get("/api/v1/rig-well/deleted", headers=headers).json() == []


def test_rig_well_read_capability_does_not_grant_mutation():
    with TestClient(app) as client:
        headers = login(client)
        create_rig(client, headers, "PRIVATE-AUDIT")
        with SessionLocal() as db:
            organization = db.query(Organization).filter_by(slug="north").one()
            permission = db.query(Permission).filter_by(organization_id=organization.id, key="rig-well:read").one()
            role = Role(organization_id=organization.id, name="Read only", permissions=[permission])
            db.add(User(
                organization_id=organization.id,
                email="reader@example.com",
                full_name="Read Only",
                password_hash=hash_password("correct-password-123"),
                roles=[role],
            ))
            db.commit()
        reader_login = client.post(
            "/api/v1/auth/login",
            json={"organization": "north", "email": "reader@example.com", "password": "correct-password-123"},
        )
        assert reader_login.status_code == 200, reader_login.text
        reader = {"Authorization": f"Bearer {reader_login.json()['access_token']}"}
        overview = client.get("/api/v1/rig-well/overview", headers=reader)
        assert overview.status_code == 200
        assert overview.json()["recent_activity"] == []
        denied = client.post(
            "/api/v1/rig-well/rigs", headers=reader,
            json={"rig_code": "NO-WRITE", "rig_name": "Denied"},
        )
        assert denied.status_code == 403
        assert client.get("/api/v1/rig-well/overview", headers=headers).status_code == 200


def test_blocks_are_a_workspace_register_and_wells_are_segregated_by_block():
    with TestClient(app) as client:
        headers = login(client)
        north = login(client, "north")
        south = login(client, "south")
        rig = create_rig(client, north, "RIG-BLOCK")
        south_rig = create_rig(client, south, "RIG-SOUTH")

        created = client.post(
            "/api/v1/rig-well/blocks", headers=north,
            json={"block_code": "omb-1", "block_name": "OML Block 1", "description": "Shallow water acreage"},
        )
        assert created.status_code == 201, created.text
        block = created.json()
        assert block["block_code"] == "OMB-1"
        assert block["description"] == "Shallow water acreage"
        second = client.post(
            "/api/v1/rig-well/blocks", headers=north,
            json={"block_code": "OMB-2", "block_name": "OML Block 2"},
        )
        assert second.status_code == 201, second.text
        duplicate = client.post(
            "/api/v1/rig-well/blocks", headers=north,
            json={"block_code": "OMB-1", "block_name": "Duplicate"},
        )
        assert duplicate.status_code == 409

        # Tenant scope: another workspace cannot see, reuse or bind the block.
        assert client.get("/api/v1/rig-well/blocks", headers=south).json() == []
        assert client.post(
            "/api/v1/rig-well/blocks", headers=south,
            json={"block_code": "OMB-1", "block_name": "Own block"},
        ).status_code == 201
        foreign_well = client.post(
            "/api/v1/rig-well/wells", headers=south,
            json={
                "rig_id": south_rig["id"], "block_id": block["id"], "well_code": "FOREIGN-BLOCK",
                "well_name": "Foreign", "well_location": "Elsewhere", "objective": "Test",
            },
        )
        assert foreign_well.status_code == 404
        assert client.get("/api/v1/rig-well/blocks", headers=north).json()[0]["well_count"] == 0

        dropdown = client.get("/api/v1/rig-well/blocks/dropdown", headers=north)
        assert dropdown.status_code == 200
        assert [item["display_name"] for item in dropdown.json()] == [
            "OMB-1 — OML Block 1", "OMB-2 — OML Block 2",
        ]

        def make_well(code: str, block_id: str) -> dict:
            response = client.post(
                "/api/v1/rig-well/wells", headers=north,
                json={
                    "rig_id": rig["id"], "block_id": block_id, "well_code": code,
                    "well_name": f"Well {code}", "well_location": "North field",
                    "objective": "Production appraisal", "remarks": "",
                },
            )
            assert response.status_code == 201, response.text
            return response.json()

        first = make_well("WELL-B1", block["id"])
        second_well = make_well("WELL-B1B", block["id"])
        third = make_well("WELL-B2", second.json()["id"])
        assert first["block_code"] == "OMB-1" and first["block"] == "OML Block 1"
        assert third["block_code"] == "OMB-2" and third["block_id"] == second.json()["id"]

        # Segregation: filtering by block returns only that block's wells.
        one = client.get(f"/api/v1/rig-well/wells?block_id={block['id']}", headers=north).json()
        assert [well["well_code"] for well in one] == ["WELL-B1", "WELL-B1B"]
        by_text = client.get("/api/v1/rig-well/wells?block=OMB-2", headers=north).json()
        assert [well["well_code"] for well in by_text] == ["WELL-B2"]
        searched = client.get("/api/v1/rig-well/wells?search=OML%20Block%201", headers=north).json()
        assert [well["well_code"] for well in searched] == ["WELL-B1", "WELL-B1B"]

        counts = {row["block_code"]: row["well_count"] for row in client.get(
            "/api/v1/rig-well/blocks", headers=north
        ).json()}
        assert counts == {"OMB-1": 2, "OMB-2": 1}
        overview = client.get("/api/v1/rig-well/overview", headers=north).json()
        assert overview["active_blocks"] == 2
        assert {row["block_code"]: row["well_count"] for row in overview["block_counts"]} == counts

        # Reassigning a well moves it between blocks.
        moved = client.patch(
            f"/api/v1/rig-well/wells/{second_well['id']}", headers=north,
            json={"block_id": second.json()["id"]},
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["block_code"] == "OMB-2"

        # A block in use is protected; it is soft-deleted first, then purged.
        assert client.delete(f"/api/v1/rig-well/blocks/{block['id']}", headers=north).status_code == 409
        assert client.delete(f"/api/v1/rig-well/blocks/{block['id']}", headers=south).status_code == 404
        for well in (first, second_well):
            assert client.delete(f"/api/v1/rig-well/wells/{well['id']}", headers=north).status_code == 200
        removed = client.delete(f"/api/v1/rig-well/blocks/{block['id']}", headers=north)
        assert removed.status_code == 200, removed.text
        assert client.get("/api/v1/rig-well/blocks", headers=north).status_code == 200
        assert block["id"] not in [row["id"] for row in client.get("/api/v1/rig-well/blocks", headers=north).json()]
        deleted = client.get("/api/v1/rig-well/deleted", headers=north).json()
        deleted_block = next(row for row in deleted if row["id"] == block["id"])
        assert deleted_block["entity_type"] == "block"
        assert deleted_block["code"] == "OMB-1"
        assert deleted_block["parent_label"] == "Block register"
        # Retained (soft-deleted) wells still pin the block, as they do a rig.
        assert client.delete(f"/api/v1/rig-well/blocks/{block['id']}/permanent", headers=north).status_code == 409
        for well in (first, second_well):
            assert client.delete(f"/api/v1/rig-well/wells/{well['id']}/permanent", headers=north).status_code == 204
        assert client.delete(f"/api/v1/rig-well/blocks/{block['id']}/permanent", headers=north).status_code == 204

        restored_block = create_block(client, north, "OMB-3", "OML Block 3")
        assert restored_block["block_code"] == "OMB-3"
        assert client.post(
            f"/api/v1/rig-well/blocks/{restored_block['id']}/restore", headers=north
        ).status_code == 409


def test_blocks_support_import_update_and_audited_export():
    with TestClient(app) as client:
        headers = login(client)
        imported = client.post(
            "/api/v1/rig-well/blocks/import", headers=headers,
            json={"rows": [
                {"block_code": "omb-9", "block_name": "OML Block 9", "description": "Imported"},
                {"block_code": "", "block_name": "Missing code"},
                {"block_code": "OMB-9", "block_name": "Duplicate"},
            ]},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["imported_count"] == 1
        assert imported.json()["error_count"] == 2
        rows = client.get("/api/v1/rig-well/blocks", headers=headers).json()
        assert [(row["block_code"], row["description"]) for row in rows] == [("OMB-9", "Imported")]

        updated = client.patch(
            f"/api/v1/rig-well/blocks/{rows[0]['id']}", headers=headers,
            json={"block_name": "OML Block Nine", "description": "Renamed block"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["block_name"] == "OML Block Nine"
        assert client.patch(
            f"/api/v1/rig-well/blocks/{rows[0]['id']}", headers=headers,
            json={"block_code": "OMB-9", "block_name": ""},
        ).status_code == 422

        assert client.post(
            "/api/v1/rig-well/export-audit", headers=headers,
            json={"module": "blocks", "format": "xlsx", "record_count": 1, "include_deleted": False},
        ).status_code == 204
        with SessionLocal() as db:
            audit = db.query(AuditLog).filter_by(entity_type="block").all()
            assert {entry.action for entry in audit} >= {"create", "update"}
            export = db.query(AuditLog).filter_by(entity_type="rig_well_export").one()
            assert "Blocks" in export.summary


def test_upcoming_wells_are_planned_started_and_can_return_to_planning():
    """Upcoming → active is the spud moment, per scope, and is reversible while clean."""
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"], "WELL-PLAN")

        def transition(action: str, scope: str = "drilling") -> object:
            return client.post(
                f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers,
                json={"action": action, "scope": scope, "remarks": f"{action} from the register"},
            )

        # Nothing is saved yet, so the scope cannot leave the planning bucket.
        assert transition("start").status_code == 409
        assert "section and phase plan" in transition("start").json()["detail"]

        hole = client.post(
            "/api/v1/master-data/hole-sections", headers=headers,
            json={"code": "17-1/2", "name": "Surface hole"},
        ).json()
        phase = client.post(
            "/api/v1/master-data/phases", headers=headers, json={"code": "DRILL", "name": "Drilling"},
        ).json()
        saved = client.put(
            f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers,
            json={"depth_unit": "m", "sections": [{
                "hole_section_id": hole["id"], "from_depth": "0", "to_depth": "1200", "remarks": "",
                "phases": [{"phase_id": phase["id"], "days": "12", "remarks": ""}],
            }]},
        )
        assert saved.status_code == 200, saved.text
        # A draft programme is still planning: budgetable, not started.
        assert transition("start").status_code == 409
        assert transition("configure").status_code == 200

        started = transition("start")
        assert started.status_code == 200, started.text
        row = started.json()
        assert (row["status"], row["completion_status"]) == ("active", "upcoming")
        assert row["tracking_status"] == "active"
        assert row["active_scope_count"] == 1 and row["upcoming_scope_count"] == 1

        # The roll-up is active, yet the Completion scope is still an upcoming
        # plan — which is exactly what the per-scope filter reports for MIS.
        assert client.get("/api/v1/rig-well/wells?status=upcoming", headers=headers).json() == []
        scoped = client.get(
            "/api/v1/rig-well/wells?scope=completion&status=upcoming", headers=headers
        ).json()
        assert [item["well_code"] for item in scoped] == ["WELL-PLAN"]
        lifecycle = client.get("/api/v1/rig-well/overview", headers=headers).json()
        assert lifecycle["upcoming_wells"] == 0
        assert lifecycle["active_wells"] == 1

        # A recorded spud on the other scope starts it from the daily-cost
        # register too, so the two registers can never disagree.
        progress = client.put(
            f"/api/v1/daily-cost/wells/{well['id']}/progress", headers=headers,
            json={"scope": "completion", "spud_at": "2026-03-02T08:00"},
        )
        assert progress.status_code == 200, progress.text
        current = client.get("/api/v1/rig-well/wells?search=WELL-PLAN", headers=headers).json()[0]
        assert current["completion_status"] == "active"
        assert current["upcoming_scope_count"] == 0

        # Deferring is allowed only while nothing has been booked. A spud date is
        # proof the scope ran, so that one stays active.
        deferred = transition("defer", "completion")
        assert deferred.status_code == 409
        assert "spud date" in deferred.json()["detail"]
        assert transition("defer", "drilling").status_code == 200
        after = client.get("/api/v1/rig-well/wells?search=WELL-PLAN", headers=headers).json()[0]
        assert (after["status"], after["completion_status"]) == ("upcoming", "active")
        assert after["tracking_status"] == "active"
        # An already-upcoming scope cannot be deferred again.
        assert transition("defer", "drilling").status_code == 409


def test_sub_activity_responsible_party_is_tracked_through_the_vendor_register():
    """The typed party is linked to Master Data vendors instead of being free text."""
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"], "WELL-VND")
        activity = create_activity(client, headers, "CID")

        def add_vendor(code: str, name: str, **overrides) -> dict:
            payload = {
                "vendor_code": code, "vendor_name": name, "category": "Directional",
                "status": "active", "description": "",
            }
            payload.update(overrides)
            created = client.post("/api/v1/master-data/vendors", headers=headers, json=payload)
            assert created.status_code == 201, created.text
            return created.json()

        vendor = add_vendor("VND-9", "Noble Directional")
        add_vendor("VND-DUP", "Same Trading")
        options = client.get("/api/v1/rig-well/sub-activities/vendor-options", headers=headers)
        assert options.status_code == 200, options.text
        assert [item["code"] for item in options.json()] == ["VND-9", "VND-DUP"]

        def add_sub_activity(code: str, **overrides) -> dict:
            payload = {
                "well_id": well["id"], "sub_activity_code": code, "sub_activity_name": f"Step {code}",
                "activity_id": activity["id"], "responsible_party": "Operations team",
                "description": "Planned work step.",
            }
            payload.update(overrides)
            created = client.post("/api/v1/rig-well/sub-activities", headers=headers, json=payload)
            assert created.status_code == 201, created.text
            return created.json()

        linked = add_sub_activity("SA-VND", vendor_id=vendor["id"], responsible_party="")
        # The vendor's own name is stored, so every report reads one column.
        assert linked["responsible_party"] == "Noble Directional"
        assert linked["vendor_id"] == vendor["id"]
        assert linked["vendor_code"] == "VND-9"
        assert linked["vendor_name"] == "Noble Directional"
        assert linked["vendor_status"] == "active"
        assert linked["responsible_party_source"] == "vendor"
        typed = add_sub_activity("SA-TYPED")
        assert typed["vendor_id"] == "" and typed["vendor_code"] == ""
        assert typed["responsible_party"] == "Operations team"
        assert typed["responsible_party_source"] == "manual"

        assert client.post(
            "/api/v1/rig-well/sub-activities", headers=headers,
            json={
                "well_id": well["id"], "sub_activity_code": "SA-BAD", "sub_activity_name": "Bad link",
                "activity_id": activity["id"], "vendor_id": "missing-vendor", "description": "x",
            },
        ).status_code == 422

        # An edit that does not touch the party keeps the link, even once the
        # vendor is blocked, so history never fails to save.
        assert client.patch(
            f"/api/v1/rig-well/sub-activities/{linked['id']}?well_id={well['id']}", headers=headers,
            json={"sub_activity_name": "Step SA-VND (renamed)"},
        ).json()["vendor_id"] == vendor["id"]
        blocked = client.patch(
            f"/api/v1/master-data/vendors/{vendor['id']}", headers=headers, json={"status": "blocked"},
        )
        assert blocked.status_code == 200, blocked.text
        assert client.patch(
            f"/api/v1/rig-well/sub-activities/{linked['id']}?well_id={well['id']}", headers=headers,
            json={"description": "Vendor re-negotiated the day rate."},
        ).status_code == 200
        # Editing a row that already carries the link still saves (history must
        # stay correctable), but the blocked vendor cannot be assigned anywhere new.
        assert client.patch(
            f"/api/v1/rig-well/sub-activities/{typed['id']}?well_id={well['id']}", headers=headers,
            json={"vendor_id": vendor["id"]},
        ).status_code == 422

        # Deleting the vendor leaves the sub activity and its party text intact.
        assert client.delete(f"/api/v1/master-data/vendors/{vendor['id']}", headers=headers).status_code == 200
        orphan = client.get(
            f"/api/v1/rig-well/sub-activities?well_id={well['id']}", headers=headers
        ).json()
        assert next(item for item in orphan if item["id"] == linked["id"])["responsible_party"] == "Noble Directional"

        # Import accepts a vendor code and links the row; unknown text is a row error.
        imported = client.post(
            f"/api/v1/rig-well/sub-activities/import?well_id={well['id']}&scope=drilling", headers=headers,
            json={"rows": [
                {
                    "sub_activity_code": "SA-IMP", "sub_activity_name": "Casing run",
                    "activity": "CID", "responsible_party": "Noble Directional",
                    "vendor_code": "VND-DUP", "description": "Imported step.",
                },
                {
                    "sub_activity_code": "SA-IMP2", "sub_activity_name": "Bad vendor",
                    "activity": "CID", "responsible_party": "Someone", "vendor_code": "NOPE",
                    "description": "Imported step.",
                },
                {
                    "sub_activity_code": "SA-TYPED", "sub_activity_name": "Step SA-TYPED",
                    "activity": "CID", "responsible_party": "Rig crew", "description": "Updated.",
                },
            ]},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["imported_count"] == 2, imported.json()
        assert imported.json()["error_count"] == 1
        assert "vendor" in imported.json()["errors"][0].lower()
        rows = client.get(f"/api/v1/rig-well/sub-activities?well_id={well['id']}", headers=headers).json()
        by_code = {row["sub_activity_code"]: row for row in rows}
        assert by_code["SA-IMP"]["vendor_code"] == "VND-DUP"
        assert by_code["SA-IMP"]["responsible_party"] == "Same Trading"
        # A link resolved from the sheet is still a vendor link; only the text
        # that no vendor matches is remembered as imported free text.
        assert by_code["SA-IMP"]["responsible_party_source"] == "vendor"
        assert by_code["SA-TYPED"]["vendor_id"] == ""
        assert by_code["SA-TYPED"]["responsible_party"] == "Rig crew"
        assert by_code["SA-TYPED"]["responsible_party_source"] == "import"
