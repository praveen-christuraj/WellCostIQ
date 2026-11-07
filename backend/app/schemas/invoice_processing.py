"""Strict API contracts for Invoice Processing."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.precision import Decimal10, Decimal10Days

TaxDirection = Literal["addition", "deduction"]
BlockCategory = Literal["own", "jv"]
SignatureRole = Literal["prepared", "checked", "verified", "approved"]
WorkflowAction = Literal["submit", "send_to_accounts", "receive_epicor", "approve_epicor"]
ExportFormat = Literal["csv", "xlsx", "pdf"]
MAX_MONEY = Decimal("9999999999999999.9999999999")
MAX_DAYS = Decimal("100000")


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _upper(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvoiceIDs(_Strict):
    ids: list[str] = Field(min_length=1, max_length=500)


class InvoiceBulkActionOut(_Strict):
    affected_count: int


class InvoiceConfigItemIn(_Strict):
    name: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=500)
    is_active: bool = True

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim(cls, value: Any) -> Any:
        return _trim(value)


class InvoiceConfigImportRow(InvoiceConfigItemIn):
    designation: str = Field(default="", max_length=150)
    signatory_role: SignatureRole | None = None

    @field_validator("designation", mode="before")
    @classmethod
    def trim_designation(cls, value: Any) -> Any:
        return _trim(value)


class InvoiceConfigImport(_Strict):
    rows: list[InvoiceConfigImportRow] = Field(min_length=1, max_length=5000)


class InvoicePaymentTermSplitIn(_Strict):
    currency_code: str = Field(min_length=2, max_length=10)
    percentage: Decimal10 = Field(gt=0, le=100)

    @field_validator("currency_code", mode="before")
    @classmethod
    def upper(cls, value: Any) -> Any:
        return _upper(value)


class InvoicePaymentTermIn(_Strict):
    term_code: str = Field(min_length=1, max_length=50)
    term_name: str = Field(min_length=1, max_length=150)
    payment_days: int = Field(ge=0, le=3650)
    description: str = Field(default="", max_length=500)
    is_active: bool = True
    splits: list[InvoicePaymentTermSplitIn] = Field(default_factory=list, max_length=10)
    vendor_ids: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("term_code", mode="before")
    @classmethod
    def upper_code(cls, value: Any) -> Any:
        return _upper(value)

    @field_validator("term_name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @model_validator(mode="after")
    def percentages_are_complete(self):
        currencies = [item.currency_code for item in self.splits]
        if len(currencies) != len(set(currencies)):
            raise ValueError("A payment term cannot repeat a currency")
        if self.splits and sum((item.percentage for item in self.splits), Decimal("0")) != Decimal("100"):
            raise ValueError("Payment split percentages must total exactly 100%")
        return self


class InvoiceTaxConfigurationIn(_Strict):
    tax_code: str = Field(min_length=1, max_length=50)
    tax_name: str = Field(min_length=1, max_length=150)
    rate_percent: Decimal10 = Field(ge=0, le=100)
    direction: TaxDirection = "deduction"
    # Report and register switches. A tax that is not report-visible is stored on
    # the IDVS and in the register but never printed or added to the report total.
    is_report_visible: bool = True
    is_net_payable: bool = True
    is_common: bool = False
    description: str = Field(default="", max_length=500)
    is_active: bool = True
    vendor_ids: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("tax_code", mode="before")
    @classmethod
    def upper_code(cls, value: Any) -> Any:
        return _upper(value)

    @field_validator("tax_name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class InvoiceExchangeRateIn(_Strict):
    base_currency: str = Field(min_length=2, max_length=10)
    quote_currency: str = Field(min_length=2, max_length=10)
    rate: Decimal10 = Field(gt=0)
    description: str = Field(default="", max_length=500)
    is_active: bool = True

    @field_validator("base_currency", "quote_currency", mode="before")
    @classmethod
    def upper(cls, value: Any) -> Any:
        return _upper(value)

    @model_validator(mode="after")
    def currencies_differ(self):
        if self.base_currency == self.quote_currency:
            raise ValueError("Base and quote currencies must be different; same-currency conversion is always 1")
        return self


class InvoiceBlockSettingIn(_Strict):
    category: BlockCategory


class InvoiceSignatoryIn(_Strict):
    signatory_role: SignatureRole
    full_name: str = Field(min_length=1, max_length=150)
    designation: str = Field(default="", max_length=150)
    is_active: bool = True

    @field_validator("full_name", "designation", mode="before")
    @classmethod
    def trim(cls, value: Any) -> Any:
        return _trim(value)


class InvoiceSignatoryOut(_Strict):
    id: str
    signatory_role: SignatureRole
    full_name: str
    designation: str
    is_active: bool
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvoiceSignatoryOption(_Strict):
    id: str
    signatory_role: SignatureRole
    full_name: str
    designation: str
    label: str


class InvoiceConfigItemOut(_Strict):
    id: str
    name: str
    description: str
    is_active: bool
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvoicePaymentTermSplitOut(_Strict):
    currency_code: str
    percentage: Decimal


class InvoicePaymentTermOut(_Strict):
    id: str
    term_code: str
    term_name: str
    payment_days: int
    description: str
    is_active: bool
    splits: list[InvoicePaymentTermSplitOut]
    vendor_ids: list[str]
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvoiceTaxConfigurationOut(_Strict):
    id: str
    tax_code: str
    tax_name: str
    rate_percent: Decimal
    direction: TaxDirection
    is_report_visible: bool
    is_net_payable: bool
    is_common: bool
    description: str
    is_active: bool
    vendor_ids: list[str]
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvoiceExchangeRateOut(_Strict):
    id: str
    base_currency: str
    quote_currency: str
    rate: Decimal
    description: str
    is_active: bool
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvoiceBlockSettingOut(_Strict):
    block_id: str
    block_code: str
    block_name: str
    # Empty means the workspace has not classified this block yet.
    category: str


class InvoiceVendorOption(_Strict):
    id: str
    vendor_code: str
    vendor_name: str
    status: str
    credit_terms_days: int | None
    payment_term_id: str | None
    payment_term_name: str
    label: str


class InvoiceOrderOption(_Strict):
    id: str
    vendor_id: str
    order_number: str
    order_type: str
    status: str
    label: str


class InvoiceCurrencyOption(_Strict):
    currency_code: str
    currency_name: str
    currency_symbol: str
    is_default: bool


class InvoiceRigOption(_Strict):
    id: str
    rig_code: str
    rig_name: str
    label: str


class InvoiceBlockOption(_Strict):
    id: str
    block_code: str
    block_name: str
    # Empty means the workspace has not classified this block yet.
    category: str
    label: str


class InvoiceWellOption(_Strict):
    id: str
    rig_id: str
    block_id: str
    well_code: str
    well_name: str
    label: str


class InvoiceReference(_Strict):
    vendors: list[InvoiceVendorOption]
    orders: list[InvoiceOrderOption]
    currencies: list[InvoiceCurrencyOption]
    rigs: list[InvoiceRigOption]
    blocks: list[InvoiceBlockOption]
    wells: list[InvoiceWellOption]
    descriptions: list[InvoiceConfigItemOut] = Field(default_factory=list)
    locations: list[InvoiceConfigItemOut]
    categories: list[InvoiceConfigItemOut]
    payment_terms: list[InvoicePaymentTermOut]
    taxes: list[InvoiceTaxConfigurationOut]
    exchange_rates: list[InvoiceExchangeRateOut]
    signatories: list[InvoiceSignatoryOption]


class InvoiceConfiguration(_Strict):
    vendors: list[InvoiceVendorOption]
    currencies: list[InvoiceCurrencyOption]
    descriptions: list[InvoiceConfigItemOut] = Field(default_factory=list)
    locations: list[InvoiceConfigItemOut]
    categories: list[InvoiceConfigItemOut]
    payment_terms: list[InvoicePaymentTermOut]
    taxes: list[InvoiceTaxConfigurationOut]
    exchange_rates: list[InvoiceExchangeRateOut]
    blocks: list[InvoiceBlockSettingOut]
    signatories: list[InvoiceSignatoryOut]


class InvoiceLineIn(_Strict):
    description: str = Field(min_length=1, max_length=2000)
    invoice_quantity: Decimal10 = Field(gt=0, le=MAX_MONEY)
    # Days are used only when the IDVS enables the day count; otherwise they are stored as 1.
    invoice_days: Decimal10Days | None = Field(default=None, gt=0, le=MAX_DAYS)
    invoice_unit_price: Decimal10 = Field(ge=0, le=MAX_MONEY)
    verified_quantity: Decimal10 | None = Field(default=None, ge=0, le=MAX_MONEY)
    verified_days: Decimal10Days | None = Field(default=None, ge=0, le=MAX_DAYS)
    verified_unit_price: Decimal10 | None = Field(default=None, ge=0, le=MAX_MONEY)
    remarks: str = Field(default="", max_length=1000)

    @field_validator("description", "remarks", mode="before")
    @classmethod
    def trim(cls, value: Any) -> Any:
        return _trim(value)


class InvoiceSignatureIn(_Strict):
    role: SignatureRole
    signatory_id: str = Field(min_length=1, max_length=36)


class InvoiceTaxIn(_Strict):
    tax_configuration_id: str | None = None
    tax_name: str = Field(default="", max_length=150)
    rate_percent: Decimal10 | None = Field(default=None, ge=0, le=100)
    direction: TaxDirection | None = None
    # Omitted values follow the linked configuration; a manual tax defaults to both on.
    is_report_visible: bool | None = None
    is_net_payable: bool | None = None

    @field_validator("tax_name", mode="before")
    @classmethod
    def trim(cls, value: Any) -> Any:
        return _trim(value)


class InvoicePaymentSplitIn(_Strict):
    currency_code: str = Field(min_length=2, max_length=10)
    percentage: Decimal10 = Field(gt=0, le=100)
    exchange_rate: Decimal10 | None = Field(default=None, gt=0)

    @field_validator("currency_code", mode="before")
    @classmethod
    def upper(cls, value: Any) -> Any:
        return _upper(value)


class InvoiceSave(_Strict):
    block_category: Literal["own", "jv", ""] | None = None
    idvs_number: str = Field(default="", max_length=60)
    idvs_date: date
    expected_revision: int | None = Field(default=None, ge=0)
    invoice_number: str = Field(min_length=1, max_length=120)
    invoice_date: date
    invoice_received_date: date
    vendor_id: str = Field(min_length=1, max_length=36)
    order_id: str | None = None
    block_id: str | None = None
    rig_id: str | None = None
    well_id: str | None = None
    location_id: str = Field(min_length=1, max_length=36)
    field_name: str = Field(default="", max_length=150)
    phase: str = Field(default="", max_length=100)
    description_category_id: str | None = None
    service_description: str = Field(min_length=1, max_length=500)
    detailed_description: str = Field(default="", max_length=2000)
    concerned_person: str = Field(default="", max_length=150)
    service_from: date | None = None
    service_to: date | None = None
    currency_code: str = Field(min_length=2, max_length=10)
    payment_term_id: str | None = None
    payment_tenure_days: int | None = Field(default=None, ge=0, le=3650)
    disallowed_amount: Decimal10 = Field(default=Decimal("0"), ge=0, le=MAX_MONEY)
    advance_amount: Decimal10 = Field(default=Decimal("0"), ge=0, le=MAX_MONEY)
    remarks: str = Field(default="", max_length=1000)
    day_count_enabled: bool = False
    # Blank signing space printed between the sign-off roles and the names, in millimetres.
    # Omitted (e.g. by a spreadsheet refresh) keeps the stored value; new IDVS records start at 15 mm.
    signature_space_mm: int | None = Field(default=None, ge=0, le=60)
    lines: list[InvoiceLineIn] = Field(min_length=1, max_length=500)
    taxes: list[InvoiceTaxIn] | None = Field(default=None, max_length=50)
    payment_splits: list[InvoicePaymentSplitIn] | None = Field(default=None, max_length=10)
    # None keeps the stored sign-off selections (used by spreadsheet re-imports); a list replaces them.
    signatures: list[InvoiceSignatureIn] | None = Field(default=None, max_length=4)

    @field_validator(
        "idvs_number", "invoice_number", "field_name", "phase", "service_description",
        "detailed_description", "concerned_person", "remarks", mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("currency_code", mode="before")
    @classmethod
    def upper_currency(cls, value: Any) -> Any:
        return _upper(value)

    @model_validator(mode="after")
    def valid_period_and_splits(self):
        if self.service_from and self.service_to and self.service_to < self.service_from:
            raise ValueError("Service To must be on or after Service From")
        if self.payment_splits is not None:
            currencies = [item.currency_code for item in self.payment_splits]
            if len(currencies) != len(set(currencies)):
                raise ValueError("Payment splits cannot repeat a currency")
            if self.payment_splits and sum((item.percentage for item in self.payment_splits), Decimal("0")) != Decimal("100"):
                raise ValueError("Payment split percentages must total exactly 100%")
        if self.signatures is not None:
            roles = [item.role for item in self.signatures]
            if len(roles) != len(set(roles)):
                raise ValueError("Each sign-off role can be assigned only once")
        return self


class InvoiceWorkflowIn(_Strict):
    action: WorkflowAction
    action_date: date | None = None
    remarks: str = Field(default="", max_length=1000)

    @field_validator("remarks", mode="before")
    @classmethod
    def trim(cls, value: Any) -> Any:
        return _trim(value)


class InvoicePaymentIn(_Strict):
    paid_date: date | None = None
    payment_reference: str = Field(default="", max_length=150)
    remarks: str = Field(default="", max_length=1000)

    @field_validator("payment_reference", "remarks", mode="before")
    @classmethod
    def trim(cls, value: Any) -> Any:
        return _trim(value)


class InvoiceSignatureOut(_Strict):
    role: SignatureRole
    signatory_id: str | None
    name: str
    designation: str


class InvoiceLineOut(_Strict):
    id: str
    description: str
    invoice_quantity: Decimal
    invoice_days: Decimal
    invoice_unit_price: Decimal
    invoice_total: Decimal
    verified_quantity: Decimal
    verified_days: Decimal
    verified_unit_price: Decimal
    verified_total: Decimal
    difference_amount: Decimal
    remarks: str
    sort_order: int


class InvoiceTaxOut(_Strict):
    id: str
    tax_configuration_id: str | None
    tax_name: str
    rate_percent: Decimal
    direction: TaxDirection
    is_report_visible: bool
    is_net_payable: bool
    source: str
    invoice_amount: Decimal
    verified_amount: Decimal
    sort_order: int


class InvoicePaymentSplitOut(_Strict):
    id: str
    currency_code: str
    percentage: Decimal
    exchange_rate: Decimal
    amount: Decimal
    sort_order: int


class InvoiceAttachmentOut(_Strict):
    id: str
    invoice_id: str
    file_name: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    is_pdf: bool
    can_inline: bool
    label: str
    notes: str
    uploaded_by_name: str
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvoiceWorkflowHistoryOut(_Strict):
    id: str
    action: str
    status_after: str
    action_date: date
    remarks: str
    actor_name: str
    created_at: datetime


class InvoiceSummaryOut(_Strict):
    id: str
    idvs_number: str
    idvs_date: date
    revision: int
    invoice_number: str
    invoice_date: date
    invoice_received_date: date
    vendor_id: str
    vendor_code: str
    vendor_name: str
    order_id: str | None
    order_number: str
    order_type: str
    block_id: str | None
    block_code: str
    block_name: str
    block_category: str
    rig_id: str | None
    rig_code: str
    rig_name: str
    well_id: str | None
    well_code: str
    well_name: str
    location_id: str
    location_name: str
    field_name: str
    phase: str
    day_count_enabled: bool
    signature_space_mm: int
    description_category_id: str | None
    description_category: str
    service_description: str
    detailed_description: str
    concerned_person: str
    service_from: date | None
    service_to: date | None
    currency_code: str
    payment_term_id: str | None
    payment_term_name: str
    payment_tenure_days: int
    due_date: date
    disallowed_amount: Decimal
    advance_amount: Decimal
    invoice_subtotal: Decimal
    verified_subtotal: Decimal
    invoice_tax_total: Decimal
    verified_tax_total: Decimal
    invoice_total: Decimal
    verified_total: Decimal
    adjusted_verified_amount: Decimal
    net_payable_amount: Decimal
    difference_amount: Decimal
    status: str
    display_status: str
    is_overdue: bool
    submitted_date: date | None
    sent_to_accounts_date: date | None
    epicor_received_date: date | None
    epicor_approved_date: date | None
    paid_date: date | None
    payment_reference: str
    remarks: str
    line_count: int
    attachment_count: int
    payment_splits: list[InvoicePaymentSplitOut]
    is_deleted: bool
    deleted_at: datetime | None
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class InvoiceDetailOut(InvoiceSummaryOut):
    lines: list[InvoiceLineOut]
    signatures: list[InvoiceSignatureOut]
    taxes: list[InvoiceTaxOut]
    history: list[InvoiceWorkflowHistoryOut]
    attachments: list[InvoiceAttachmentOut]


class InvoiceImportRow(_Strict):
    block_category: Literal["own", "jv", ""] | None = None
    idvs_number: str = Field(default="", max_length=60)
    idvs_date: Any
    invoice_received_date: Any
    vendor_code: str = Field(min_length=1, max_length=50)
    order_number: str = Field(default="", max_length=100)
    invoice_number: str = Field(min_length=1, max_length=120)
    invoice_date: Any
    block_code: str = Field(default="", max_length=50)
    rig_code: str = Field(default="", max_length=50)
    well_code: str = Field(default="", max_length=50)
    location: str = Field(min_length=1, max_length=150)
    description_category: str = Field(default="", max_length=150)
    service_description: str = Field(min_length=1, max_length=500)
    detailed_description: str = Field(default="", max_length=2000)
    concerned_person: str = Field(default="", max_length=150)
    field_name: str = Field(default="", max_length=150)
    phase: str = Field(default="", max_length=100)
    service_from: Any = None
    service_to: Any = None
    currency_code: str = Field(min_length=2, max_length=10)
    payment_term_code: str = Field(default="", max_length=50)
    payment_tenure_days: Any = None
    disallowed_amount: Any = 0
    advance_amount: Any = 0
    description: str = Field(min_length=1, max_length=2000)
    invoice_quantity: Any
    invoice_days: Any = None
    invoice_unit_price: Any
    verified_quantity: Any = None
    verified_days: Any = None
    verified_unit_price: Any = None
    line_remarks: str = Field(default="", max_length=1000)
    remarks: str = Field(default="", max_length=1000)

    @field_validator(
        "idvs_number", "vendor_code", "order_number", "invoice_number", "block_code", "rig_code",
        "well_code", "location", "description_category", "service_description", "detailed_description",
        "concerned_person", "field_name", "phase", "payment_term_code", "description", "line_remarks",
        "remarks", mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)

    @field_validator("currency_code", mode="before")
    @classmethod
    def upper_currency(cls, value: Any) -> Any:
        return _upper(value)


class InvoiceImportRequest(_Strict):
    rows: list[InvoiceImportRow] = Field(min_length=1, max_length=5000)


class InvoiceImportOut(_Strict):
    imported_count: int
    invoice_count: int
    errors: list[str]
    success: bool


class InvoiceExportAudit(_Strict):
    module: Literal["register", "deleted", "dashboard", "configuration", "idvs"]
    format: ExportFormat
    record_count: int = Field(ge=0)
    detail: str = Field(default="", max_length=200)


class InvoiceCountByStatus(_Strict):
    status: str
    label: str
    count: int


class InvoiceCurrencyTotals(_Strict):
    currency_code: str
    invoice_count: int
    invoice_total: Decimal
    verified_total: Decimal
    adjusted_verified_amount: Decimal
    net_payable_amount: Decimal
    difference_amount: Decimal
    outstanding_count: int
    overdue_count: int


class InvoiceVendorDashboardRow(_Strict):
    vendor_id: str
    vendor_name: str
    currency_code: str
    invoice_count: int
    invoice_total: Decimal
    verified_total: Decimal
    difference_amount: Decimal
    approved_count: int
    discrepancy_count: int


class InvoiceBlockDashboardRow(_Strict):
    block_id: str
    block_code: str
    block_name: str
    block_category: str
    currency_code: str
    invoice_count: int
    invoice_total: Decimal
    verified_total: Decimal


class InvoiceAgeingRow(_Strict):
    bucket: str
    currency_code: str
    invoice_count: int
    adjusted_verified_amount: Decimal
    net_payable_amount: Decimal


class InvoiceRecentActivity(_Strict):
    id: str
    invoice_id: str
    idvs_number: str
    invoice_number: str
    vendor_name: str
    action: str
    action_label: str
    actor_name: str
    action_date: date
    remarks: str
    created_at: datetime


class InvoiceDashboard(_Strict):
    as_of: date
    total_invoices: int
    draft_count: int
    submitted_count: int
    sent_to_accounts_count: int
    verification_count: int
    epicor_pending_count: int
    epicor_count: int
    approved_count: int
    paid_count: int
    overdue_count: int
    discrepancy_count: int
    attachment_count: int
    own_block_count: int
    jv_block_count: int
    unclassified_block_count: int
    status_counts: list[InvoiceCountByStatus]
    currency_totals: list[InvoiceCurrencyTotals]
    vendor_rows: list[InvoiceVendorDashboardRow]
    block_rows: list[InvoiceBlockDashboardRow]
    ageing_rows: list[InvoiceAgeingRow]
    recent_activity: list[InvoiceRecentActivity]
