"""Cross-module regression coverage for the three-decimal entry contract."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Numeric

import app.models  # noqa: F401 - registers every model with Base.metadata
from app.core.database import Base
from app.core.precision import Decimal3
from app.core.units import depth_to_meters
from app.domain.afe_costing import money as afe_money
from app.schemas.afe import (
    ConsumableLineOut,
    ExchangeRateIn,
    ExchangeRateOut,
    RateIn,
    ScopeDaysIn,
    ScopeRateIn,
    ServiceLineOut,
    TangibleLineOut,
)
from app.schemas.catalogue import UnitRevise  # fuel prices revise through the shared priced-spec model
from app.schemas.daily_cost import DailyCostEntryCreate
from app.schemas.mud_cost import MudCostLineIn
from app.schemas.rig_well import ConfigurationPhaseIn, ConfigurationSectionIn
from app.schemas.sow_adjustment import AfeSowServiceLineIn, PlanPhaseIn
from app.services.catalogue import final_cost
from app.services.daily_cost import _fx, _money, _rate


THREE_PLACES = "1.123"
FOUR_PLACES = "1.1234"


def test_shared_decimal_contract_accepts_three_places_and_rejects_four():
    adapter = TypeAdapter(Decimal3)
    assert adapter.validate_python(THREE_PLACES) == Decimal(THREE_PLACES)
    with pytest.raises(ValidationError):
        adapter.validate_python(FOUR_PLACES)


@pytest.mark.parametrize(
    ("schema", "valid", "field"),
    [
        (ConfigurationPhaseIn, {"phase_id": "phase", "days": THREE_PLACES}, "days"),
        (
            ConfigurationSectionIn,
            {
                "hole_section_id": "section", "from_depth": THREE_PLACES, "to_depth": "2.123",
                "phases": [{"phase_id": "phase", "days": "1"}],
            },
            "from_depth",
        ),
        (UnitRevise, {"unit_rate": THREE_PLACES, "currency": "USD", "reason": "precision correction"}, "unit_rate"),
        (RateIn, {"category": "Operation", "unit_rate": THREE_PLACES}, "unit_rate"),
        (
            ScopeRateIn,
            {"hole_section_id": "section", "category": "Operation", "unit_rate": THREE_PLACES},
            "unit_rate",
        ),
        (
            ScopeDaysIn,
            {"hole_section_id": "section", "category": "Operation", "quantity": THREE_PLACES},
            "quantity",
        ),
        (ExchangeRateIn, {"currency_code": "EUR", "rate": THREE_PLACES}, "rate"),
        (MudCostLineIn, {"line_code": "opening_stock", "amount": THREE_PLACES}, "amount"),
        (
            DailyCostEntryCreate,
            {"well_id": "well", "afe_id": "afe", "cost_date": date(2026, 10, 20), "usd_exchange_rate": THREE_PLACES},
            "usd_exchange_rate",
        ),
        (
            AfeSowServiceLineIn,
            {
                "service_id": "service", "charging_basis": "Day Rate",
                "currency": "USD", "service_amount": THREE_PLACES,
            },
            "service_amount",
        ),
        (
            PlanPhaseIn,
            {"phase_id": "phase", "days": THREE_PLACES},
            "days",
        ),
    ],
)
def test_float_entry_schemas_share_the_three_decimal_limit(schema, valid, field):
    assert getattr(schema.model_validate(valid), field) == Decimal(THREE_PLACES)
    invalid = {**valid, field: FOUR_PLACES}
    with pytest.raises(ValidationError):
        schema.model_validate(invalid)


def test_all_decimal_database_columns_retain_three_places():
    decimal_columns = [
        column
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Numeric)
    ]
    assert decimal_columns
    assert all((column.type.precision, column.type.scale) == (28, 3) for column in decimal_columns)


def test_calculation_helpers_do_not_round_before_three_places():
    value = Decimal(THREE_PLACES)
    assert afe_money(value) == value
    assert _money(value) == value
    assert _rate(value) == value
    assert _fx(value) == value
    assert final_cost(value, Decimal("100")) == value
    assert depth_to_meters(value, "m") == value


@pytest.mark.parametrize(
    ("model", "values", "expected"),
    [
        (ServiceLineOut, {"service_amount": Decimal("0E-3")}, '"service_amount":"0.000"'),
        (
            ConsumableLineOut,
            {
                "quantity": Decimal("12.000"),
                "override_rate": Decimal("0E-3"),
                "estimated_amount": Decimal("0.730"),
            },
            '"estimated_amount":"0.730"',
        ),
        (TangibleLineOut, {"quantity": Decimal("1E+2")}, '"quantity":"100"'),
        (ExchangeRateOut, {"currency_code": "EUR", "rate": Decimal("1.230")}, '"rate":"1.230"'),
    ],
)
def test_afe_editable_decimal_responses_use_plain_notation(model, values, expected):
    serialized = model.model_construct(**values).model_dump_json()
    assert expected in serialized
    assert "E-" not in serialized
    assert "E+" not in serialized



def test_currency_and_fractional_day_pricing_round_only_the_result():
    from app.domain.afe_costing import UNIT_HOURS, normalize_days

    assert afe_money(Decimal('1.2345')) == Decimal('1.235')
    assert _money(Decimal('-1.2345')) == Decimal('-1.235')
    assert _money(Decimal('9999999999999999.1255')) == Decimal('9999999999999999.126')
    assert afe_money(normalize_days(Decimal('1'), UNIT_HOURS) * Decimal('24000')) == Decimal('1000.000')
    assert _fx(Decimal('0.001')) == Decimal('0.001')
    with pytest.raises(ValidationError):
        ExchangeRateIn(currency_code='EUR', rate='0.0004')
