"""Response shapes for Cost Intelligence (read-only analysis; advice only)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class IntelligenceEvidence(BaseModel):
    label: str
    value: str


class IntelligenceFinding(BaseModel):
    id: str
    code: str
    severity: Literal["critical", "warning", "info"]
    category: Literal["budget", "trend", "anomaly", "schedule", "npt", "data-quality"]
    title: str
    detail: str
    basis: str
    suggestion: str
    well_id: str
    well_code: str
    cost_date: date | None = None
    amount: float | None = None
    evidence: list[IntelligenceEvidence] = []
    action_path: str = ""
    action_label: str = ""


class IntelligenceForecast(BaseModel):
    available: bool = False
    reason: str = ""
    recent_daily: float | None = None
    planned_daily: float | None = None
    remaining_days: float | None = None
    estimate: float | None = None
    low: float | None = None
    high: float | None = None
    variance: float | None = None
    variance_percent: float | None = None
    exhaustion_date: date | None = None
    days_to_exhaustion: float | None = None
    past_plan: bool = False


class IntelligenceWell(BaseModel):
    well_id: str
    well_code: str
    well_name: str = ""
    rig_code: str = ""
    status: str = ""
    currency: str = ""
    afe_amount: float | None = None
    actual_amount: float | None = None
    utilisation_percent: float | None = None
    planned_days: float | None = None
    actual_days: float | None = None
    npt_amount: float | None = None
    npt_share_percent: float | None = None
    recorded_days: int = 0
    first_cost_date: date | None = None
    last_cost_date: date | None = None
    score: int = 100
    band: Literal["good", "watch", "at-risk"] = "good"
    critical: int = 0
    warning: int = 0
    info: int = 0
    summary: str = ""
    forecast: IntelligenceForecast = IntelligenceForecast()
    analysed: bool = True


class IntelligenceDay(BaseModel):
    cost_date: date
    actual: float
    cumulative: float
    npt: float = 0
    baseline: float | None = None
    planned_cumulative: float | None = None
    cusum_up: float | None = None
    cusum_down: float | None = None
    spike: bool = False


class IntelligenceProjection(BaseModel):
    cost_date: date
    estimate: float
    low: float
    high: float


class IntelligenceWellDetail(BaseModel):
    well: IntelligenceWell
    findings: list[IntelligenceFinding]
    days: list[IntelligenceDay]
    projection: list[IntelligenceProjection] = []
    missing_dates: list[date] = []
    cusum_limit: float
    drift_baseline: float | None = None
    drift_start: date | None = None
    drift_direction: str = ""
    notes: list[str] = []


class IntelligenceKpis(BaseModel):
    wells: int = 0
    analysed_wells: int = 0
    afe_amount: float | None = None
    actual_amount: float | None = None
    forecast_amount: float | None = None
    forecast_variance: float | None = None
    forecast_variance_percent: float | None = None
    amount_at_risk: float | None = None
    critical: int = 0
    warning: int = 0
    info: int = 0
    wells_at_risk: int = 0
    score: int = 100
    band: Literal["good", "watch", "at-risk"] = "good"


class IntelligenceCount(BaseModel):
    key: str
    label: str
    critical: int = 0
    warning: int = 0
    info: int = 0


class IntelligenceSuggestion(BaseModel):
    """One thing to do next, ranked across the whole workspace."""

    rank: int
    severity: Literal["critical", "warning", "info"]
    well_id: str
    well_code: str
    title: str
    suggestion: str
    amount: float | None = None
    action_path: str = ""
    action_label: str = ""
    finding_id: str


class IntelligenceCapabilities(BaseModel):
    budget: bool
    actuals: bool
    plan: bool
    export: bool


class IntelligenceOverview(BaseModel):
    generated_at: datetime
    as_of: date
    date_from: date | None = None
    date_to: date | None = None
    currency: str = ""
    capabilities: IntelligenceCapabilities
    kpis: IntelligenceKpis
    headline: list[str] = []
    wells: list[IntelligenceWell] = []
    findings: list[IntelligenceFinding] = []
    suggestions: list[IntelligenceSuggestion] = []
    by_category: list[IntelligenceCount] = []
    notes: list[str] = []
    methods: list[str] = []


class IntelligenceExportAudit(BaseModel):
    format: Literal["csv", "xlsx", "pdf"]
    record_count: int = 0
    sections: str = ""
