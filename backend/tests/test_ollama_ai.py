"""Offline LAN Ollama integration: .env validation, LAN error handling, Guide Q&A,
multi-well comparison, Cost Intelligence opt-in review, RBAC, tenant isolation & audit.
"""

from contextlib import contextmanager
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time
from typing import Any

from fastapi.testclient import TestClient
import pytest

from test_business_dashboard import _post, _setup, fresh_database, login  # noqa: F401 - autouse fixture

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User
from app.services import ollama as ollama_service


def _grant(org_slug: str, email: str, keys: tuple[str, ...]) -> None:
    with SessionLocal() as db:
        org = db.query(Organization).filter(Organization.slug == org_slug).one()
        user = db.query(User).filter(User.organization_id == org.id, User.email == email).one()
        existing = {p.key: p for p in db.query(Permission).filter(Permission.organization_id == org.id).all()}
        role = user.roles[0]
        for key in keys:
            perm = existing.get(key)
            if perm is None:
                perm = Permission(organization_id=org.id, key=key, description=key)
                db.add(perm)
                db.flush()
                existing[key] = perm
            if perm not in role.permissions:
                role.permissions.append(perm)
        db.commit()


def _create_scoped_user(org_slug: str, email: str, keys: tuple[str, ...]) -> None:
    with SessionLocal() as db:
        org = db.query(Organization).filter(Organization.slug == org_slug).one()
        existing = {p.key: p for p in db.query(Permission).filter(Permission.organization_id == org.id).all()}
        perms: list[Permission] = []
        for key in keys:
            perm = existing.get(key)
            if perm is None:
                perm = Permission(organization_id=org.id, key=key, description=key)
                db.add(perm)
                db.flush()
                existing[key] = perm
            perms.append(perm)
        role = Role(organization_id=org.id, name=f"role-{email}", permissions=perms)
        db.add(
            User(
                organization_id=org.id,
                email=email,
                full_name="Limited Reader",
                password_hash=hash_password("correct-password-123"),
                roles=[role],
            )
        )
        db.commit()


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _mock_ollama_server(handler_fn):
    """Run a real HTTP server on loopback representing a LAN Ollama machine."""
    recorded: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def _dispatch(self, method: str) -> None:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            parsed: Any = None
            if raw:
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except ValueError:
                    parsed = raw.decode("utf-8", errors="replace")
            req = {
                "method": method,
                "path": self.path,
                "auth": self.headers.get("Authorization", ""),
                "body": parsed,
            }
            recorded.append(req)
            status, payload, extra_headers = handler_fn(req)
            body_bytes = (
                payload
                if isinstance(payload, bytes)
                else json.dumps(payload).encode("utf-8")
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_bytes)))
            for hk, hv in (extra_headers or {}).items():
                self.send_header(hk, hv)
            self.end_headers()
            try:
                self.wfile.write(body_bytes)
            except BrokenPipeError:
                return

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def log_message(self, fmt: str, *args: Any) -> None:  # silence test output
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", recorded
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _add_second_well(client: TestClient, headers: dict[str, str], setup: dict[str, Any], *, code: str, name: str, daily_rates: list[str], planned_rate: str = "1000", start: date = date(2026, 10, 1)) -> dict[str, Any]:
    well = _post(client, "/api/v1/rig-well/wells", headers, {
        "rig_id": setup["rig"]["id"], "block_id": setup["well"]["block_id"],
        "well_code": code, "well_name": name,
        "well_location": "Field East", "objective": "Appraisal", "remarks": "",
    })
    assert client.put(f"/api/v1/rig-well/wells/{well['id']}/configuration", headers=headers, json={
        "depth_unit": "m",
        "sections": [{
            "hole_section_id": setup["hole"]["id"], "from_depth": "0", "to_depth": "1500", "remarks": "",
            "phases": [{"phase_id": setup["phase"]["id"], "days": "15", "remarks": ""}],
        }],
    }).status_code == 200
    assert client.post(f"/api/v1/rig-well/wells/{well['id']}/transition", headers=headers, json={
        "action": "configure", "remarks": "Configured",
    }).status_code == 200
    sub = _post(client, "/api/v1/rig-well/sub-activities", headers, {
        "well_id": well["id"], "sub_activity_code": f"SA-{code}", "sub_activity_name": f"Drill {code}",
        "activity_id": setup["activity"]["id"], "responsible_party": "Drilling team",
        "description": "Drilling operations",
    })
    afe = _post(client, "/api/v1/afe/afes", headers, {
        "rig_id": setup["rig"]["id"], "well_id": well["id"], "afe_code": f"AFE-{code}",
        "afe_name": f"{name} Drilling AFE", "afe_type": "Drilling", "remarks": "",
    }, status=200)
    assert client.put(f"/api/v1/afe/afes/{afe['id']}/estimate", headers=headers, json={
        "services": [{
            "client_key": "svc", "service_id": setup["service"]["id"], "charging_basis": "Day Rate",
            "hole_section_id": setup["hole"]["id"], "phase_id": setup["phase"]["id"], "currency": "USD",
            "service_amount": "0", "remarks": "",
            "rates": [{"category": "Operation", "unit_rate": planned_rate}],
            "charges": [{"category": "Operation", "quantity": "15", "quantity_unit": "days"}],
            "section_rates": [],
        }],
        "consumables": [], "tangibles": [], "standard_currency": "", "exchange_rates": [],
    }).status_code == 200

    entry_ids: list[str] = []
    for idx, rate_val in enumerate(daily_rates):
        day_str = (start + timedelta(days=idx)).isoformat()
        created = _post(client, "/api/v1/daily-cost/entries", headers, {
            "well_id": well["id"], "afe_id": afe["id"], "cost_date": day_str, "remarks": "",
        })
        eid = created["entry"]["id"]
        entry_ids.append(eid)
        baseline = client.get(f"/api/v1/daily-cost/entries/{eid}/baseline", headers=headers).json()
        rate_id = baseline["service_rates"][0]["id"]
        line_payload: dict[str, Any] = {
            "activity_id": setup["activity"]["id"], "hole_section_id": setup["hole"]["id"],
            "phase_id": setup["phase"]["id"], "sub_activity_id": sub["id"],
            "vendor_id": setup["vendor"]["id"], "quantity": "1", "quantity_unit": "days",
            "currency": "USD", "service_id": setup["service"]["id"],
            "baseline_service_rate_id": rate_id, "charging_basis": "Day Rate",
            "charge_category": "Operation",
        }
        if rate_val != planned_rate:
            line_payload["override_rate"] = rate_val
            line_payload["override_reason"] = "Field invoice adjustment"
        saved = client.put(f"/api/v1/daily-cost/entries/{eid}", headers=headers, json={
            "remarks": "daily cost", "services": [line_payload], "consumables": [], "tangibles": [],
        })
        assert saved.status_code == 200, saved.text
    return {"well": well, "afe": afe, "entries": entry_ids}


# ---------------------------------------------------------------------------
# 1. Settings & .env validation
# ---------------------------------------------------------------------------

def test_ollama_settings_defaults_lan_urls_normalization_and_secret_masking():
    defaults = Settings()
    assert defaults.ollama_enabled is False
    assert defaults.ollama_model == "qwen3:4b-q4_K_M"
    assert defaults.ollama_api_path == "/api/chat"
    assert defaults.ollama_tags_path == "/api/tags"
    assert defaults.ollama_connect_timeout_seconds == 5
    assert defaults.ollama_timeout_seconds == 90
    assert defaults.ollama_think is False

    # LAN IP + accidental whitespace around ':' + pasted endpoint path + API key
    dummy_key = "placeholder-" + ("k" * 16) + "-9876"
    lan = Settings(
        ollama_enabled=True,
        ollama_base_url="http://192.168.1.50:11434/v1/chat/completions",
        ollama_model="qwen3: 4b-q4_K_M",
        ollama_api_key=dummy_key,
        ollama_connect_timeout_seconds=4,
        ollama_timeout_seconds=120,
        ollama_temperature=0.15,
        ollama_num_ctx=16384,
        ollama_max_tokens=1500,
        ollama_keep_alive="30m",
    )
    assert lan.ollama_base_url == "http://192.168.1.50:11434"
    assert lan.ollama_endpoint_label == "http://192.168.1.50:11434"
    assert lan.ollama_api_path == "/v1/chat/completions"
    assert lan.ollama_model == "qwen3:4b-q4_K_M"
    assert dummy_key not in str(lan.safe_summary())
    assert dummy_key not in repr(lan)
    assert lan.safe_summary()["ollama_api_key"] == "***9876"

    # Private LAN HTTP remains permitted in production deployments.
    prod = Settings(
        environment="production",
        secret_key="p" * 48,
        secure_cookies=True,
        cors_origins="https://wellcost.example.com",
        ollama_enabled=True,
        ollama_base_url="http://10.20.30.40:11434",
        ollama_model="qwen3:4b-q4_K_M",
    )
    assert prod.ollama_endpoint_label == "http://10.20.30.40:11434"

    # Invalid settings fail closed.
    for bad in (
        {"ollama_base_url": "ftp://192.168.1.50:11434"},
        {"ollama_base_url": "http://user:pass@192.168.1.50:11434"},
        {"ollama_base_url": "http://192.168.1.*:11434"},
        {"ollama_base_url": "http://192.168.1.50:11434/../../etc"},
        {"ollama_api_path": "api/chat"},
        {"ollama_api_path": "/api/../secret"},
        {"ollama_model": "bad model with spaces"},
        {"ollama_connect_timeout_seconds": 30, "ollama_timeout_seconds": 10},
        {"ollama_timeout_seconds": 999},
        {"ollama_temperature": 1.5},
        {"ollama_num_ctx": 256},
        {"ollama_max_tokens": 16},
    ):
        with pytest.raises(ValueError):
            Settings(**bad)


# ---------------------------------------------------------------------------
# 2. Ollama client protocols, <think> stripping, probe & communication errors
# ---------------------------------------------------------------------------

def test_ollama_client_protocols_probe_and_think_fallback():
    saw_think_rejection = {"count": 0}

    def responder(req: dict[str, Any]):
        if req["path"] == "/api/tags":
            return 200, {"models": [{"name": "qwen3:4b-q4_K_M"}, {"name": "nomic-embed-text:latest"}]}, {}
        if req["path"] == "/api/chat":
            assert req["auth"] == "Bearer lan-token-123"
            # Simulate an older Ollama build rejecting top-level `think` on first try.
            if "think" in req["body"] and saw_think_rejection["count"] == 0:
                saw_think_rejection["count"] += 1
                return 400, {"error": "unknown field: think"}, {}
            return 200, {
                "model": "qwen3:4b-q4_K_M",
                "message": {"role": "assistant", "content": "<think>internal math</think>WELL-X total cost is USD 12,500.00."},
            }, {}
        if req["path"] == "/v1/chat/completions":
            return 200, {
                "model": "qwen3:4b-q4_K_M",
                "choices": [{"message": {"role": "assistant", "content": "OpenAI-compatible Ollama reply."}}],
            }, {}
        if req["path"] == "/api/generate":
            return 200, {"model": "qwen3:4b-q4_K_M", "response": "Generate endpoint reply."}, {}
        return 404, {"error": "not found"}, {}

    with _mock_ollama_server(responder) as (base_url, calls):
        cfg = Settings(
            ollama_enabled=True,
            ollama_base_url=base_url,
            ollama_model="qwen3:4b-q4_K_M",
            ollama_api_key="lan-token-123",
        )
        status = ollama_service.check_status(probe=True, settings=cfg)
        assert status.status == "ready"
        assert status.reachable is True
        assert status.model_available is True
        assert "qwen3:4b-q4_K_M" in status.installed_models

        reply = ollama_service.chat(system_prompt="sys", user_prompt="hello", settings=cfg)
        assert reply.content == "WELL-X total cost is USD 12,500.00."
        assert "<think>" not in reply.content
        assert saw_think_rejection["count"] == 1

        openai_cfg = Settings(ollama_enabled=True, ollama_base_url=base_url, ollama_api_path="/v1/chat/completions")
        assert ollama_service.chat(system_prompt="sys", user_prompt="hi", settings=openai_cfg).content == "OpenAI-compatible Ollama reply."

        gen_cfg = Settings(ollama_enabled=True, ollama_base_url=base_url, ollama_api_path="/api/generate")
        assert ollama_service.chat(system_prompt="sys", user_prompt="hi", settings=gen_cfg).content == "Generate endpoint reply."
        assert len(calls) == 5


def test_ollama_client_reports_every_communication_failure_clearly():
    # Disabled in .env
    disabled_cfg = Settings(ollama_enabled=False)
    assert ollama_service.check_status(probe=True, settings=disabled_cfg).error_code == "disabled"
    with pytest.raises(ollama_service.OllamaCommunicationError) as exc_info:
        ollama_service.chat(system_prompt="s", user_prompt="u", settings=disabled_cfg)
    assert exc_info.value.code == "disabled" and "OLLAMA_ENABLED=true" in exc_info.value.message

    # Connection refused (unused local port simulating stopped Ollama on LAN PC)
    dead_port = _unused_local_port()
    refused_cfg = Settings(
        ollama_enabled=True,
        ollama_base_url=f"http://127.0.0.1:{dead_port}",
        ollama_connect_timeout_seconds=2,
        ollama_timeout_seconds=5,
    )
    probe_refused = ollama_service.check_status(probe=True, settings=refused_cfg)
    assert probe_refused.status == "error"
    assert probe_refused.error_code == "connection_refused"
    assert f"127.0.0.1:{dead_port}" in probe_refused.message
    assert "OLLAMA_HOST=0.0.0.0" in probe_refused.message

    # HTTP error cases, missing model, malformed response, timeout
    mode = {"case": "missing_in_tags"}

    def error_server(req: dict[str, Any]):
        c = mode["case"]
        if c == "missing_in_tags":
            return 200, {"models": [{"name": "qwen3:8b"}]}, {}
        if c == "auth":
            return 401, {"error": "unauthorized"}, {}
        if c == "model_404":
            return 404, {"error": "model 'qwen3:4b-q4_K_M' not found, try pulling it first"}, {}
        if c == "path_404":
            return 404, {"error": "404 page not found"}, {}
        if c == "redirect":
            return 302, b"", {"Location": "http://evil.example.com"}
        if c == "oom_500":
            return 500, {"error": "model requires more system memory than is available"}, {}
        if c == "bad_json":
            return 200, b"<html>not ollama</html>", {}
        if c == "only_think":
            return 200, {"message": {"content": "<think>still thinking without closing"}}, {}
        if c == "slow":
            time.sleep(1.4)
            return 200, {"message": {"content": "late"}}, {}
        return 200, {"message": {"content": "ok"}}, {}

    with _mock_ollama_server(error_server) as (base_url, _):
        cfg = Settings(ollama_enabled=True, ollama_base_url=base_url, ollama_connect_timeout_seconds=2, ollama_timeout_seconds=5)

        st = ollama_service.check_status(probe=True, settings=cfg)
        assert st.status == "error" and st.error_code == "model_missing"
        assert "ollama pull qwen3:4b-q4_K_M" in st.message and "qwen3:8b" in st.message

        expected = (
            ("auth", "auth_error", "OLLAMA_API_KEY"),
            ("model_404", "model_missing", "ollama pull qwen3:4b-q4_K_M"),
            ("path_404", "bad_endpoint", "OLLAMA_API_PATH"),
            ("redirect", "bad_endpoint", "redirect"),
            ("oom_500", "server_error", "system memory"),
            ("bad_json", "invalid_response", "non-JSON"),
            ("only_think", "invalid_response", "OLLAMA_THINK=false"),
        )
        for case_name, exp_code, exp_text in expected:
            mode["case"] = case_name
            with pytest.raises(ollama_service.OllamaCommunicationError) as err:
                ollama_service.chat(system_prompt="s", user_prompt="u", settings=cfg)
            assert err.value.code == exp_code
            assert exp_text in err.value.message

        # Socket read timeout test via custom short read_timeout
        mode["case"] = "slow"
        with pytest.raises(ollama_service.OllamaCommunicationError) as t_err:
            ollama_service._request_json(cfg, method="POST", route_path="/api/chat", payload={}, read_timeout=1)
        assert t_err.value.code == "timeout" and "timed out" in t_err.value.message


# ---------------------------------------------------------------------------
# 3. Guide (Assistant): Well X vs Well Y comparison, DB/workflow AI, RBAC & alerts
# ---------------------------------------------------------------------------

def test_assistant_well_comparison_ai_grounding_tenant_rbac_and_comm_alert(monkeypatch):
    _grant("north", "owner@example.com", ("assistant:read", "assistant:manage", "cost-intelligence:read", "invoice-processing:read"))
    _grant("south", "owner@example.com", ("assistant:read",))

    with TestClient(app) as client:
        north = login(client, "north")
        setup = _setup(client, north)
        # Create Well X (total = 12,000 + 3,000 LIH = 15,000) and Well Y (total = 8,500)
        wx = _add_second_well(client, north, setup, code="WELL-X", name="Well X", daily_rates=["6000", "6000"], planned_rate="5000")
        _add_second_well(client, north, setup, code="WELL-Y", name="Well Y", daily_rates=["4000", "4500"], planned_rate="5000")
        assert client.put("/api/v1/lih-cost/day", headers=north, json={
            "rig_id": setup["rig"]["id"],
            "well_id": wx["well"]["id"],
            "afe_id": wx["afe"]["id"],
            "cost_date": "2026-10-02",
            "remarks": "Downhole BHA lost",
            "lines": [{
                "item_description": "8.5in PDC Bit",
                "no_of_units": "1",
                "unit": "EA",
                "unit_cost": "3000",
                "remarks": "Fish left in hole",
            }],
        }).status_code == 200

        # Create a confidential well in South organization to verify strict tenant isolation.
        south = login(client, "south")
        south_setup = _setup(client, south)
        _add_second_well(client, south, south_setup, code="SOUTH-SECRET", name="South Secret Well", daily_rates=["99999"], planned_rate="50000")

        # 3a. Deterministic comparison (no AI enabled) already compares Well X vs Well Y accurately.
        det = client.post("/api/v1/assistant/ask", headers=north, json={
            "question": 'I need "Well X" total cost and compare with "Well Y" cost',
        })
        assert det.status_code == 200, det.text
        det_body = det.json()
        assert det_body["intent"] == "well_comparison"
        assert det_body["ai_used"] is False
        assert det_body["ai_error"] == ""
        assert "15,000.00" in det_body["answer"]  # 12,000 actual + 3,000 LIH
        assert "8,500.00" in det_body["answer"]
        assert "6,500.00" in det_body["answer"]   # exact difference 15,000 - 8,500
        assert det_body["tables"] and "WELL-X" in det_body["tables"][0]["title"] and "WELL-Y" in det_body["tables"][0]["title"]
        assert det_body["tables"][0]["numeric"] == [1, 2, 3]

        # 3b. Comparison mentioning a non-existent well explicitly flags it without guessing.
        missing = client.post("/api/v1/assistant/ask", headers=north, json={
            "question": 'Compare "Well X" with "Well Ghost"',
        }).json()
        assert "Well Ghost" in missing["answer"]
        assert "15,000.00" in missing["answer"]

        # 3c. Live mock LAN Ollama Q&A studies DB + workflows without leaking South's records.
        def ai_handler(req: dict[str, Any]):
            if req["path"] == "/api/tags":
                return 200, {"models": [{"name": "qwen3:4b-q4_K_M"}]}, {}
            prompt_text = req["body"]["messages"][1]["content"]
            return 200, {
                "model": "qwen3:4b-q4_K_M",
                "message": {
                    "role": "assistant",
                    "content": (
                        "WELL-X (Well X) total cost including LIH is USD 15,000.00 (USD 12,000.00 daily cost + USD 3,000.00 LIH), "
                        "compared with WELL-Y (Well Y) at USD 8,500.00 — WELL-X is USD 6,500.00 (+76.5%) higher."
                    ),
                },
            }, {"X-Seen-Len": str(len(prompt_text))}

        with _mock_ollama_server(ai_handler) as (base_url, calls):
            cfg = get_settings()
            monkeypatch.setattr(cfg, "ollama_enabled", True)
            monkeypatch.setattr(cfg, "ollama_base_url", base_url)
            monkeypatch.setattr(cfg, "ollama_model", "qwen3:4b-q4_K_M")

            probe = client.get("/api/v1/assistant/ai-status?probe=true", headers=north)
            assert probe.status_code == 200
            assert probe.json()["status"] == "ready"
            assert probe.json()["model_available"] is True

            ai_res = client.post("/api/v1/assistant/ask", headers=north, json={
                "question": 'I need a "Well X" total cost and compare with "Well Y" cost',
                "route": "/daily-cost",
                "use_ai": True,
            })
            assert ai_res.status_code == 200, ai_res.text
            ai_body = ai_res.json()
            assert ai_body["ai_used"] is True
            assert ai_body["ai_model"] == "qwen3:4b-q4_K_M"
            assert ai_body["ai_error"] == ""
            assert "USD 15,000.00" in ai_body["answer"] and "USD 6,500.00" in ai_body["answer"]
            assert len(ai_body["tables"]) == 1 and len(ai_body["facts"]) >= 4

            # Inspect exact prompt handed to Ollama: North's DB + workflows IN, South's well OUT!
            chat_calls = [c for c in calls if c["path"] == "/api/chat"]
            assert len(chat_calls) == 1
            sent_prompt = chat_calls[0]["body"]["messages"][1]["content"]
            assert "WELL-X" in sent_prompt and "15,000.00" in sent_prompt
            assert "WELL-Y" in sent_prompt and "8,500.00" in sent_prompt
            assert "+USD 6,500.00" in sent_prompt
            assert "WELLCOSTIQ WORKFLOW & CALCULATION RULES" in sent_prompt
            assert "SOUTH-SECRET" not in sent_prompt
            assert "99,999" not in sent_prompt

            # 3d. RBAC isolation: user without daily-cost:read never receives well cost numbers.
            _create_scoped_user("north", "rigonly@example.com", ("assistant:read", "rig-well:read"))
            rig_only = login(client, "north", "rigonly@example.com")
            denied = client.post("/api/v1/assistant/ask", headers=rig_only, json={
                "question": 'Compare "Well X" and "Well Y" cost',
                "use_ai": True,
            }).json()
            assert denied["intent"] == "permission"
            assert len([c for c in calls if c["path"] == "/api/chat"]) == 1  # Ollama not called on permission refusal

            wf = client.post("/api/v1/assistant/ask", headers=rig_only, json={
                "question": "Explain the well status ladder workflow",
                "use_ai": True,
            }).json()
            assert wf["ai_used"] is True
            restricted_prompt = [c for c in calls if c["path"] == "/api/chat"][-1]["body"]["messages"][1]["content"]
            assert "daily-cost:read" in restricted_prompt.split("CALLER RESTRICTED CAPABILITIES")[1].splitlines()[0]
            assert "15,000.00" not in restricted_prompt and "8,500.00" not in restricted_prompt

            # User without assistant:read is blocked from /assistant/ai-status.
            _create_scoped_user("north", "noassist@example.com", ("rig-well:read",))
            no_assist = login(client, "north", "noassist@example.com")
            assert client.get("/api/v1/assistant/ai-status?probe=true", headers=no_assist).status_code == 403

        # 3e. Communication error alert when LAN Ollama host goes offline mid-session.
        dead_url = f"http://127.0.0.1:{_unused_local_port()}"
        monkeypatch.setattr(get_settings(), "ollama_enabled", True)
        monkeypatch.setattr(get_settings(), "ollama_base_url", dead_url)
        monkeypatch.setattr(get_settings(), "ollama_connect_timeout_seconds", 2)

        offline = client.post("/api/v1/assistant/ask", headers=north, json={
            "question": 'I need "Well X" total cost and compare with "Well Y" cost',
            "use_ai": True,
        })
        assert offline.status_code == 200
        off_body = offline.json()
        assert off_body["ai_used"] is False
        assert off_body["ai_error_code"] == "connection_refused"
        assert "AI communication error" in off_body["ai_error"]
        assert ".env" in off_body["ai_error"]
        # Verified local comparison still delivered safely alongside the alert.
        assert "15,000.00" in off_body["answer"] and "8,500.00" in off_body["answer"]

        # Verify audit records exist for both successful AI query and communication failure.
        with SessionLocal() as db:
            logs = db.query(AuditLog).filter(AuditLog.action == "ai-query").all()
            assert len(logs) >= 2


# ---------------------------------------------------------------------------
# 4. Cost Intelligence: opt-in AI toggle, anomaly/mistake review, RBAC & alerts
# ---------------------------------------------------------------------------

def test_cost_intelligence_ai_review_opt_in_anomalies_mistakes_rbac_and_alerts(monkeypatch):
    _grant("north", "owner@example.com", ("cost-intelligence:read", "cost-intelligence:export"))

    with TestClient(app) as client:
        north = login(client, "north")
        setup = _setup(client, north)
        # Seed a 12-day well containing an obvious 10x keying spike on day 9 (25,000 vs 2,500/day).
        rates = ["2500"] * 12
        rates[8] = "25000"
        spiked = _add_second_well(
            client, north, setup, code="WELL-SPIKE", name="Spike Audit Well",
            daily_rates=rates, planned_rate="2500", start=date(2026, 10, 1),
        )

        # South organization well to verify cross-tenant protection.
        south = login(client, "south")
        south_setup = _setup(client, south)

        review_mode = {"format": "json"}

        def ci_ollama(req: dict[str, Any]):
            if req["path"] == "/api/tags":
                return 200, {"models": [{"name": "qwen3:4b-q4_K_M"}]}, {}
            if review_mode["format"] == "plain":
                return 200, {
                    "model": "qwen3:4b-q4_K_M",
                    "message": {
                        "role": "assistant",
                        "content": (
                            "Portfolio spend shows an abnormal spike on WELL-SPIKE.\n"
                            "- Verify 2026-10-09 service rate override of USD 25,000 against USD 2,500 baseline.\n"
                            "- Submit pending draft daily sheets after verification."
                        ),
                    },
                }, {}
            return 200, {
                "model": "qwen3:4b-q4_K_M",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "risk_posture": "at-risk",
                        "executive_summary": (
                            "WELL-SPIKE exhibits a 10x single-day service cost anomaly on 2026-10-09 "
                            "(USD 25,000 vs USD 2,500 opening baseline), driving total recorded spend to USD 52,500 against USD 37,500 AFE."
                        ),
                        "findings": [
                            {
                                "severity": "critical",
                                "category": "entry-mistake",
                                "well_code": "WELL-SPIKE",
                                "reference": "2026-10-09",
                                "title": "Suspected 10x digit slip on Mud logging rate",
                                "detail": "Day rate jumped from USD 2,500 to USD 25,000 for a single day before returning to USD 2,500.",
                                "recommendation": "Open the 2026-10-09 daily sheet and confirm whether USD 25,000 should be USD 2,500.",
                            },
                            {
                                "severity": "warning",
                                "category": "budget",
                                "well_code": "UNKNOWN-HALLUCINATED",
                                "reference": "",
                                "title": "AFE exceeded by USD 15,000",
                                "detail": "Recorded actual USD 52,500 exceeds USD 37,500 AFE (140.0%).",
                                "recommendation": "Correct the spike entry or raise a SOW adjustment if genuine.",
                            },
                        ],
                        "recommendations": [
                            "Audit and amend the 2026-10-09 rate override on WELL-SPIKE before submitting draft sheets.",
                            "Reconcile remaining AFE coverage once the anomaly is verified.",
                        ],
                        "data_quality_notes": [
                            "All 12 sheets on WELL-SPIKE are currently in draft status.",
                        ],
                    }),
                },
            }, {}

        with _mock_ollama_server(ci_ollama) as (base_url, calls):
            cfg = get_settings()
            monkeypatch.setattr(cfg, "ollama_enabled", True)
            monkeypatch.setattr(cfg, "ollama_base_url", base_url)
            monkeypatch.setattr(cfg, "ollama_model", "qwen3:4b-q4_K_M")

            # 4a. Standard deterministic overview NEVER calls Ollama even when enabled!
            ov = client.get("/api/v1/cost-intelligence/overview", headers=north)
            assert ov.status_code == 200
            assert calls == []

            # 4b. Connection check endpoint reports ready.
            st = client.get("/api/v1/cost-intelligence/ai-status?probe=true", headers=north)
            assert st.status_code == 200 and st.json()["status"] == "ready"

            # 4c. On-demand single-well AI review catches the 10x spike & entry-check signals.
            rev = client.post("/api/v1/cost-intelligence/ai-review", headers=north, json={
                "scope": "well",
                "focus": "mistakes",
                "well_id": spiked["well"]["id"],
                "question": "Check 2026-10-09 for any keying mistakes",
            })
            assert rev.status_code == 200, rev.text
            body = rev.json()
            assert body["model"] == "qwen3:4b-q4_K_M"
            assert body["scope"] == "well" and body["well_code"] == "WELL-SPIKE"
            assert body["risk_posture"] == "at-risk"
            assert "25,000" in body["executive_summary"]
            assert len(body["findings"]) == 2
            # Verified well links to its real analysis route; unknown well_code is scrubbed to empty!
            assert body["findings"][0]["well_id"] == spiked["well"]["id"]
            assert body["findings"][0]["action_path"] == f"/daily-cost/analysis/{spiked['well']['id']}"
            assert body["findings"][1]["well_id"] == "" and body["findings"][1]["well_code"] == ""
            assert body["entry_signals_count"] >= 1
            assert any(sig["action_path"].startswith("/daily-cost/entries/") for sig in body["entry_signals"])
            assert len(body["recommendations"]) == 2
            assert len(body["data_quality_notes"]) == 1

            # Verify prompt sent to Ollama included the spike finding, entry-check signals, and operator question.
            sent = [c for c in calls if c["path"] == "/api/chat"][-1]["body"]["messages"][1]["content"]
            assert "WELL-SPIKE" in sent and "2026-10-09" in sent
            assert "Check 2026-10-09 for any keying mistakes" in sent
            assert "DAILY COST SHEET ENTRY-CHECK MISTAKE SIGNALS" in sent

            # 4d. Plain-text fallback works seamlessly if a 4B model skips JSON formatting.
            review_mode["format"] = "plain"
            portfolio_rev = client.post("/api/v1/cost-intelligence/ai-review", headers=north, json={
                "scope": "portfolio",
                "focus": "full",
            })
            assert portfolio_rev.status_code == 200, portfolio_rev.text
            assert "WELL-SPIKE" in portfolio_rev.json()["executive_summary"]
            assert len(portfolio_rev.json()["recommendations"]) == 2

            # 4e. Cross-tenant well_id returns 404 without invoking Ollama.
            before_count = len(calls)
            cross = client.post("/api/v1/cost-intelligence/ai-review", headers=north, json={
                "scope": "well",
                "focus": "full",
                "well_id": south_setup["well"]["id"],
            })
            assert cross.status_code == 404
            assert len(calls) == before_count

            # 4f. RBAC: user without cost-intelligence:read receives 403.
            _create_scoped_user("north", "noci@example.com", ("daily-cost:read",))
            no_ci = login(client, "north", "noci@example.com")
            assert client.get("/api/v1/cost-intelligence/ai-status?probe=true", headers=no_ci).status_code == 403
            assert client.post("/api/v1/cost-intelligence/ai-review", headers=no_ci, json={"scope": "portfolio"}).status_code == 403

        # 4g. Communication outage alerts user via HTTP 503 while leaving deterministic overview intact.
        monkeypatch.setattr(get_settings(), "ollama_enabled", True)
        monkeypatch.setattr(get_settings(), "ollama_base_url", f"http://127.0.0.1:{_unused_local_port()}")
        monkeypatch.setattr(get_settings(), "ollama_connect_timeout_seconds", 2)

        fail_rev = client.post("/api/v1/cost-intelligence/ai-review", headers=north, json={"scope": "portfolio"})
        assert fail_rev.status_code == 503
        assert "AI communication error" in fail_rev.json()["detail"]
        assert client.get("/api/v1/cost-intelligence/overview", headers=north).status_code == 200

        # Disabled in .env returns clear 503 configuration guidance.
        monkeypatch.setattr(get_settings(), "ollama_enabled", False)
        dis_rev = client.post("/api/v1/cost-intelligence/ai-review", headers=north, json={"scope": "portfolio"})
        assert dis_rev.status_code == 503
        assert "OLLAMA_ENABLED=true" in dis_rev.json()["detail"]

        # Verify immutable audit rows recorded for reviews and communication failures.
        with SessionLocal() as db:
            ci_logs = db.query(AuditLog).filter(
                AuditLog.entity_type == "cost_intelligence",
                AuditLog.action == "ai-review",
            ).all()
            assert len(ci_logs) == 3


def test_assistant_ai_studies_afes_catalogue_registers_invoices_and_workspace_memory(monkeypatch):
    _grant(
        "north",
        "owner@example.com",
        ("assistant:read", "assistant:manage", "cost-intelligence:read", "invoice-processing:read", "invoice-processing:create"),
    )
    with TestClient(app) as client:
        north = login(client, "north")
        setup = _setup(client, north)

        # Teach a custom workspace convention in the Guide memory.
        assert client.post("/api/v1/assistant/memory", headers=north, json={
            "title": "AFE escalation approval rule",
            "category": "policy",
            "keywords": "afe escalation barite approval threshold",
            "body": "Any AFE variance over 10 percent requires Drilling Manager sign-off.",
            "steps": ["Prepare SOW adjustment", "Route for Drilling Manager approval"],
            "route": "/afe",
            "permission": "",
            "is_active": True,
        }).status_code == 201

        captured: list[str] = []

        def domain_ollama(req: dict[str, Any]):
            captured.append(req["body"]["messages"][1]["content"])
            return 200, {
                "model": "qwen3:4b-q4_K_M",
                "message": {"role": "assistant", "content": "Verified across AFE-01, Acme Services, Barite, LIH, mud, fuel, NDT, and invoices."},
            }, {}

        with _mock_ollama_server(domain_ollama) as (base_url, _):
            cfg = get_settings()
            monkeypatch.setattr(cfg, "ollama_enabled", True)
            monkeypatch.setattr(cfg, "ollama_base_url", base_url)

            res = client.post("/api/v1/assistant/ask", headers=north, json={
                "question": (
                    "Review WELL-01 AFE escalation budget, Acme vendor, Barite chemical rate, "
                    "mud, fuel, LIH, NDT inspections, invoices, and anomalies"
                ),
                "route": "/afe",
                "use_ai": True,
            })
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["ai_used"] is True
            assert body["ai_error"] == ""
            assert len(captured) == 1
            dossier = captured[0]
            assert "AFE escalation approval rule" in dossier
            assert "AFE-01" in dossier
            assert "Acme Services" in dossier
            assert "Barite" in dossier
            assert "Mud Cost Register" in dossier
            assert "Fuel Cost Register" in dossier
            assert "LIH (Lost In Hole) Register" in dossier
            assert "NDT Inspection Register" in dossier
            assert "Invoice Processing / IDVS summary" in dossier
            assert "Cost Intelligence overview" in dossier

