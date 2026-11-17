"""Wire contract consumed by the Well Operations Overview's recent-report rows."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from test_rig_well import create_rig, create_well, fresh_database, login  # noqa: F401 - autouse fixture

from app.core.database import SessionLocal
from app.main import app
from app.models.operations import OpsActivityBlock


OPS = "/api/v1/operations"


def test_recent_reports_have_public_block_lists():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        for day in ("2026-11-16", "2026-11-17"):
            created = client.post(f"{OPS}/reports", headers=headers, json={
                "well_id": well["id"], "rig_id": rig["id"], "report_date": day,
            })
            assert created.status_code == 200, created.text
        report = created.json()
        start = datetime(2026, 11, 17, tzinfo=timezone.utc)
        # The workbook extractor writes draft blocks directly, including rows
        # beyond the editor's 200-row limit. Don't hide those reports or rows.
        with SessionLocal() as db:
            for seq, minutes, deleted in [(1, 60, False), (2, 30, True), (201, 0, False)]:
                db.add(OpsActivityBlock(
                    organization_id=report["organization_id"], report_id=report["id"],
                    sequence_no=seq, started_at=start, ended_at=start + timedelta(minutes=minutes),
                    duration_minutes=minutes, is_deleted=deleted,
                ))
            db.commit()

        response = client.get(f"{OPS}/dashboard", headers=headers)
        assert response.status_code == 200, response.text
        populated, empty = response.json()["recent_reports"]
        assert populated["id"] == report["id"]
        assert sorted((b["sequence_no"], b["duration_minutes"]) for b in populated["blocks"]) == [(1, 60), (201, 0)]
        assert populated["total_block_minutes"] == 60
        assert empty["blocks"] == []
        assert "_blocks" not in populated
        other_workspace = client.get(f"{OPS}/dashboard", headers=login(client, "south"))
        assert other_workspace.status_code == 200, other_workspace.text
        assert other_workspace.json()["recent_reports"] == []

        # Reading an extracted draft must not loosen validation of manual edits.
        edit = client.put(f"{OPS}/reports/{report['id']}", headers=headers, json={
            "report": {},
            "blocks": [{
                "sequence_no": 201, "duration_minutes": 0,
                "started_at": start.isoformat(), "ended_at": start.isoformat(),
            }],
        })
        assert edit.status_code == 422, edit.text
        assert {error["loc"][-1] for error in edit.json()["detail"]} == {"sequence_no", "duration_minutes"}
