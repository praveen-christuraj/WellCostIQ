"""Tenant-scoped Invoice Processing, IDVS, configuration and document custody."""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.invoice_processing import calculate_idvs, money, payment_due_date
from app.models import (
    AuditLog,
    Block,
    Currency,
    PurchaseOrder,
    Rig,
    User,
    Vendor,
    Well,
)
from app.models.invoice_processing import (
    SIGNATURE_ROLES,
    Invoice,
    InvoiceAttachment,
    InvoiceBlockSetting,
    InvoiceDescriptionCategory,
    InvoiceExchangeRate,
    InvoiceLine,
    InvoiceLocation,
    InvoicePaymentSplit,
    InvoicePaymentTerm,
    InvoicePaymentTermSplit,
    InvoiceSignatory,
    InvoiceSignature,
    InvoiceTax,
    InvoiceTaxConfiguration,
    InvoiceVendorPaymentTerm,
    InvoiceVendorTax,
    InvoiceWorkflowHistory,
)
from app.schemas.invoice_processing import (
    InvoiceAgeingRow,
    InvoiceAttachmentOut,
    InvoiceBlockDashboardRow,
    InvoiceBlockOption,
    InvoiceBlockSettingIn,
    InvoiceBlockSettingOut,
    InvoiceBulkActionOut,
    InvoiceConfigItemIn,
    InvoiceConfigItemOut,
    InvoiceConfiguration,
    InvoiceCountByStatus,
    InvoiceCurrencyOption,
    InvoiceCurrencyTotals,
    InvoiceDashboard,
    InvoiceDetailOut,
    InvoiceExchangeRateIn,
    InvoiceExchangeRateOut,
    InvoiceExportAudit,
    InvoiceImportOut,
    InvoiceImportRequest,
    InvoiceImportRow,
    InvoiceLineIn,
    InvoiceLineOut,
    InvoiceOrderOption,
    InvoicePaymentIn,
    InvoicePaymentSplitIn,
    InvoicePaymentSplitOut,
    InvoicePaymentTermIn,
    InvoicePaymentTermOut,
    InvoicePaymentTermSplitOut,
    InvoiceRecentActivity,
    InvoiceReference,
    InvoiceRigOption,
    InvoiceSave,
    InvoiceSignatoryIn,
    InvoiceSignatoryOption,
    InvoiceSignatoryOut,
    InvoiceSignatureIn,
    InvoiceSignatureOut,
    InvoiceSummaryOut,
    InvoiceTaxConfigurationIn,
    InvoiceTaxConfigurationOut,
    InvoiceTaxIn,
    InvoiceTaxOut,
    InvoiceVendorDashboardRow,
    InvoiceVendorOption,
    InvoiceWellOption,
    InvoiceWorkflowHistoryOut,
    InvoiceWorkflowIn,
)
from app.services import audit
from app.services.dependencies import assert_no_dependencies

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
ALLOWED_ATTACHMENT_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".rtf",
    ".png", ".jpg", ".jpeg", ".msg", ".eml",
)
STATUS_LABELS = {
    "draft": "Draft",
    "submitted": "Submitted for verification",
    "sent_to_accounts": "Verified & sent to Accounts",
    "epicor_pending": "Received for EPICOR approval",
    "approved": "Approved in EPICOR",
    "paid": "Paid",
}
WORKFLOW = {
    "submit": ("draft", "submitted", "submitted_date"),
    "send_to_accounts": ("submitted", "sent_to_accounts", "sent_to_accounts_date"),
    "receive_epicor": ("sent_to_accounts", "epicor_pending", "epicor_received_date"),
    "approve_epicor": ("epicor_pending", "approved", "epicor_approved_date"),
}
SIGNATURE_LABELS = {
    "prepared": "Prepared by",
    "checked": "Checked by",
    "verified": "Verified by",
    "approved": "Approved by",
}
DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y",
    "%Y/%m/%d", "%d-%b-%Y", "%d-%B-%Y", "%b %d, %Y", "%B %d, %Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M",
)


def _actor(user: User) -> str:
    return user.full_name or user.email


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _commit(db: Session, message: str = "The invoice change conflicts with an existing workspace record") -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        logger.warning("Invoice Processing integrity conflict: %s", error.orig)
        raise HTTPException(409, message) from error
    except SQLAlchemyError as error:
        db.rollback()
        logger.exception("Invoice Processing database failure")
        raise HTTPException(503, "Invoice Processing could not save the change because of a database error") from error


def _clean_text(value: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value or "").strip()


def _active(db: Session, model: Any, record_id: str, organization_id: str, label: str) -> Any:
    row = db.scalar(
        select(model).where(
            model.id == record_id,
            model.organization_id == organization_id,
            model.is_deleted.is_(False),
        )
    )
    if row is None:
        raise HTTPException(422, f"The selected {label} is not available in this workspace")
    return row


def _config_item_out(row: InvoiceLocation | InvoiceDescriptionCategory) -> InvoiceConfigItemOut:
    return InvoiceConfigItemOut(
        id=row.id,
        name=row.location_name if isinstance(row, InvoiceLocation) else row.category_name,
        description=row.description,
        is_active=row.is_active,
        is_deleted=row.is_deleted,
        deleted_at=row.deleted_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _term_out(row: InvoicePaymentTerm) -> InvoicePaymentTermOut:
    return InvoicePaymentTermOut(
        id=row.id, term_code=row.term_code, term_name=row.term_name, payment_days=row.payment_days,
        description=row.description, is_active=row.is_active,
        splits=[InvoicePaymentTermSplitOut(currency_code=s.currency_code, percentage=s.percentage) for s in row.splits],
        vendor_ids=[link.vendor_id for link in row.vendor_links], is_deleted=row.is_deleted,
        deleted_at=row.deleted_at, created_at=row.created_at, updated_at=row.updated_at,
    )


def _tax_config_out(row: InvoiceTaxConfiguration) -> InvoiceTaxConfigurationOut:
    return InvoiceTaxConfigurationOut(
        id=row.id, tax_code=row.tax_code, tax_name=row.tax_name, rate_percent=row.rate_percent,
        direction=row.direction, is_common=row.is_common, description=row.description,
        is_active=row.is_active, vendor_ids=[link.vendor_id for link in row.vendor_links],
        is_deleted=row.is_deleted, deleted_at=row.deleted_at, created_at=row.created_at, updated_at=row.updated_at,
    )


def _exchange_out(row: InvoiceExchangeRate) -> InvoiceExchangeRateOut:
    return InvoiceExchangeRateOut(
        id=row.id, base_currency=row.base_currency, quote_currency=row.quote_currency, rate=row.rate,
        description=row.description, is_active=row.is_active, is_deleted=row.is_deleted,
        deleted_at=row.deleted_at, created_at=row.created_at, updated_at=row.updated_at,
    )


def _block_category_map(db: Session, organization_id: str) -> dict[str, str]:
    rows = db.scalars(
        select(InvoiceBlockSetting).where(
            InvoiceBlockSetting.organization_id == organization_id,
            InvoiceBlockSetting.is_deleted.is_(False),
        )
    ).all()
    return {row.block_id: row.category for row in rows}


def _sorted_signatories(rows: Iterable[InvoiceSignatory]) -> list[InvoiceSignatory]:
    return sorted(rows, key=lambda row: (SIGNATURE_ROLES.index(row.signatory_role), row.full_name.lower()))


def _signatory_out(row: InvoiceSignatory) -> InvoiceSignatoryOut:
    return InvoiceSignatoryOut(
        id=row.id, signatory_role=row.signatory_role, full_name=row.full_name, designation=row.designation,
        is_active=row.is_active, is_deleted=row.is_deleted, deleted_at=row.deleted_at,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def _signatory_option(row: InvoiceSignatory) -> InvoiceSignatoryOption:
    return InvoiceSignatoryOption(
        id=row.id, signatory_role=row.signatory_role, full_name=row.full_name, designation=row.designation,
        label=f"{row.full_name} — {row.designation}" if row.designation else row.full_name,
    )


def reference_data(db: Session, organization_id: str) -> InvoiceReference:
    vendors = db.scalars(
        select(Vendor).where(Vendor.organization_id == organization_id, Vendor.is_deleted.is_(False))
        .order_by(Vendor.vendor_name)
    ).all()
    orders = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
            PurchaseOrder.is_current.is_(True),
        ).order_by(PurchaseOrder.order_number)
    ).all()
    currencies = db.scalars(
        select(Currency).where(Currency.organization_id == organization_id, Currency.is_deleted.is_(False))
        .order_by(Currency.is_default.desc(), Currency.currency_code)
    ).all()
    rigs = db.scalars(
        select(Rig).where(Rig.organization_id == organization_id, Rig.is_deleted.is_(False)).order_by(Rig.rig_code)
    ).all()
    blocks = db.scalars(
        select(Block).where(Block.organization_id == organization_id, Block.is_deleted.is_(False)).order_by(Block.block_code)
    ).all()
    wells = db.scalars(
        select(Well).where(Well.organization_id == organization_id, Well.is_deleted.is_(False)).order_by(Well.well_code)
    ).all()
    categories = _block_category_map(db, organization_id)
    locations = db.scalars(
        select(InvoiceLocation).where(
            InvoiceLocation.organization_id == organization_id,
            InvoiceLocation.is_deleted.is_(False), InvoiceLocation.is_active.is_(True),
        ).order_by(InvoiceLocation.location_name)
    ).all()
    description_categories = db.scalars(
        select(InvoiceDescriptionCategory).where(
            InvoiceDescriptionCategory.organization_id == organization_id,
            InvoiceDescriptionCategory.is_deleted.is_(False), InvoiceDescriptionCategory.is_active.is_(True),
        ).order_by(InvoiceDescriptionCategory.category_name)
    ).all()
    terms = db.scalars(
        select(InvoicePaymentTerm).where(
            InvoicePaymentTerm.organization_id == organization_id,
            InvoicePaymentTerm.is_deleted.is_(False), InvoicePaymentTerm.is_active.is_(True),
        ).order_by(InvoicePaymentTerm.term_code)
    ).all()
    taxes = db.scalars(
        select(InvoiceTaxConfiguration).where(
            InvoiceTaxConfiguration.organization_id == organization_id,
            InvoiceTaxConfiguration.is_deleted.is_(False), InvoiceTaxConfiguration.is_active.is_(True),
        ).order_by(InvoiceTaxConfiguration.tax_code)
    ).all()
    exchange_rates = db.scalars(
        select(InvoiceExchangeRate).where(
            InvoiceExchangeRate.organization_id == organization_id,
            InvoiceExchangeRate.is_deleted.is_(False), InvoiceExchangeRate.is_active.is_(True),
        ).order_by(InvoiceExchangeRate.base_currency, InvoiceExchangeRate.quote_currency)
    ).all()
    signatories = db.scalars(
        select(InvoiceSignatory).where(
            InvoiceSignatory.organization_id == organization_id,
            InvoiceSignatory.is_deleted.is_(False), InvoiceSignatory.is_active.is_(True),
        )
    ).all()
    term_by_id = {term.id: term for term in terms}
    vendor_term = {
        link.vendor_id: link.term_id
        for term in terms
        for link in term.vendor_links
    }
    return InvoiceReference(
        vendors=[InvoiceVendorOption(
            id=v.id, vendor_code=v.vendor_code, vendor_name=v.vendor_name, status=v.status,
            credit_terms_days=v.credit_terms_days,
            payment_term_id=vendor_term.get(v.id),
            payment_term_name=term_by_id[vendor_term[v.id]].term_name if v.id in vendor_term else "",
            label=f"{v.vendor_code} — {v.vendor_name}",
        ) for v in vendors],
        orders=[InvoiceOrderOption(
            id=o.id, vendor_id=o.vendor_id, order_number=o.order_number, order_type=o.order_type,
            status=o.status, label=f"{o.order_type} · {o.order_number}",
        ) for o in orders],
        currencies=[InvoiceCurrencyOption(
            currency_code=c.currency_code, currency_name=c.currency_name,
            currency_symbol=c.currency_symbol, is_default=c.is_default,
        ) for c in currencies],
        rigs=[InvoiceRigOption(id=r.id, rig_code=r.rig_code, rig_name=r.rig_name, label=f"{r.rig_code} — {r.rig_name}") for r in rigs],
        blocks=[InvoiceBlockOption(
            id=b.id, block_code=b.block_code, block_name=b.block_name, category=categories.get(b.id, ""),
            label=f"{b.block_code} — {b.block_name}",
        ) for b in blocks],
        wells=[InvoiceWellOption(
            id=w.id, rig_id=w.rig_id, block_id=w.block_id, well_code=w.well_code,
            well_name=w.well_name, label=f"{w.well_code} — {w.well_name}",
        ) for w in wells],
        locations=[_config_item_out(row) for row in locations],
        categories=[_config_item_out(row) for row in description_categories],
        payment_terms=[_term_out(row) for row in terms],
        taxes=[_tax_config_out(row) for row in taxes],
        exchange_rates=[_exchange_out(row) for row in exchange_rates],
        signatories=[_signatory_option(row) for row in _sorted_signatories(signatories)],
    )


def configuration_data(db: Session, organization_id: str) -> InvoiceConfiguration:
    locations = db.scalars(select(InvoiceLocation).where(InvoiceLocation.organization_id == organization_id).order_by(InvoiceLocation.location_name)).all()
    categories = db.scalars(select(InvoiceDescriptionCategory).where(InvoiceDescriptionCategory.organization_id == organization_id).order_by(InvoiceDescriptionCategory.category_name)).all()
    terms = db.scalars(select(InvoicePaymentTerm).where(InvoicePaymentTerm.organization_id == organization_id).order_by(InvoicePaymentTerm.term_code)).all()
    taxes = db.scalars(select(InvoiceTaxConfiguration).where(InvoiceTaxConfiguration.organization_id == organization_id).order_by(InvoiceTaxConfiguration.tax_code)).all()
    rates = db.scalars(select(InvoiceExchangeRate).where(InvoiceExchangeRate.organization_id == organization_id).order_by(InvoiceExchangeRate.base_currency, InvoiceExchangeRate.quote_currency)).all()
    blocks = db.scalars(select(Block).where(Block.organization_id == organization_id, Block.is_deleted.is_(False)).order_by(Block.block_code)).all()
    vendors = db.scalars(select(Vendor).where(Vendor.organization_id == organization_id, Vendor.is_deleted.is_(False)).order_by(Vendor.vendor_code)).all()
    currencies = db.scalars(select(Currency).where(Currency.organization_id == organization_id, Currency.is_deleted.is_(False)).order_by(Currency.currency_code)).all()
    signatories = db.scalars(select(InvoiceSignatory).where(InvoiceSignatory.organization_id == organization_id)).all()
    categories_by_block = _block_category_map(db, organization_id)
    term_by_id = {term.id: term for term in terms}
    vendor_term = {link.vendor_id: link.term_id for term in terms for link in term.vendor_links}
    return InvoiceConfiguration(
        signatories=[_signatory_out(row) for row in _sorted_signatories(signatories)],
        vendors=[InvoiceVendorOption(
            id=v.id, vendor_code=v.vendor_code, vendor_name=v.vendor_name, status=v.status,
            credit_terms_days=v.credit_terms_days, payment_term_id=vendor_term.get(v.id),
            payment_term_name=term_by_id[vendor_term[v.id]].term_name if v.id in vendor_term else "",
            label=f"{v.vendor_code} — {v.vendor_name}",
        ) for v in vendors],
        currencies=[InvoiceCurrencyOption(
            currency_code=c.currency_code, currency_name=c.currency_name,
            currency_symbol=c.currency_symbol, is_default=c.is_default,
        ) for c in currencies],
        locations=[_config_item_out(row) for row in locations],
        categories=[_config_item_out(row) for row in categories],
        payment_terms=[_term_out(row) for row in terms],
        taxes=[_tax_config_out(row) for row in taxes],
        exchange_rates=[_exchange_out(row) for row in rates],
        blocks=[InvoiceBlockSettingOut(
            block_id=block.id, block_code=block.block_code, block_name=block.block_name,
            category=categories_by_block.get(block.id, ""),
        ) for block in blocks],
    )


# ---------------------------------------------------------------------------
# Configuration maintenance
# ---------------------------------------------------------------------------

CONFIG_MODELS = {"locations": InvoiceLocation, "categories": InvoiceDescriptionCategory}


def _unique_name(
    db: Session, model: Any, organization_id: str, field: str, value: str, exclude_id: str = "",
) -> None:
    column = getattr(model, field)
    query = select(model.id).where(
        model.organization_id == organization_id, func.lower(column) == value.strip().lower()
    )
    if exclude_id:
        query = query.where(model.id != exclude_id)
    if db.scalar(query):
        raise HTTPException(409, f"{value} already exists in this workspace")


def save_config_item(
    db: Session, organization_id: str, kind: str, data: InvoiceConfigItemIn,
    user: User, request: Request | None, record_id: str = "",
) -> InvoiceConfigItemOut:
    model = CONFIG_MODELS.get(kind)
    if model is None:
        raise HTTPException(404, "Unknown invoice configuration type")
    field = "location_name" if model is InvoiceLocation else "category_name"
    row = db.scalar(select(model).where(model.id == record_id, model.organization_id == organization_id)) if record_id else None
    if record_id and row is None:
        raise HTTPException(404, "Invoice configuration record not found")
    _unique_name(db, model, organization_id, field, data.name, record_id)
    if row is None:
        row = model(organization_id=organization_id, created_by=_actor(user), updated_by=_actor(user))
        db.add(row)
    setattr(row, field, data.name)
    row.description = data.description
    row.is_active = data.is_active
    row.is_deleted = False
    row.deleted_at = None
    row.updated_by = _actor(user)
    db.flush()
    audit.record(
        db, organization_id=organization_id, actor=user, action="update" if record_id else "create",
        entity_type="invoice_configuration", entity_id=row.id, entity_label=data.name,
        summary=f"{'Updated' if record_id else 'Created'} invoice {kind[:-1]} {data.name}", request=request,
    )
    _commit(db)
    return _config_item_out(row)


def save_signatory(
    db: Session, organization_id: str, data: InvoiceSignatoryIn,
    user: User, request: Request | None, record_id: str = "",
) -> InvoiceSignatoryOut:
    row = db.scalar(select(InvoiceSignatory).where(
        InvoiceSignatory.id == record_id, InvoiceSignatory.organization_id == organization_id,
    )) if record_id else None
    if record_id and row is None:
        raise HTTPException(404, "Sign-off signatory not found")
    label = SIGNATURE_LABELS[data.signatory_role]
    duplicate = db.scalar(select(InvoiceSignatory.id).where(
        InvoiceSignatory.organization_id == organization_id,
        InvoiceSignatory.signatory_role == data.signatory_role,
        func.lower(InvoiceSignatory.full_name) == data.full_name.lower(),
        *([InvoiceSignatory.id != record_id] if record_id else []),
    ))
    if duplicate:
        raise HTTPException(409, f"{data.full_name} is already listed under {label}")
    if row is None:
        row = InvoiceSignatory(organization_id=organization_id, created_by=_actor(user), updated_by=_actor(user))
        db.add(row)
    row.signatory_role = data.signatory_role
    row.full_name = data.full_name
    row.designation = data.designation
    row.is_active = data.is_active
    row.is_deleted = False
    row.deleted_at = None
    row.updated_by = _actor(user)
    db.flush()
    audit.record(
        db, organization_id=organization_id, actor=user, action="update" if record_id else "create",
        entity_type="invoice_signatory", entity_id=row.id, entity_label=data.full_name,
        summary=f"{'Updated' if record_id else 'Created'} {label} signatory {data.full_name}"
        f"{f' ({data.designation})' if data.designation else ''}", request=request,
    )
    _commit(db)
    return _signatory_out(row)


def _validate_vendors(db: Session, organization_id: str, vendor_ids: Iterable[str]) -> list[str]:
    ids = list(dict.fromkeys(vendor_ids))
    if not ids:
        return []
    found = set(db.scalars(
        select(Vendor.id).where(
            Vendor.organization_id == organization_id, Vendor.id.in_(ids), Vendor.is_deleted.is_(False)
        )
    ).all())
    if found != set(ids):
        raise HTTPException(422, "One or more selected vendors are not available in this workspace")
    return ids


def save_payment_term(
    db: Session, organization_id: str, data: InvoicePaymentTermIn,
    user: User, request: Request | None, record_id: str = "",
) -> InvoicePaymentTermOut:
    row = db.scalar(select(InvoicePaymentTerm).where(
        InvoicePaymentTerm.id == record_id, InvoicePaymentTerm.organization_id == organization_id
    )) if record_id else None
    if record_id and row is None:
        raise HTTPException(404, "Payment term not found")
    _unique_name(db, InvoicePaymentTerm, organization_id, "term_code", data.term_code, record_id)
    vendor_ids = _validate_vendors(db, organization_id, data.vendor_ids)
    if row is None:
        row = InvoicePaymentTerm(organization_id=organization_id, created_by=_actor(user), updated_by=_actor(user))
        db.add(row)
    row.term_code = data.term_code
    row.term_name = data.term_name
    row.payment_days = data.payment_days
    row.description = data.description
    row.is_active = data.is_active
    row.is_deleted = False
    row.deleted_at = None
    row.updated_by = _actor(user)
    if record_id:
        row.splits.clear()
        row.vendor_links.clear()
    # Persist parent/scalar changes and removals before inserting rows with the
    # same unique currency or vendor keys. This also assigns a new parent's ID.
    db.flush()
    row.splits = [InvoicePaymentTermSplit(
        organization_id=organization_id, currency_code=item.currency_code,
        percentage=item.percentage, sort_order=index,
    ) for index, item in enumerate(data.splits)]
    # One current term per vendor; this is the bulk assignment surface.
    existing_links = db.scalars(select(InvoiceVendorPaymentTerm).where(
        InvoiceVendorPaymentTerm.organization_id == organization_id,
        InvoiceVendorPaymentTerm.vendor_id.in_(vendor_ids),
    )).all() if vendor_ids else []
    for link in existing_links:
        if link.term_id != row.id:
            db.delete(link)
    db.flush()
    row.vendor_links = [InvoiceVendorPaymentTerm(organization_id=organization_id, vendor_id=vendor_id) for vendor_id in vendor_ids]
    db.flush()
    audit.record(
        db, organization_id=organization_id, actor=user, action="update" if record_id else "create",
        entity_type="invoice_payment_term", entity_id=row.id, entity_label=row.term_name,
        summary=f"Saved {row.term_code}: {row.payment_days} days, {len(row.splits)} split(s), {len(vendor_ids)} vendor(s)",
        request=request,
    )
    _commit(db)
    return _term_out(row)


def save_tax_configuration(
    db: Session, organization_id: str, data: InvoiceTaxConfigurationIn,
    user: User, request: Request | None, record_id: str = "",
) -> InvoiceTaxConfigurationOut:
    row = db.scalar(select(InvoiceTaxConfiguration).where(
        InvoiceTaxConfiguration.id == record_id, InvoiceTaxConfiguration.organization_id == organization_id
    )) if record_id else None
    if record_id and row is None:
        raise HTTPException(404, "Tax configuration not found")
    _unique_name(db, InvoiceTaxConfiguration, organization_id, "tax_code", data.tax_code, record_id)
    vendor_ids = _validate_vendors(db, organization_id, data.vendor_ids)
    if row is None:
        row = InvoiceTaxConfiguration(organization_id=organization_id, created_by=_actor(user), updated_by=_actor(user))
        db.add(row)
    for field in ("tax_code", "tax_name", "rate_percent", "direction", "is_common", "description", "is_active"):
        setattr(row, field, getattr(data, field))
    row.is_deleted = False
    row.deleted_at = None
    row.updated_by = _actor(user)
    if record_id:
        row.vendor_links.clear()
        db.flush()
    row.vendor_links = [InvoiceVendorTax(organization_id=organization_id, vendor_id=vendor_id) for vendor_id in vendor_ids]
    db.flush()
    audit.record(
        db, organization_id=organization_id, actor=user, action="update" if record_id else "create",
        entity_type="invoice_tax_configuration", entity_id=row.id, entity_label=row.tax_name,
        summary=f"Saved {row.tax_code} at {row.rate_percent}% ({row.direction}); common={row.is_common}; {len(vendor_ids)} vendor(s)",
        request=request,
    )
    _commit(db)
    return _tax_config_out(row)


def save_exchange_rate(
    db: Session, organization_id: str, data: InvoiceExchangeRateIn,
    user: User, request: Request | None, record_id: str = "",
) -> InvoiceExchangeRateOut:
    row = db.scalar(select(InvoiceExchangeRate).where(
        InvoiceExchangeRate.id == record_id, InvoiceExchangeRate.organization_id == organization_id
    )) if record_id else None
    if record_id and row is None:
        raise HTTPException(404, "Exchange rate not found")
    for code in (data.base_currency, data.quote_currency):
        if not db.scalar(select(Currency.id).where(
            Currency.organization_id == organization_id, Currency.currency_code == code, Currency.is_deleted.is_(False)
        )):
            raise HTTPException(422, f"Currency {code} is not available in Master Data")
    query = select(InvoiceExchangeRate).where(
        InvoiceExchangeRate.organization_id == organization_id,
        InvoiceExchangeRate.base_currency == data.base_currency,
        InvoiceExchangeRate.quote_currency == data.quote_currency,
    )
    if record_id:
        query = query.where(InvoiceExchangeRate.id != record_id)
    if db.scalar(query):
        raise HTTPException(409, f"An exchange rate for {data.base_currency} → {data.quote_currency} already exists")
    if row is None:
        row = InvoiceExchangeRate(organization_id=organization_id, created_by=_actor(user), updated_by=_actor(user))
        db.add(row)
    row.base_currency = data.base_currency
    row.quote_currency = data.quote_currency
    row.rate = data.rate
    row.description = data.description
    row.is_active = data.is_active
    row.is_deleted = False
    row.deleted_at = None
    row.updated_by = _actor(user)
    db.flush()
    audit.record(
        db, organization_id=organization_id, actor=user, action="update" if record_id else "create",
        entity_type="invoice_exchange_rate", entity_id=row.id,
        entity_label=f"{row.base_currency} → {row.quote_currency}",
        summary=f"1 {row.base_currency} = {row.rate} {row.quote_currency}", request=request,
    )
    _commit(db)
    return _exchange_out(row)


def set_block_category(
    db: Session, organization_id: str, block_id: str, data: InvoiceBlockSettingIn,
    user: User, request: Request | None,
) -> InvoiceBlockSettingOut:
    block = _active(db, Block, block_id, organization_id, "block")
    row = db.scalar(select(InvoiceBlockSetting).where(
        InvoiceBlockSetting.organization_id == organization_id, InvoiceBlockSetting.block_id == block_id
    ))
    if row is None:
        row = InvoiceBlockSetting(
            organization_id=organization_id, block_id=block_id,
            created_by=_actor(user), updated_by=_actor(user),
        )
        db.add(row)
    row.category = data.category
    row.is_deleted = False
    row.deleted_at = None
    row.updated_by = _actor(user)
    db.flush()
    audit.record(
        db, organization_id=organization_id, actor=user, action="configure", entity_type="invoice_block_setting",
        entity_id=row.id, entity_label=block.block_name,
        summary=f"Classified {block.block_code} as {'Own Block' if data.category == 'own' else 'JV Block'}", request=request,
    )
    _commit(db)
    return InvoiceBlockSettingOut(
        block_id=block.id, block_code=block.block_code, block_name=block.block_name, category=row.category,
    )


def bulk_configuration(
    db: Session, organization_id: str, kind: str, ids: list[str], action: str,
    user: User, request: Request | None,
) -> InvoiceBulkActionOut:
    models = {
        **CONFIG_MODELS,
        "payment-terms": InvoicePaymentTerm,
        "taxes": InvoiceTaxConfiguration,
        "exchange-rates": InvoiceExchangeRate,
        "signatories": InvoiceSignatory,
    }
    model = models.get(kind)
    if model is None:
        raise HTTPException(404, "Unknown invoice configuration type")
    rows = db.scalars(select(model).where(model.organization_id == organization_id, model.id.in_(ids))).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more invoice configuration records were not found")
    affected = 0
    timestamp = datetime.now(timezone.utc)
    for row in rows:
        label = (
            getattr(row, "name", "") or getattr(row, "term_name", "") or getattr(row, "tax_name", "")
            or getattr(row, "full_name", "") or f"{getattr(row, 'base_currency', '')} → {getattr(row, 'quote_currency', '')}"
        )
        if action == "delete" and not row.is_deleted:
            row.is_deleted, row.deleted_at = True, timestamp
            row.updated_by = _actor(user)
            affected += 1
        elif action == "restore" and row.is_deleted:
            row.is_deleted, row.deleted_at = False, None
            row.updated_by = _actor(user)
            affected += 1
        elif action == "permanent-delete":
            if not row.is_deleted:
                raise HTTPException(409, "Only deleted configuration records can be permanently removed")
            assert_no_dependencies(db, row, organization_id, entity_label=label)
            db.delete(row)
            affected += 1
    audit.record(
        db, organization_id=organization_id, actor=user, action=action, entity_type="invoice_configuration",
        entity_label=kind, summary=f"{action.replace('-', ' ').title()}: {affected} {kind} record(s)", request=request,
    )
    _commit(db)
    return InvoiceBulkActionOut(affected_count=affected)


# ---------------------------------------------------------------------------
# IDVS entry and calculation
# ---------------------------------------------------------------------------

def _split_out(row: InvoicePaymentSplit) -> InvoicePaymentSplitOut:
    return InvoicePaymentSplitOut(
        id=row.id, currency_code=row.currency_code, percentage=row.percentage,
        exchange_rate=row.exchange_rate, amount=row.amount, sort_order=row.sort_order,
    )


def _attachment_out(row: InvoiceAttachment) -> InvoiceAttachmentOut:
    return InvoiceAttachmentOut(
        id=row.id, invoice_id=row.invoice_id, file_name=row.file_name, content_type=row.content_type,
        size_bytes=row.size_bytes, checksum_sha256=row.checksum_sha256,
        is_pdf=row.content_type.lower() == "application/pdf",
        can_inline=row.content_type.lower() == "application/pdf",
        label=row.label, notes=row.notes,
        uploaded_by_name=row.uploaded_by_name, is_deleted=row.is_deleted, deleted_at=row.deleted_at,
        created_at=row.created_at, updated_at=row.updated_at,
    )


def _summary_out(row: Invoice) -> InvoiceSummaryOut:
    display_status = "paid" if row.paid_date else row.status
    return InvoiceSummaryOut(
        id=row.id, idvs_number=row.idvs_number, idvs_date=row.idvs_date, revision=row.revision,
        invoice_number=row.invoice_number, invoice_date=row.invoice_date,
        invoice_received_date=row.invoice_received_date, vendor_id=row.vendor_id,
        vendor_code=row.vendor_code_snapshot, vendor_name=row.vendor_name_snapshot,
        order_id=row.order_id, order_number=row.order_number_snapshot, order_type=row.order_type_snapshot,
        block_id=row.block_id, block_code=row.block_code_snapshot, block_name=row.block_name_snapshot,
        block_category=row.block_category, rig_id=row.rig_id, rig_code=row.rig_code_snapshot,
        rig_name=row.rig_name_snapshot, well_id=row.well_id, well_code=row.well_code_snapshot,
        well_name=row.well_name_snapshot, location_id=row.location_id,
        location_name=row.location_name_snapshot, field_name=row.field_name, phase=row.phase,
        day_count_enabled=row.day_count_enabled,
        description_category_id=row.description_category_id,
        description_category=row.description_category_snapshot, service_description=row.service_description,
        detailed_description=row.detailed_description, concerned_person=row.concerned_person,
        service_from=row.service_from, service_to=row.service_to, currency_code=row.currency_code,
        payment_term_id=row.payment_term_id, payment_term_name=row.payment_term_name_snapshot,
        payment_tenure_days=row.payment_tenure_days, due_date=row.due_date,
        disallowed_amount=row.disallowed_amount, advance_amount=row.advance_amount,
        invoice_subtotal=row.invoice_subtotal, verified_subtotal=row.verified_subtotal,
        invoice_tax_total=row.invoice_tax_total, verified_tax_total=row.verified_tax_total,
        invoice_total=row.invoice_total, verified_total=row.verified_total,
        adjusted_verified_amount=row.adjusted_verified_amount, difference_amount=row.difference_amount,
        status=row.status, display_status=display_status,
        is_overdue=not row.paid_date and row.due_date < _today(),
        submitted_date=row.submitted_date, sent_to_accounts_date=row.sent_to_accounts_date,
        epicor_received_date=row.epicor_received_date, epicor_approved_date=row.epicor_approved_date,
        paid_date=row.paid_date, payment_reference=row.payment_reference, remarks=row.remarks,
        line_count=len(row.lines), attachment_count=sum(not item.is_deleted for item in row.attachments),
        payment_splits=[_split_out(item) for item in row.payment_splits],
        is_deleted=row.is_deleted, deleted_at=row.deleted_at, created_by=row.created_by,
        updated_by=row.updated_by, created_at=row.created_at, updated_at=row.updated_at,
    )


def _detail_out(row: Invoice) -> InvoiceDetailOut:
    values = _summary_out(row).model_dump()
    return InvoiceDetailOut(
        **values,
        lines=[InvoiceLineOut(
            id=line.id, description=line.description, invoice_quantity=line.invoice_quantity,
            invoice_days=line.invoice_days, invoice_unit_price=line.invoice_unit_price, invoice_total=line.invoice_total,
            verified_quantity=line.verified_quantity, verified_days=line.verified_days,
            verified_unit_price=line.verified_unit_price,
            verified_total=line.verified_total, difference_amount=line.difference_amount,
            remarks=line.remarks, sort_order=line.sort_order,
        ) for line in row.lines],
        signatures=[InvoiceSignatureOut(
            role=item.signature_role, signatory_id=item.signatory_id, name=item.signatory_name,
            designation=item.designation,
        ) for item in row.signatures],
        taxes=[InvoiceTaxOut(
            id=tax.id, tax_configuration_id=tax.tax_configuration_id, tax_name=tax.tax_name,
            rate_percent=tax.rate_percent, direction=tax.direction, source=tax.source,
            invoice_amount=tax.invoice_amount, verified_amount=tax.verified_amount, sort_order=tax.sort_order,
        ) for tax in row.taxes],
        history=[InvoiceWorkflowHistoryOut(
            id=item.id, action=item.action, status_after=item.status_after, action_date=item.action_date,
            remarks=item.remarks, actor_name=item.actor_name, created_at=item.created_at,
        ) for item in row.history],
        attachments=[_attachment_out(item) for item in row.attachments],
    )


def _next_number(db: Session, organization_id: str, idvs_date: date) -> str:
    prefix = f"IDVS-{idvs_date.year}-"
    count = db.scalar(
        select(func.count(Invoice.id)).where(
            Invoice.organization_id == organization_id, Invoice.idvs_number.like(f"{prefix}%")
        )
    ) or 0
    candidate = count + 1
    while db.scalar(select(Invoice.id).where(
        Invoice.organization_id == organization_id, Invoice.idvs_number == f"{prefix}{candidate:05d}"
    )):
        candidate += 1
    return f"{prefix}{candidate:05d}"


def _exchange_rate(db: Session, organization_id: str, base: str, quote: str, supplied: Decimal | None) -> Decimal:
    if base == quote:
        return Decimal("1")
    if supplied is not None:
        return supplied
    direct = db.scalar(select(InvoiceExchangeRate).where(
        InvoiceExchangeRate.organization_id == organization_id,
        InvoiceExchangeRate.base_currency == base, InvoiceExchangeRate.quote_currency == quote,
        InvoiceExchangeRate.is_deleted.is_(False), InvoiceExchangeRate.is_active.is_(True),
    ))
    if direct:
        return direct.rate
    inverse = db.scalar(select(InvoiceExchangeRate).where(
        InvoiceExchangeRate.organization_id == organization_id,
        InvoiceExchangeRate.base_currency == quote, InvoiceExchangeRate.quote_currency == base,
        InvoiceExchangeRate.is_deleted.is_(False), InvoiceExchangeRate.is_active.is_(True),
    ))
    if inverse:
        return money(Decimal("1") / inverse.rate)
    raise HTTPException(
        422,
        f"Configure an exchange rate for {base} → {quote}, or enter the rate on this payment split before saving",
    )


def _auto_taxes(db: Session, organization_id: str, vendor_id: str) -> list[tuple[InvoiceTaxConfiguration, str]]:
    rows = db.scalars(select(InvoiceTaxConfiguration).where(
        InvoiceTaxConfiguration.organization_id == organization_id,
        InvoiceTaxConfiguration.is_deleted.is_(False), InvoiceTaxConfiguration.is_active.is_(True),
    ).order_by(InvoiceTaxConfiguration.tax_code)).all()
    result = []
    for tax in rows:
        vendor_match = any(link.vendor_id == vendor_id for link in tax.vendor_links)
        if tax.is_common or vendor_match:
            result.append((tax, "common" if tax.is_common else "vendor"))
    return result


def _line_days(item: InvoiceLineIn, day_count_enabled: bool) -> tuple[Decimal, Decimal]:
    """Return ``(invoice_days, verified_days)``; both are 1 when the IDVS day count is off."""
    if not day_count_enabled:
        return Decimal("1"), Decimal("1")
    invoice_days = item.invoice_days if item.invoice_days is not None else Decimal("1")
    verified_days = invoice_days if item.verified_days is None else item.verified_days
    return invoice_days, verified_days


def _signature_rows(db: Session, organization_id: str, items: list[InvoiceSignatureIn]) -> list[InvoiceSignature]:
    """Snapshot the selected active signatories onto the IDVS, one row per sign-off role."""
    rows: list[InvoiceSignature] = []
    for item in items:
        label = SIGNATURE_LABELS[item.role]
        signatory = db.scalar(select(InvoiceSignatory).where(
            InvoiceSignatory.id == item.signatory_id,
            InvoiceSignatory.organization_id == organization_id,
            InvoiceSignatory.is_deleted.is_(False), InvoiceSignatory.is_active.is_(True),
        ))
        if signatory is None:
            raise HTTPException(422, f"The selected {label} signatory is not available in this workspace")
        if signatory.signatory_role != item.role:
            raise HTTPException(422, f"The selected signatory is not configured for {label}")
        rows.append(InvoiceSignature(
            organization_id=organization_id, signature_role=item.role, signatory_id=signatory.id,
            signatory_name=signatory.full_name, designation=signatory.designation,
            sort_order=SIGNATURE_ROLES.index(item.role),
        ))
    return rows


def _write_invoice(
    db: Session, organization_id: str, data: InvoiceSave, user: User,
    request: Request | None, row: Invoice | None = None,
) -> Invoice:
    creating = row is None
    if row is not None:
        if row.status != "draft":
            raise HTTPException(409, "Only a Draft IDVS can be edited. Tracking milestones have their own dated actions")
        if data.expected_revision is not None and data.expected_revision != row.revision:
            raise HTTPException(409, "This IDVS changed in another session. Reload it before saving your edits")
    vendor = _active(db, Vendor, data.vendor_id, organization_id, "vendor")
    order = None
    if data.order_id:
        order = _active(db, PurchaseOrder, data.order_id, organization_id, "PO/SO order")
        if order.vendor_id != vendor.id:
            raise HTTPException(422, "The selected PO/SO order does not belong to the selected vendor")
    well = _active(db, Well, data.well_id, organization_id, "well") if data.well_id else None
    rig = _active(db, Rig, data.rig_id, organization_id, "rig") if data.rig_id else None
    block = _active(db, Block, data.block_id, organization_id, "block") if data.block_id else None
    if well:
        if rig and well.rig_id != rig.id:
            raise HTTPException(422, "The selected well does not belong to the selected rig")
        if block and well.block_id != block.id:
            raise HTTPException(422, "The selected well does not belong to the selected block")
        rig = well.rig
        block = well.block_record
    location = _active(db, InvoiceLocation, data.location_id, organization_id, "invoice location")
    if not location.is_active:
        raise HTTPException(422, "The selected invoice location is inactive")
    category = None
    if data.description_category_id:
        category = _active(db, InvoiceDescriptionCategory, data.description_category_id, organization_id, "description category")
        if not category.is_active:
            raise HTTPException(422, "The selected description category is inactive")
    if not db.scalar(select(Currency.id).where(
        Currency.organization_id == organization_id, Currency.currency_code == data.currency_code,
        Currency.is_deleted.is_(False),
    )):
        raise HTTPException(422, "The selected invoice currency is not available in Master Data")
    term = None
    if data.payment_term_id:
        term = _active(db, InvoicePaymentTerm, data.payment_term_id, organization_id, "payment term")
        if not term.is_active:
            raise HTTPException(422, "The selected payment term is inactive")
    tenure = data.payment_tenure_days
    if tenure is None:
        tenure = term.payment_days if term else (vendor.credit_terms_days or 0)

    duplicate_query = select(Invoice.id).where(
        Invoice.organization_id == organization_id, Invoice.vendor_id == vendor.id,
        func.lower(Invoice.invoice_number) == data.invoice_number.lower(),
    )
    if row is not None:
        duplicate_query = duplicate_query.where(Invoice.id != row.id)
    if db.scalar(duplicate_query):
        raise HTTPException(409, f"Invoice {data.invoice_number} is already registered for {vendor.vendor_name}")

    block_category = ""
    if block:
        setting = db.scalar(select(InvoiceBlockSetting).where(
            InvoiceBlockSetting.organization_id == organization_id,
            InvoiceBlockSetting.block_id == block.id, InvoiceBlockSetting.is_deleted.is_(False),
        ))
        block_category = setting.category if setting else ""

    if creating:
        row = Invoice(
            organization_id=organization_id, idvs_number=data.idvs_number.upper() or _next_number(db, organization_id, data.idvs_date),
            created_by=_actor(user), updated_by=_actor(user),
        )
        db.add(row)
    elif data.idvs_number and data.idvs_number.upper() != row.idvs_number:
        raise HTTPException(422, "The IDVS number cannot be changed after creation")

    scalar_values = {
        "idvs_date": data.idvs_date, "invoice_number": data.invoice_number,
        "invoice_date": data.invoice_date, "invoice_received_date": data.invoice_received_date,
        "vendor_id": vendor.id, "vendor_code_snapshot": vendor.vendor_code,
        "vendor_name_snapshot": vendor.vendor_name,
        "order_id": order.id if order else None,
        "order_number_snapshot": order.order_number if order else "",
        "order_type_snapshot": order.order_type if order else "",
        "block_id": block.id if block else None,
        "block_code_snapshot": block.block_code if block else "",
        "block_name_snapshot": block.block_name if block else "",
        "block_category": block_category,
        "rig_id": rig.id if rig else None, "rig_code_snapshot": rig.rig_code if rig else "",
        "rig_name_snapshot": rig.rig_name if rig else "",
        "well_id": well.id if well else None, "well_code_snapshot": well.well_code if well else "",
        "well_name_snapshot": well.well_name if well else "",
        "location_id": location.id, "location_name_snapshot": location.location_name,
        "field_name": data.field_name, "phase": data.phase,
        "description_category_id": category.id if category else None,
        "description_category_snapshot": category.category_name if category else "",
        "service_description": data.service_description, "detailed_description": data.detailed_description,
        "concerned_person": data.concerned_person, "service_from": data.service_from, "service_to": data.service_to,
        "currency_code": data.currency_code, "payment_term_id": term.id if term else None,
        "payment_term_name_snapshot": term.term_name if term else "",
        "payment_tenure_days": tenure, "due_date": payment_due_date(data.invoice_date, tenure),
        "disallowed_amount": data.disallowed_amount, "advance_amount": data.advance_amount,
        "remarks": data.remarks, "day_count_enabled": data.day_count_enabled, "updated_by": _actor(user),
    }
    for field, value in scalar_values.items():
        setattr(row, field, value)

    if not creating:
        row.lines.clear()
        row.taxes.clear()
        row.payment_splits.clear()
        if data.signatures is not None:
            row.signatures.clear()
        # Unique payment currencies must be deleted before their replacements
        # are inserted. History and attachments are deliberately not replaced.
        db.flush()

    new_lines: list[InvoiceLine] = []
    for index, item in enumerate(data.lines):
        invoice_days, verified_days = _line_days(item, data.day_count_enabled)
        new_lines.append(InvoiceLine(
            organization_id=organization_id, description=item.description,
            invoice_quantity=item.invoice_quantity, invoice_days=invoice_days,
            invoice_unit_price=item.invoice_unit_price,
            verified_quantity=item.invoice_quantity if item.verified_quantity is None else item.verified_quantity,
            verified_days=verified_days,
            verified_unit_price=item.invoice_unit_price if item.verified_unit_price is None else item.verified_unit_price,
            remarks=item.remarks, sort_order=index,
        ))
    row.lines = new_lines

    tax_inputs = data.taxes
    auto_sources: dict[str, str] = {}
    if tax_inputs is None:
        auto = _auto_taxes(db, organization_id, vendor.id)
        auto_sources = {tax.id: source for tax, source in auto}
        tax_inputs = [InvoiceTaxIn(tax_configuration_id=tax.id) for tax, _source in auto]
    new_taxes: list[InvoiceTax] = []
    for index, item in enumerate(tax_inputs):
        config = None
        if item.tax_configuration_id:
            config = _active(db, InvoiceTaxConfiguration, item.tax_configuration_id, organization_id, "tax configuration")
        name = item.tax_name or (config.tax_name if config else "")
        rate = item.rate_percent if item.rate_percent is not None else (config.rate_percent if config else None)
        direction = item.direction or (config.direction if config else None)
        if not name or rate is None or direction is None:
            raise HTTPException(422, f"Tax row {index + 1} needs a name, rate and addition/deduction direction")
        source = "manual"
        if config:
            source = auto_sources.get(config.id) or ("common" if config.is_common else "vendor" if any(link.vendor_id == vendor.id for link in config.vendor_links) else "manual")
        new_taxes.append(InvoiceTax(
            organization_id=organization_id, tax_configuration_id=config.id if config else None,
            tax_name=name, rate_percent=rate, direction=direction, source=source, sort_order=index,
        ))
    row.taxes = new_taxes

    split_inputs = data.payment_splits
    if split_inputs is None:
        split_inputs = [InvoicePaymentSplitIn(currency_code=item.currency_code, percentage=item.percentage) for item in term.splits] if term else []
    if not split_inputs:
        split_inputs = [InvoicePaymentSplitIn(currency_code=data.currency_code, percentage=Decimal("100"), exchange_rate=Decimal("1"))]
    percentages = sum((item.percentage for item in split_inputs), Decimal("0"))
    if percentages != Decimal("100"):
        raise HTTPException(422, "Payment split percentages must total exactly 100%")
    new_splits: list[InvoicePaymentSplit] = []
    seen_currencies: set[str] = set()
    for index, item in enumerate(split_inputs):
        if item.currency_code in seen_currencies:
            raise HTTPException(422, "Payment splits cannot repeat a currency")
        seen_currencies.add(item.currency_code)
        if not db.scalar(select(Currency.id).where(
            Currency.organization_id == organization_id, Currency.currency_code == item.currency_code,
            Currency.is_deleted.is_(False),
        )):
            raise HTTPException(422, f"Payment currency {item.currency_code} is not available in Master Data")
        new_splits.append(InvoicePaymentSplit(
            organization_id=organization_id, currency_code=item.currency_code, percentage=item.percentage,
            exchange_rate=_exchange_rate(db, organization_id, data.currency_code, item.currency_code, item.exchange_rate),
            sort_order=index,
        ))
    row.payment_splits = new_splits
    if data.signatures is not None:
        row.signatures = _signature_rows(db, organization_id, data.signatures)
    db.flush()
    totals = calculate_idvs(row.lines, row.taxes, row.payment_splits, data.disallowed_amount, data.advance_amount)
    if totals["invoice_total"] < 0 or totals["verified_total"] < 0:
        raise HTTPException(422, "Tax deductions cannot make the invoice or verified total negative")
    if totals["adjusted_verified_amount"] < 0:
        raise HTTPException(422, "Disallowed and advance amounts cannot exceed the verified total")
    for field, value in totals.items():
        setattr(row, field, value)
    if not creating:
        row.revision += 1
    db.flush()
    audit.record(
        db, organization_id=organization_id, actor=user, action="create" if creating else "update",
        entity_type="invoice_idvs", entity_id=row.id, entity_label=row.idvs_number,
        summary=(
            f"{'Created' if creating else 'Updated'} {row.idvs_number} for invoice {row.invoice_number}; "
            f"{len(row.lines)} line(s); {row.verified_total} {row.currency_code}; due {row.due_date}"
        ), request=request,
    )
    return row


def create_invoice(db: Session, organization_id: str, data: InvoiceSave, user: User, request: Request | None) -> InvoiceDetailOut:
    row = _write_invoice(db, organization_id, data, user, request)
    _commit(db)
    return _detail_out(row)


def _invoice_or_404(db: Session, organization_id: str, invoice_id: str, deleted: bool | None = False) -> Invoice:
    query = select(Invoice).where(Invoice.id == invoice_id, Invoice.organization_id == organization_id)
    if deleted is not None:
        query = query.where(Invoice.is_deleted.is_(deleted))
    row = db.scalar(query)
    if row is None:
        raise HTTPException(404, "IDVS record not found in this workspace")
    return row


def get_invoice(db: Session, organization_id: str, invoice_id: str) -> InvoiceDetailOut:
    return _detail_out(_invoice_or_404(db, organization_id, invoice_id, deleted=None))


def update_invoice(
    db: Session, organization_id: str, invoice_id: str, data: InvoiceSave,
    user: User, request: Request | None,
) -> InvoiceDetailOut:
    row = _invoice_or_404(db, organization_id, invoice_id)
    _write_invoice(db, organization_id, data, user, request, row)
    _commit(db)
    return _detail_out(row)


def list_invoices(
    db: Session, organization_id: str, *, deleted: bool = False,
    status: str = "", vendor_id: str = "", block_id: str = "", rig_id: str = "", well_id: str = "",
    currency_code: str = "", location_id: str = "", overdue: bool = False,
    date_field: str = "invoice_received_date", date_from: date | None = None, date_to: date | None = None,
) -> list[InvoiceSummaryOut]:
    if date_from and date_to and date_to < date_from:
        raise HTTPException(422, "The To date must be on or after the From date")
    query = select(Invoice).where(Invoice.organization_id == organization_id, Invoice.is_deleted.is_(deleted))
    if status:
        if status == "paid":
            query = query.where(Invoice.paid_date.is_not(None))
        elif status == "approved_unpaid":
            query = query.where(Invoice.status == "approved", Invoice.paid_date.is_(None))
        else:
            query = query.where(Invoice.status == status, Invoice.paid_date.is_(None))
    for field, value in (
        ("vendor_id", vendor_id), ("block_id", block_id), ("rig_id", rig_id), ("well_id", well_id),
        ("currency_code", currency_code.upper()), ("location_id", location_id),
    ):
        if value:
            query = query.where(getattr(Invoice, field) == value)
    if overdue:
        query = query.where(Invoice.paid_date.is_(None), Invoice.due_date < _today())
    allowed_dates = {"invoice_received_date", "invoice_date", "idvs_date", "due_date", "paid_date"}
    selected_date = date_field if date_field in allowed_dates else "invoice_received_date"
    column = getattr(Invoice, selected_date)
    if date_from:
        query = query.where(column >= date_from)
    if date_to:
        query = query.where(column <= date_to)
    rows = db.scalars(query.order_by(Invoice.invoice_received_date.desc(), Invoice.idvs_number.desc())).all()
    return [_summary_out(row) for row in rows]


# ---------------------------------------------------------------------------
# Dated tracking workflow
# ---------------------------------------------------------------------------

def transition_invoice(
    db: Session, organization_id: str, invoice_id: str, data: InvoiceWorkflowIn,
    user: User, request: Request | None,
) -> InvoiceDetailOut:
    row = _invoice_or_404(db, organization_id, invoice_id)
    expected, target, date_field = WORKFLOW[data.action]
    if row.status != expected:
        raise HTTPException(409, f"{row.idvs_number} is {STATUS_LABELS.get(row.status, row.status)}; the next action is not {data.action.replace('_', ' ')}")
    action_date = data.action_date or _today()
    previous_dates = [row.invoice_received_date, row.submitted_date, row.sent_to_accounts_date, row.epicor_received_date]
    earlier = max((value for value in previous_dates if value is not None), default=row.invoice_received_date)
    if action_date < earlier:
        raise HTTPException(422, f"The action date cannot be before {earlier.isoformat()}, the previous tracking milestone")
    row.status = target
    setattr(row, date_field, action_date)
    row.revision += 1
    row.updated_by = _actor(user)
    row.history.append(InvoiceWorkflowHistory(
        organization_id=organization_id, action=data.action, status_after=target,
        action_date=action_date, remarks=data.remarks, actor_user_id=user.id, actor_name=_actor(user),
    ))
    audit.record(
        db, organization_id=organization_id, actor=user, action=data.action, entity_type="invoice_idvs",
        entity_id=row.id, entity_label=row.idvs_number,
        summary=f"{STATUS_LABELS[target]} on {action_date}" + (f" — {data.remarks}" if data.remarks else ""), request=request,
    )
    _commit(db)
    return _detail_out(row)


def record_payment(
    db: Session, organization_id: str, invoice_id: str, data: InvoicePaymentIn,
    user: User, request: Request | None,
) -> InvoiceDetailOut:
    row = _invoice_or_404(db, organization_id, invoice_id)
    if row.status != "approved":
        raise HTTPException(409, "Payment can be recorded only after the invoice is approved in EPICOR")
    if data.paid_date and row.epicor_approved_date and data.paid_date < row.epicor_approved_date:
        raise HTTPException(422, "Paid Date cannot be before the EPICOR approval date")
    clearing = row.paid_date is not None and data.paid_date is None
    row.paid_date = data.paid_date
    row.payment_reference = data.payment_reference
    row.revision += 1
    row.updated_by = _actor(user)
    if data.paid_date:
        row.history.append(InvoiceWorkflowHistory(
            organization_id=organization_id, action="payment", status_after="paid",
            action_date=data.paid_date, remarks=data.remarks, actor_user_id=user.id, actor_name=_actor(user),
        ))
    audit.record(
        db, organization_id=organization_id, actor=user, action="payment_clear" if clearing else "payment",
        entity_type="invoice_idvs", entity_id=row.id, entity_label=row.idvs_number,
        summary=(f"Payment recorded on {data.paid_date}; reference {data.payment_reference or 'not supplied'}" if data.paid_date else "Cleared the paid date"), request=request,
    )
    _commit(db)
    return _detail_out(row)


def bulk_invoices(
    db: Session, organization_id: str, ids: list[str], action: str,
    user: User, request: Request | None,
) -> InvoiceBulkActionOut:
    rows = db.scalars(select(Invoice).where(Invoice.organization_id == organization_id, Invoice.id.in_(ids))).all()
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "One or more IDVS records were not found")
    affected = 0
    timestamp = datetime.now(timezone.utc)
    for row in rows:
        if action == "delete" and not row.is_deleted:
            row.is_deleted, row.deleted_at, row.updated_by = True, timestamp, _actor(user)
            affected += 1
        elif action == "restore" and row.is_deleted:
            row.is_deleted, row.deleted_at, row.updated_by = False, None, _actor(user)
            affected += 1
        elif action == "permanent-delete":
            if not row.is_deleted:
                raise HTTPException(409, "Only IDVS records in Deleted entries can be permanently removed")
            db.delete(row)
            affected += 1
    audit.record(
        db, organization_id=organization_id, actor=user, action=action, entity_type="invoice_idvs",
        entity_label=f"{affected} IDVS record(s)", summary=f"{action.replace('-', ' ').title()}: {affected} IDVS record(s)", request=request,
    )
    _commit(db)
    return InvoiceBulkActionOut(affected_count=affected)


# ---------------------------------------------------------------------------
# Spreadsheet import and export audit
# ---------------------------------------------------------------------------

def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if re.fullmatch(r"\d+(\.\d+)?", text):
        serial = float(text)
        if 1 < serial < 200000:
            return (datetime(1899, 12, 30) + timedelta(days=serial)).date()
    raise ValueError(f"Unrecognized date '{text}' (use YYYY-MM-DD or DD/MM/YYYY)")


def _validation_message(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    )


def _import_payloads(db: Session, organization_id: str, rows: list[InvoiceImportRow]) -> tuple[list[tuple[int, InvoiceSave]], list[str]]:
    reference = reference_data(db, organization_id)
    vendors = {value: vendor for vendor in reference.vendors for value in (vendor.vendor_code.lower(), vendor.vendor_name.lower())}
    locations = {item.name.lower(): item for item in reference.locations}
    categories = {item.name.lower(): item for item in reference.categories}
    terms = {item.term_code.lower(): item for item in reference.payment_terms}
    rigs = {item.rig_code.lower(): item for item in reference.rigs}
    blocks = {item.block_code.lower(): item for item in reference.blocks}
    wells = {item.well_code.lower(): item for item in reference.wells}
    currencies = {item.currency_code for item in reference.currencies}
    prepared: list[tuple[int, InvoiceSave]] = []
    errors: list[str] = []
    for number, item in enumerate(rows, 2):
        try:
            vendor = vendors.get(item.vendor_code.lower())
            if not vendor:
                raise ValueError(f"Vendor '{item.vendor_code}' was not found in Master Data")
            order = next((option for option in reference.orders if option.vendor_id == vendor.id and option.order_number.lower() == item.order_number.lower()), None) if item.order_number else None
            if item.order_number and not order:
                raise ValueError(f"PO/SO '{item.order_number}' was not found for {vendor.vendor_code}")
            location = locations.get(item.location.lower())
            if not location:
                raise ValueError(f"Invoice location '{item.location}' was not found in Invoice Configuration")
            if item.currency_code not in currencies:
                raise ValueError(f"Currency '{item.currency_code}' was not found in Master Data")
            category = categories.get(item.description_category.lower()) if item.description_category else None
            if item.description_category and not category:
                raise ValueError(f"Description category '{item.description_category}' was not found")
            rig = rigs.get(item.rig_code.lower()) if item.rig_code else None
            block = blocks.get(item.block_code.lower()) if item.block_code else None
            well = wells.get(item.well_code.lower()) if item.well_code else None
            if item.rig_code and not rig:
                raise ValueError(f"Rig '{item.rig_code}' was not found")
            if item.block_code and not block:
                raise ValueError(f"Block '{item.block_code}' was not found")
            if item.well_code and not well:
                raise ValueError(f"Well '{item.well_code}' was not found")
            term = terms.get(item.payment_term_code.lower()) if item.payment_term_code else None
            if item.payment_term_code and not term:
                raise ValueError(f"Payment term '{item.payment_term_code}' was not found")
            idvs_date = _parse_date(item.idvs_date)
            invoice_date = _parse_date(item.invoice_date)
            received_date = _parse_date(item.invoice_received_date)
            if not idvs_date or not invoice_date or not received_date:
                raise ValueError("IDVS Date, Invoice Date and Invoice Received Date are required")
            tenure = None if item.payment_tenure_days in (None, "") else int(item.payment_tenure_days)
            line = InvoiceLineIn(
                description=item.description, invoice_quantity=item.invoice_quantity,
                invoice_days=None if item.invoice_days in (None, "") else item.invoice_days,
                invoice_unit_price=item.invoice_unit_price,
                verified_quantity=None if item.verified_quantity in (None, "") else item.verified_quantity,
                verified_days=None if item.verified_days in (None, "") else item.verified_days,
                verified_unit_price=None if item.verified_unit_price in (None, "") else item.verified_unit_price,
                remarks=item.line_remarks,
            )
            # A row that supplies either day column turns on the IDVS day count; groups OR this flag together.
            day_count = item.invoice_days not in (None, "") or item.verified_days not in (None, "")
            payload = InvoiceSave(
                idvs_number=item.idvs_number, idvs_date=idvs_date, invoice_number=item.invoice_number,
                invoice_date=invoice_date, invoice_received_date=received_date, vendor_id=vendor.id,
                order_id=order.id if order else None, block_id=block.id if block else None,
                rig_id=rig.id if rig else None, well_id=well.id if well else None,
                location_id=location.id, field_name=item.field_name, phase=item.phase,
                description_category_id=category.id if category else None,
                service_description=item.service_description, detailed_description=item.detailed_description,
                concerned_person=item.concerned_person, service_from=_parse_date(item.service_from),
                service_to=_parse_date(item.service_to), currency_code=item.currency_code,
                payment_term_id=term.id if term else None, payment_tenure_days=tenure,
                disallowed_amount=item.disallowed_amount or 0, advance_amount=item.advance_amount or 0,
                remarks=item.remarks, day_count_enabled=day_count, lines=[line], taxes=None, payment_splits=None,
                signatures=None,
            )
            prepared.append((number, payload))
        except (ValueError, ValidationError, TypeError) as error:
            errors.append(f"Row {number}: {_validation_message(error) if isinstance(error, ValidationError) else str(error)}")
    return prepared, errors


def import_invoices(
    db: Session, organization_id: str, data: InvoiceImportRequest,
    user: User, request: Request | None,
) -> InvoiceImportOut:
    prepared, errors = _import_payloads(db, organization_id, data.rows)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for number, payload in prepared:
        key = (payload.vendor_id, payload.invoice_number.lower())
        # The day-count flag is per IDVS, so rows may differ on it; it is OR'd across the group below.
        shared = payload.model_dump(exclude={"lines", "day_count_enabled"})
        if key not in groups:
            groups[key] = {
                "number": number, "payload": payload, "shared": shared,
                "lines": list(payload.lines), "day_count": payload.day_count_enabled,
            }
        else:
            if groups[key]["shared"] != shared:
                errors.append(f"Row {number}: invoice header values differ from the first row for {payload.invoice_number}")
            else:
                groups[key]["lines"].extend(payload.lines)
                groups[key]["day_count"] = groups[key]["day_count"] or payload.day_count_enabled
    if errors:
        return InvoiceImportOut(imported_count=0, invoice_count=0, errors=errors, success=False)

    successful: list[Invoice] = []
    line_count = 0
    for group in groups.values():
        payload = group["payload"].model_copy(
            update={"lines": group["lines"], "day_count_enabled": group["day_count"]},
        )
        try:
            with db.begin_nested():
                existing = db.scalar(select(Invoice).where(
                    Invoice.organization_id == organization_id,
                    Invoice.vendor_id == payload.vendor_id,
                    func.lower(Invoice.invoice_number) == payload.invoice_number.lower(),
                ))
                if existing and existing.idvs_number != payload.idvs_number and payload.idvs_number:
                    raise HTTPException(409, "The existing invoice has a different IDVS number")
                if existing and existing.is_deleted:
                    raise HTTPException(409, "The invoice is in Deleted entries; restore it before importing changes")
                row = _write_invoice(db, organization_id, payload, user, request, existing)
                successful.append(row)
                line_count += len(group["lines"])
        except (HTTPException, ValidationError, ValueError) as error:
            detail = error.detail if isinstance(error, HTTPException) else _validation_message(error) if isinstance(error, ValidationError) else str(error)
            errors.append(f"Row {group['number']}: {detail}")
    if errors:
        db.rollback()
        return InvoiceImportOut(imported_count=0, invoice_count=0, errors=errors, success=False)
    audit.record(
        db, organization_id=organization_id, actor=user, action="import", entity_type="invoice_idvs",
        entity_label="IDVS Register", summary=f"Imported {line_count} line(s) into {len(successful)} IDVS record(s)", request=request,
    )
    _commit(db)
    return InvoiceImportOut(imported_count=line_count, invoice_count=len(successful), errors=[], success=True)


def audit_export(
    db: Session, organization_id: str, data: InvoiceExportAudit,
    user: User, request: Request | None,
) -> None:
    audit.record(
        db, organization_id=organization_id, actor=user, action="export", entity_type="invoice_processing_export",
        entity_label=data.module, summary=f"Exported {data.record_count} {data.module} record(s) as {data.format.upper()}" + (f" — {data.detail}" if data.detail else ""),
        request=request,
    )
    _commit(db)


# ---------------------------------------------------------------------------
# Supporting documents (25 MB per file, database-backed)
# ---------------------------------------------------------------------------

async def upload_attachments(
    db: Session, organization_id: str, invoice_id: str, files: list[UploadFile],
    label: str, notes: str, user: User, request: Request | None,
) -> list[InvoiceAttachmentOut]:
    invoice = _invoice_or_404(db, organization_id, invoice_id)
    if not files:
        raise HTTPException(422, "Choose at least one supporting document")
    if len(files) > 20:
        raise HTTPException(422, "Upload at most 20 documents at a time")
    saved: list[InvoiceAttachment] = []
    existing_checksums = set(db.scalars(select(InvoiceAttachment.checksum_sha256).where(
        InvoiceAttachment.organization_id == organization_id,
        InvoiceAttachment.invoice_id == invoice.id, InvoiceAttachment.is_deleted.is_(False),
    )).all())
    batch_checksums: set[str] = set()
    for upload in files:
        original = Path(upload.filename or "").name
        file_name = _clean_text(original)[:300]
        suffix = Path(file_name).suffix.lower()
        if not file_name or suffix not in ALLOWED_ATTACHMENT_EXTENSIONS:
            raise HTTPException(422, f"{file_name or 'This file'} has an unsupported file type")
        content = await upload.read(MAX_ATTACHMENT_BYTES + 1)
        if not content:
            raise HTTPException(422, f"{file_name} is empty")
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(413, f"{file_name} exceeds the 25 MB per-document limit")
        checksum = hashlib.sha256(content).hexdigest()
        if checksum in existing_checksums or checksum in batch_checksums:
            raise HTTPException(409, f"{file_name} is already attached to this IDVS")
        batch_checksums.add(checksum)
        content_type = (upload.content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream")[:120]
        row = InvoiceAttachment(
            organization_id=organization_id, invoice_id=invoice.id, file_name=file_name,
            content_type=content_type, size_bytes=len(content), checksum_sha256=checksum,
            label=_clean_text(label)[:200], notes=_clean_text(notes)[:500], content=content,
            uploaded_by_user_id=user.id, uploaded_by_name=_actor(user),
            created_by=_actor(user), updated_by=_actor(user),
        )
        db.add(row)
        saved.append(row)
    db.flush()
    for row in saved:
        audit.record(
            db, organization_id=organization_id, actor=user, action="document_upload", entity_type="invoice_attachment",
            entity_id=row.id, entity_label=row.file_name,
            summary=f"Attached {row.file_name} ({row.size_bytes} bytes) to {invoice.idvs_number}", request=request,
        )
    _commit(db)
    return [_attachment_out(row) for row in saved]


def download_attachment(db: Session, organization_id: str, attachment_id: str, user: User, request: Request | None) -> InvoiceAttachment:
    row = db.scalar(select(InvoiceAttachment).where(
        InvoiceAttachment.id == attachment_id, InvoiceAttachment.organization_id == organization_id,
        InvoiceAttachment.is_deleted.is_(False),
    ))
    if row is None:
        raise HTTPException(404, "Invoice attachment not found in this workspace")
    audit.record(
        db, organization_id=organization_id, actor=user, action="document_download", entity_type="invoice_attachment",
        entity_id=row.id, entity_label=row.file_name, summary=f"Opened {row.file_name}", request=request,
    )
    _commit(db)
    return row


def delete_attachment(db: Session, organization_id: str, attachment_id: str, user: User, request: Request | None) -> None:
    row = db.scalar(select(InvoiceAttachment).where(
        InvoiceAttachment.id == attachment_id, InvoiceAttachment.organization_id == organization_id,
        InvoiceAttachment.is_deleted.is_(False),
    ))
    if row is None:
        raise HTTPException(404, "Invoice attachment not found in this workspace")
    if row.invoice.is_deleted:
        raise HTTPException(409, "Restore the IDVS before changing its supporting documents")
    row.is_deleted = True
    row.deleted_at = datetime.now(timezone.utc)
    row.updated_by = _actor(user)
    audit.record(
        db, organization_id=organization_id, actor=user, action="document_delete", entity_type="invoice_attachment",
        entity_id=row.id, entity_label=row.file_name, summary=f"Removed {row.file_name} from the active attachment list", request=request,
    )
    _commit(db)


# ---------------------------------------------------------------------------
# Module dashboard (amounts grouped by currency)
# ---------------------------------------------------------------------------

def dashboard_data(db: Session, organization_id: str) -> InvoiceDashboard:
    rows = db.scalars(select(Invoice).where(
        Invoice.organization_id == organization_id, Invoice.is_deleted.is_(False),
    )).all()
    status_counts: dict[str, int] = defaultdict(int)
    currencies: dict[str, dict[str, Any]] = {}
    vendors: dict[tuple[str, str], dict[str, Any]] = {}
    blocks: dict[tuple[str, str], dict[str, Any]] = {}
    ageing_buckets = ("Current / not due", "1–30 days overdue", "31–60 days overdue", "61–90 days overdue", "Over 90 days overdue")
    ageing: dict[tuple[str, str], dict[str, Any]] = {}
    today = _today()
    for row in rows:
        display = "paid" if row.paid_date else row.status
        status_counts[display] += 1
        bucket = currencies.setdefault(row.currency_code, {
            "invoice_count": 0, "invoice_total": Decimal("0"), "verified_total": Decimal("0"),
            "adjusted_verified_amount": Decimal("0"), "difference_amount": Decimal("0"),
            "outstanding_count": 0, "overdue_count": 0,
        })
        bucket["invoice_count"] += 1
        bucket["invoice_total"] += row.invoice_total
        bucket["verified_total"] += row.verified_total
        bucket["adjusted_verified_amount"] += row.adjusted_verified_amount
        bucket["difference_amount"] += row.difference_amount
        if not row.paid_date:
            bucket["outstanding_count"] += 1
            bucket["overdue_count"] += int(row.due_date < today)
        vendor_key = (row.vendor_id, row.currency_code)
        vendor = vendors.setdefault(vendor_key, {
            "vendor_name": row.vendor_name_snapshot, "invoice_count": 0,
            "invoice_total": Decimal("0"), "verified_total": Decimal("0"),
            "difference_amount": Decimal("0"), "approved_count": 0, "discrepancy_count": 0,
        })
        vendor["invoice_count"] += 1
        vendor["invoice_total"] += row.invoice_total
        vendor["verified_total"] += row.verified_total
        vendor["difference_amount"] += row.difference_amount
        vendor["approved_count"] += int(row.status == "approved")
        vendor["discrepancy_count"] += int(row.difference_amount != 0)
        block_key = (row.block_id or "", row.currency_code)
        block = blocks.setdefault(block_key, {
            "block_code": row.block_code_snapshot or "COMMON", "block_name": row.block_name_snapshot or "Materials / no block assigned",
            "block_category": row.block_category, "invoice_count": 0,
            "invoice_total": Decimal("0"), "verified_total": Decimal("0"),
        })
        block["invoice_count"] += 1
        block["invoice_total"] += row.invoice_total
        block["verified_total"] += row.verified_total
        if not row.paid_date:
            overdue_days = (today - row.due_date).days
            if overdue_days <= 0:
                ageing_bucket = ageing_buckets[0]
            elif overdue_days <= 30:
                ageing_bucket = ageing_buckets[1]
            elif overdue_days <= 60:
                ageing_bucket = ageing_buckets[2]
            elif overdue_days <= 90:
                ageing_bucket = ageing_buckets[3]
            else:
                ageing_bucket = ageing_buckets[4]
            values = ageing.setdefault((row.currency_code, ageing_bucket), {
                "invoice_count": 0, "adjusted_verified_amount": Decimal("0"),
            })
            values["invoice_count"] += 1
            values["adjusted_verified_amount"] += row.adjusted_verified_amount
    history = db.scalars(select(InvoiceWorkflowHistory).where(
        InvoiceWorkflowHistory.organization_id == organization_id,
    ).order_by(InvoiceWorkflowHistory.created_at.desc()).limit(10)).all()
    invoice_numbers = {
        item.id: item for item in db.scalars(select(Invoice).where(Invoice.organization_id == organization_id)).all()
    }
    attachments = db.scalar(select(func.count(InvoiceAttachment.id)).join(
        Invoice, Invoice.id == InvoiceAttachment.invoice_id,
    ).where(
        InvoiceAttachment.organization_id == organization_id, InvoiceAttachment.is_deleted.is_(False),
        Invoice.is_deleted.is_(False),
    )) or 0
    action_labels = {
        "submit": "Submitted for verification", "send_to_accounts": "Verified & sent to Accounts",
        "receive_epicor": "Received for EPICOR approval", "approve_epicor": "Approved in EPICOR",
        "payment": "Paid date recorded",
    }
    return InvoiceDashboard(
        as_of=today, total_invoices=len(rows), draft_count=status_counts["draft"], submitted_count=status_counts["submitted"],
        sent_to_accounts_count=status_counts["sent_to_accounts"],
        verification_count=status_counts["submitted"] + status_counts["sent_to_accounts"],
        epicor_pending_count=status_counts["epicor_pending"], epicor_count=status_counts["epicor_pending"],
        approved_count=status_counts["approved"], paid_count=status_counts["paid"],
        overdue_count=sum(not row.paid_date and row.due_date < today for row in rows),
        discrepancy_count=sum(row.difference_amount != 0 for row in rows), attachment_count=attachments,
        own_block_count=sum(row.block_category == "own" for row in rows),
        jv_block_count=sum(row.block_category == "jv" for row in rows),
        unclassified_block_count=sum(bool(row.block_id) and not row.block_category for row in rows),
        status_counts=[InvoiceCountByStatus(status=key, label=STATUS_LABELS[key], count=status_counts[key]) for key in ("draft", "submitted", "sent_to_accounts", "epicor_pending", "approved", "paid")],
        currency_totals=[InvoiceCurrencyTotals(currency_code=code, **values) for code, values in sorted(currencies.items())],
        vendor_rows=[InvoiceVendorDashboardRow(vendor_id=key[0], currency_code=key[1], **values) for key, values in sorted(vendors.items(), key=lambda pair: (-pair[1]["verified_total"], pair[1]["vendor_name"]))],
        block_rows=[InvoiceBlockDashboardRow(block_id=key[0], currency_code=key[1], **values) for key, values in sorted(blocks.items(), key=lambda pair: (-pair[1]["verified_total"], pair[1]["block_name"]))],
        ageing_rows=[InvoiceAgeingRow(
            bucket=label, currency_code=code,
            invoice_count=ageing.get((code, label), {}).get("invoice_count", 0),
            adjusted_verified_amount=ageing.get((code, label), {}).get("adjusted_verified_amount", Decimal("0")),
        ) for code in sorted(currencies) for label in ageing_buckets],
        recent_activity=[InvoiceRecentActivity(
            id=item.id, invoice_id=item.invoice_id,
            idvs_number=invoice_numbers[item.invoice_id].idvs_number if item.invoice_id in invoice_numbers else "Deleted IDVS",
            invoice_number=invoice_numbers[item.invoice_id].invoice_number if item.invoice_id in invoice_numbers else "",
            vendor_name=invoice_numbers[item.invoice_id].vendor_name_snapshot if item.invoice_id in invoice_numbers else "",
            action=item.action, action_label=action_labels.get(item.action, item.action.replace("_", " ").title()),
            actor_name=item.actor_name, action_date=item.action_date, remarks=item.remarks, created_at=item.created_at,
        ) for item in history],
    )
