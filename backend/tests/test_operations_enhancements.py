"""End-to-end coverage for Well Operations reopen workflows, multi-day operation
summary, full MD/TVD/wellbore extraction prefill, WAT (UTC+1:00) timezone
standardization, Alembic migration d4f7a2c81e90, and qwen3:1.7b-tuned Offline AI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import patch

from test_operations_workflow import MODELS, OPS, configured_well, good, scoped_login
from test_rig_well import fresh_database, login  # noqa: F401

# isort: split

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.time import WAT, WAT_TZ_NAME, as_wat, format_wat, wat_now, wat_today
from app.main import app
from app.models import AuditLog
from app.services import ollama
from fastapi.testclient import TestClient
from sqlalchemy import select


def test_wat_timezone_helpers_and_default_ops_settings(fresh_database):
    """All timestamp helpers use West Africa Time (Africa/Lagos, UTC+1:00) with no DST."""
    utc_midnight = datetime(2026, 6, 15, 0, 0, 0, tzinfo=UTC)
    wat_dt = as_wat(utc_midnight)
    assert wat_dt.utcoffset() == timedelta(hours=1)
    assert (wat_dt.hour, wat_dt.minute) == (1, 0)
    assert format_wat(utc_midnight) == "2026-06-15 01:00"
    assert format_wat(utc_midnight, "%Y-%m-%d %H:%M:%S WAT") == "2026-06-15 01:00:00 WAT"
    assert format_wat(datetime(2026, 6, 14, 23, 30, 0)) == "2026-06-15 00:30"
    assert wat_now().tzinfo == WAT
    assert isinstance(wat_today().isoformat(), str)

    with TestClient(app) as client:
        headers = login(client)
        cfg = good(client.get(OPS + "/settings", headers=headers))
        assert cfg["operating_timezone"] == WAT_TZ_NAME


def test_reopen_active_and_superseded_operation_plans_with_audit(fresh_database):
    """Active and superseded operation plans can be reopened to editable draft, revised, and re-activated."""
    with TestClient(app) as client:
        headers = login(client)
        target = configured_well(client, headers, "WAT-PLAN-01")

        # Create v1, add item, activate
        v1 = good(
            client.post(
                OPS + "/plans",
                headers=headers,
                json={
                    **target,
                    "label": "AFE Drilling Programme",
                    "basis": "programme",
                    "planned_start_at": "2026-05-01T06:00:00+01:00",
                },
            )
        )
        assert v1["status"] == "draft"

        # Cannot reopen a draft
        assert (
            client.post(OPS + f"/plans/{v1['id']}/reopen", headers=headers, json={"remarks": "Too early"}).status_code
            == 409
        )

        good(
            client.put(
                OPS + f"/plans/{v1['id']}/items",
                headers=headers,
                json=[
                    {
                        "sequence_no": 1,
                        "description": "Drill 26in hole to 500m",
                        "planned_hours": "24",
                        "target_depth_m": "500",
                        "delta_depth_m": "500",
                    }
                ],
            )
        )
        v1 = good(client.post(OPS + f"/plans/{v1['id']}/activate", headers=headers))
        assert v1["status"] == "active"
        assert v1["approved_by"]

        # Short remark rejected (422)
        assert (
            client.post(OPS + f"/plans/{v1['id']}/reopen", headers=headers, json={"remarks": "x"}).status_code == 422
        )

        # User without ops-plan:reopen gets 403
        reader_headers = scoped_login(client, "plan-reader", ["ops-plan:read", "ops-plan:update"])
        assert (
            client.post(
                OPS + f"/plans/{v1['id']}/reopen", headers=reader_headers, json={"remarks": "Need edit"}
            ).status_code
            == 403
        )

        # Reopen active v1 -> editable draft with audit trail
        reopened = good(
            client.post(
                OPS + f"/plans/{v1['id']}/reopen",
                headers=headers,
                json={"remarks": "Update 26in shoe depth to 550m and add 17.5in section"},
            )
        )
        assert reopened["status"] == "draft"
        assert reopened["reopened_at"] is not None
        assert reopened["reopened_by"]
        assert "550m" in reopened["reopen_reason"]

        # Edit metadata & timeline items on reopened draft, then re-activate
        updated = good(
            client.put(
                OPS + f"/plans/{v1['id']}",
                headers=headers,
                json={
                    "label": "AFE Drilling Programme (Rev 1A)",
                    "planned_start_at": "2026-05-01T08:00:00+01:00",
                    "notes": "Revised surface shoe depth",
                },
            )
        )
        assert updated["label"] == "AFE Drilling Programme (Rev 1A)"

        good(
            client.put(
                OPS + f"/plans/{v1['id']}/items",
                headers=headers,
                json=[
                    {
                        "sequence_no": 1,
                        "description": "Drill 26in hole to 550m",
                        "planned_hours": "28",
                        "target_depth_m": "550",
                        "delta_depth_m": "550",
                    },
                    {
                        "sequence_no": 2,
                        "description": "Drill 17.5in hole to 2100m",
                        "planned_hours": "72",
                        "target_depth_m": "2100",
                        "delta_depth_m": "1550",
                    },
                ],
            )
        )
        reactivated = good(client.post(OPS + f"/plans/{v1['id']}/activate", headers=headers))
        assert reactivated["status"] == "active"
        assert len(reactivated["items"]) == 2
        assert Decimal(reactivated["items"][1]["target_depth_m"]) == Decimal("2100")

        # Create & activate v2 (superseding v1), then reopen superseded v1 and re-activate it
        v2 = good(
            client.post(
                OPS + "/plans",
                headers=headers,
                json={**target, "label": "Programme v2", "basis": "programme"},
            )
        )
        good(
            client.put(
                OPS + f"/plans/{v2['id']}/items",
                headers=headers,
                json=[{"sequence_no": 1, "description": "Drill to TD", "planned_hours": "96", "target_depth_m": "2100"}],
            )
        )
        v2 = good(client.post(OPS + f"/plans/{v2['id']}/activate", headers=headers))
        assert v2["status"] == "active"
        v1_sup = good(client.get(OPS + f"/plans/{v1['id']}", headers=headers))
        assert v1_sup["status"] == "superseded"

        v1_reopened = good(
            client.post(
                OPS + f"/plans/{v1['id']}/reopen",
                headers=headers,
                json={"remarks": "Revert baseline to v1 schedule after programme review"},
            )
        )
        assert v1_reopened["status"] == "draft"
        v1_active_again = good(client.post(OPS + f"/plans/{v1['id']}/activate", headers=headers))
        assert v1_active_again["status"] == "active"
        assert good(client.get(OPS + f"/plans/{v2['id']}", headers=headers))["status"] == "superseded"

        with SessionLocal() as db:
            reopen_logs = db.scalars(
                select(AuditLog).where(AuditLog.entity_type == "ops_plan", AuditLog.action == "reopen")
            ).all()
            assert len(reopen_logs) == 2


def test_reopen_submitted_and_approved_reports_30day_guard_and_summary(fresh_database):
    """Submitted & approved reports can be reopened to draft with remarks, revised with full MD/TVD/mud fields, and aggregated in multi-day Well Operation Summary."""
    with TestClient(app) as client:
        headers = login(client)
        target = configured_well(client, headers, "OML-WELL-07")
        npt_code = good(
            client.post(
                OPS + "/masters/npt-codes",
                headers=headers,
                json={"npt_code": "RIG-EQ", "npt_name": "Rig Equipment Failure"},
            )
        )
        npt_code_id = npt_code["id"]
        recent_day = (wat_today() - timedelta(days=5)).isoformat()
        next_day = (wat_today() - timedelta(days=4)).isoformat()
        old_day = (wat_today() - timedelta(days=45)).isoformat()

        r1 = good(
            client.post(
                OPS + "/reports",
                headers=headers,
                json={**target, "report_date": recent_day, "report_no_text": "DDR-01", "report_type": "DDR"},
            )
        )
        # Save complete day 1 with MD, TVD, bit depth, mud, casing, BHA, survey & WAT blocks
        r1 = good(
            client.put(
                OPS + f"/reports/{r1['id']}",
                headers=headers,
                json={
                    "expected_updated_at": r1["updated_at"],
                    "report": {
                        "depth_start_m": "1200.000",
                        "depth_end_m": "1450.500",
                        "tvd_start_m": "1180.000",
                        "tvd_m": "1410.250",
                        "bit_depth_m": "1450.500",
                        "md_auth_m": "3200.000",
                        "rotating_hours": "14.500",
                        "hole_section_text": "12.25in Intermediate",
                        "hole_size_in": "12.250",
                        "last_casing_size_in": "13.375",
                        "last_casing_depth_m": "1195.000",
                        "mud_type": "OBM",
                        "mud_weight_ppg": "10.400",
                        "mud_viscosity_sec": "54.000",
                        "mud_pv_cp": "22.000",
                        "mud_yp_lbf": "18.000",
                        "bha_summary": "12.25in PDC + RSS + MWD/LWD",
                        "pob_count": 88,
                        "supervisor": "Engr. Adewale",
                        "engineer": "Engr. Okafor",
                        "operation_summary": "Drilled 12.25in hole from 1200m to 1450.5m MD (1410.25m TVD).",
                        "forward_plan": "Drill ahead 12.25in section to 1800m MD.",
                        "hse_summary": "0 LTI, 28 STOP cards, BOP drill completed.",
                    },
                    "blocks": [
                        {
                            "sequence_no": 1,
                            "started_at": f"{recent_day}T00:00:00+01:00",
                            "ended_at": f"{recent_day}T18:00:00+01:00",
                            "duration_minutes": 1080,
                            "classification": "Planned",
                            "allocation": "PT",
                            "is_productive": True,
                            "depth_from_m": "1200.000",
                            "depth_to_m": "1450.500",
                            "tvd_from_m": "1180.000",
                            "tvd_to_m": "1410.250",
                            "bit_depth_m": "1450.500",
                            "mud_weight_ppg": "10.400",
                            "rotating_hours": "14.500",
                            "narrative": "Drill 12.25in hole with RSS from 1200m to 1450.5m MD.",
                            "review_state": "edited",
                        },
                        {
                            "sequence_no": 2,
                            "started_at": f"{recent_day}T18:00:00+01:00",
                            "ended_at": f"{next_day}T00:00:00+01:00",
                            "duration_minutes": 360,
                            "classification": "NPT",
                            "allocation": "NPT",
                            "is_productive": False,
                            "npt_code_id": npt_code_id,
                            "depth_from_m": "1450.500",
                            "depth_to_m": "1450.500",
                            "tvd_from_m": "1410.250",
                            "tvd_to_m": "1410.250",
                            "bit_depth_m": "1420.000",
                            "responsible_party": "Rig Contractor",
                            "reason": "Top drive washpipe packing leak",
                            "narrative": "Replace top drive washpipe packing and pressure test.",
                            "review_state": "edited",
                        },
                    ],
                    "surveys": [
                        {
                            "md_m": "1440.000",
                            "tvd_m": "1401.200",
                            "inc_deg": "18.400",
                            "azi_deg": "142.500",
                            "dls_deg_per_30m": "1.250",
                            "source": "manual",
                            "tool": "MWD",
                        }
                    ],
                },
            )
        )
        assert Decimal(r1["tvd_m"]) == Decimal("1410.250")
        assert r1["tvd_source"] == "manual"
        assert Decimal(r1["mud_weight_ppg"]) == Decimal("10.400")
        assert Decimal(r1["blocks"][0]["tvd_to_m"]) == Decimal("1410.250")

        # Submit -> reopen from submitted
        r1 = good(client.post(OPS + f"/reports/{r1['id']}/submit", headers=headers))
        assert r1["status"] == "submitted"
        r1 = good(
            client.post(
                OPS + f"/reports/{r1['id']}/reopen",
                headers=headers,
                json={"remarks": "Correct closing MD after pipe tally check"},
            )
        )
        assert r1["status"] == "draft"
        assert r1["reopened_at"] is not None
        assert "pipe tally" in r1["reopen_reason"]

        # Revise closing MD to 1455m, submit -> approve -> reopen from approved -> re-submit -> re-approve
        r1 = good(
            client.put(
                OPS + f"/reports/{r1['id']}",
                headers=headers,
                json={"expected_updated_at": r1["updated_at"], "report": {"depth_end_m": "1455.000"}},
            )
        )
        r1 = good(client.post(OPS + f"/reports/{r1['id']}/submit", headers=headers))
        r1 = good(client.post(OPS + f"/reports/{r1['id']}/approve", headers=headers))
        assert r1["status"] == "approved"

        # Caller without ops-report:reopen gets 403
        no_reopen = scoped_login(client, "rep-noreopen", ["ops-report:read", "ops-report:update"])
        assert (
            client.post(
                OPS + f"/reports/{r1['id']}/reopen", headers=no_reopen, json={"remarks": "Attempt reopen"}
            ).status_code
            == 403
        )

        # Reopen approved report, verify editability, then submit & approve again
        r1 = good(
            client.post(
                OPS + f"/reports/{r1['id']}/reopen",
                headers=headers,
                json={"remarks": "Add updated mud weight 10.6 ppg from night check"},
            )
        )
        assert r1["status"] == "draft"
        assert r1["approved_at"] is None
        r1 = good(
            client.put(
                OPS + f"/reports/{r1['id']}",
                headers=headers,
                json={"expected_updated_at": r1["updated_at"], "report": {"mud_weight_ppg": "10.600"}},
            )
        )
        r1 = good(client.post(OPS + f"/reports/{r1['id']}/submit", headers=headers))
        r1 = good(client.post(OPS + f"/reports/{r1['id']}/approve", headers=headers))
        assert r1["status"] == "approved"
        assert Decimal(r1["mud_weight_ppg"]) == Decimal("10.600")

        # 30-day window requires ops-report:amend in addition to ops-report:reopen
        old_next = (wat_today() - timedelta(days=44)).isoformat()
        r_old = good(
            client.post(
                OPS + "/reports",
                headers=headers,
                json={**target, "report_date": old_day, "report_no_text": "DDR-OLD", "report_type": "DDR"},
            )
        )
        r_old = good(
            client.put(
                OPS + f"/reports/{r_old['id']}",
                headers=headers,
                json={
                    "expected_updated_at": r_old["updated_at"],
                    "report": {"depth_start_m": "100", "depth_end_m": "200"},
                    "blocks": [
                        {
                            "sequence_no": 1,
                            "started_at": f"{old_day}T00:00:00+01:00",
                            "ended_at": f"{old_next}T00:00:00+01:00",
                            "duration_minutes": 1440,
                            "classification": "Planned",
                            "allocation": "PT",
                            "is_productive": True,
                            "narrative": "Spud and drill 26in hole.",
                            "review_state": "edited",
                        }
                    ],
                },
            )
        )
        r_old = good(client.post(OPS + f"/reports/{r_old['id']}/submit", headers=headers))
        reopen_only = scoped_login(client, "reopen-no-amend", ["ops-report:read", "ops-report:reopen"])
        denied_old = client.post(
            OPS + f"/reports/{r_old['id']}/reopen",
            headers=reopen_only,
            json={"remarks": "Amend report older than 30 days"},
        )
        assert denied_old.status_code == 403
        assert "ops-report:amend" in denied_old.text
        # Owner holds ops-report:amend -> allowed
        reopened_old = good(
            client.post(
                OPS + f"/reports/{r_old['id']}/reopen",
                headers=headers,
                json={"remarks": "Authorized historical correction"},
            )
        )
        assert reopened_old["status"] == "draft"

        # Multi-day Well Operation Summary verifies full KPI, daily, activity, NPT, survey, fluid & WAT contract
        summary = good(
            client.get(
                OPS + f"/summary?well_id={target['well_id']}&scope=drilling&include_drafts=false",
                headers=headers,
            )
        )
        assert summary["timezone"] == "Africa/Lagos"
        assert summary["timezone_label"] == "WAT (UTC+1:00)"
        assert summary["kpis"]["total_reports"] == 1  # r_old is draft and excluded
        assert summary["kpis"]["current_md_m"] == 1455.0
        assert summary["kpis"]["current_tvd_m"] == 1410.25
        assert summary["kpis"]["total_footage_m"] == 255.0
        assert summary["kpis"]["productive_hours"] == 18.0
        assert summary["kpis"]["npt_hours"] == 6.0
        assert summary["kpis"]["latest_mud_weight_ppg"] == 10.6
        assert len(summary["daily_rollup"]) == 1
        assert len(summary["activities"]) == 2
        assert summary["activities"][0]["start_wat"].endswith("00:00")
        assert summary["activities"][0]["end_wat"].endswith("18:00")
        assert any(b["responsible_party"] == "Rig Contractor" for b in summary["pt_npt_breakdown"])
        assert len(summary["surveys"]) == 1
        assert "13.375" in summary["last_casing"]

        # include_drafts=true brings in r_old too
        with_drafts = good(
            client.get(
                OPS + f"/summary?well_id={target['well_id']}&scope=drilling&include_drafts=true",
                headers=headers,
            )
        )
        assert with_drafts["kpis"]["total_reports"] == 2

        # Export audit trail works for pdf, xlsx, csv
        for fmt in ("pdf", "xlsx", "csv"):
            good(
                client.post(
                    OPS + "/summary/export-audit",
                    headers=headers,
                    json={"format": fmt, "record_count": len(summary["activities"])},
                )
            )


def test_real_openwells_pdf_and_summary_xlsx_prefill_all_depths_and_wat(fresh_database):
    """Extracting real OpenWells PDF & Summary Excel files prefills MDs, TVDs, wellbore params, surveys & WAT blocks."""
    pdf_path = MODELS / "DDR#31.pdf"
    xlsx_path = MODELS / "Summary ANE-02.xlsx"
    if not pdf_path.exists() or not xlsx_path.exists():
        return

    with TestClient(app) as client:
        headers = login(client)
        target = configured_well(client, headers, "ANE-02")

        # Upload & extract real OpenWells DDR PDF
        with pdf_path.open("rb") as fh:
            docs = good(
                client.post(
                    OPS + "/documents",
                    headers=headers,
                    data={"well_id": target["well_id"], "scope": "drilling", "document_type": "DDR"},
                    files=[("files", (pdf_path.name, fh, "application/pdf"))],
                )
            )
        extracted = good(
            client.post(OPS + "/reports/extract", headers=headers, json={"document_id": docs[0]["id"]})
        )
        assert extracted["depth_end_m"] is not None and Decimal(extracted["depth_end_m"]) > 0
        assert extracted["depth_start_m"] is not None and Decimal(extracted["depth_start_m"]) > 0
        assert extracted["tvd_m"] is not None and Decimal(extracted["tvd_m"]) > 0
        assert extracted["tvd_source"] != ""
        assert extracted["operation_summary"] != ""
        assert len(extracted["blocks"]) > 0
        # OpenWells day starts at 00:00 WAT (stored as previous day 23:00Z)
        first_start = datetime.fromisoformat(extracted["blocks"][0]["started_at"].replace("Z", "+00:00"))
        assert (as_wat(first_start).hour, as_wat(first_start).minute) == (0, 0)

        # Upload & extract real multi-day Summary workbook
        with xlsx_path.open("rb") as fh:
            xdocs = good(
                client.post(
                    OPS + "/documents",
                    headers=headers,
                    data={"well_id": target["well_id"], "scope": "drilling", "document_type": "Summary"},
                    files=[
                        (
                            "files",
                            (
                                xlsx_path.name,
                                fh,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            ),
                        )
                    ],
                )
            )
        xrep = good(
            client.post(OPS + "/reports/extract", headers=headers, json={"document_id": xdocs[0]["id"]})
        )
        assert xrep["depth_end_m"] is not None and Decimal(xrep["depth_end_m"]) > 0
        assert len(xrep["blocks"]) > 0


def test_offline_ai_qwen3_1_7b_narratives_prefill_review_and_guides(fresh_database, monkeypatch):
    """Offline AI (qwen3:1.7b) works for narratives, AI prefill, operational review, D&C guide, and fails gracefully."""
    # Verify Qwen3 thinking-tag stripping helper
    assert ollama.extract_json_object('<think>internal chain</think>{"ok": true}') == {"ok": True}

    with TestClient(app) as client:
        headers = login(client)
        target = configured_well(client, headers, "AI-WELL-01")
        day = wat_today().isoformat()
        next_day = (wat_today() + timedelta(days=1)).isoformat()

        r = good(
            client.post(
                OPS + "/reports",
                headers=headers,
                json={**target, "report_date": day, "report_no_text": "DDR-AI-1", "report_type": "DDR"},
            )
        )
        r = good(
            client.put(
                OPS + f"/reports/{r['id']}",
                headers=headers,
                json={
                    "expected_updated_at": r["updated_at"],
                    "report": {
                        "depth_start_m": "2000",
                        "depth_end_m": "2180",
                        "tvd_m": "2095",
                        "mud_weight_ppg": "11.2",
                        "rotating_hours": "12",
                    },
                    "blocks": [
                        {
                            "sequence_no": 1,
                            "started_at": f"{day}T00:00:00+01:00",
                            "ended_at": f"{next_day}T00:00:00+01:00",
                            "duration_minutes": 1440,
                            "classification": "Planned",
                            "allocation": "PT",
                            "is_productive": True,
                            "classification_source": "default",
                            "narrative": "Drilled 8.5in production section from 2000m to 2180m MD with 11.2 ppg OBM; circulated hole clean.",
                        }
                    ],
                },
            )
        )

        # 1. Rule-based narrative generation (use_ai=false)
        det_nar = good(
            client.post(OPS + f"/reports/{r['id']}/narratives", headers=headers, json={"use_ai": False})
        )
        assert det_nar["ai_used"] is False
        assert "2180" in det_nar["operation_summary"]
        assert det_nar["forward_plan"] != ""

        # 2. Mocked qwen3:1.7b narrative generation (use_ai=true)
        monkeypatch.setenv("OLLAMA_ENABLED", "true")
        monkeypatch.setenv("OLLAMA_MODEL", "qwen3:1.7b")
        get_settings.cache_clear()

        def fake_nar_chat(**kwargs):
            return ollama.OllamaReply(
                content=json.dumps(
                    {
                        "operation_summary": "Drilled 8.5in hole 2000-2180m MD (2095m TVD, 180m in 12.0 rot h) with 11.2 ppg OBM.",
                        "forward_plan": "Drill ahead 8.5in production hole and take MWD checkshot surveys.",
                        "hse_summary": "Zero incidents recorded; routine rig-floor safety checks maintained.",
                        "engineering_brief": "ROP averaged 15.0 m/h across 24.0 h productive drilling with zero NPT.",
                    }
                ),
                model="qwen3:1.7b",
                endpoint="http://192.168.1.50:11434",
                duration_ms=310,
            )

        with patch("app.services.operations.ops_ai.ollama.chat", side_effect=fake_nar_chat):
            ai_nar = good(
                client.post(OPS + f"/reports/{r['id']}/narratives", headers=headers, json={"use_ai": True})
            )
            assert ai_nar["ai_used"] is True
            assert ai_nar["ai_model"] == "qwen3:1.7b"
            assert "2180m MD" in ai_nar["operation_summary"]

        # 3. Mocked qwen3:1.7b AI prefill fills missing header fields without overwriting existing depths
        def fake_prefill_chat(**kwargs):
            return ollama.OllamaReply(
                content=json.dumps(
                    {
                        "header": {
                            "depth_end_m": 9999,  # Must NOT overwrite existing 2180!
                            "mud_type": "OBM",
                            "hole_section_text": "8.5in Production",
                            "hole_size_in": 8.5,
                            "operation_summary": "Drilled 8.5in section 2000-2180m MD with 11.2 ppg OBM.",
                        },
                        "blocks": [{"seq": 1, "classification": "Planned", "allocation": "PT", "phase_raw": "PRD"}],
                    }
                ),
                model="qwen3:1.7b",
                endpoint="http://192.168.1.50:11434",
                duration_ms=280,
            )

        with patch("app.services.operations.ops_ai.ollama.chat", side_effect=fake_prefill_chat):
            prefilled = good(client.post(OPS + f"/reports/{r['id']}/ai-prefill", headers=headers))
            assert prefilled["ai_used"] is True
            assert "mud_type" in prefilled["updated_header_fields"]
            assert Decimal(prefilled["report"]["depth_end_m"]) == Decimal("2180")
            assert prefilled["report"]["mud_type"] == "OBM"
            assert prefilled["report"]["hole_section_text"] == "8.5in Production"

        # 4. Submit report and run AI Operational Review (both live-mocked and offline fallback)
        # Confirm any AI-suggested blocks first
        latest = prefilled["report"]
        b0 = latest["blocks"][0]
        latest = good(
            client.put(
                OPS + f"/reports/{r['id']}",
                headers=headers,
                json={
                    "expected_updated_at": latest["updated_at"],
                    "confirm_review": True,
                    "report": {},
                    "blocks": [
                        {
                            "block_id": b0["id"],
                            "sequence_no": 1,
                            "started_at": b0["started_at"],
                            "ended_at": b0["ended_at"],
                            "duration_minutes": b0["duration_minutes"],
                            "classification": b0["classification"],
                            "allocation": b0["allocation"],
                            "is_productive": b0["is_productive"],
                            "phase_raw": b0["phase_raw"],
                            "narrative": b0["narrative"],
                            "review_state": "accepted",
                        }
                    ],
                },
            )
        )
        good(client.post(OPS + f"/reports/{r['id']}/submit", headers=headers))

        def fake_review_chat(**kwargs):
            return ollama.OllamaReply(
                content=json.dumps(
                    {
                        "executive_summary": "AI-WELL-01 drilled 180.0 m in 12.0 rotating hours (15.0 m/h ROP) with 0.0% NPT.",
                        "highlights": ["180.0 m daily footage at 15.0 m/h rotating ROP with 11.2 ppg OBM."],
                        "anomalies": [
                            {
                                "severity": "info",
                                "category": "rop",
                                "title": "Consistent 8.5in production ROP",
                                "detail": "Achieved 15.0 m/h rotating ROP with 11.2 ppg OBM.",
                                "well_code": "AI-WELL-01",
                                "report_date": day,
                            }
                        ],
                        "recommended_actions": ["Continue survey tracking and hole-cleaning sweeps toward section TD."],
                    }
                ),
                model="qwen3:1.7b",
                endpoint="http://192.168.1.50:11434",
                duration_ms=420,
            )

        with patch("app.services.operations.ops_ai.ollama.chat", side_effect=fake_review_chat):
            rev = good(
                client.post(
                    OPS + "/ai-review",
                    headers=headers,
                    json={"well_id": target["well_id"], "scope": "drilling", "focus": "full", "use_ai": True},
                )
            )
            assert rev["ai_used"] is True
            assert rev["ai_model"] == "qwen3:1.7b"
            assert "180.0 m" in rev["executive_summary"]
            assert len(rev["highlights"]) == 1
            assert len(rev["recommended_actions"]) == 1

        # Graceful offline fallback when Ollama host is unreachable
        def unreachable_chat(**kwargs):
            raise ollama.OllamaCommunicationError(
                "Connection refused",
                code="connection_refused",
                endpoint="http://192.168.1.50:11434",
                model="qwen3:1.7b",
            )

        with patch("app.services.operations.ops_ai.ollama.chat", side_effect=unreachable_chat):
            fallback = good(
                client.post(
                    OPS + "/ai-review",
                    headers=headers,
                    json={"well_id": target["well_id"], "scope": "drilling", "focus": "npt", "use_ai": True},
                )
            )
            assert fallback["ai_used"] is False
            assert fallback["ai_error_code"] == "connection_refused"
            assert fallback["deterministic_summary"] != ""

        # 5. D&C engineering knowledge + live workspace Well Operations DB answers in Guide
        dnc = good(
            client.post(
                "/api/v1/assistant/ask",
                headers=headers,
                json={"question": "How do I prevent pack-off and differential stuck pipe?", "route": "/operations/guide"},
            )
        )
        assert dnc["confidence"] == "high"
        assert "differential" in dnc["answer"].lower() or "pack" in dnc["answer"].lower()

        reopen_help = good(
            client.post(
                "/api/v1/assistant/ask",
                headers=headers,
                json={"question": "How do I reopen an approved daily report or active plan?", "route": "/operations/reports"},
            )
        )
        assert reopen_help["confidence"] == "high"
        assert "reopen" in reopen_help["answer"].lower()

        live_ops = good(
            client.post(
                "/api/v1/assistant/ask",
                headers=headers,
                json={"question": "What is the drilling depth and NPT summary for AI-WELL-01?", "route": "/operations/guide"},
            )
        )
        assert "AI-WELL-01" in live_ops["answer"]
        assert any("2180" in f["value"].replace(",", "") for f in live_ops["facts"])
    get_settings.cache_clear()
