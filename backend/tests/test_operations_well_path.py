"""Well path and well diagram: minimum curvature, seats, current depth, provenance.

The diagram is only trustworthy if it draws what the record holds and says so.
These checks therefore cover the geometry arithmetic, the case where a well has
no surveys at all (nothing may be invented), a printed TVD that contradicts the
integration, and the casing-seat reading that turns reports into a schematic.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from test_rig_well import create_rig, create_well, fresh_database, login  # noqa: F401 - autouse fixture

# The shared fixture must configure its disposable database before app.core.database is imported.
# isort: split

from app.core.database import SessionLocal
from app.main import app
from app.models.operations import OpsDailyReport, OpsSurvey
from app.models.rig_well import Well
from fastapi.testclient import TestClient

OPS = "/api/v1/operations"


def _org(well_id: str) -> str:
    with SessionLocal() as db:
        return db.get(Well, well_id).organization_id


def _configure(well_id: str) -> None:
    with SessionLocal() as db:
        db.get(Well, well_id).config_status = "configured"
        db.commit()


def _survey(organization_id: str, well_id: str, md, inc, azi, **extra) -> OpsSurvey:
    return OpsSurvey(
        organization_id=organization_id,
        well_id=well_id,
        scope="drilling",
        station_no=None,
        md_m=Decimal(str(md)),
        inc_deg=Decimal(str(inc)),
        azi_deg=Decimal(str(azi)),
        source="manual",
        **extra,
    )


def _report(organization_id: str, well_id: str, rig_id: str, **values) -> OpsDailyReport:
    day = values.pop("report_date", datetime(2026, 11, 16, tzinfo=UTC).date())
    return OpsDailyReport(
        organization_id=organization_id,
        well_id=well_id,
        rig_id=rig_id,
        scope="drilling",
        report_type="DDR",
        report_date=day,
        period_minutes=1440,
        **values,
    )


def test_vertical_well_with_no_surveys_is_not_invented():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        _configure(well["id"])
        org = _org(well["id"])
        with SessionLocal() as db:
            db.add(
                _report(
                    org,
                    well["id"],
                    rig["id"],
                    depth_start_m=Decimal("3200"),
                    depth_end_m=Decimal("3930"),
                    tvd_m=Decimal("2813.06"),
                    bit_depth_m=Decimal("3930"),
                    last_casing_size_in=Decimal("9.625"),
                    last_casing_depth_m=Decimal("3928"),
                )
            )
            db.commit()

        response = client.get(f"{OPS}/well-path", headers=headers, params={"well_id": well["id"]})
        assert response.status_code == 200, response.text
        body = response.json()
        # No station was recorded, so no curve is drawn — but the current depth and
        # the casing schematic still come from the report that recorded them.
        assert body["curve"] == []
        assert body["is_surveyed"] is False
        assert "not drawn" in body["assumption"]
        assert body["summary"]["current_md_m"] == 3930.0
        assert body["summary"]["current_tvd_m"] == 2813.06
        assert body["summary"]["current_tvd_basis"] == "report header"
        assert body["summary"]["bit_depth_m"] == 3930.0
        # Size alone would not place a shoe; size + printed depth does.
        assert [s["casing_label"] for s in body["sections"]] == ['9-5/8"']
        assert body["sections"][0]["to_depth_m"] == 3928.0
        # 3930 m is below the 3928 m shoe, so 2 m of hole is open.
        assert body["open_hole"]["from_depth_m"] == 3928.0
        assert body["open_hole"]["to_depth_m"] == 3930.0


def test_minimum_curvature_curve_and_current_depth_follow_the_surveys():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        _configure(well["id"])
        org = _org(well["id"])
        with SessionLocal() as db:
            for md, inc, azi in [(0, 0, 0), (500, 0, 0), (1000, 30, 45), (1500, 30, 45), (2000, 60, 90)]:
                db.add(_survey(org, well["id"], md, inc, azi))
            db.commit()

        body = client.get(f"{OPS}/well-path", headers=headers, params={"well_id": well["id"]}).json()
        curve = {row["md_m"]: row for row in body["curve"]}
        assert body["is_surveyed"] is True
        # Published minimum-curvature results for this shape.
        assert abs(curve[1000.0]["tvd_m"] - 977.465) < 0.01
        assert abs(curve[1000.0]["ns_m"] - 90.465) < 0.01
        assert abs(curve[1000.0]["ew_m"] - 90.465) < 0.01
        assert abs(curve[1500.0]["tvd_m"] - 1410.483) < 0.01
        assert abs(curve[2000.0]["dls_deg_per_30m"] - 2.5397) < 0.01
        assert body["summary"]["max_inc_deg"] == 60.0
        assert body["summary"]["kickoff_md_m"] == 1000.0
        assert abs(body["vertical_section_azimuth_deg"] - 58.484) < 0.01
        # No report exists yet, so the current position is the last station.
        assert body["summary"]["current_md_m"] == 2000.0
        assert abs(body["summary"]["current_tvd_m"] - 1768.421) < 0.01


def test_a_printed_tvd_that_contradicts_the_integration_is_reported_not_overwritten():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        _configure(well["id"])
        org = _org(well["id"])
        with SessionLocal() as db:
            db.add(_survey(org, well["id"], 0, 0, 0, tvd_m=Decimal("0")))
            db.add(_survey(org, well["id"], 1000, 0, 0, tvd_m=Decimal("50")))
            db.commit()
        body = client.get(f"{OPS}/well-path", headers=headers, params={"well_id": well["id"]}).json()
        assert body["curve"][-1]["tvd_m"] == 1000.0
        assert body["survey_discrepancies"][0]["printed_tvd_m"] == 50.0
        assert body["survey_discrepancies"][0]["difference_m"] == -950.0


def test_casing_seats_build_the_schematic_in_order():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        _configure(well["id"])
        org = _org(well["id"])
        with SessionLocal() as db:
            db.add(
                _report(
                    org,
                    well["id"],
                    rig["id"],
                    report_date=datetime(2026, 11, 10, tzinfo=UTC).date(),
                    depth_end_m=Decimal("1865"),
                    last_casing_size_in=Decimal("13.375"),
                    last_casing_depth_m=Decimal("1865"),
                )
            )
            db.add(
                _report(
                    org,
                    well["id"],
                    rig["id"],
                    report_date=datetime(2026, 11, 16, tzinfo=UTC).date(),
                    depth_end_m=Decimal("3930"),
                    last_casing_size_in=Decimal("9.625"),
                    last_casing_depth_m=Decimal("3928"),
                )
            )
            db.commit()
        body = client.get(f"{OPS}/well-path", headers=headers, params={"well_id": well["id"]}).json()
        assert [(s["from_depth_m"], s["to_depth_m"]) for s in body["sections"]] == [
            (0.0, 1865.0),
            (1865.0, 3928.0),
        ]
        assert [s["casing_label"] for s in body["sections"]] == ['13-3/8"', '9-5/8"']
        assert body["sections"][-1]["is_deepest"] is True


def test_well_path_is_tenant_scoped_and_dashboard_carries_the_visual():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        _configure(well["id"])
        org = _org(well["id"])
        with SessionLocal() as db:
            db.add(_survey(org, well["id"], 0, 0, 0))
            db.add(_survey(org, well["id"], 500, 10, 90))
            db.add(
                _report(
                    org,
                    well["id"],
                    rig["id"],
                    depth_end_m=Decimal("500"),
                    last_casing_size_in=Decimal("13.375"),
                    last_casing_depth_m=Decimal("500"),
                )
            )
            db.commit()

        other = login(client, "south")
        blocked = client.get(f"{OPS}/well-path", headers=other, params={"well_id": well["id"]})
        assert blocked.status_code == 404

        dashboard = client.get(
            f"{OPS}/dashboard", headers=headers, params={"well_id": well["id"], "scope": "drilling"}
        ).json()
        visual = dashboard["well_visual"]
        assert visual["well_code"] == well["well_code"]
        assert visual["summary"]["current_md_m"] == 500.0
        assert visual["sections"][0]["casing_label"] == '13-3/8"'
        # A multi-well filter shows no single well's drawing.
        assert client.get(f"{OPS}/dashboard", headers=headers).json()["well_visual"] is None


def test_diagram_endpoint_lists_configured_wells_of_the_scope():
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        drilling = create_well(client, headers, rig["id"], code="WELL-D")
        completion = create_well(client, headers, rig["id"], code="WELL-C")
        with SessionLocal() as db:
            db.get(Well, drilling["id"]).config_status = "configured"
            db.get(Well, completion["id"]).completion_config_status = "configured"
            db.commit()
        drilling_rows = client.get(f"{OPS}/well-diagram", headers=headers).json()["wells"]
        completion_rows = client.get(
            f"{OPS}/well-diagram", headers=headers, params={"scope": "completion"}
        ).json()["wells"]
        assert [row["well_code"] for row in drilling_rows] == ["WELL-D"]
        assert [row["well_code"] for row in completion_rows] == ["WELL-C"]


def test_latest_verified_report_wins_over_a_newer_draft():
    """A draft cannot move the current depth marker ahead of the verified record."""
    with TestClient(app) as client:
        headers = login(client)
        rig = create_rig(client, headers)
        well = create_well(client, headers, rig["id"])
        _configure(well["id"])
        org = _org(well["id"])
        with SessionLocal() as db:
            db.add(
                _report(
                    org,
                    well["id"],
                    rig["id"],
                    report_date=datetime(2026, 11, 15, tzinfo=UTC).date(),
                    status="submitted",
                    depth_end_m=Decimal("3000"),
                )
            )
            db.add(
                _report(
                    org,
                    well["id"],
                    rig["id"],
                    report_date=datetime(2026, 11, 16, tzinfo=UTC).date(),
                    status="draft",
                    depth_end_m=Decimal("3100"),
                )
            )
            db.commit()
        body = client.get(f"{OPS}/well-path", headers=headers, params={"well_id": well["id"]}).json()
        assert body["summary"]["current_md_m"] == 3000.0
        assert body["summary"]["depth_basis"] == "latest verified report"
