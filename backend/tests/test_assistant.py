"""The in-application guide: constant memory, permission-aware answers, no fiction.

The guide must answer from durable memory and the workspace's own figures, must
never disclose a figure the caller may not read, must say which capability is
missing instead of guessing, and must let a workspace add its own memory.
"""

import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import Block, Organization, Permission, Rig, Role, User, Well
from app.services import assistant as service


PERMISSIONS = [
    *(f"rig-well:{action}" for action in ("read", "create", "update")),
    *(f"afe:{action}" for action in ("read", "create", "estimate", "approve")),
    *(f"daily-cost:{action}" for action in ("read", "create", "update", "submit")),
    *(f"master-data:{action}" for action in ("read", "create", "update")),
    "assistant:read",
    "assistant:manage",
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
            viewer_role = Role(
                organization_id=organization.id, name="Viewer", is_owner=False,
                permissions=[row for row in permissions if row.key in ("rig-well:read", "assistant:read")],
            )
            db.add(User(
                organization_id=organization.id, email="owner@example.com", full_name="Test Owner",
                password_hash=hash_password("correct-password-123"), roles=[owner_role],
            ))
            db.add(User(
                organization_id=organization.id, email="viewer@example.com", full_name="Read Only",
                password_hash=hash_password("correct-password-123"), roles=[viewer_role],
            ))
        db.commit()
    yield


def login(client: TestClient, email: str = "owner@example.com", organization: str = "north") -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={
        "organization": organization, "email": email, "password": "correct-password-123",
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _well(organization_slug: str = "north", code: str = "WELL-01", *, spud: bool = True) -> str:
    with SessionLocal() as db:
        organization = db.query(Organization).filter(Organization.slug == organization_slug).one()
        suffix = code.split("-")[-1]
        rig = Rig(organization_id=organization.id, rig_code=f"RIG-{suffix}", rig_name=f"Rig {suffix}", remarks="")
        block = Block(
            organization_id=organization.id, block_code=f"BLOCK-{suffix}",
            block_name=f"Block {suffix}", description="",
        )
        db.add_all([rig, block])
        db.flush()
        well = Well(
            organization_id=organization.id, rig_id=rig.id, block_id=block.id,
            well_code=code, well_name="Well One", well_location="North field",
            objective="Development", remarks="", status="active", config_status="configured",
        )
        if spud:
            well.drilling_spud_at = __import__("datetime").datetime(2026, 10, 19, 10, 0)
        db.add(well)
        db.commit()
        return well.id


def test_overview_seeds_the_constant_memory():
    with TestClient(app) as client:
        headers = login(client)
        response = client.get("/api/v1/assistant/overview", headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["enabled"] is True
        assert data["can_manage"] is True
        assert data["memory_entries"] >= len(service.SYSTEM_MEMORY)
        assert len(data["quick_prompts"]) >= 4
        # The shipped memory is idempotent: a second read does not duplicate it.
        again = client.get("/api/v1/assistant/overview", headers=headers).json()
        assert again["memory_entries"] == data["memory_entries"]

        memory = client.get("/api/v1/assistant/memory", headers=headers)
        assert memory.status_code == 200, memory.text
        rows = memory.json()
        keys = {row["memory_key"] for row in rows}
        assert {"calc-actual-days", "calc-responsible-party", "entry-daily-sheet"} <= keys
        assert all(row["is_system"] for row in rows)
        assert all(row["body"] for row in rows)


def test_knowledge_answers_quote_memory_and_give_a_route():
    with TestClient(app) as client:
        headers = login(client)
        answer = client.post("/api/v1/assistant/ask", headers=headers, json={
            "question": "How are actual days calculated?",
        })
        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert body["intent"] == "knowledge"
        assert body["memory_key"] == "calc-actual-days"
        assert "0.583" in body["answer"]
        assert body["steps"], "workflow memory must carry its steps"
        assert any(source["route"] for source in body["sources"])
        assert body["confidence"] in ("high", "medium")

        # A responsible-party question must find the attribution memory, not AFE text.
        party = client.post("/api/v1/assistant/ask", headers=headers, json={
            "question": "How is cost attributed to the responsible party?",
        }).json()
        assert party["memory_key"] == "calc-responsible-party"
        assert "booked" in party["answer"].lower()

        # An unmatchable question lists what the guide can answer instead of inventing.
        unknown = client.post("/api/v1/assistant/ask", headers=headers, json={
            "question": "Who won the world cup?",
        }).json()
        assert unknown["confidence"] == "low"
        assert "memory" in unknown["answer"].lower()


def test_permissions_decide_both_the_figures_and_the_answer():
    with TestClient(app) as client:
        _well()
        viewer = login(client, "viewer@example.com")
        # A viewer may use the guide but has no daily-cost capability: the guide
        # names the missing capability instead of showing or guessing a figure.
        response = client.post("/api/v1/assistant/ask", headers=viewer, json={
            "question": "AFE balance on WELL-01",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["intent"] == "permission"
        assert "daily-cost:read" in body["answer"]

        # Data-health checks only cover what the viewer can read.
        health = client.post("/api/v1/assistant/ask", headers=viewer, json={
            "question": "What is missing in my workspace?",
        }).json()
        assert health["intent"] == "data_health"
        assert all("afe:read" not in fact["label"].lower() for fact in health["facts"])

        # A workspace memory entry is not manageable by a viewer.
        create = client.post("/api/v1/assistant/memory", headers=viewer, json={
            "title": "Viewer convention", "body": "This must not be created by a viewer.",
        })
        assert create.status_code == 403


def test_workspace_memory_is_used_and_isolated():
    with TestClient(app) as client:
        headers = login(client)
        created = client.post("/api/v1/assistant/memory", headers=headers, json={
            "title": "Our approval rule",
            "category": "policy",
            "memory_key": "local-approval-rule",
            "keywords": "approval sign off authority local rule",
            "body": "In this workspace an AFE above 5,000,000 must be approved by the drilling manager "
                    "and the finance controller before the estimate is submitted.",
            "steps": ["Raise the AFE.", "Route it to both approvers."],
            "route": "/afe",
        })
        assert created.status_code == 201, created.text
        row = created.json()
        assert row["is_system"] is False

        asked = client.post("/api/v1/assistant/ask", headers=headers, json={
            "question": "What is our local approval rule for a large AFE?",
        }).json()
        assert asked["memory_key"] == "local-approval-rule"
        assert "drilling manager" in asked["answer"]

        # Shipped memory cannot be rewritten or deleted, but workspace memory can.
        memory = client.get("/api/v1/assistant/memory", headers=headers).json()
        system_row = next(item for item in memory if item["is_system"])
        assert client.patch(f"/api/v1/assistant/memory/{system_row['id']}", headers=headers, json={
            "title": "Rewritten shipped memory",
        }).status_code == 409
        assert client.delete(f"/api/v1/assistant/memory/{system_row['id']}", headers=headers).status_code == 409

        updated = client.patch(f"/api/v1/assistant/memory/{row['id']}", headers=headers, json={
            "title": "Our approval rule (revised)", "body": "AFEs above 1,000,000 need the drilling manager.",
        })
        assert updated.status_code == 200, updated.text
        assert updated.json()["title"].endswith("(revised)")

        # Another workspace never sees this memory.
        south = login(client, organization="south")
        south_memory = client.get("/api/v1/assistant/memory", headers=south).json()
        assert all(item["memory_key"] != "local-approval-rule" for item in south_memory)

        assert client.delete(f"/api/v1/assistant/memory/{row['id']}", headers=headers).status_code == 204


def test_data_health_and_status_answers_come_from_the_workspace():
    with TestClient(app) as client:
        headers = login(client)
        _well(code="WELL-01", spud=True)
        _well(code="WELL-02", spud=False)

        status = client.post("/api/v1/assistant/ask", headers=headers, json={
            "question": "How many wells are active?",
        }).json()
        assert status["intent"] == "status"
        assert any(fact["label"] == "Active" and fact["value"] == "2" for fact in status["facts"])

        health = client.post("/api/v1/assistant/ask", headers=headers, json={
            "question": "What is missing in my workspace?",
        }).json()
        assert health["intent"] == "data_health"
        labels = {fact["label"] for fact in health["facts"]}
        assert "Wells without a spud instant" in labels
        spud_gap = next(fact for fact in health["facts"] if fact["label"] == "Wells without a spud instant")
        assert "WELL-02" in spud_gap["hint"]
        assert "WELL-01" not in spud_gap["hint"]

        # No daily cost exists yet, so actual days are honestly reported as absent.
        days = client.post("/api/v1/assistant/ask", headers=headers, json={
            "question": "How many actual days does WELL-01 have?",
        }).json()
        assert days["intent"] in ("actual_days", "knowledge")
        assert "spud" in days["answer"].lower()


def test_the_transcript_is_private_to_the_caller():
    with TestClient(app) as client:
        headers = login(client)
        client.post("/api/v1/assistant/ask", headers=headers, json={"question": "Where is the well cost analysis?"})
        history = client.get("/api/v1/assistant/history", headers=headers)
        assert history.status_code == 200, history.text
        assert history.json()[0]["question"] == "Where is the well cost analysis?"

        other = login(client, "viewer@example.com")
        assert client.get("/api/v1/assistant/history", headers=other).json() == []

        with SessionLocal() as db:
            organization = db.query(Organization).filter(Organization.slug == "north").one()
            assert db.scalar(
                select(service.AssistantConversation).where(
                    service.AssistantConversation.organization_id == organization.id,
                )
            ) is not None
