"""Typed API contracts for Vendors and PO/SO Orders (Master Data Management)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.precision import Decimal3

MAX_RATE = Decimal("999999999999.999")

VendorType = Literal["Inhouse", "Third party"]
VendorStatus = Literal["active", "inactive", "blocked"]
OrderType = Literal["PO", "SO", "Callout", "Others"]
OrderStatus = Literal["open", "closed", "cancelled"]
LineChangeType = Literal["initial", "price_revision", "detail_amendment", "order_amendment_copy"]
DocumentKind = Literal[
    "po_copy", "signed_copy", "amendment_copy", "specification", "correspondence", "other"
]


def _trim(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class VendorCreate(BaseModel):
    vendor_type: VendorType = "Third party"
    vendor_code: str = Field(min_length=1, max_length=50)
    vendor_name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="", max_length=80)
    contact_person: str = Field(default="", max_length=150)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=60)
    website: str = Field(default="", max_length=255)
    country: str = Field(default="", max_length=100)
    tax_registration_no: str = Field(default="", max_length=60)
    address: str = Field(default="", max_length=500)
    status: VendorStatus = "active"
    credit_terms_days: int | None = Field(default=None, ge=0, le=365)
    description: str = Field(default="", max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "vendor_code", "vendor_name", "category", "contact_person", "email", "phone",
        "website", "country", "tax_registration_no", "address", "description",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class VendorUpdate(BaseModel):
    vendor_type: VendorType | None = None
    vendor_code: str | None = Field(default=None, min_length=1, max_length=50)
    vendor_name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    contact_person: str | None = Field(default=None, max_length=150)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=60)
    website: str | None = Field(default=None, max_length=255)
    country: str | None = Field(default=None, max_length=100)
    tax_registration_no: str | None = Field(default=None, max_length=60)
    address: str | None = Field(default=None, max_length=500)
    status: VendorStatus | None = None
    credit_terms_days: int | None = Field(default=None, ge=0, le=365)
    description: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "vendor_code", "vendor_name", "category", "contact_person", "email", "phone",
        "website", "country", "tax_registration_no", "address", "description",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class VendorOut(BaseModel):
    vendor_type: VendorType
    id: str
    vendor_code: str
    vendor_name: str
    category: str
    contact_person: str
    email: str
    phone: str
    website: str
    country: str
    tax_registration_no: str
    address: str
    status: VendorStatus
    credit_terms_days: int | None = None
    description: str
    order_count: int = 0
    document_count: int = 0
    latest_order_date: date | None = None
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class VendorOption(BaseModel):
    vendor_type: VendorType
    id: str
    vendor_code: str
    vendor_name: str
    status: VendorStatus
    order_count: int = 0
    label: str


class OrderCreate(BaseModel):
    order_number: str = Field(min_length=1, max_length=100)
    order_type: OrderType = "PO"
    vendor_id: str = Field(min_length=1, max_length=36)
    issue_date: date | None = None
    expiry_date: date | None = None
    status: OrderStatus = "open"
    description: str = Field(default="", max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("order_number", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OrderUpdate(BaseModel):
    order_number: str | None = Field(default=None, min_length=1, max_length=100)
    order_type: OrderType | None = None
    vendor_id: str | None = Field(default=None, min_length=1, max_length=36)
    issue_date: date | None = None
    expiry_date: date | None = None
    status: OrderStatus | None = None
    description: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("order_number", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OrderAmendmentCreate(BaseModel):
    """A new revision of an existing order. The server assigns the revision number."""

    revision_note: str = Field(min_length=1, max_length=500)
    order_type: OrderType | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    status: OrderStatus | None = None
    description: str | None = Field(default=None, max_length=500)
    copy_documents: bool = True
    copy_line_items: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("revision_note", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OrderOut(BaseModel):
    id: str
    order_number: str
    order_type: OrderType
    vendor_id: str
    vendor_code: str
    vendor_name: str
    vendor_status: VendorStatus
    revision_number: int
    is_current: bool
    revision_note: str
    parent_order_id: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    status: OrderStatus
    description: str
    document_count: int = 0
    line_item_count: int = 0
    revision_count: int = 1
    is_expired: bool = False
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OrderRevisionOut(BaseModel):
    id: str
    revision_number: int
    is_current: bool
    revision_note: str
    issue_date: date | None = None
    status: OrderStatus
    document_count: int = 0
    line_item_count: int = 0
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class OrderLineItemCreate(BaseModel):
    line_item_code: str = Field(min_length=1, max_length=80)
    vendor_code: str = Field(default="", max_length=80)
    description: str = Field(min_length=1, max_length=2000)
    unit_rate: Decimal3 = Field(ge=0, le=MAX_RATE)
    currency: str = Field(min_length=2, max_length=10)
    effective_date: date | None = None
    sort_order: int | None = Field(default=None, ge=1, le=100_000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("line_item_code", "vendor_code", "description", "currency", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OrderLineItemUpdate(BaseModel):
    """Non-price metadata correction on a PO/SO line item.

    Rate and currency revisions go through ``OrderLineItemAmend`` so every price
    movement keeps its previous value, effective date and reason.
    """

    line_item_code: str | None = Field(default=None, min_length=1, max_length=80)
    vendor_code: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    sort_order: int | None = Field(default=None, ge=1, le=100_000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("line_item_code", "vendor_code", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OrderLineItemAmend(BaseModel):
    """Audited amendment of a PO/SO line item's rate, currency or schedule details."""

    unit_rate: Decimal3 = Field(ge=0, le=MAX_RATE)
    currency: str = Field(min_length=2, max_length=10)
    vendor_code: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    effective_date: date | None = None
    reason: str = Field(min_length=3, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("currency", "vendor_code", "description", "reason", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class OrderLineItemOut(BaseModel):
    id: str
    order_id: str
    order_number: str
    order_type: OrderType
    order_revision_number: int
    order_is_current: bool
    order_vendor_id: str
    order_vendor_code: str
    order_vendor_name: str
    parent_line_item_id: str | None = None
    line_item_code: str
    vendor_code: str
    description: str
    unit_rate: Decimal
    currency: str
    effective_date: date | None = None
    current_revision_number: int
    added_in_order_revision: int
    sort_order: int
    is_deleted: bool
    deleted_at: datetime | None = None
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class OrderLineItemRevisionOut(BaseModel):
    id: str
    line_item_id: str
    revision_number: int
    change_type: LineChangeType
    unit_rate: Decimal
    previous_unit_rate: Decimal
    currency: str
    previous_currency: str
    vendor_code: str
    description: str
    previous_description: str
    effective_date: date
    reason: str
    recorded_by: str
    created_at: datetime


class OrderLineItemImportResponse(BaseModel):
    imported_count: int
    created_count: int = 0
    revised_count: int = 0
    unchanged_count: int = 0
    error_count: int
    errors: list[str]
    success: bool


class OrderLineItemBulkReviseRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=10_000)
    reason: str = Field(min_length=3, max_length=500)
    effective_date: date | None = None
    allow_new_items: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: Any) -> Any:
        return _trim(value)


class OrderLineItemBulkReviseResponse(BaseModel):
    revised_count: int
    added_count: int = 0
    unchanged_count: int
    skipped_count: int = 0
    error_count: int = 0
    effective_date: date | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentUpdate(BaseModel):
    document_kind: DocumentKind | None = None
    label: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("label", "notes", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return _trim(value)


class DocumentOut(BaseModel):
    id: str
    order_id: str
    order_number: str
    file_name: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    document_kind: DocumentKind
    label: str
    notes: str
    revision_number: int
    uploaded_by_name: str
    is_deleted: bool
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DocumentUploadItem(BaseModel):
    file_name: str
    order_number: str = ""
    revision_number: int | None = None
    document_id: str | None = None
    accepted: bool
    message: str


class DocumentUploadResult(BaseModel):
    uploaded_count: int
    rejected_count: int
    items: list[DocumentUploadItem]


class VendorPoCount(BaseModel):
    key: str
    label: str
    count: int


class VendorPoTopVendor(BaseModel):
    vendor_id: str
    vendor_code: str
    vendor_name: str
    order_count: int
    document_count: int


class VendorPoOverview(BaseModel):
    vendors_active: int
    vendors_inactive: int
    vendors_blocked: int
    vendors_deleted: int
    orders_active: int
    orders_amendments: int
    orders_deleted: int
    orders_by_type: list[VendorPoCount]
    orders_by_status: list[VendorPoCount]
    line_items_active: int = 0
    orders_with_line_items: int = 0
    documents_active: int
    documents_deleted: int
    storage_bytes: int
    top_vendors: list[VendorPoTopVendor]
