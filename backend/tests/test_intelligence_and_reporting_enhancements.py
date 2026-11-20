"""Targeted regression tests for WellSenseIQ reporting, intelligence, and assistant upgrades.

Covers:
1. Tangible-aware Cost Intelligence: end-of-scope lump-sum tangibles never fire false
   spikes, CUSUM drift alarms, or burn-ahead warnings; forecast adds unbooked tangible
   AFE once instead of multiplying tangibles by remaining days.
2. Smarter Cost Intelligence domain rules: UPA share, depth vs operational spend
   mismatch, Actual / AFE % KPIs, and group overrun severity.
3. Assistant live data extraction: catalogue price lookup (tangibles & consumables),
   keyword cost search, RBAC enforcement, and structured tables on AssistantAnswer.
"""

from datetime import date, timedelta
from decimal import Decimal
import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.domain import cost_intelligence as domain
from app.main import app
from app.models import (
    Block,
    CatalogueOption,
    FuelType,
    MudChemical,
    NdtInspection,
    Organization,
    Permission,
    Rig,
    Role,
    Tangible,
    User,
    Well,
)


PERMISSIONS = [
    *(f"rig-well:{action}" for action in ("read", "create", "update")),
    *(f"afe:{action}" for action in ("read", "create", "estimate", "approve")),
    *(f"daily-cost:{action}" for action in ("read", "create", "update", "submit")),
    *(f"master-data:{action}" for action in ("read", "create", "update")),
    "assistant:read",
    "assistant:manage",
    "cost-intelligence:read",
]


@pytest.fixture
def client_and_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        org = Organization(slug="alpha", name="Alpha Energy")
        db.add(org)
        db.flush()
        perms = [Permission(organization_id=org.id, key=key, description=key) for key in PERMISSIONS]
        owner_role = Role(organization_id=org.id, name="Owner", is_owner=True, permissions=perms)
        restricted_role = Role(
            organization_id=org.id,
            name="Restricted",
            is_owner=False,
            permissions=[p for p in perms if p.key in ("assistant:read",)],
        )
        db.add(User(
            organization_id=org.id,
            email="owner@example.com",
            full_name="Alpha Owner",
            password_hash=hash_password("correct-password-123"),
            roles=[owner_role],
        ))
        db.add(User(
            organization_id=org.id,
            email="restricted@example.com",
            full_name="Restricted User",
            password_hash=hash_password("correct-password-123"),
            roles=[restricted_role],
        ))
        db.commit()
    with TestClient(app) as client:
        yield client


def _login(client: TestClient, email: str = "owner@example.com") -> dict[str, str]:
    res = client.post("/api/v1/auth/login", json={
        "organization": "alpha", "email": email, "password": "correct-password-123",
    })
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Item 2: Tangible-aware Cost Intelligence (domain layer)
# ---------------------------------------------------------------------------


def test_end_of_scope_tangible_booking_does_not_trigger_spike_drift_or_at_risk():
    """Booking $350,000 of casing/tubing on the final day of a scope must NOT flag a
    cost-spike, CUSUM drift-up, or mark an otherwise healthy well as at-risk."""
    start = date(2026, 3, 1)
    days = [
        domain.DayCost(
            cost_date=start + timedelta(days=i),
            actual=25_000.0 + (200.0 if i % 2 == 0 else -200.0),
            tangibles=0.0,
            services=20_000.0,
            consumables=5_000.0 + (200.0 if i % 2 == 0 else -200.0),
        )
        for i in range(15)
    ]
    # Day 16: normal operational cost ($25,000) PLUS $350,000 lump-sum casing tangibles
    days.append(
        domain.DayCost(
            cost_date=start + timedelta(days=15),
            actual=375_000.0,
            tangibles=350_000.0,
            services=20_000.0,
            consumables=5_000.0,
        )
    )
    total_actual = sum(d.actual for d in days)
    well = domain.WellInput(
        well_id="w-tang",
        well_code="WELL-TANG-01",
        status="active",
        currency="USD",
        afe_amount=1_000_000.0,  # $600k operational + $400k tangibles
        actual_amount=total_actual,
        planned_days=24.0,
        actual_days=16.0,
        days=tuple(days),
        groups=(
            domain.GroupCost(label="Services", planned=480_000.0, actual=320_000.0),
            domain.GroupCost(label="Consumables", planned=120_000.0, actual=80_000.0),
            domain.GroupCost(label="Tangibles", planned=400_000.0, actual=350_000.0),
        ),
    )

    result = domain.analyse_well(well, as_of=start + timedelta(days=15))
    codes = {f.code for f in result.findings}

    assert "cost-spike" not in codes, f"End-of-scope tangibles triggered false cost-spike: {codes}"
    assert "drift-up" not in codes, f"End-of-scope tangibles triggered false drift-up: {codes}"
    assert "burn-ahead" not in codes, f"Budgeted tangibles triggered false burn-ahead: {codes}"
    assert result.band == "good", f"Expected healthy well band='good', got {result.band} ({codes})"
    assert result.score == 100
    # Forecast: actual ($750k) + 8 remaining days * $25k operational ($200k) + $50k unbooked tangible AFE = $1,000k
    assert result.forecast.available is True
    assert result.forecast.recent_daily == pytest.approx(25_000.0, abs=300.0)
    assert result.forecast.remaining_tangibles == pytest.approx(50_000.0, abs=1.0)
    assert result.forecast.estimate == pytest.approx(1_000_000.0, abs=3_000.0)


def test_tangible_only_closeout_sheet_does_not_fire_cost_dip():
    """A standalone closeout sheet carrying only tangibles ($0 operational) must not fire cost-dip."""
    start = date(2026, 4, 1)
    days = [
        domain.DayCost(cost_date=start + timedelta(days=i), actual=30_000.0, services=30_000.0)
        for i in range(10)
    ]
    days.append(
        domain.DayCost(cost_date=start + timedelta(days=10), actual=180_000.0, tangibles=180_000.0)
    )
    well = domain.WellInput(
        well_id="w-close",
        well_code="WELL-CLOSE",
        status="completed",
        currency="USD",
        afe_amount=600_000.0,
        actual_amount=sum(d.actual for d in days),
        planned_days=12.0,
        actual_days=11.0,
        days=tuple(days),
        groups=(domain.GroupCost(label="Tangibles", planned=200_000.0, actual=180_000.0),),
    )
    result = domain.analyse_well(well, as_of=start + timedelta(days=10))
    codes = {f.code for f in result.findings}
    assert "cost-dip" not in codes
    assert "cost-spike" not in codes
    assert result.band == "good"


# ---------------------------------------------------------------------------
# Item 3 (Part A): Smarter Cost Intelligence rules
# ---------------------------------------------------------------------------


def test_smarter_domain_checks_upa_and_depth_mismatch():
    """High UPA share and operational spend outpacing depth progress raise actionable findings."""
    start = date(2026, 5, 1)
    days = tuple(
        domain.DayCost(cost_date=start + timedelta(days=i), actual=50_000.0, upa=12_000.0)
        for i in range(8)
    )
    well = domain.WellInput(
        well_id="w-smart",
        well_code="WELL-SMART",
        status="active",
        currency="USD",
        afe_amount=500_000.0,
        actual_amount=400_000.0,  # 80% operational AFE spent
        planned_days=12.0,
        actual_days=8.0,
        upa_amount=96_000.0,  # 24% of actual -> critical upa-share
        planned_depth=3_000.0,
        actual_depth=1_050.0,
        depth_progress_percent=35.0,  # 80% spend vs 35% depth -> depth-cost-mismatch
        days=days,
    )
    result = domain.analyse_well(well, as_of=start + timedelta(days=7))
    by_code = {f.code: f for f in result.findings}
    assert "upa-share" in by_code
    assert by_code["upa-share"].severity == "critical"
    assert "depth-cost-mismatch" in by_code
    assert by_code["depth-cost-mismatch"].severity == "warning"


# ---------------------------------------------------------------------------
# Item 3 (Part B): Assistant live price lookup, keyword cost search & RBAC
# ---------------------------------------------------------------------------


def test_assistant_price_lookup_cost_search_and_rbac(client_and_db: TestClient):
    with SessionLocal() as db:
        org = db.query(Organization).filter(Organization.slug == "alpha").one()
        cat = CatalogueOption(
            organization_id=org.id, list_key="tangible_category", parent_key="",
            value="Casing", value_key="casing",
        )
        mfr = CatalogueOption(
            organization_id=org.id, list_key="manufacturer", parent_key="",
            value="Tenaris", value_key="tenaris",
        )
        mud_grp = CatalogueOption(
            organization_id=org.id, list_key="mud_chemical_group", parent_key="",
            value="Weighting", value_key="weighting",
        )
        db.add_all([cat, mfr, mud_grp])
        db.flush()
        sub = CatalogueOption(
            organization_id=org.id, list_key="tangible_subcategory", parent_id=cat.id,
            parent_key=cat.id, value="9-5/8 in", value_key="9-5/8 in",
        )
        db.add(sub)
        db.flush()

        db.add(Tangible(
            organization_id=org.id,
            tangible_code="CSG-958",
            tangible_name="9-5/8 in L80 Casing",
            scope="Drilling",
            category_id=cat.id,
            subcategory_id=sub.id,
            manufacturer_id=mfr.id,
            uom="ft",
            unit_rate=Decimal("120.00"),
            cost_uplift=Decimal("110.00"),
            final_cost=Decimal("132.00"),
            currency="USD",
            effective_date=date(2026, 1, 15),
        ))
        db.add(MudChemical(
            organization_id=org.id,
            chemical_code="BAR-01",
            chemical_name="Barite API Grade",
            group_id=mud_grp.id,
            uom="MT",
            unit_rate=Decimal("245.50"),
            currency="USD",
            effective_date=date(2026, 2, 1),
        ))
        db.add(FuelType(
            organization_id=org.id,
            fuel_code="AGO",
            fuel_name="Automotive Gas Oil Diesel",
            uom="L",
            unit_rate=Decimal("1.15"),
            currency="USD",
            effective_date=date(2026, 3, 1),
        ))
        rig = Rig(organization_id=org.id, rig_code="RIG-01", rig_name="Rig One", remarks="")
        block = Block(organization_id=org.id, block_code="BLK-1", block_name="Block One", description="")
        db.add_all([rig, block])
        db.flush()
        well = Well(
            organization_id=org.id, rig_id=rig.id, block_id=block.id,
            well_code="WELL-09", well_name="Well Nine", well_location="Alpha",
            objective="Dev", remarks="", status="active", config_status="configured",
        )
        db.add(well)
        db.flush()
        db.add(NdtInspection(
            organization_id=org.id, rig_id=rig.id, rig_code_snapshot="RIG-01", rig_name_snapshot="Rig One",
            well_id=well.id, well_code_snapshot="WELL-09", well_name_snapshot="Well Nine",
            scope="drilling", description="9-5/8 Casing MPI Thread Inspection",
            quantity_received=Decimal("40"), quantity_consumed=Decimal("36"),
            quantity_backloaded_good=Decimal("3"), quantity_backloaded_bad=Decimal("1"),
        ))
        db.commit()

    owner_headers = _login(client_and_db, "owner@example.com")

    # 1. Price lookup for a specific tangible
    res = client_and_db.post("/api/v1/assistant/ask", headers=owner_headers, json={
        "question": "What is the price of 9-5/8 casing?",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["intent"] == "price_lookup"
    assert body["confidence"] == "high"
    assert body["tables"], "Expected structured price table"
    flat_rows = " ".join(" ".join(r) for t in body["tables"] for r in t["rows"])
    assert "9-5/8 in L80 Casing" in flat_rows
    assert "132.00" in flat_rows

    # 2. Price lookup for a consumable (mud chemical)
    res_chem = client_and_db.post("/api/v1/assistant/ask", headers=owner_headers, json={
        "question": "Price of Barite",
    })
    assert res_chem.status_code == 200
    body_chem = res_chem.json()
    assert body_chem["intent"] == "price_lookup"
    assert any("Barite API Grade" in " ".join(r) and "245.50" in " ".join(r) for t in body_chem["tables"] for r in t["rows"])

    # 3. Keyword search across NDT & catalogue even with a plain keyword query
    res_search = client_and_db.post("/api/v1/assistant/ask", headers=owner_headers, json={
        "question": "Search costs for MPI",
    })
    assert res_search.status_code == 200
    body_search = res_search.json()
    assert body_search["intent"] == "cost_search"
    assert any("MPI Thread Inspection" in " ".join(r) for t in body_search["tables"] for r in t["rows"])

    # 4. RBAC check: restricted user without master-data:read or daily-cost:read cannot read prices
    restricted_headers = _login(client_and_db, "restricted@example.com")
    res_denied = client_and_db.post("/api/v1/assistant/ask", headers=restricted_headers, json={
        "question": "What is the price of Barite?",
    })
    assert res_denied.status_code == 200
    denied_body = res_denied.json()
    assert denied_body["intent"] == "permission"
    assert "master-data:read" in denied_body["answer"]
    assert not denied_body["tables"]
