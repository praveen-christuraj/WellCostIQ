"""Tenant-scoped Vendors, PO/SO orders and the documents attached to them.

This is the commercial side of Master Data Management: vendors are added
first, every PO/SO order belongs to one vendor, and each order keeps its own
amendment chain plus the scanned copies the user attaches for later reference.
No prices or values are stored — the attached document *is* the record.

Everything follows the module conventions: column-wise tables (never a JSON
payload column), the shared ``MasterDataRecord`` lifecycle columns, per
workspace uniqueness, and soft deletion with restore/purge.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.precision import DECIMAL_PLACES
from app.models.master_data import MasterDataRecord, now, uid

VENDOR_STATUSES = ("active", "inactive", "blocked")
ORDER_TYPES = ("PO", "SO", "Callout", "Others")
ORDER_STATUSES = ("open", "closed", "cancelled")
DOCUMENT_KINDS = (
    "po_copy",
    "signed_copy",
    "amendment_copy",
    "specification",
    "correspondence",
    "other",
)
VENDOR_CATEGORIES = (
    "Drilling",
    "Completions",
    "Well Services",
    "Cementing",
    "Mud & Chemicals",
    "Casing & Tubulars",
    "Bits & Tools",
    "Logistics & Transport",
    "Equipment Rental",
    "Catering & Camps",
    "Inspection & Testing",
    "Engineering Services",
    "Other",
)


class Vendor(MasterDataRecord):
    """A supplier the workspace buys from. Parents every PO/SO order."""

    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("organization_id", "vendor_code", name="uq_vendors_org_code"),
        CheckConstraint("vendor_type IN ('Inhouse', 'Third party')", name="ck_vendors_type"),
    )

    vendor_code: Mapped[str] = mapped_column(String(50), nullable=False)
    vendor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="Third party", server_default="Third party")
    vendor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="", server_default="")
    contact_person: Mapped[str] = mapped_column(String(150), default="", server_default="")
    email: Mapped[str] = mapped_column(String(255), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(60), default="", server_default="")
    website: Mapped[str] = mapped_column(String(255), default="", server_default="")
    country: Mapped[str] = mapped_column(String(100), default="", server_default="")
    tax_registration_no: Mapped[str] = mapped_column(String(60), default="", server_default="")
    address: Mapped[str] = mapped_column(String(500), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    credit_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    orders: Mapped[list["PurchaseOrder"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )


class PurchaseOrder(MasterDataRecord):
    """One PO/SO issue: revision 0 is the original, later rows are amendments.

    ``parent_order_id`` keeps the lineage of an amendment chain, ``is_current``
    marks the revision a user should quote today, and the pair
    (order_number, revision_number) is unique per workspace.
    """

    __tablename__ = "po_so_orders"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "order_number",
            "revision_number",
            name="uq_po_so_orders_org_number_revision",
        ),
    )

    order_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    order_type: Mapped[str] = mapped_column(String(20), default="PO", server_default="PO", index=True)
    vendor_id: Mapped[str] = mapped_column(
        ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_order_id: Mapped[str | None] = mapped_column(
        ForeignKey("po_so_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    revision_note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open", index=True)

    vendor: Mapped[Vendor] = relationship(back_populates="orders", lazy="joined")
    documents: Mapped[list["OrderDocument"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    line_items: Mapped[list["PurchaseOrderLineItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLineItem.sort_order, PurchaseOrderLineItem.line_item_code",
    )


class OrderDocument(MasterDataRecord):
    """A file attached to a PO/SO revision, stored with its bytes in-database.

    The workspace database is the durable store (Render/Compose filesystems are
    ephemeral), so the payload lives in a deferred ``content`` column and the
    metadata stays in ordinary typed columns. ``description`` is the note the
    user writes about the file.
    """

    __tablename__ = "po_so_documents"

    order_id: Mapped[str] = mapped_column(
        ForeignKey("po_so_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(120), default="application/octet-stream", server_default="application/octet-stream"
    )
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), default="", server_default="")
    document_kind: Mapped[str] = mapped_column(String(30), default="po_copy", server_default="po_copy")
    label: Mapped[str] = mapped_column(String(200), default="", server_default="")
    revision_number: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    uploaded_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    uploaded_by_name: Mapped[str] = mapped_column(String(160), default="", server_default="")

    order: Mapped[PurchaseOrder] = relationship(back_populates="documents")


PO_LINE_CHANGE_TYPES = (
    "initial",
    "price_revision",
    "detail_amendment",
    "order_amendment_copy",
)


class PurchaseOrderLineItem(Base):
    """One priced schedule row under a PO/SO revision.

    ``vendor_code`` holds the optional vendor-side catalog, part or service code
    when the supplier provides one; ``description`` matches IDVS line capacity
    (2,000 chars) so extracting a PO line item into an IDVS never truncates.
    """

    __tablename__ = "po_so_line_items"
    __table_args__ = (
        UniqueConstraint("order_id", "line_item_code", name="uq_po_so_line_items_order_code"),
        CheckConstraint("unit_rate >= 0", name="ck_po_so_line_items_rate_non_negative"),
        CheckConstraint("current_revision_number >= 1", name="ck_po_so_line_items_rev_positive"),
        Index("ix_po_so_line_items_org_order", "organization_id", "order_id", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[str] = mapped_column(
        ForeignKey("po_so_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_line_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("po_so_line_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    line_item_code: Mapped[str] = mapped_column(String(80), nullable=False)
    vendor_code: Mapped[str] = mapped_column(String(80), default="", server_default="", nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    unit_rate: Mapped[Decimal] = mapped_column(
        Numeric(28, DECIMAL_PLACES), default=Decimal("0"), server_default="0", nullable=False
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_revision_number: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    added_in_order_revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )

    order: Mapped[PurchaseOrder] = relationship(back_populates="line_items")
    revisions: Mapped[list["PurchaseOrderLineItemRevision"]] = relationship(
        back_populates="line_item",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLineItemRevision.revision_number.desc()",
    )


class PurchaseOrderLineItemRevision(Base):
    """Append-only rate and detail amendment history for one PO/SO line item."""

    __tablename__ = "po_so_line_item_revisions"
    __table_args__ = (
        UniqueConstraint("line_item_id", "revision_number", name="uq_po_so_line_item_rev_number"),
        CheckConstraint(
            "unit_rate >= 0 AND previous_unit_rate >= 0",
            name="ck_po_so_line_item_rev_rates",
        ),
        CheckConstraint(
            "change_type IN ('initial', 'price_revision', 'detail_amendment', 'order_amendment_copy')",
            name="ck_po_so_line_item_rev_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_item_id: Mapped[str] = mapped_column(
        ForeignKey("po_so_line_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    change_type: Mapped[str] = mapped_column(
        String(24), default="initial", server_default="initial", nullable=False
    )
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=False)
    previous_unit_rate: Mapped[Decimal] = mapped_column(Numeric(28, DECIMAL_PLACES), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    previous_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    vendor_code: Mapped[str] = mapped_column(String(80), default="", server_default="", nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    previous_description: Mapped[str] = mapped_column(
        String(2000), default="", server_default="", nullable=False
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    line_item: Mapped[PurchaseOrderLineItem] = relationship(back_populates="revisions")
