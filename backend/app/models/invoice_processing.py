"""Column-wise Invoice Processing and IDVS persistence.

The module keeps the commercial source references, operational scope, invoice
and verified quantities/rates, tax and payment-term snapshots, workflow dates,
and supporting documents in ordinary typed columns. No JSON payloads are used.
Monetary values from different currencies are deliberately never combined in a
single database column without an explicit payment-currency conversion.
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
from app.models.rig_well import now, uid

INVOICE_STATUSES = ("draft", "submitted", "sent_to_accounts", "epicor_pending", "approved")
INVOICE_WORKFLOW_ACTIONS = ("submit", "send_to_accounts", "receive_epicor", "approve_epicor")
TAX_DIRECTIONS = ("addition", "deduction")
BLOCK_CATEGORIES = ("own", "jv")
# Sign-off roles printed on the IDVS, in printed order.
SIGNATURE_ROLES = ("prepared", "checked", "verified", "approved")


class InvoiceRecord(Base):
    """Common tenant, audit and soft-delete lifecycle for module records."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now, nullable=False
    )


class InvoiceLocation(InvoiceRecord):
    __tablename__ = "invoice_locations"
    __table_args__ = (
        UniqueConstraint("organization_id", "location_name", name="uq_invoice_locations_org_name"),
        Index("ix_invoice_locations_org_deleted", "organization_id", "is_deleted"),
    )

    location_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)


class InvoiceDescriptionCategory(InvoiceRecord):
    __tablename__ = "invoice_description_categories"
    __table_args__ = (
        UniqueConstraint("organization_id", "category_name", name="uq_invoice_description_categories_org_name"),
        Index("ix_invoice_description_categories_org_deleted", "organization_id", "is_deleted"),
    )

    category_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)


class InvoiceDescription(InvoiceRecord):
    __tablename__ = "invoice_descriptions"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_invoice_descriptions_org_name"),)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)


class InvoicePaymentTerm(InvoiceRecord):
    __tablename__ = "invoice_payment_terms"
    __table_args__ = (
        UniqueConstraint("organization_id", "term_code", name="uq_invoice_payment_terms_org_code"),
        CheckConstraint("payment_days >= 0", name="ck_invoice_payment_terms_days"),
        Index("ix_invoice_payment_terms_org_deleted", "organization_id", "is_deleted"),
    )

    term_code: Mapped[str] = mapped_column(String(50), nullable=False)
    term_name: Mapped[str] = mapped_column(String(150), nullable=False)
    payment_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    splits: Mapped[list["InvoicePaymentTermSplit"]] = relationship(
        back_populates="term", cascade="all, delete-orphan", order_by="InvoicePaymentTermSplit.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    vendor_links: Mapped[list["InvoiceVendorPaymentTerm"]] = relationship(
        back_populates="term", cascade="all, delete-orphan", lazy="selectin", passive_deletes=True,
    )


class InvoicePaymentTermSplit(Base):
    __tablename__ = "invoice_payment_term_splits"
    __table_args__ = (
        UniqueConstraint("term_id", "currency_code", name="uq_invoice_payment_term_splits_currency"),
        CheckConstraint("percentage > 0 AND percentage <= 100", name="ck_invoice_payment_term_splits_percentage"),
        Index("ix_invoice_payment_term_splits_org_term", "organization_id", "term_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    term_id: Mapped[str] = mapped_column(
        ForeignKey("invoice_payment_terms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False)
    percentage: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    term: Mapped[InvoicePaymentTerm] = relationship(back_populates="splits")


class InvoiceVendorPaymentTerm(Base):
    __tablename__ = "invoice_vendor_payment_terms"
    __table_args__ = (
        UniqueConstraint("organization_id", "vendor_id", name="uq_invoice_vendor_payment_terms_vendor"),
        Index("ix_invoice_vendor_payment_terms_org_term", "organization_id", "term_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    term_id: Mapped[str] = mapped_column(
        ForeignKey("invoice_payment_terms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    term: Mapped[InvoicePaymentTerm] = relationship(back_populates="vendor_links")


class InvoiceTaxConfiguration(InvoiceRecord):
    __tablename__ = "invoice_tax_configurations"
    __table_args__ = (
        UniqueConstraint("organization_id", "tax_code", name="uq_invoice_tax_configurations_org_code"),
        CheckConstraint("rate_percent >= 0 AND rate_percent <= 100", name="ck_invoice_tax_configurations_rate"),
        CheckConstraint("direction IN ('addition', 'deduction')", name="ck_invoice_tax_configurations_direction"),
        Index("ix_invoice_tax_configurations_org_deleted", "organization_id", "is_deleted"),
    )

    tax_code: Mapped[str] = mapped_column(String(50), nullable=False)
    tax_name: Mapped[str] = mapped_column(String(150), nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), default="deduction", server_default="deduction", nullable=False)
    # Printed on the IDVS report, so it moves the report's invoice/verified total.
    is_report_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    # Applied to the register's Net payable amount (IDVS amount less register-only taxes).
    is_net_payable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    is_common: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    vendor_links: Mapped[list["InvoiceVendorTax"]] = relationship(
        back_populates="tax", cascade="all, delete-orphan", lazy="selectin", passive_deletes=True,
    )


class InvoiceVendorTax(Base):
    __tablename__ = "invoice_vendor_taxes"
    __table_args__ = (
        UniqueConstraint("organization_id", "vendor_id", "tax_id", name="uq_invoice_vendor_taxes_pair"),
        Index("ix_invoice_vendor_taxes_org_tax", "organization_id", "tax_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    tax_id: Mapped[str] = mapped_column(
        ForeignKey("invoice_tax_configurations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    tax: Mapped[InvoiceTaxConfiguration] = relationship(back_populates="vendor_links")


class InvoiceExchangeRate(InvoiceRecord):
    """One current conversion: 1 base currency = rate quote currency."""

    __tablename__ = "invoice_exchange_rates"
    __table_args__ = (
        UniqueConstraint("organization_id", "base_currency", "quote_currency", name="uq_invoice_exchange_rates_pair"),
        CheckConstraint("rate > 0", name="ck_invoice_exchange_rates_rate"),
        CheckConstraint("base_currency <> quote_currency", name="ck_invoice_exchange_rates_distinct"),
        Index("ix_invoice_exchange_rates_org_deleted", "organization_id", "is_deleted"),
    )

    base_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)


class InvoiceBlockSetting(InvoiceRecord):
    __tablename__ = "invoice_block_settings"
    __table_args__ = (
        UniqueConstraint("organization_id", "block_id", name="uq_invoice_block_settings_block"),
        CheckConstraint("category IN ('own', 'jv')", name="ck_invoice_block_settings_category"),
    )

    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(10), default="own", server_default="own", nullable=False)


class InvoiceSignatory(InvoiceRecord):
    """A named person and designation offered for one IDVS sign-off role."""

    __tablename__ = "invoice_signatories"
    __table_args__ = (
        UniqueConstraint("organization_id", "signatory_role", "full_name", name="uq_invoice_signatories_org_role_name"),
        CheckConstraint(
            "signatory_role IN ('prepared', 'checked', 'verified', 'approved')",
            name="ck_invoice_signatories_role",
        ),
        Index("ix_invoice_signatories_org_deleted", "organization_id", "is_deleted"),
    )

    signatory_role: Mapped[str] = mapped_column(String(20), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    designation: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)


class InvoiceSignature(Base):
    """Snapshot of the name and designation chosen for one sign-off role on an IDVS."""

    __tablename__ = "invoice_idvs_signatures"
    __table_args__ = (
        UniqueConstraint("invoice_id", "signature_role", name="uq_invoice_idvs_signatures_role"),
        CheckConstraint(
            "signature_role IN ('prepared', 'checked', 'verified', 'approved')",
            name="ck_invoice_idvs_signatures_role",
        ),
        Index("ix_invoice_idvs_signatures_invoice_order", "invoice_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoice_idvs.id", ondelete="CASCADE"), nullable=False)
    signature_role: Mapped[str] = mapped_column(String(20), nullable=False)
    signatory_id: Mapped[str | None] = mapped_column(
        ForeignKey("invoice_signatories.id", ondelete="SET NULL"), nullable=True
    )
    signatory_name: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    designation: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    invoice: Mapped["Invoice"] = relationship(back_populates="signatures")


class Invoice(InvoiceRecord):
    __tablename__ = "invoice_idvs"
    __table_args__ = (
        UniqueConstraint("organization_id", "idvs_number", name="uq_invoice_idvs_org_number"),
        UniqueConstraint("organization_id", "vendor_id", "invoice_number", name="uq_invoice_idvs_org_vendor_invoice"),
        CheckConstraint("payment_tenure_days >= 0", name="ck_invoice_idvs_tenure"),
        CheckConstraint(
            "signature_space_mm >= 0 AND signature_space_mm <= 60", name="ck_invoice_idvs_signature_space"
        ),
        CheckConstraint("disallowed_amount >= 0", name="ck_invoice_idvs_disallowed"),
        CheckConstraint("advance_amount >= 0", name="ck_invoice_idvs_advance"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'sent_to_accounts', 'epicor_pending', 'approved')",
            name="ck_invoice_idvs_status",
        ),
        Index("ix_invoice_idvs_org_status_date", "organization_id", "is_deleted", "status", "invoice_date"),
        Index("ix_invoice_idvs_org_vendor", "organization_id", "vendor_id"),
        Index("ix_invoice_idvs_org_scope", "organization_id", "block_id", "rig_id", "well_id"),
        Index("ix_invoice_idvs_org_due", "organization_id", "is_deleted", "due_date"),
    )

    idvs_number: Mapped[str] = mapped_column(String(60), nullable=False)
    idvs_date: Mapped[date] = mapped_column(Date, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    invoice_number: Mapped[str] = mapped_column(String(120), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    invoice_received_date: Mapped[date] = mapped_column(Date, nullable=False)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False)
    vendor_code_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    vendor_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("po_so_orders.id", ondelete="RESTRICT"), nullable=True)
    order_number_snapshot: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False)
    order_type_snapshot: Mapped[str] = mapped_column(String(20), default="", server_default="", nullable=False)

    block_id: Mapped[str | None] = mapped_column(ForeignKey("blocks.id", ondelete="RESTRICT"), nullable=True)
    block_code_snapshot: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    block_name_snapshot: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    block_category: Mapped[str] = mapped_column(String(10), default="", server_default="", nullable=False)
    rig_id: Mapped[str | None] = mapped_column(ForeignKey("rigs.id", ondelete="RESTRICT"), nullable=True)
    rig_code_snapshot: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    rig_name_snapshot: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    well_id: Mapped[str | None] = mapped_column(ForeignKey("wells.id", ondelete="RESTRICT"), nullable=True)
    well_code_snapshot: Mapped[str] = mapped_column(String(50), default="", server_default="", nullable=False)
    well_name_snapshot: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)

    location_id: Mapped[str] = mapped_column(ForeignKey("invoice_locations.id", ondelete="RESTRICT"), nullable=False)
    location_name_snapshot: Mapped[str] = mapped_column(String(150), nullable=False)
    field_name: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    phase: Mapped[str] = mapped_column(String(100), default="", server_default="", nullable=False)
    # Services and rental tools bill per day; the column is shown only when this is true.
    day_count_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # Blank signing space printed between the sign-off role row and the name row.
    signature_space_mm: Mapped[int] = mapped_column(Integer, default=15, server_default="15", nullable=False)
    description_category_id: Mapped[str | None] = mapped_column(
        ForeignKey("invoice_description_categories.id", ondelete="RESTRICT"), nullable=True
    )
    description_category_snapshot: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    service_description: Mapped[str] = mapped_column(String(500), nullable=False)
    detailed_description: Mapped[str] = mapped_column(String(2000), default="", server_default="", nullable=False)
    concerned_person: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    service_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    service_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    currency_code: Mapped[str] = mapped_column(String(10), nullable=False)
    payment_term_id: Mapped[str | None] = mapped_column(
        ForeignKey("invoice_payment_terms.id", ondelete="RESTRICT"), nullable=True
    )
    payment_term_name_snapshot: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    payment_tenure_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    disallowed_amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    advance_amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    invoice_subtotal: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    verified_subtotal: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    invoice_tax_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    verified_tax_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    invoice_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    verified_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    adjusted_verified_amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    # Register-only amount: the verified total with every net-payable tax applied,
    # including taxes the IDVS report deliberately leaves out. Payment splits keep
    # using ``adjusted_verified_amount`` (the IDVS report amount).
    net_payable_amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    difference_amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)

    status: Mapped[str] = mapped_column(String(30), default="draft", server_default="draft", nullable=False)
    submitted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sent_to_accounts_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    epicor_received_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    epicor_approved_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_reference: Mapped[str] = mapped_column(String(150), default="", server_default="", nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)

    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    taxes: Mapped[list["InvoiceTax"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceTax.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    payment_splits: Mapped[list["InvoicePaymentSplit"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoicePaymentSplit.sort_order",
        lazy="selectin", passive_deletes=True,
    )
    history: Mapped[list["InvoiceWorkflowHistory"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceWorkflowHistory.created_at",
        lazy="selectin", passive_deletes=True,
    )
    attachments: Mapped[list["InvoiceAttachment"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin", passive_deletes=True,
    )
    signatures: Mapped[list["InvoiceSignature"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceSignature.sort_order",
        lazy="selectin", passive_deletes=True,
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_idvs_lines"
    __table_args__ = (
        CheckConstraint("LENGTH(TRIM(description)) > 0", name="ck_invoice_idvs_lines_description"),
        CheckConstraint("invoice_quantity > 0", name="ck_invoice_idvs_lines_invoice_quantity"),
        CheckConstraint("invoice_days > 0", name="ck_invoice_idvs_lines_invoice_days"),
        CheckConstraint("invoice_unit_price >= 0", name="ck_invoice_idvs_lines_invoice_price"),
        CheckConstraint("verified_quantity >= 0", name="ck_invoice_idvs_lines_verified_quantity"),
        CheckConstraint("verified_days >= 0", name="ck_invoice_idvs_lines_verified_days"),
        CheckConstraint("verified_unit_price >= 0", name="ck_invoice_idvs_lines_verified_price"),
        Index("ix_invoice_idvs_lines_invoice_order", "invoice_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoice_idvs.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    invoice_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    invoice_days: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("1"), server_default="1", nullable=False)
    invoice_unit_price: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    invoice_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    verified_quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    verified_days: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("1"), server_default="1", nullable=False)
    verified_unit_price: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    verified_total: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    difference_amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class InvoiceTax(Base):
    __tablename__ = "invoice_idvs_taxes"
    __table_args__ = (
        CheckConstraint("rate_percent >= 0 AND rate_percent <= 100", name="ck_invoice_idvs_taxes_rate"),
        CheckConstraint("direction IN ('addition', 'deduction')", name="ck_invoice_idvs_taxes_direction"),
        Index("ix_invoice_idvs_taxes_invoice_order", "invoice_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoice_idvs.id", ondelete="CASCADE"), nullable=False)
    tax_configuration_id: Mapped[str | None] = mapped_column(
        ForeignKey("invoice_tax_configurations.id", ondelete="SET NULL"), nullable=True
    )
    tax_name: Mapped[str] = mapped_column(String(150), nullable=False)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    # Snapshots of the configuration switches taken when the IDVS line was saved.
    is_report_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    is_net_payable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual", nullable=False)
    invoice_amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    verified_amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="taxes")


class InvoicePaymentSplit(Base):
    __tablename__ = "invoice_idvs_payment_splits"
    __table_args__ = (
        UniqueConstraint("invoice_id", "currency_code", name="uq_invoice_idvs_payment_splits_currency"),
        CheckConstraint("percentage > 0 AND percentage <= 100", name="ck_invoice_idvs_payment_splits_percentage"),
        CheckConstraint("exchange_rate > 0", name="ck_invoice_idvs_payment_splits_rate"),
        Index("ix_invoice_idvs_payment_splits_invoice_order", "invoice_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoice_idvs.id", ondelete="CASCADE"), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False)
    percentage: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(28, 10), default=Decimal("0"), server_default="0", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="payment_splits")


class InvoiceWorkflowHistory(Base):
    __tablename__ = "invoice_workflow_history"
    __table_args__ = (
        CheckConstraint(
            "action IN ('submit', 'send_to_accounts', 'receive_epicor', 'approve_epicor', 'payment')",
            name="ck_invoice_workflow_history_action",
        ),
        Index("ix_invoice_workflow_history_invoice_date", "invoice_id", "action_date"),
        Index("ix_invoice_workflow_history_org_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoice_idvs.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    status_after: Mapped[str] = mapped_column(String(30), nullable=False)
    action_date: Mapped[date] = mapped_column(Date, nullable=False)
    remarks: Mapped[str] = mapped_column(String(1000), default="", server_default="", nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="history")


class InvoiceAttachment(InvoiceRecord):
    __tablename__ = "invoice_attachments"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0 AND size_bytes <= 26214400", name="ck_invoice_attachments_size"),
        Index("ix_invoice_attachments_invoice_deleted", "invoice_id", "is_deleted"),
    )

    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoice_idvs.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream", server_default="application/octet-stream", nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(200), default="", server_default="", nullable=False)
    notes: Mapped[str] = mapped_column(String(500), default="", server_default="", nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    uploaded_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    uploaded_by_name: Mapped[str] = mapped_column(String(160), default="", server_default="", nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="attachments")
