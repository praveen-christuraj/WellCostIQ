"""Response shapes for Cost Intelligence (read-only analysis; advice only)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    remaining_tangibles: float = 0.0
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
    operational_amount: float | None = None
    tangible_amount: float | None = None
    planned_days: float | None = None
    actual_days: float | None = None
    npt_amount: float | None = None
    npt_share_percent: float | None = None
    upa_amount: float | None = None
    upa_share_percent: float | None = None
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
    operational: float = 0.0
    tangibles: float = 0.0
    services: float = 0.0
    consumables: float = 0.0
    other_expenses: float = 0.0
    tangible_booking_day: bool = False
    cumulative: float
    npt: float = 0
    baseline: float | None = None
    planned_cumulative: float | None = None
    cusum_up: float | None = None
    cusum_down: float | None = None
    spike: bool = False


class IntelligenceGroupBreakdown(BaseModel):
    label: str
    planned: float | None = None
    actual: float = 0.0
    balance: float | None = None
    utilisation_percent: float | None = None
    share_percent: float | None = None


class IntelligenceSectionBreakdown(BaseModel):
    section_code: str
    section_name: str
    scope: str = "drilling"
    planned_days: float | None = None
    active_days: int = 0
    amount: float = 0.0
    share_percent: float | None = None


class IntelligenceActivityBreakdown(BaseModel):
    activity_code: str
    activity_name: str
    classification: str = "Planned"
    active_days: int = 0
    amount: float = 0.0
    share_percent: float | None = None


class IntelligenceUnitEconomics(BaseModel):
    operational_actual: float = 0.0
    tangible_actual: float = 0.0
    tangible_afe: float | None = None
    tangible_utilisation_percent: float | None = None
    tangible_booking_dates: list[date] = []
    operational_daily_avg: float | None = None
    planned_operational_daily: float | None = None
    cost_per_meter: float | None = None
    actual_depth: float | None = None
    planned_depth: float | None = None
    depth_progress_percent: float | None = None
    burn_efficiency_index: float | None = None
    upa_amount: float = 0.0
    upa_share_percent: float | None = None
    npt_days: float | None = None
    upa_days: float | None = None
    top_cost_driver: str = ""


class IntelligenceWellBreakdown(BaseModel):
    cost_groups: list[IntelligenceGroupBreakdown] = []
    sections: list[IntelligenceSectionBreakdown] = []
    activities: list[IntelligenceActivityBreakdown] = []
    unit_economics: IntelligenceUnitEconomics = IntelligenceUnitEconomics()


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
    breakdown: IntelligenceWellBreakdown | None = None
    notes: list[str] = []


class IntelligenceKpis(BaseModel):
    wells: int = 0
    analysed_wells: int = 0
    afe_amount: float | None = None
    actual_amount: float | None = None
    utilisation_percent: float | None = None
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


AiReviewScope = Literal["portfolio", "well"]
AiReviewFocus = Literal["full", "anomalies", "mistakes", "budget"]
AiFindingCategory = Literal["anomaly", "entry-mistake", "budget", "trend", "npt-upa", "data-quality"]


class IntelligenceAiReviewIn(BaseModel):
    """Opt-in request to engage the offline LAN Ollama model on Cost Intelligence."""

    scope: AiReviewScope = "portfolio"
    focus: AiReviewFocus = "full"
    date_from: date | None = None
    date_to: date | None = None
    rig_id: str = Field(default="", max_length=36)
    well_id: str = Field(default="", max_length=36)
    well_status: str = Field(default="", max_length=20)
    currency: str = Field(default="", max_length=10)
    include_draft: bool = True
    question: str = Field(default="", max_length=500)


class IntelligenceAiFinding(BaseModel):
    """One AI-synthesized anomaly, suspected entry mistake, or cost risk."""

    severity: Literal["critical", "warning", "info"] = "info"
    category: AiFindingCategory = "anomaly"
    well_id: str = ""
    well_code: str = ""
    reference: str = ""
    title: str
    detail: str
    recommendation: str = ""
    action_path: str = ""
    action_label: str = ""


class IntelligenceAiEntrySignal(BaseModel):
    """Verified daily-sheet entry check inspected during the AI review."""

    well_id: str
    well_code: str
    entry_id: str
    daily_cost_code: str
    cost_date: date
    severity: Literal["warning", "notice"]
    title: str
    message: str
    current_display: str = ""
    suggested_display: str = ""
    action_path: str


class IntelligenceAiReviewOut(BaseModel):
    """Automated cost analytic review generated on demand by Ollama."""

    generated_at: datetime
    as_of: date
    scope: AiReviewScope
    focus: AiReviewFocus
    well_id: str = ""
    well_code: str = ""
    currency: str = ""
    model: str
    endpoint: str
    duration_ms: int
    inspected_wells: int = 0
    statistical_findings_count: int = 0
    entry_signals_count: int = 0
    risk_posture: Literal["good", "watch", "at-risk"] = "good"
    executive_summary: str
    findings: list[IntelligenceAiFinding] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)
    entry_signals: list[IntelligenceAiEntrySignal] = Field(default_factory=list)

