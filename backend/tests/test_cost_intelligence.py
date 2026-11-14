"""Cost Intelligence: the analysis rules, then the API's access and audit rules."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from test_business_dashboard import _setup, fresh_database, login  # noqa: F401 - fixture is used by name

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.domain import cost_intelligence as ci
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User
from app.services.provisioning import CAPABILITIES

START = date(2026, 10, 1)


def well(values, *, afe=1_000_000.0, planned=40.0, status="active", skip=(), npt=0.0, **extra):
    days, offset = [], 0
    for value in values:
        while offset in skip:
            offset += 1
        days.append(ci.DayCost(cost_date=START + timedelta(days=offset), actual=float(value)))
        offset += 1
    return ci.WellInput(
        well_id="w1", well_code="W-1", status=status, currency="USD", afe_amount=afe,
        actual_amount=float(sum(values)), planned_days=planned, actual_days=float(len(values)),
        npt_amount=npt, sheet_count=len(values), days=tuple(days), **extra,
    )


def codes(analysis):
    return [item.code for item in analysis.findings]


STEADY = [25_000 + (index % 5) * 300 for index in range(30)]


def test_a_steady_well_on_plan_raises_nothing():
    analysis = ci.analyse_well(well(STEADY), as_of=START + timedelta(days=29))
    assert codes(analysis) == []
    assert analysis.score == 100 and analysis.band == "good"
    assert analysis.forecast.available
    # 30 days recorded, 10 to go at about 25.6k a day.
    assert abs(analysis.forecast.estimate - (sum(STEADY) + 10 * sum(STEADY[-7:]) / 7)) < 1


def test_one_day_keyed_ten_times_too_high_is_the_only_spike():
    values = list(STEADY)
    values[17] = 250_000
    analysis = ci.analyse_well(well(values), as_of=START + timedelta(days=29))
    spikes = [item for item in analysis.findings if item.code == "cost-spike"]
    assert len(spikes) == 1 and spikes[0].cost_date == START + timedelta(days=17)
    assert "drift-up" not in codes(analysis), "one bad day is not a trend"
    # The forecast ignores the spike day when estimating the daily rate.
    assert analysis.forecast.recent_daily < 30_000


def test_a_step_to_a_new_level_and_a_recurring_peak_are_not_spikes():
    step = [25_000] * 5 + [34_000 + (index % 3) * 200 for index in range(25)]
    assert ci.find_spikes([float(v) for v in step]) == []
    recurring = [57_000 if index % 3 == 0 else 41_500 + index * 10 for index in range(27)]
    assert ci.find_spikes([float(v) for v in recurring]) == []


def test_creeping_cost_is_caught_and_dated():
    values = STEADY[:12] + [26_000 + 1_400 * step for step in range(18)]
    analysis = ci.analyse_well(well(values, afe=1_500_000.0), as_of=START + timedelta(days=29))
    drift = next(item for item in analysis.findings if item.code == "drift-up")
    assert START + timedelta(days=11) <= drift.cost_date <= START + timedelta(days=16)
    assert analysis.drift.change_percent > 20
    assert "cost-spike" not in codes(analysis), "a creep is not reported as a string of spikes"


def test_forecast_overrun_and_recorded_overrun_are_distinguished():
    forecast = ci.analyse_well(well([30_000] * 30, afe=1_000_000.0, planned=40.0))
    finding = next(item for item in forecast.findings if item.code == "forecast-overrun")
    assert finding.severity == "critical" and abs(finding.amount - 200_000) < 1
    recorded = ci.analyse_well(well([30_000] * 30, afe=800_000.0, planned=40.0))
    assert "afe-exceeded" in codes(recorded) and "forecast-overrun" not in codes(recorded)


def test_schedule_npt_and_record_gaps():
    analysis = ci.analyse_well(
        well(STEADY, planned=24.0, npt=sum(STEADY) * 0.22, skip=(12, 13)), as_of=START + timedelta(days=40),
    )
    found = codes(analysis)
    assert {"schedule-overrun", "npt-share", "missing-sheets", "stale-record"} <= set(found)
    assert analysis.missing_dates == [START + timedelta(days=12), START + timedelta(days=13)]
    npt = next(item for item in analysis.findings if item.code == "npt-share")
    assert npt.severity == "critical"


def test_unknown_figures_skip_checks_instead_of_guessing():
    analysis = ci.analyse_well(well(STEADY, afe=None, planned=None))
    assert not {"afe-exceeded", "forecast-overrun", "burn-ahead", "schedule-overrun"} & set(codes(analysis))
    assert analysis.forecast.available is False and analysis.forecast.reason


def test_every_finding_explains_itself_and_scores_are_bounded():
    values = list(STEADY)
    values[17] = 250_000
    analysis = ci.analyse_well(well(values, afe=500_000.0, planned=20.0, npt=300_000.0, skip=(3, 4)))
    assert analysis.findings and all(item.basis and item.suggestion and item.detail for item in analysis.findings)
    assert 0 <= analysis.score <= 100
    assert [ci.SEVERITY_ORDER[item.severity] for item in analysis.findings] == sorted(
        ci.SEVERITY_ORDER[item.severity] for item in analysis.findings)


def test_short_records_are_left_alone():
    analysis = ci.analyse_well(well([25_000, 90_000, 25_000]))
    assert "cost-spike" not in codes(analysis) and analysis.drift.available is False


# --- API -------------------------------------------------------------------

def _grant(email: str, keys: tuple[str, ...]) -> None:
    with SessionLocal() as db:
        organization = db.query(Organization).filter(Organization.slug == "north").one()
        permissions = []
        for key in keys:
            permission = db.query(Permission).filter(
                Permission.organization_id == organization.id, Permission.key == key).one_or_none()
            if permission is None:
                permission = Permission(organization_id=organization.id, key=key, description=key)
                db.add(permission)
            permissions.append(permission)
        role = Role(organization_id=organization.id, name=f"Role for {email}", permissions=permissions)
        db.add(role)
        db.flush()
        db.add(User(organization_id=organization.id, email=email, full_name=email,
                    password_hash=hash_password("correct-password-123"), roles=[role]))
        db.commit()


def test_the_capabilities_are_provisioned():
    assert CAPABILITIES["cost-intelligence"] == ("read", "export")


def test_overview_matches_the_dashboard_and_respects_access():
    with TestClient(app) as client:
        owner = login(client)
        _setup(client, owner)
        dashboard = client.get("/api/v1/dashboard/business", headers=owner).json()
        response = client.get("/api/v1/cost-intelligence/overview", headers=owner)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["kpis"]["wells"] == dashboard["kpis"]["wells"] == 1
        row, source = data["wells"][0], dashboard["wells"][0]
        assert row["well_id"] == source["well_id"]
        assert abs(row["actual_amount"] - float(source["actual_amount"])) < 0.01
        assert abs(row["afe_amount"] - float(source["effective_afe_amount"])) < 0.01
        assert data["headline"] and data["methods"]
        assert data["capabilities"] == {"budget": True, "actuals": True, "plan": True, "export": True}

        detail = client.get(f"/api/v1/cost-intelligence/wells/{row['well_id']}", headers=owner)
        assert detail.status_code == 200, detail.text
        days = detail.json()["days"]
        assert days and abs(days[-1]["cumulative"] - row["actual_amount"]) < 0.01

        # Without the capability the module is closed, whatever else is held.
        _grant("costs@example.com", ("daily-cost:read", "afe:read", "rig-well:read"))
        outsider = login(client, email="costs@example.com")
        assert client.get("/api/v1/cost-intelligence/overview", headers=outsider).status_code == 403

        # With it, the figures still follow the source capabilities: no AFE here.
        _grant("analyst@example.com", ("cost-intelligence:read", "daily-cost:read"))
        analyst = login(client, email="analyst@example.com")
        limited = client.get("/api/v1/cost-intelligence/overview", headers=analyst)
        assert limited.status_code == 200, limited.text
        payload = limited.json()
        assert payload["capabilities"]["budget"] is False and payload["capabilities"]["export"] is False
        assert payload["kpis"]["afe_amount"] is None and payload["wells"][0]["afe_amount"] is None
        assert any("AFE amounts are not part of your access" in note for note in payload["notes"])
        assert not [item for item in payload["findings"] if item["category"] == "budget"]

        # Another workspace cannot read this well, and sees none of its figures.
        south = login(client, organization="south")
        assert client.get(f"/api/v1/cost-intelligence/wells/{row['well_id']}", headers=south).status_code == 404
        assert client.get("/api/v1/cost-intelligence/overview", headers=south).json()["kpis"]["wells"] == 0

        # Exports are audited, and need their own capability.
        refused = client.post("/api/v1/cost-intelligence/exports", headers=analyst, json={"format": "pdf", "record_count": 3})
        assert refused.status_code == 403
        recorded = client.post("/api/v1/cost-intelligence/exports", headers=owner,
                               json={"format": "xlsx", "record_count": 3, "sections": "summary,findings"})
        assert recorded.status_code == 204, recorded.text
        with SessionLocal() as db:
            entry = db.query(AuditLog).filter(AuditLog.entity_type == "cost_intelligence").one()
            assert entry.action == "export" and "XLSX" in entry.summary and "summary,findings" in entry.summary

        assert client.get("/api/v1/cost-intelligence/overview?from=2026-02-01&to=2026-01-01", headers=owner).status_code == 422
