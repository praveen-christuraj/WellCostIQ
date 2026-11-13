"""The well-status and plan-status ladders, their one-step rollbacks and their RBAC.

    Well status  upcoming -> active -> final_review -> completed
    Plan status  draft -> configured -> completed

Every forward move has exactly one rollback that lands on the previous status.
Forward moves need ``rig-well:update``; rollbacks need ``rig-well:rollback``.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User, Well
from app.models.rig_well import rolled_up_plan, rolled_up_status
from app.services import well_lifecycle
from app.services.provisioning import CAPABILITIES

PASSWORD = "correct-password-123"
PERMISSIONS = [
    "rig-well:read", "rig-well:create", "rig-well:update", "rig-well:delete", "rig-well:restore",
    "rig-well:rollback", "rig-well:plan-adjust",
    "master-data:read", "master-data:create",
    "afe:read", "afe:create",
    "audit:read",
]
# Non-owner accounts, each holding exactly the capabilities under test.
ACCOUNTS = {
    "planner@example.com": ["rig-well:read", "rig-well:update"],
    "approver@example.com": ["rig-well:read", "rig-well:rollback"],
    "viewer@example.com": ["rig-well:read"],
}


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        organization = Organization(slug="north", name="North Energy")
        db.add(organization)
        db.flush()
        permissions = {
            key: Permission(organization_id=organization.id, key=key, description=key) for key in PERMISSIONS
        }
        db.add_all(permissions.values())
        owner = Role(organization_id=organization.id, name="Owner", is_owner=True, permissions=list(permissions.values()))
        db.add(User(
            organization_id=organization.id, email="owner@example.com", full_name="Owner",
            password_hash=hash_password(PASSWORD), roles=[owner],
        ))
        for email, keys in ACCOUNTS.items():
            role = Role(
                organization_id=organization.id, name=email.split("@")[0].title(),
                permissions=[permissions[key] for key in keys],
            )
            db.add(User(
                organization_id=organization.id, email=email, full_name=email.split("@")[0].title(),
                password_hash=hash_password(PASSWORD), roles=[role],
            ))
        db.commit()
    yield


def login(client: TestClient, email: str = "owner@example.com") -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"organization": "north", "email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _post(client: TestClient, path: str, headers: dict[str, str], payload: dict, expected: int = 201) -> dict:
    response = client.post(path, headers=headers, json=payload)
    assert response.status_code == expected, response.text
    return response.json()


def make_well(client: TestClient, headers: dict[str, str], code: str = "WELL-01", *, plan: bool = True) -> dict:
    """A well with a saved (still Draft) drilling plan; Completion stays untouched."""
    rigs = client.get("/api/v1/rig-well/rigs", headers=headers).json()
    rig = rigs[0] if rigs else _post(client, "/api/v1/rig-well/rigs", headers, {"rig_code": "RIG-01", "rig_name": "Rig One", "remarks": ""})
    blocks = client.get("/api/v1/rig-well/blocks", headers=headers).json()
    block = blocks[0] if blocks else _post(client, "/api/v1/rig-well/blocks", headers, {"block_code": "BLK-A", "block_name": "Block A", "description": ""})
    well = _post(client, "/api/v1/rig-well/wells", headers, {
        "rig_id": rig["id"], "block_id": block["id"], "well_code": code, "well_name": f"Well {code}",
        "well_location": "North field", "objective": "Appraisal", "remarks": "",
    })
    if plan:
        holes = client.get("/api/v1/master-data/hole-sections", headers=headers).json()
        hole = holes[0] if holes else _post(client, "/api/v1/master-data/hole-sections", headers, {"code": "17-1/2", "name": "Surface hole"})
        phases = client.get("/api/v1/master-data/phases", headers=headers).json()
        phase = phases[0] if phases else _post(client, "/api/v1/master-data/phases", headers, {"code": "DRILL", "name": "Drilling"})
        saved = client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json={
            "depth_unit": "m",
            "sections": [{
                "hole_section_id": hole["id"], "from_depth": "0", "to_depth": "500", "remarks": "",
                "phases": [{"phase_id": phase["id"], "days": "12", "remarks": ""}],
            }],
        })
        assert saved.status_code == 200, saved.text
    return well


def move(client: TestClient, headers: dict[str, str], well_id: str, action: str, scope: str = "drilling", remarks: str = "Recorded for the test"):
    return client.post(
        f"/api/v1/rig-well/wells/{well_id}/transition", headers=headers,
        json={"action": action, "scope": scope, "remarks": remarks},
    )


def state(payload: dict, scope: str = "drilling") -> tuple[str, str]:
    prefix = "completion_" if scope == "completion" else ""
    return payload[f"{prefix}status"], payload[f"{prefix}config_status"]


def offered(payload: dict, scope: str = "drilling") -> dict[str, dict]:
    return {option["action"]: option for option in payload[f"{scope}_transitions"]}


# ---------------------------------------------------------------------------
# The ladders
# ---------------------------------------------------------------------------
def test_every_step_forward_has_one_step_back_to_the_previous_status():
    with TestClient(app) as client:
        headers = login(client)
        well = make_well(client, headers)
        well_id = well["id"]
        assert state(well) == ("upcoming", "draft")

        # (action, state it must produce). Walking this list forwards and then
        # its mirror backwards visits every status and every rollback.
        forward = [
            ("configure", ("upcoming", "configured")),
            ("start", ("active", "configured")),
            ("final_review", ("final_review", "completed")),
            ("complete", ("completed", "completed")),
        ]
        visited = [("upcoming", "draft")]
        for action, expected in forward:
            response = move(client, headers, well_id, action)
            assert response.status_code == 200, response.text
            assert state(response.json()) == expected
            visited.append(expected)

        backward = ["reopen", "reactivate", "defer", "draft"]
        for action, expected in zip(backward, reversed(visited[:-1])):
            response = move(client, headers, well_id, action)
            assert response.status_code == 200, response.text
            # A rollback lands on exactly the status the forward move left.
            assert state(response.json()) == expected

        with SessionLocal() as db:
            entries = db.query(AuditLog).filter(AuditLog.entity_type == "well", AuditLog.entity_id == well_id).all()
        assert sum(1 for entry in entries if entry.action == "rollback") == 4
        assert all("Recorded for the test" in entry.summary for entry in entries if entry.action == "rollback")


def test_moves_cannot_skip_a_step_or_run_from_the_wrong_status():
    with TestClient(app) as client:
        headers = login(client)
        well = make_well(client, headers)
        well_id = well["id"]

        # Upcoming / Draft: nothing but `configure` is possible.
        for action in ("start", "defer", "final_review", "reactivate", "complete", "reopen", "draft"):
            refused = move(client, headers, well_id, action)
            assert refused.status_code == 409, (action, refused.text)
        assert "Configured first" in move(client, headers, well_id, "start").json()["detail"]

        assert move(client, headers, well_id, "configure").status_code == 200
        assert move(client, headers, well_id, "start").status_code == 200
        # Active: completion must pass through final review.
        assert move(client, headers, well_id, "complete").status_code == 409
        # A plan reopened as Draft cannot be sent for final review.
        assert move(client, headers, well_id, "draft").status_code == 200
        blocked = move(client, headers, well_id, "final_review")
        assert blocked.status_code == 409
        assert "Configured first" in blocked.json()["detail"]
        assert move(client, headers, well_id, "configure").status_code == 200
        assert move(client, headers, well_id, "final_review").status_code == 200
        # Final review: the plan is closed, and the well cannot jump back to Upcoming.
        for action in ("configure", "draft", "start", "defer", "final_review", "reopen"):
            assert move(client, headers, well_id, action).status_code == 409, action
        assert move(client, headers, well_id, "complete").status_code == 200
        # Completed: only one step back is possible.
        for action in ("configure", "draft", "start", "defer", "final_review", "reactivate", "complete"):
            assert move(client, headers, well_id, action).status_code == 409, action

        unknown = client.post(
            f"/api/v1/rig-well/wells/{well_id}/transition", headers=headers,
            json={"action": "activate", "scope": "drilling", "remarks": "Old action name"},
        )
        assert unknown.status_code == 422
        short = move(client, headers, well_id, "reopen", remarks="x")
        assert short.status_code == 422


def test_a_plan_cannot_be_configured_or_started_without_saved_sections():
    with TestClient(app) as client:
        headers = login(client)
        well = make_well(client, headers, plan=False)
        refused = move(client, headers, well["id"], "configure")
        assert refused.status_code == 409
        assert "Save the drilling section and phase plan" in refused.json()["detail"]
        option = offered(well)["configure"]
        assert option["allowed"] is False
        assert "Save the drilling section and phase plan" in option["reason"]


def test_the_register_offers_exactly_the_moves_the_api_accepts():
    with TestClient(app) as client:
        headers = login(client)
        well = make_well(client, headers)
        well_id = well["id"]

        def refreshed() -> dict:
            return next(item for item in client.get("/api/v1/rig-well/wells", headers=headers).json() if item["id"] == well_id)

        expected_by_state = {
            ("upcoming", "draft"): ({"configure"}, {"start"}),
            ("upcoming", "configured"): ({"draft", "start"}, set()),
            ("active", "configured"): ({"draft", "defer", "final_review"}, set()),
            ("final_review", "completed"): ({"reactivate", "complete"}, set()),
            ("completed", "completed"): ({"reopen"}, set()),
        }
        for action in (None, "configure", "start", "final_review", "complete"):
            if action:
                assert move(client, headers, well_id, action).status_code == 200
            current = refreshed()
            allowed, disabled = expected_by_state[state(current)]
            options = offered(current)
            assert {name for name, option in options.items() if option["allowed"]} == allowed
            assert {name for name, option in options.items() if not option["allowed"]} == disabled
            # Every disabled move says what to do first, and every offered move works.
            assert all(option["reason"] for option in options.values() if not option["allowed"])
            for option in options.values():
                assert option["direction"] in ("forward", "rollback")
                assert option["permission"] == (
                    "rig-well:rollback" if option["direction"] == "rollback" else "rig-well:update"
                )
        # The configuration dialog reads the same list.
        configuration = client.get(f"/api/v1/rig-well/wells/{well_id}/configuration", headers=headers).json()
        assert [option["action"] for option in configuration["transitions"]] == ["reopen"]


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_forward_moves_need_update_and_rollbacks_need_the_rollback_permission():
    with TestClient(app) as client:
        owner = login(client)
        planner = login(client, "planner@example.com")
        approver = login(client, "approver@example.com")
        viewer = login(client, "viewer@example.com")
        well_id = make_well(client, owner)["id"]

        # Read-only: refused before any state is considered.
        denied = move(client, viewer, well_id, "configure")
        assert denied.status_code == 403
        assert "rig-well:update" in denied.json()["detail"] and "rig-well:rollback" in denied.json()["detail"]

        # The approver holds rollback only, so it cannot move a well forward.
        denied = move(client, approver, well_id, "configure")
        assert denied.status_code == 403
        assert "rig-well:update" in denied.json()["detail"]

        # The planner moves the scope forward ...
        configured = move(client, planner, well_id, "configure")
        assert configured.status_code == 200, configured.text
        # ... and is offered the rollback as unavailable, with the capability named.
        option = offered(configured.json())["draft"]
        assert option["allowed"] is False and option["permitted"] is False
        assert "rig-well:rollback" in option["reason"]
        # A forward move that is theirs but blocked by state stays visible, with the reason.
        assert offered(configured.json())["start"]["permitted"] is True
        # The API refuses it too: the menu is a convenience, never the control.
        denied = move(client, planner, well_id, "draft")
        assert denied.status_code == 403
        assert "rig-well:rollback" in denied.json()["detail"]

        for action in ("start", "final_review", "complete"):
            assert move(client, planner, well_id, action).status_code == 200
        for action in ("reopen", "reactivate", "defer", "draft"):
            # A rollback the planner may not make is refused whatever the state.
            assert move(client, planner, well_id, action).status_code == 403

        # The approver walks every rollback, and is told when a forward move is not theirs.
        for action, expected in (
            ("reopen", ("final_review", "completed")),
            ("reactivate", ("active", "configured")),
            ("defer", ("upcoming", "configured")),
            ("draft", ("upcoming", "draft")),
        ):
            response = move(client, approver, well_id, action)
            assert response.status_code == 200, response.text
            assert state(response.json()) == expected
        approver_view = offered(response.json())
        assert approver_view["configure"]["allowed"] is False and approver_view["configure"]["permitted"] is False
        assert "rig-well:update" in approver_view["configure"]["reason"]
        # Blocked by state *and* not theirs: the state reason is shown, but the register hides the move.
        assert approver_view["start"]["allowed"] is False and approver_view["start"]["permitted"] is False

        with SessionLocal() as db:
            entries = db.query(AuditLog).filter(AuditLog.entity_type == "well", AuditLog.action == "rollback").all()
        assert {entry.actor_email for entry in entries} == {"approver@example.com"}
        assert len(entries) == 4


def test_rollback_is_a_provisioned_capability_owners_always_hold():
    assert "rollback" in CAPABILITIES["rig-well"]
    assert well_lifecycle.ROLLBACK_PERMISSION == "rig-well:rollback"
    assert {item.action for item in well_lifecycle.TRANSITIONS if item.direction == "rollback"} == {
        "draft", "defer", "reactivate", "reopen",
    }


def test_transitions_stay_inside_the_callers_workspace():
    with TestClient(app) as client:
        owner = login(client)
        well_id = make_well(client, owner)["id"]
        with SessionLocal() as db:
            other = Organization(slug="south", name="South Energy")
            db.add(other)
            db.flush()
            keys = [Permission(organization_id=other.id, key=key, description=key) for key in PERMISSIONS]
            role = Role(organization_id=other.id, name="Owner", is_owner=True, permissions=keys)
            db.add(User(
                organization_id=other.id, email="owner@example.com", full_name="South Owner",
                password_hash=hash_password(PASSWORD), roles=[role],
            ))
            db.commit()
        response = client.post("/api/v1/auth/login", json={"organization": "south", "email": "owner@example.com", "password": PASSWORD})
        south = {"Authorization": f"Bearer {response.json()['access_token']}"}
        assert move(client, south, well_id, "configure").status_code == 404


# ---------------------------------------------------------------------------
# One rule for both ladders, everywhere
# ---------------------------------------------------------------------------
def test_the_database_refuses_a_scope_whose_two_statuses_disagree():
    with TestClient(app) as client:
        headers = login(client)
        well_id = make_well(client, headers)["id"]
    for status, plan in (("final_review", "configured"), ("completed", "draft"), ("active", "completed"), ("upcoming", "completed")):
        with SessionLocal() as db:
            well = db.get(Well, well_id)
            well.status = status
            well.config_status = plan
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    # The helper every non-ladder writer uses always returns a legal pair.
    assert well_lifecycle.consistent_plan("final_review", "configured") == "completed"
    assert well_lifecycle.consistent_plan("completed", "draft") == "completed"
    assert well_lifecycle.consistent_plan("active", "completed") == "configured"
    assert well_lifecycle.consistent_plan("upcoming", "draft") == "draft"


def test_roll_up_rules_are_the_same_in_python_and_in_the_register_filter():
    assert rolled_up_status(["completed", "completed"]) == "completed"
    assert rolled_up_status(["upcoming", "upcoming"]) == "upcoming"
    assert rolled_up_status(["final_review", "completed"]) == "final_review"
    assert rolled_up_status(["final_review", "final_review"]) == "final_review"
    assert rolled_up_status(["active", "upcoming"]) == "active"
    assert rolled_up_status(["completed", "upcoming"]) == "active"
    assert rolled_up_status(["final_review", "upcoming"]) == "active"
    assert rolled_up_plan([("upcoming", "draft"), ("active", "configured")]) == "configured"
    assert rolled_up_plan([("upcoming", "draft"), ("completed", "completed")]) == "draft"
    assert rolled_up_plan([("final_review", "completed"), ("completed", "completed")]) == "completed"

    with TestClient(app) as client:
        headers = login(client)
        # Completion is removed from each well so one scope decides it.
        targets = {"upcoming": [], "active": ["configure", "start"],
                   "final_review": ["configure", "start", "final_review"],
                   "completed": ["configure", "start", "final_review", "complete"]}
        ids = {}
        for index, (status, actions) in enumerate(targets.items()):
            well = make_well(client, headers, f"WELL-{index}")
            ids[status] = well["id"]
            assert client.delete(f"/api/v1/rig-well/wells/{well['id']}?scope=completion", headers=headers).status_code == 200
            for action in actions:
                assert move(client, headers, well["id"], action).status_code == 200
        # A mixed well: Drilling completed, Completion still upcoming -> Active.
        mixed = make_well(client, headers, "WELL-MIX")
        for action in ("configure", "start", "final_review", "complete"):
            assert move(client, headers, mixed["id"], action).status_code == 200

        for status in targets:
            listed = client.get(f"/api/v1/rig-well/wells?status={status}", headers=headers).json()
            expected = {ids[status]} | ({mixed["id"]} if status == "active" else set())
            assert {item["id"] for item in listed} == expected
            assert {item["tracking_status"] for item in listed} == {status}
        # With a scope the filter reads that scope's own status.
        scoped = client.get("/api/v1/rig-well/wells?status=completed&scope=drilling", headers=headers).json()
        assert {item["id"] for item in scoped} == {ids["completed"], mixed["id"]}
        by_plan = client.get("/api/v1/rig-well/wells?config_status=completed&scope=drilling", headers=headers).json()
        assert {item["id"] for item in by_plan} == {ids["final_review"], ids["completed"], mixed["id"]}
        assert client.get("/api/v1/rig-well/wells?config_status=final_review", headers=headers).status_code == 422

        overview = client.get("/api/v1/rig-well/overview", headers=headers).json()
        counts = {key: overview[f"{key}_wells"] for key in ("upcoming", "active", "final_review", "completed")}
        assert counts == {"upcoming": 1, "active": 2, "final_review": 1, "completed": 1}
        # The four well statuses partition the live wells.
        assert sum(counts.values()) == 5
        # Plan counts cover the wells still open: the upcoming one is a draft, the
        # active one is configured, and the mixed one has a draft Completion plan.
        assert (overview["draft_wells"], overview["configured_wells"]) == (2, 1)


def test_a_closed_scope_takes_no_plan_edit_budget_or_adjustment_until_rolled_back():
    with TestClient(app) as client:
        headers = login(client)
        well = make_well(client, headers)
        well_id = well["id"]
        plan = client.get(f"/api/v1/rig-well/wells/{well_id}/configuration", headers=headers).json()
        payload = {
            "depth_unit": "m",
            "sections": [{
                "hole_section_id": section["hole_section_id"], "from_depth": "0", "to_depth": "500", "remarks": "",
                "phases": [{"phase_id": phase["phase_id"], "days": "12", "remarks": ""} for phase in section["phases"]],
            } for section in plan["sections"]],
        }
        afe = {"rig_id": well["rig_id"], "well_id": well_id, "afe_name": "Drill well", "afe_type": "Drilling", "remarks": ""}

        # Draft plan: no budget yet.
        early = client.post("/api/v1/afe/afes", headers=headers, json={**afe, "afe_code": "AFE-0"})
        assert early.status_code == 422
        assert "Mark it as Configured" in early.json()["detail"]

        # Upcoming with a configured plan is budgetable before the scope starts.
        assert move(client, headers, well_id, "configure").status_code == 200
        assert client.post("/api/v1/afe/afes", headers=headers, json={**afe, "afe_code": "AFE-1"}).status_code == 200

        assert move(client, headers, well_id, "start").status_code == 200
        assert move(client, headers, well_id, "final_review").status_code == 200
        refused = client.post("/api/v1/afe/afes", headers=headers, json={**afe, "afe_code": "AFE-2"})
        assert refused.status_code == 422
        assert "Final review" in refused.json()["detail"] and "Return it to Active" in refused.json()["detail"]
        locked = client.put(f"/api/v1/rig-well/wells/{well_id}/configuration", headers=headers, json=payload)
        assert locked.status_code == 409
        assert "Final review" in locked.json()["detail"]
        adjustment_payload = {
            "configuration_scope": "drilling", "reason": "Late change", "sow_summary": "Extra run",
            "sections": payload["sections"],
        }
        adjustment = client.post(
            f"/api/v1/rig-well/wells/{well_id}/plan-adjustments", headers=headers, json=adjustment_payload,
        )
        assert adjustment.status_code == 409, adjustment.text
        assert "Final review" in adjustment.json()["detail"] and "plan adjustment" in adjustment.json()["detail"]

        assert move(client, headers, well_id, "complete").status_code == 200
        refused = client.post("/api/v1/afe/afes", headers=headers, json={**afe, "afe_code": "AFE-3"})
        assert refused.status_code == 422
        assert "Completed" in refused.json()["detail"]

        # Rolling back one step at a time reopens the work in the same order.
        assert move(client, headers, well_id, "reopen").status_code == 200
        assert client.post("/api/v1/afe/afes", headers=headers, json={**afe, "afe_code": "AFE-4"}).status_code == 422
        assert move(client, headers, well_id, "reactivate").status_code == 200
        assert client.post("/api/v1/afe/afes", headers=headers, json={**afe, "afe_code": "AFE-5"}).status_code == 200
        # A draft adjustment recorded while Active cannot be approved once the scope is closed again.
        recorded = client.post(
            f"/api/v1/rig-well/wells/{well_id}/plan-adjustments", headers=headers, json=adjustment_payload,
        )
        assert recorded.status_code == 201, recorded.text
        assert move(client, headers, well_id, "final_review").status_code == 200
        late = client.post(
            f"/api/v1/rig-well/plan-adjustments/{recorded.json()['id']}/approve", headers=headers, json={"remarks": "Too late"},
        )
        assert late.status_code == 409, late.text
        assert "Final review" in late.json()["detail"]
        assert move(client, headers, well_id, "reactivate").status_code == 200
        approved = client.post(
            f"/api/v1/rig-well/plan-adjustments/{recorded.json()['id']}/approve", headers=headers, json={"remarks": "Agreed"},
        )
        assert approved.status_code == 200, approved.text
        # The plan itself still needs to be reopened as Draft before it is edited.
        assert client.put(f"/api/v1/rig-well/wells/{well_id}/configuration", headers=headers, json=payload).status_code == 409
        assert move(client, headers, well_id, "draft").status_code == 200
        assert client.put(f"/api/v1/rig-well/wells/{well_id}/configuration", headers=headers, json=payload).status_code == 200


def test_a_re_added_scope_starts_at_the_first_rung_of_both_ladders():
    with TestClient(app) as client:
        headers = login(client)
        well = make_well(client, headers)
        well_id = well["id"]
        assert client.delete(f"/api/v1/rig-well/wells/{well_id}?scope=completion", headers=headers).status_code == 200
        added = client.post(f"/api/v1/rig-well/wells/{well_id}/scopes/completion/activate", headers=headers)
        assert added.status_code == 200, added.text
        assert state(added.json(), "completion") == ("upcoming", "draft")
        assert set(offered(added.json(), "completion")) == {"configure", "start"}


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------
def test_migration_moves_final_review_to_the_well_ladder_and_grants_rollback(tmp_path):
    database = tmp_path / "lifecycle.sqlite3"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    backend = Path(__file__).resolve().parents[1]

    def migrate(target: str, op: str = "upgrade") -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", op, target], cwd=backend,
            env=environment, check=True, capture_output=True, text=True,
        )

    def wells(connection) -> dict[str, tuple[str, str, str, str]]:
        return {
            row[0]: row[1:]
            for row in connection.execute(
                "SELECT well_code, status, config_status, completion_status, completion_config_status FROM wells"
            )
        }

    migrate("d7e3a91c4f60")
    # (well, drilling status, drilling plan, completion status, completion plan) in the old vocabulary.
    legacy = [
        ("W-PLAN", "upcoming", "draft", "upcoming", "draft"),
        ("W-SIGNED", "upcoming", "final_review", "upcoming", "configured"),
        ("W-RUN", "active", "configured", "active", "draft"),
        ("W-REVIEW", "active", "final_review", "active", "final_review"),
        ("W-DONE", "completed", "final_review", "completed", "configured"),
    ]
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("INSERT INTO organizations (id, slug, name, created_at) VALUES ('org', 'legacy', 'Legacy', CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO rigs (id, organization_id, rig_code, rig_name, created_at, updated_at) VALUES ('rig', 'org', 'R-1', 'Rig', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO blocks (id, organization_id, block_code, block_name, created_at, updated_at) VALUES ('block', 'org', 'B-1', 'Block', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        for index, (code, status, plan, completion_status, completion_plan) in enumerate(legacy):
            connection.execute(
                "INSERT INTO wells (id, organization_id, rig_id, block_id, well_code, well_name, well_location, objective, "
                "status, config_status, completion_status, completion_config_status, created_at, updated_at) "
                "VALUES (?, 'org', 'rig', 'block', ?, 'Well', 'Location', 'Objective', ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (f"well-{index}", code, status, plan, completion_status, completion_plan),
            )
        for key, permission_id in (("rig-well:update", "p-update"), ("rig-well:read", "p-read")):
            connection.execute(
                "INSERT INTO permissions (id, organization_id, key, description, created_at) VALUES (?, 'org', ?, ?, CURRENT_TIMESTAMP)",
                (permission_id, key, key),
            )
        for role_id, name, is_owner in (("r-owner", "Owner", 1), ("r-planner", "Planner", 0), ("r-viewer", "Viewer", 0)):
            connection.execute(
                "INSERT INTO roles (id, organization_id, name, description, is_owner, created_at) VALUES (?, 'org', ?, '', ?, CURRENT_TIMESTAMP)",
                (role_id, name, is_owner),
            )
        connection.executemany(
            "INSERT INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
            [("r-planner", "p-update"), ("r-planner", "p-read"), ("r-viewer", "p-read")],
        )

    migrate("head")
    with sqlite3.connect(database) as connection:
        assert wells(connection) == {
            "W-PLAN": ("upcoming", "draft", "upcoming", "draft"),
            # Signed off but never started: still upcoming, on a configured plan.
            "W-SIGNED": ("upcoming", "configured", "upcoming", "configured"),
            "W-RUN": ("active", "configured", "active", "draft"),
            # Final review moved from the plan ladder to the well ladder.
            "W-REVIEW": ("final_review", "completed", "final_review", "completed"),
            "W-DONE": ("completed", "completed", "completed", "completed"),
        }
        holders = {
            row[0] for row in connection.execute(
                "SELECT role_id FROM role_permissions JOIN permissions ON permissions.id = role_permissions.permission_id "
                "WHERE permissions.key = 'rig-well:rollback'"
            )
        }
        # The owner, and the role that could already reopen / defer / reactivate.
        assert holders == {"r-owner", "r-planner"}
        for invalid in (
            "UPDATE wells SET config_status = 'final_review' WHERE well_code = 'W-RUN'",
            "UPDATE wells SET status = 'final_review' WHERE well_code = 'W-RUN'",
            "UPDATE wells SET config_status = 'completed' WHERE well_code = 'W-RUN'",
            "UPDATE wells SET completion_status = 'active' WHERE well_code = 'W-DONE'",
            "UPDATE wells SET status = 'archived' WHERE well_code = 'W-PLAN'",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(invalid)

    # Downgrade the lifecycle migration itself: `-1` would only step back over the
    # migration that happens to sit above it, so name the revision it revises.
    migrate("d7e3a91c4f60", op="downgrade")
    with sqlite3.connect(database) as connection:
        assert wells(connection) == {
            "W-PLAN": ("upcoming", "draft", "upcoming", "draft"),
            "W-SIGNED": ("upcoming", "configured", "upcoming", "configured"),
            "W-RUN": ("active", "configured", "active", "draft"),
            "W-REVIEW": ("active", "final_review", "active", "final_review"),
            "W-DONE": ("completed", "final_review", "completed", "final_review"),
        }
        assert connection.execute("SELECT COUNT(*) FROM permissions WHERE key = 'rig-well:rollback'").fetchone() == (0,)
    migrate("head")
    with sqlite3.connect(database) as connection:
        assert wells(connection)["W-REVIEW"] == ("final_review", "completed", "final_review", "completed")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
