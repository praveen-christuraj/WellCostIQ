"""Tenant-scoped Vendors and PO/SO Orders APIs (Master Data Management).

Vendors are maintained first; each PO/SO order belongs to one vendor, keeps an
amendment chain (revision 0 is the original, later revisions are amendments) and
holds the scanned copies the user attaches. No monetary values are stored — the
attached document is the source of truth, so document custody (upload, download,
replace, remove, restore) is audited like any other change.

Attachments are kept in the workspace database (``po_so_documents.content``)
because the deployed API filesystem is ephemeral; metadata stays column-wise.
"""

import csv
import hashlib
import io
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Current, Db, require
from app.core.config import get_settings
from app.core.precision import DECIMAL_QUANT
from app.core.spreadsheets import safe_csv_cell
from app.models import AuditLog
from app.models.master_data import Currency
from app.models.service_master import Service
from app.models.vendor_master import (
    DOCUMENT_KINDS,
    ORDER_STATUSES,
    ORDER_TYPES,
    VENDOR_STATUSES,
    OrderDocument,
    PurchaseOrder,
    PurchaseOrderLineItem,
    PurchaseOrderLineItemRevision,
    Vendor,
)
from app.schemas.master_data import (
    MasterDataActivity,
    MasterDataBulkActionResponse,
    MasterDataIDs,
    MasterDataImportRequest,
    MasterDataImportResponse,
)
from app.schemas.vendor_master import (
    DocumentOut,
    DocumentUpdate,
    DocumentUploadItem,
    DocumentUploadResult,
    MAX_RATE,
    OrderAmendmentCreate,
    OrderCreate,
    OrderLineItemAmend,
    OrderLineItemBulkReviseRequest,
    OrderLineItemBulkReviseResponse,
    OrderLineItemCreate,
    OrderLineItemImportResponse,
    OrderLineItemOut,
    OrderLineItemRevisionOut,
    OrderLineItemUpdate,
    OrderOut,
    OrderRevisionOut,
    OrderUpdate,
    VendorCreate,
    VendorOption,
    VendorOut,
    VendorPoCount,
    VendorPoOverview,
    VendorPoTopVendor,
    VendorUpdate,
)
from app.services import audit
from app.services.dependencies import assert_no_dependencies

router = APIRouter(prefix="/master-data", tags=["Vendors & PO/SO Orders"])

VENDOR_LABEL = "Vendors"
ORDER_LABEL = "PO/SO Orders"
DOCUMENT_LABEL = "PO/SO Documents"
LINE_ITEM_LABEL = "PO/SO Line Items"

VENDOR_ENTITY = "vendor"
ORDER_ENTITY = "po_so_order"
DOCUMENT_ENTITY = "po_so_document"
LINE_ITEM_ENTITY = "po_so_line_item"
AUDIT_ENTITY_TYPES = (VENDOR_ENTITY, ORDER_ENTITY, DOCUMENT_ENTITY, LINE_ITEM_ENTITY)

# Documents are the payload of this module, so the accepted families are explicit.
ALLOWED_DOCUMENT_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".rtf",
    ".png", ".jpg", ".jpeg", ".msg", ".eml",
)
DOCUMENT_KIND_LABELS = {
    "po_copy": "PO/SO copy",
    "signed_copy": "Signed copy",
    "amendment_copy": "Amendment copy",
    "specification": "Specification",
    "correspondence": "Correspondence",
    "other": "Other",
}

VENDOR_IMPORT_ALIASES = {
    "vendor_type": ("vendor_type", "vendor type"),
    "vendor_code": ("vendor_code", "code", "vendor code", "supplier_code"),
    "vendor_name": ("vendor_name", "name", "vendor name", "supplier_name"),
    "category": ("category", "vendor_category", "type"),
    "contact_person": ("contact_person", "contact", "contact person", "contact_name"),
    "email": ("email", "e_mail", "email_id"),
    "phone": ("phone", "mobile", "telephone", "contact_number"),
    "website": ("website", "web", "url"),
    "country": ("country",),
    "tax_registration_no": ("tax_registration_no", "tax_id", "tax_no", "gst_no", "vat_no", "registration_no"),
    "address": ("address", "location"),
    "status": ("status", "vendor_status"),
    "credit_terms_days": ("credit_terms_days", "credit_days", "payment_terms_days"),
    "description": ("description", "remarks", "notes", "desc"),
}

ORDER_IMPORT_ALIASES = {
    "order_number": ("order_number", "po_so_number", "po_number", "so_number", "number"),
    "order_type": ("order_type", "type", "po_type"),
    "vendor_code": ("vendor_code", "vendor", "supplier_code", "supplier"),
    "issue_date": ("issue_date", "effective_date", "po_date", "order_date", "date"),
    "expiry_date": ("expiry_date", "valid_until", "validity_date", "end_date"),
    "status": ("status", "order_status"),
    "description": ("description", "remarks", "notes", "scope", "desc"),
}

LINE_ITEM_IMPORT_ALIASES = {
    "order_number": ("order_number", "po_so_number", "po_number", "so_number", "order", "po"),
    "order_revision": ("order_revision", "revision_number", "po_revision", "order_rev", "rev"),
    "line_item_code": ("line_item_code", "line_code", "item_code", "code", "line_no", "line_number", "schedule_code"),
    "vendor_code": ("vendor_code", "vendor_item_code", "supplier_item_code", "catalog_code", "catalogue_code", "part_code"),
    "description": ("description", "item_description", "line_description", "scope", "particulars", "desc"),
    "unit_rate": ("unit_rate", "new_unit_rate", "rate", "unit_price", "price", "new_rate", "current_unit_rate"),
    "new_unit_rate": ("new_unit_rate", "revised_unit_rate", "new_rate", "revised_rate"),
    "currency": ("currency", "currency_code", "ccy", "curr"),
    "new_currency": ("new_currency", "revised_currency"),
    "effective_date": ("effective_date", "valid_from", "rate_date", "date"),
    "reason": ("reason", "amendment_reason", "revision_note", "notes", "remarks"),
    "sort_order": ("sort_order", "line_order", "sequence", "sl_no"),
}

# Spreadsheet-friendly aliases, so an ERP dump imports without hand editing.
VENDOR_STATUS_ALIASES = {
    "active": "active", "a": "active", "enabled": "active", "approved": "active",
    "inactive": "inactive", "i": "inactive", "disabled": "inactive", "dormant": "inactive",
    "blocked": "blocked", "b": "blocked", "hold": "blocked", "on hold": "blocked",
    "on-hold": "blocked", "blacklisted": "blocked", "suspended": "blocked",
}
ORDER_TYPE_ALIASES = {
    "po": "PO", "purchase order": "PO", "purchase": "PO",
    "so": "SO", "service order": "SO", "service": "SO",
    "callout": "Callout", "call out": "Callout", "call-out": "Callout",
    "others": "Others", "other": "Others",
}
ORDER_STATUS_ALIASES = {
    "open": "open", "issued": "open", "active": "open", "in progress": "open",
    "closed": "closed", "complete": "closed", "completed": "closed", "done": "closed",
    "cancelled": "cancelled", "canceled": "cancelled", "void": "cancelled",
}

DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y",
    "%Y/%m/%d", "%d-%b-%Y", "%d-%B-%Y", "%b %d, %Y", "%B %d, %Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M",
)
# `<ORDER NUMBER>_Rev3`, `<ORDER NUMBER>__3`, `<ORDER NUMBER> Rev 3`, `<ORDER NUMBER>_3`
REVISION_SUFFIX = re.compile(r"(?P<number>.+?)[\s_\-]*(?:rev(?:ision)?[\s_\-.]*)?(?P<revision>\d{1,3})$", re.IGNORECASE)


class MasterDataAction:
    """Action labels are centralized so audit summaries stay consistent."""

    CREATE = "create"
    UPDATE = "update"
    AMEND = "amend"
    SOFT_DELETE = "soft_delete"
    RESTORE = "restore"
    PERMANENT_DELETE = "permanent_delete"
    IMPORT = "import"
    DOCUMENT_UPLOAD = "document_upload"
    DOCUMENT_DOWNLOAD = "document_download"
    DOCUMENT_DELETE = "document_delete"
    DOCUMENT_RESTORE = "document_restore"
    DOCUMENT_PERMANENT_DELETE = "document_permanent_delete"


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This record conflicts with an existing workspace record") from error


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _validation_message(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    )


def _check_email(value: str) -> str:
    if not value:
        return ""
    try:
        return str(TypeAdapter(EmailStr).validate_python(value)).lower()
    except Exception as error:
        raise ValueError(f"'{value}' is not a valid e-mail address") from error


def _check_website(value: str) -> str:
    if not value:
        return ""
    candidate = value if re.match(r"^https?://", value, re.IGNORECASE) else f"https://{value}"
    if not re.match(r"^https?://[^\s/]+\.[^\s/]{2,}", candidate, re.IGNORECASE):
        raise ValueError(f"'{value}' is not a valid website address")
    return candidate


def _parse_import_date(value: Any) -> date | None:
    """Accept the date shapes people actually export from Excel and ERP lists."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if re.fullmatch(r"\d+(\.\d+)?", text):
        serial = float(text)
        if 1 < serial < 200000:  # Excel/Sheets day serial
            return (datetime(1899, 12, 30) + timedelta(days=serial)).date()
    parts = re.split(r"[-/. ]", text.split()[0])
    if len(parts) == 3:
        year, month, day = parts if len(parts[0]) == 4 else (parts[2], parts[1], parts[0])
        if len(year) == 2:
            year = f"20{year}" if int(year) < 50 else f"19{year}"
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            pass
    raise ValueError(f"Unrecognized date '{text}' (use YYYY-MM-DD or DD/MM/YYYY)")


def _normalize_import_row(row: dict[str, Any], aliases: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    """Map a spreadsheet header row onto this module's field names."""
    lowered = {str(key).strip().lower().replace(" ", "_").replace("-", "_"): value for key, value in row.items()}
    normalized: dict[str, Any] = {}
    for field, candidates in aliases.items():
        for candidate in candidates:
            value = lowered.get(candidate.replace(" ", "_"))
            if value not in (None, ""):
                normalized[field] = value
                break
    return normalized


# --------------------------------------------------------------------------- #
# Record lookups and output shaping
# --------------------------------------------------------------------------- #


def _vendor_or_404(db: Session, vendor_id: str, organization_id: str, *, include_deleted: bool = True) -> Vendor:
    statement = select(Vendor).where(Vendor.id == vendor_id, Vendor.organization_id == organization_id)
    if not include_deleted:
        statement = statement.where(Vendor.is_deleted.is_(False))
    vendor = db.scalar(statement)
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found in this workspace")
    return vendor


def _order_or_404(db: Session, order_id: str, organization_id: str, *, include_deleted: bool = True) -> PurchaseOrder:
    statement = select(PurchaseOrder).where(
        PurchaseOrder.id == order_id, PurchaseOrder.organization_id == organization_id
    )
    if not include_deleted:
        statement = statement.where(PurchaseOrder.is_deleted.is_(False))
    order = db.scalar(statement)
    if order is None:
        raise HTTPException(status_code=404, detail="PO/SO order not found in this workspace")
    return order


def _document_or_404(db: Session, document_id: str, organization_id: str) -> OrderDocument:
    document = db.scalar(
        select(OrderDocument).where(
            OrderDocument.id == document_id, OrderDocument.organization_id == organization_id
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found in this workspace")
    return document


def _document_counts(db: Session, organization_id: str, order_ids: Iterable[str]) -> dict[str, int]:
    ids = [order_id for order_id in order_ids]
    if not ids:
        return {}
    rows = db.execute(
        select(OrderDocument.order_id, func.count(OrderDocument.id))
        .where(
            OrderDocument.organization_id == organization_id,
            OrderDocument.is_deleted.is_(False),
            OrderDocument.order_id.in_(ids),
        )
        .group_by(OrderDocument.order_id)
    ).all()
    return {order_id: count for order_id, count in rows}


def _line_item_or_404(
    db: Session,
    line_item_id: str,
    organization_id: str,
    *,
    include_deleted: bool = True,
) -> PurchaseOrderLineItem:
    statement = select(PurchaseOrderLineItem).where(
        PurchaseOrderLineItem.id == line_item_id,
        PurchaseOrderLineItem.organization_id == organization_id,
    )
    if not include_deleted:
        statement = statement.where(PurchaseOrderLineItem.is_deleted.is_(False))
    item = db.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="PO/SO line item not found in this workspace")
    return item


def _line_item_counts(db: Session, organization_id: str, order_ids: Iterable[str]) -> dict[str, int]:
    ids = [order_id for order_id in order_ids]
    if not ids:
        return {}
    rows = db.execute(
        select(PurchaseOrderLineItem.order_id, func.count(PurchaseOrderLineItem.id))
        .where(
            PurchaseOrderLineItem.organization_id == organization_id,
            PurchaseOrderLineItem.is_deleted.is_(False),
            PurchaseOrderLineItem.order_id.in_(ids),
        )
        .group_by(PurchaseOrderLineItem.order_id)
    ).all()
    return {order_id: count for order_id, count in rows}


def _revision_counts(db: Session, organization_id: str, order_numbers: Iterable[str]) -> dict[str, int]:
    numbers = list({number for number in order_numbers if number})
    if not numbers:
        return {}
    rows = db.execute(
        select(PurchaseOrder.order_number, func.count(PurchaseOrder.id))
        .where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
            PurchaseOrder.order_number.in_(numbers),
        )
        .group_by(PurchaseOrder.order_number)
    ).all()
    return {number: count for number, count in rows}


def _vendor_stats(db: Session, organization_id: str) -> tuple[dict[str, int], dict[str, int], dict[str, date | None]]:
    """Orders, documents and the latest order date per vendor (active orders only)."""
    order_rows = db.execute(
        select(
            PurchaseOrder.vendor_id,
            func.count(PurchaseOrder.id),
            func.max(PurchaseOrder.issue_date),
        )
        .where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
        )
        .group_by(PurchaseOrder.vendor_id)
    ).all()
    document_rows = db.execute(
        select(PurchaseOrder.vendor_id, func.count(OrderDocument.id))
        .join(OrderDocument, OrderDocument.order_id == PurchaseOrder.id)
        .where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
            OrderDocument.is_deleted.is_(False),
        )
        .group_by(PurchaseOrder.vendor_id)
    ).all()
    return (
        {vendor_id: count for vendor_id, count, _ in order_rows},
        {vendor_id: count for vendor_id, count in document_rows},
        {vendor_id: latest for vendor_id, _, latest in order_rows},
    )


def _service_count_for_vendor(
    db: Session,
    organization_id: str,
    vendor_id: str,
    *,
    active_only: bool,
) -> int:
    statement = select(func.count(Service.id)).where(
        Service.organization_id == organization_id,
        Service.vendor_id == vendor_id,
    )
    if active_only:
        statement = statement.where(Service.is_deleted.is_(False))
    return db.scalar(statement) or 0


def _vendor_out(
    vendor: Vendor,
    *,
    order_count: int = 0,
    document_count: int = 0,
    latest_order_date: date | None = None,
) -> VendorOut:
    return VendorOut(
        id=vendor.id,
        vendor_code=vendor.vendor_code,
        vendor_name=vendor.vendor_name,
        vendor_type=vendor.vendor_type,
        category=vendor.category or "",
        contact_person=vendor.contact_person or "",
        email=vendor.email or "",
        phone=vendor.phone or "",
        website=vendor.website or "",
        country=vendor.country or "",
        tax_registration_no=vendor.tax_registration_no or "",
        address=vendor.address or "",
        status=vendor.status,
        credit_terms_days=vendor.credit_terms_days,
        description=vendor.description or "",
        order_count=order_count,
        document_count=document_count,
        latest_order_date=latest_order_date,
        is_deleted=vendor.is_deleted,
        deleted_at=vendor.deleted_at,
        created_at=vendor.created_at,
        updated_at=vendor.updated_at,
    )


def _order_out(
    order: PurchaseOrder,
    *,
    document_count: int = 0,
    line_item_count: int = 0,
    revision_count: int = 1,
) -> OrderOut:
    expiry = order.expiry_date
    return OrderOut(
        id=order.id,
        order_number=order.order_number,
        order_type=order.order_type,
        vendor_id=order.vendor_id,
        vendor_code=order.vendor.vendor_code if order.vendor else "",
        vendor_name=order.vendor.vendor_name if order.vendor else "",
        vendor_status=order.vendor.status if order.vendor else "inactive",
        revision_number=order.revision_number,
        is_current=order.is_current,
        revision_note=order.revision_note or "",
        parent_order_id=order.parent_order_id,
        issue_date=order.issue_date,
        expiry_date=expiry,
        status=order.status,
        description=order.description or "",
        document_count=document_count,
        line_item_count=line_item_count,
        revision_count=revision_count,
        is_expired=bool(expiry and expiry < _today()),
        is_deleted=order.is_deleted,
        deleted_at=order.deleted_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def _line_item_out(item: PurchaseOrderLineItem, order: PurchaseOrder | None = None) -> OrderLineItemOut:
    order = order or item.order
    vendor = order.vendor if order else None
    return OrderLineItemOut(
        id=item.id,
        order_id=item.order_id,
        order_number=order.order_number if order else "",
        order_type=order.order_type if order else "PO",
        order_revision_number=order.revision_number if order else 0,
        order_is_current=bool(order.is_current) if order else False,
        order_vendor_id=order.vendor_id if order else "",
        order_vendor_code=vendor.vendor_code if vendor else "",
        order_vendor_name=vendor.vendor_name if vendor else "",
        parent_line_item_id=item.parent_line_item_id,
        line_item_code=item.line_item_code,
        vendor_code=item.vendor_code or "",
        description=item.description or "",
        unit_rate=item.unit_rate,
        currency=item.currency,
        effective_date=item.effective_date,
        current_revision_number=item.current_revision_number,
        added_in_order_revision=item.added_in_order_revision,
        sort_order=item.sort_order,
        is_deleted=item.is_deleted,
        deleted_at=item.deleted_at,
        created_by=item.created_by or "",
        updated_by=item.updated_by or "",
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _line_item_revision_out(revision: PurchaseOrderLineItemRevision) -> OrderLineItemRevisionOut:
    return OrderLineItemRevisionOut(
        id=revision.id,
        line_item_id=revision.line_item_id,
        revision_number=revision.revision_number,
        change_type=revision.change_type,  # type: ignore[arg-type]
        unit_rate=revision.unit_rate,
        previous_unit_rate=revision.previous_unit_rate,
        currency=revision.currency,
        previous_currency=revision.previous_currency,
        vendor_code=revision.vendor_code or "",
        description=revision.description or "",
        previous_description=revision.previous_description or "",
        effective_date=revision.effective_date,
        reason=revision.reason or "",
        recorded_by=revision.recorded_by or "",
        created_at=revision.created_at,
    )


def _document_out(document: OrderDocument, order: PurchaseOrder | None = None) -> DocumentOut:
    order = order or document.order
    return DocumentOut(
        id=document.id,
        order_id=document.order_id,
        order_number=order.order_number if order else "",
        file_name=document.file_name,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        checksum_sha256=document.checksum_sha256,
        document_kind=document.document_kind,
        label=document.label or "",
        notes=document.description or "",
        revision_number=document.revision_number,
        uploaded_by_name=document.uploaded_by_name or "",
        is_deleted=document.is_deleted,
        deleted_at=document.deleted_at,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _audit(
    db: Session,
    *,
    user: Any,
    action: str,
    entity_type: str,
    entity_label: str,
    summary: str,
    request: Request,
    entity_id: str | None = None,
) -> None:
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label[:255],
        summary=summary,
        request=request,
    )


def _order_label(order: PurchaseOrder) -> str:
    return f"{ORDER_LABEL} · {order.order_number} (Rev {order.revision_number})"


# --------------------------------------------------------------------------- #
# Documents (file payload handling)
# --------------------------------------------------------------------------- #


def _max_document_bytes() -> int:
    return max(1, get_settings().document_max_size_mb) * 1024 * 1024


def _read_upload(upload: UploadFile) -> tuple[bytes, str]:
    """Validate extension, size and content before anything is persisted."""
    filename = (upload.filename or "").strip()
    if not filename:
        raise ValueError("The file has no name")
    extension = ("." + filename.rsplit(".", 1)[1].lower()) if "." in filename else ""
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValueError(
            f"'{extension or filename}' is not an accepted file type. Allowed: {', '.join(ALLOWED_DOCUMENT_EXTENSIONS)}"
        )
    limit = _max_document_bytes()
    # Read at most one byte past the limit: an oversized upload is refused without
    # ever being held in memory, which is what made a "15 MB" cap unbounded before.
    content = upload.file.read(limit + 1)
    if not content:
        raise ValueError("The file is empty")
    if len(content) > limit:
        raise ValueError(f"The file is larger than the {limit // (1024 * 1024)} MB limit")
    return content, filename


def _human_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{max(1, size // 1024)} KB"


# The uploader decides the Content-Type header, so it cannot be trusted: a file
# named `.pdf` can be HTML with `Content-Type: text/html`, which would run script on
# the API origin when previewed. The served type is derived from the signature
# instead, and only verified document/image types may be displayed inline.
INLINE_SAFE_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg", "image/gif"})
SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _sniff_document_type(content: bytes, filename: str) -> str:
    for signature, mime in SIGNATURES:
        if content.startswith(signature):
            return mime
    lowered = filename.lower()
    if content.startswith(b"PK\x03\x04"):
        if lowered.endswith(".docx"):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if lowered.endswith(".xlsx"):
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if lowered.endswith(".csv"):
        return "text/csv"
    if lowered.endswith(".txt"):
        return "text/plain"
    return "application/octet-stream"

def _content_disposition(disposition: str, filename: str) -> str:
    ascii_name = re.sub(r"[\"\\\r\n]", "_", filename.encode("ascii", "ignore").decode()) or "attachment"
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _store_document(
    db: Session,
    *,
    order: PurchaseOrder,
    user: Any,
    content: bytes,
    filename: str,
    content_type: str,
    document_kind: str,
    label: str,
    notes: str,
) -> OrderDocument:
    """Persist one attachment, refusing an exact duplicate inside the same order."""
    checksum = hashlib.sha256(content).hexdigest()
    duplicate = db.scalar(
        select(OrderDocument).where(
            OrderDocument.order_id == order.id,
            OrderDocument.organization_id == order.organization_id,
            OrderDocument.checksum_sha256 == checksum,
            OrderDocument.is_deleted.is_(False),
        )
    )
    if duplicate is not None:
        raise ValueError(f"An identical file is already attached as '{duplicate.file_name}'")
    document = OrderDocument(
        organization_id=order.organization_id,
        order_id=order.id,
        file_name=filename[:300],
        content_type=_sniff_document_type(content, filename),
        size_bytes=len(content),
        checksum_sha256=checksum,
        document_kind=document_kind,
        label=label[:200],
        description=notes[:500],
        revision_number=order.revision_number,
        content=content,
        uploaded_by_user_id=user.id,
        uploaded_by_name=user.full_name,
    )
    db.add(document)
    return document


def _split_revision_hint(filename: str) -> tuple[str, int | None]:
    """Read an optional revision suffix such as ``PO-100_Rev2`` or ``PO-100__2``."""
    stem = filename.rsplit(".", 1)[0].strip()
    match = REVISION_SUFFIX.match(stem)
    if match:
        number = match.group("number").strip(" _-.")
        revision = int(match.group("revision"))
        if number and revision <= 200:
            return number, revision
    return stem, None


# --------------------------------------------------------------------------- #
# Module dashboard
# --------------------------------------------------------------------------- #


@router.get(
    "/vendor-po/overview",
    response_model=VendorPoOverview,
    dependencies=[Depends(require("master-data:read"))],
)
def vendor_po_overview(db: Db, user: Current) -> VendorPoOverview:
    """KPIs for the Vendors and PO/SO Orders tabs of Master Data Management."""
    organization_id = user.organization_id

    def vendor_count(status: str | None = None, *, deleted: bool = False) -> int:
        statement = select(func.count(Vendor.id)).where(
            Vendor.organization_id == organization_id, Vendor.is_deleted.is_(deleted)
        )
        if status:
            statement = statement.where(Vendor.status == status)
        return db.scalar(statement) or 0

    def order_count(*, deleted: bool = False, amendments: bool = False, status: str | None = None) -> int:
        statement = select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.organization_id == organization_id, PurchaseOrder.is_deleted.is_(deleted)
        )
        if amendments:
            statement = statement.where(PurchaseOrder.revision_number > 0)
        if status:
            statement = statement.where(PurchaseOrder.status == status)
        return db.scalar(statement) or 0

    type_rows = db.execute(
        select(PurchaseOrder.order_type, func.count(PurchaseOrder.id))
        .where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
        )
        .group_by(PurchaseOrder.order_type)
    ).all()
    types = {order_type: count for order_type, count in type_rows}

    top_rows = db.execute(
        select(
            Vendor.id,
            Vendor.vendor_code,
            Vendor.vendor_name,
            func.count(PurchaseOrder.id),
        )
        .join(PurchaseOrder, PurchaseOrder.vendor_id == Vendor.id)
        .where(
            Vendor.organization_id == organization_id,
            Vendor.is_deleted.is_(False),
            PurchaseOrder.is_deleted.is_(False),
        )
        .group_by(Vendor.id, Vendor.vendor_code, Vendor.vendor_name)
        .order_by(func.count(PurchaseOrder.id).desc(), Vendor.vendor_code)
        .limit(5)
    ).all()
    document_rows = db.execute(
        select(PurchaseOrder.vendor_id, func.count(OrderDocument.id))
        .join(OrderDocument, OrderDocument.order_id == PurchaseOrder.id)
        .where(
            PurchaseOrder.organization_id == organization_id,
            PurchaseOrder.is_deleted.is_(False),
            OrderDocument.is_deleted.is_(False),
        )
        .group_by(PurchaseOrder.vendor_id)
    ).all()
    documents_by_vendor = {vendor_id: count for vendor_id, count in document_rows}

    return VendorPoOverview(
        vendors_active=vendor_count("active"),
        vendors_inactive=vendor_count("inactive"),
        vendors_blocked=vendor_count("blocked"),
        vendors_deleted=vendor_count(deleted=True),
        orders_active=order_count(),
        orders_amendments=order_count(amendments=True),
        orders_deleted=order_count(deleted=True),
        orders_by_type=[
            VendorPoCount(key=order_type, label=order_type, count=types.get(order_type, 0))
            for order_type in ORDER_TYPES
        ],
        orders_by_status=[
            VendorPoCount(key=status, label=status.title(), count=order_count(status=status))
            for status in ORDER_STATUSES
        ],
        line_items_active=db.scalar(
            select(func.count(PurchaseOrderLineItem.id))
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLineItem.order_id)
            .where(
                PurchaseOrderLineItem.organization_id == organization_id,
                PurchaseOrderLineItem.is_deleted.is_(False),
                PurchaseOrder.is_deleted.is_(False),
                PurchaseOrder.is_current.is_(True),
            )
        ) or 0,
        orders_with_line_items=db.scalar(
            select(func.count(func.distinct(PurchaseOrderLineItem.order_id)))
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLineItem.order_id)
            .where(
                PurchaseOrderLineItem.organization_id == organization_id,
                PurchaseOrderLineItem.is_deleted.is_(False),
                PurchaseOrder.is_deleted.is_(False),
                PurchaseOrder.is_current.is_(True),
            )
        ) or 0,
        documents_active=db.scalar(
            select(func.count(OrderDocument.id)).where(
                OrderDocument.organization_id == organization_id,
                OrderDocument.is_deleted.is_(False),
            )
        ) or 0,
        documents_deleted=db.scalar(
            select(func.count(OrderDocument.id)).where(
                OrderDocument.organization_id == organization_id,
                OrderDocument.is_deleted.is_(True),
            )
        ) or 0,
        storage_bytes=db.scalar(
            select(func.coalesce(func.sum(OrderDocument.size_bytes), 0)).where(
                OrderDocument.organization_id == organization_id,
                OrderDocument.is_deleted.is_(False),
            )
        ) or 0,
        top_vendors=[
            VendorPoTopVendor(
                vendor_id=vendor_id,
                vendor_code=vendor_code,
                vendor_name=vendor_name,
                order_count=order_total,
                document_count=documents_by_vendor.get(vendor_id, 0),
            )
            for vendor_id, vendor_code, vendor_name, order_total in top_rows
        ],
    )


@router.get(
    "/vendor-po/activity",
    response_model=list[MasterDataActivity],
    dependencies=[Depends(require("master-data:read"))],
)
def vendor_po_activity(db: Db, user: Current) -> list[MasterDataActivity]:
    """Recent vendor, order and document activity for the module dashboard."""
    entries = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == user.organization_id,
            AuditLog.entity_type.in_(AUDIT_ENTITY_TYPES),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(8)
    ).all()
    return [
        MasterDataActivity(
            id=entry.id,
            action=entry.action,
            entity_label=entry.entity_label,
            summary=entry.summary,
            created_at=entry.created_at,
        )
        for entry in entries
    ]


# --------------------------------------------------------------------------- #
# Vendors
# --------------------------------------------------------------------------- #


@router.get(
    "/vendors/options",
    response_model=list[VendorOption],
    dependencies=[Depends(require("master-data:read"))],
)
def vendor_options(db: Db, user: Current) -> list[VendorOption]:
    """Lightweight vendor list for PO/SO forms and filters (active vendors only)."""
    vendors = db.scalars(
        select(Vendor)
        .where(
            Vendor.organization_id == user.organization_id,
            Vendor.is_deleted.is_(False),
        )
        .order_by(Vendor.vendor_code)
    ).all()
    orders, _, _ = _vendor_stats(db, user.organization_id)
    return [
        VendorOption(
            id=vendor.id,
            vendor_code=vendor.vendor_code,
            vendor_name=vendor.vendor_name,
            vendor_type=vendor.vendor_type,
            status=vendor.status,
            order_count=orders.get(vendor.id, 0),
            label=f"{vendor.vendor_code} — {vendor.vendor_name}",
        )
        for vendor in vendors
    ]


@router.get(
    "/vendors/deleted",
    response_model=list[VendorOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_deleted_vendors(db: Db, user: Current) -> list[VendorOut]:
    vendors = db.scalars(
        select(Vendor)
        .where(Vendor.organization_id == user.organization_id, Vendor.is_deleted.is_(True))
        .order_by(Vendor.deleted_at.desc(), Vendor.vendor_code)
    ).all()
    return [_vendor_out(vendor) for vendor in vendors]


@router.get("/vendors", response_model=list[VendorOut], dependencies=[Depends(require("master-data:read"))])
def list_vendors(db: Db, user: Current) -> list[VendorOut]:
    """Active vendors with their PO/SO and attached-document counts."""
    vendors = db.scalars(
        select(Vendor)
        .where(Vendor.organization_id == user.organization_id, Vendor.is_deleted.is_(False))
        .order_by(Vendor.vendor_code)
    ).all()
    orders, documents, latest = _vendor_stats(db, user.organization_id)
    return [
        _vendor_out(
            vendor,
            order_count=orders.get(vendor.id, 0),
            document_count=documents.get(vendor.id, 0),
            latest_order_date=latest.get(vendor.id),
        )
        for vendor in vendors
    ]


@router.get(
    "/vendors/{vendor_id}",
    response_model=VendorOut,
    dependencies=[Depends(require("master-data:read"))],
)
def get_vendor(vendor_id: str, db: Db, user: Current) -> VendorOut:
    vendor = _vendor_or_404(db, vendor_id, user.organization_id)
    orders, documents, latest = _vendor_stats(db, user.organization_id)
    return _vendor_out(
        vendor,
        order_count=orders.get(vendor.id, 0),
        document_count=documents.get(vendor.id, 0),
        latest_order_date=latest.get(vendor.id),
    )


# Every editable vendor column; partial updates are validated against the whole record.
VENDOR_FIELDS = (
    "vendor_code", "vendor_name", "vendor_type", "category", "contact_person", "email", "phone",
    "website", "country", "tax_registration_no", "address", "status",
    "credit_terms_days", "description",
)


def _vendor_values(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the free-text business fields and map them onto model columns."""
    values = dict(payload)
    code = str(values.get("vendor_code") or "").strip().upper()
    if not code:
        raise ValueError("Vendor code is required")
    values["vendor_code"] = code
    name = str(values.get("vendor_name") or "").strip()
    if not name:
        raise ValueError("Vendor name is required")
    values["vendor_name"] = name
    if values.get("vendor_type") not in ("Inhouse", "Third party"):
        raise ValueError("Vendor type must be Inhouse or Third party")
    values["email"] = _check_email(str(values.get("email") or "").strip())
    values["website"] = _check_website(str(values.get("website") or "").strip())
    status = values.get("status") or "active"
    if status not in VENDOR_STATUSES:
        raise ValueError(f"Status must be one of {', '.join(VENDOR_STATUSES)}")
    values["status"] = status
    for field in ("category", "contact_person", "phone", "country", "tax_registration_no", "address", "description"):
        values[field] = str(values.get(field) or "").strip()
    terms = values.get("credit_terms_days")
    values["credit_terms_days"] = int(terms) if terms not in (None, "") else None
    return values


def _duplicate_vendor(db: Session, organization_id: str, code: str, *, exclude_id: str | None = None) -> Vendor | None:
    statement = select(Vendor).where(
        Vendor.organization_id == organization_id,
        func.upper(Vendor.vendor_code) == code,
    )
    if exclude_id:
        statement = statement.where(Vendor.id != exclude_id)
    return db.scalar(statement)


@router.post(
    "/vendors",
    response_model=VendorOut,
    status_code=201,
    dependencies=[Depends(require("master-data:create"))],
)
def create_vendor(data: VendorCreate, request: Request, db: Db, user: Current) -> VendorOut:
    try:
        payload = _vendor_values(data.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if _duplicate_vendor(db, user.organization_id, payload["vendor_code"]):
        raise HTTPException(
            status_code=409,
            detail=f"Vendor code '{payload['vendor_code']}' already exists; restore or permanently remove its deleted entry first",
        )
    vendor = Vendor(organization_id=user.organization_id, **payload)
    db.add(vendor)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Vendor code already exists in this workspace") from error
    _audit(
        db,
        user=user,
        action=MasterDataAction.CREATE,
        entity_type=VENDOR_ENTITY,
        entity_id=vendor.id,
        entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
        summary=f"Created vendor {vendor.vendor_code} ({vendor.vendor_name})",
        request=request,
    )
    _commit(db)
    db.refresh(vendor)
    return _vendor_out(vendor)


@router.patch(
    "/vendors/{vendor_id}",
    response_model=VendorOut,
    dependencies=[Depends(require("master-data:update"))],
)
def update_vendor(
    vendor_id: str,
    data: VendorUpdate,
    request: Request,
    db: Db,
    user: Current,
) -> VendorOut:
    vendor = _vendor_or_404(db, vendor_id, user.organization_id)
    supplied = data.model_dump(exclude_unset=True)
    if not supplied:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    # Validate against the whole record so a partial update still satisfies the
    # required fields, then write back only what the caller supplied.
    merged = {field: getattr(vendor, field) for field in VENDOR_FIELDS}
    merged.update(supplied)
    try:
        payload = _vendor_values(merged)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if _duplicate_vendor(db, user.organization_id, payload["vendor_code"], exclude_id=vendor.id):
        raise HTTPException(
            status_code=409, detail=f"Vendor code '{payload['vendor_code']}' already exists in this workspace"
        )

    changed = [field for field in supplied if getattr(vendor, field) != payload[field]]
    for field in supplied:
        setattr(vendor, field, payload[field])
    if changed:
        _audit(
            db,
            user=user,
            action=MasterDataAction.UPDATE,
            entity_type=VENDOR_ENTITY,
            entity_id=vendor.id,
            entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
            summary=f"Updated vendor {vendor.vendor_code}: {', '.join(sorted(changed))}",
            request=request,
        )
        _commit(db)
        db.refresh(vendor)
    return _vendor_out(vendor)


@router.delete(
    "/vendors/{vendor_id}",
    response_model=VendorOut,
    dependencies=[Depends(require("master-data:delete"))],
)
def soft_delete_vendor(vendor_id: str, request: Request, db: Db, user: Current) -> VendorOut:
    vendor = _vendor_or_404(db, vendor_id, user.organization_id, include_deleted=False)
    live_orders = db.scalar(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.vendor_id == vendor.id,
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.is_deleted.is_(False),
        )
    ) or 0
    if live_orders:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Vendor {vendor.vendor_code} still has {live_orders} active PO/SO "
                f"{'order' if live_orders == 1 else 'orders'}. Move them to deleted entries first."
            ),
        )
    active_services = _service_count_for_vendor(
        db, user.organization_id, vendor.id, active_only=True
    )
    if active_services:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Vendor {vendor.vendor_code} is still assigned to {active_services} active "
                f"service {'record' if active_services == 1 else 'records'}. "
                "Move those services to deleted entries first."
            ),
        )
    vendor.is_deleted = True
    vendor.deleted_at = datetime.now(timezone.utc)
    _audit(
        db,
        user=user,
        action=MasterDataAction.SOFT_DELETE,
        entity_type=VENDOR_ENTITY,
        entity_id=vendor.id,
        entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
        summary=f"Moved vendor {vendor.vendor_code} to deleted entries",
        request=request,
    )
    _commit(db)
    db.refresh(vendor)
    return _vendor_out(vendor)


@router.post(
    "/vendors/{vendor_id}/restore",
    response_model=VendorOut,
    dependencies=[Depends(require("master-data:restore"))],
)
def restore_vendor(vendor_id: str, request: Request, db: Db, user: Current) -> VendorOut:
    vendor = _vendor_or_404(db, vendor_id, user.organization_id)
    if not vendor.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted vendor can be restored")
    vendor.is_deleted = False
    vendor.deleted_at = None
    _audit(
        db,
        user=user,
        action=MasterDataAction.RESTORE,
        entity_type=VENDOR_ENTITY,
        entity_id=vendor.id,
        entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
        summary=f"Restored vendor {vendor.vendor_code}",
        request=request,
    )
    _commit(db)
    db.refresh(vendor)
    return _vendor_out(vendor)


@router.delete(
    "/vendors/{vendor_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("master-data:permanent-delete"))],
)
def permanently_delete_vendor(vendor_id: str, request: Request, db: Db, user: Current) -> None:
    vendor = _vendor_or_404(db, vendor_id, user.organization_id)
    if not vendor.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted vendor can be permanently deleted")
    remaining = db.scalar(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.vendor_id == vendor.id,
            PurchaseOrder.organization_id == user.organization_id,
        )
    ) or 0
    if remaining:
        raise HTTPException(
            status_code=409,
            detail=f"Vendor {vendor.vendor_code} still holds {remaining} PO/SO order rows. Permanently delete those first.",
        )
    remaining_services = _service_count_for_vendor(
        db, user.organization_id, vendor.id, active_only=False
    )
    if remaining_services:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Vendor {vendor.vendor_code} is still referenced by {remaining_services} service "
                f"{'record' if remaining_services == 1 else 'records'}. Permanently delete those services first."
            ),
        )
    assert_no_dependencies(db, vendor, user.organization_id, entity_label=f"vendor {vendor.vendor_code}")
    _audit(
        db,
        user=user,
        action=MasterDataAction.PERMANENT_DELETE,
        entity_type=VENDOR_ENTITY,
        entity_id=vendor.id,
        entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
        summary=f"Permanently deleted vendor {vendor.vendor_code}",
        request=request,
    )
    db.delete(vendor)
    _commit(db)
    return None


def _vendors_for_ids(db: Session, ids: list[str], organization_id: str, *, deleted: bool) -> list[Vendor]:
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Duplicate vendor IDs are not allowed")
    vendors = list(
        db.scalars(
            select(Vendor).where(Vendor.organization_id == organization_id, Vendor.id.in_(ids))
        ).all()
    )
    if len(vendors) != len(ids):
        raise HTTPException(status_code=404, detail="One or more vendors were not found in this workspace")
    if any(vendor.is_deleted is not deleted for vendor in vendors):
        expected = "deleted" if deleted else "active"
        raise HTTPException(status_code=409, detail=f"Bulk action requires only {expected} vendors")
    return vendors


@router.post(
    "/vendors/bulk-delete",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:delete"))],
)
def bulk_soft_delete_vendors(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    vendors = _vendors_for_ids(db, data.ids, user.organization_id, deleted=False)
    blocked = [
        vendor.vendor_code
        for vendor in vendors
        if (
            db.scalar(
                select(func.count(PurchaseOrder.id)).where(
                    PurchaseOrder.vendor_id == vendor.id,
                    PurchaseOrder.is_deleted.is_(False),
                )
            )
            or 0
        )
    ]
    if blocked:
        raise HTTPException(
            status_code=409,
            detail=f"These vendors still have active PO/SO orders: {', '.join(sorted(blocked))}",
        )
    blocked_services = [
        vendor.vendor_code
        for vendor in vendors
        if _service_count_for_vendor(
            db, user.organization_id, vendor.id, active_only=True
        )
    ]
    if blocked_services:
        raise HTTPException(
            status_code=409,
            detail=f"These vendors are still assigned to active services: {', '.join(sorted(blocked_services))}",
        )
    deleted_at = datetime.now(timezone.utc)
    for vendor in vendors:
        vendor.is_deleted = True
        vendor.deleted_at = deleted_at
        _audit(
            db,
            user=user,
            action=MasterDataAction.SOFT_DELETE,
            entity_type=VENDOR_ENTITY,
            entity_id=vendor.id,
            entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
            summary=f"Moved vendor {vendor.vendor_code} to deleted entries (bulk action)",
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(vendors))


@router.post(
    "/vendors/bulk-restore",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:restore"))],
)
def bulk_restore_vendors(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    vendors = _vendors_for_ids(db, data.ids, user.organization_id, deleted=True)
    for vendor in vendors:
        vendor.is_deleted = False
        vendor.deleted_at = None
        _audit(
            db,
            user=user,
            action=MasterDataAction.RESTORE,
            entity_type=VENDOR_ENTITY,
            entity_id=vendor.id,
            entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
            summary=f"Restored vendor {vendor.vendor_code} (bulk action)",
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(vendors))


@router.post(
    "/vendors/bulk-permanent-delete",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:permanent-delete"))],
)
def bulk_permanent_delete_vendors(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    vendors = _vendors_for_ids(db, data.ids, user.organization_id, deleted=True)
    for vendor in vendors:
        remaining = db.scalar(
            select(func.count(PurchaseOrder.id)).where(PurchaseOrder.vendor_id == vendor.id)
        ) or 0
        if remaining:
            raise HTTPException(
                status_code=409,
                detail=f"Vendor {vendor.vendor_code} still holds {remaining} PO/SO order rows",
            )
        remaining_services = _service_count_for_vendor(
            db, user.organization_id, vendor.id, active_only=False
        )
        if remaining_services:
            raise HTTPException(
                status_code=409,
                detail=f"Vendor {vendor.vendor_code} is still referenced by {remaining_services} service rows",
            )
    for vendor in vendors:
        assert_no_dependencies(db, vendor, user.organization_id, entity_label=f"vendor {vendor.vendor_code}")
    for vendor in vendors:
        _audit(
            db,
            user=user,
            action=MasterDataAction.PERMANENT_DELETE,
            entity_type=VENDOR_ENTITY,
            entity_id=vendor.id,
            entity_label=f"{VENDOR_LABEL} · {vendor.vendor_code}",
            summary=f"Permanently deleted vendor {vendor.vendor_code} (bulk action)",
            request=request,
        )
        db.delete(vendor)
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(vendors))


@router.post(
    "/vendors/import",
    response_model=MasterDataImportResponse,
    dependencies=[Depends(require("master-data:import"))],
)
def import_vendors(
    data: MasterDataImportRequest, request: Request, db: Db, user: Current
) -> MasterDataImportResponse:
    """Upsert vendors from a previewed spreadsheet, reporting per-row problems."""
    imported = 0
    errors: list[str] = []
    seen: set[str] = set()

    for row_number, row in enumerate(data.rows, start=1):
        normalized = _normalize_import_row(row, VENDOR_IMPORT_ALIASES)
        # Older spreadsheets have no type column; preserve the existing classification.
        if "vendor_type" not in normalized:
            existing = _duplicate_vendor(db, user.organization_id, str(normalized.get("vendor_code") or "").strip().upper())
            if existing:
                normalized["vendor_type"] = existing.vendor_type
        status_text = str(normalized.get("status") or "").strip().lower()
        if status_text:
            if status_text not in VENDOR_STATUS_ALIASES:
                errors.append(
                    f"Row {row_number}: status '{status_text}' is not recognized (use active, inactive or blocked)"
                )
                continue
            normalized["status"] = VENDOR_STATUS_ALIASES[status_text]
        terms_text = str(normalized.get("credit_terms_days") or "").strip()
        if terms_text:
            digits = re.sub(r"[^0-9]", "", terms_text)
            if not digits:
                errors.append(f"Row {row_number}: credit terms '{terms_text}' is not a number of days")
                continue
            normalized["credit_terms_days"] = int(digits)
        try:
            payload = _vendor_values(VendorCreate.model_validate(normalized).model_dump())
        except ValidationError as error:
            errors.append(f"Row {row_number}: {_validation_message(error)}")
            continue
        except ValueError as error:
            errors.append(f"Row {row_number}: {error}")
            continue

        code = payload["vendor_code"]
        if code in seen:
            errors.append(f"Row {row_number} ({code}): duplicate vendor code in this import file")
            continue
        seen.add(code)

        vendor = _duplicate_vendor(db, user.organization_id, code)
        if vendor is None:
            vendor = Vendor(organization_id=user.organization_id, **payload)
            db.add(vendor)
            try:
                db.flush()
            except IntegrityError as error:
                db.rollback()
                errors.append(f"Row {row_number} ({code}): vendor code already exists")
                continue
            action = MasterDataAction.CREATE
            summary = f"Created vendor {code} from import"
        else:
            for field, value in payload.items():
                setattr(vendor, field, value)
            if vendor.is_deleted:
                vendor.is_deleted = False
                vendor.deleted_at = None
                action = MasterDataAction.RESTORE
                summary = f"Restored and updated vendor {code} from import"
            else:
                action = MasterDataAction.UPDATE
                summary = f"Updated vendor {code} from import"
        _audit(
            db,
            user=user,
            action=action,
            entity_type=VENDOR_ENTITY,
            entity_id=vendor.id,
            entity_label=f"{VENDOR_LABEL} · {code}",
            summary=summary,
            request=request,
        )
        imported += 1

    _audit(
        db,
        user=user,
        action=MasterDataAction.IMPORT,
        entity_type=VENDOR_ENTITY,
        entity_label=VENDOR_LABEL,
        summary=f"Imported {imported} vendors with {len(errors)} validation errors",
        request=request,
    )
    _commit(db)
    return MasterDataImportResponse(
        imported_count=imported,
        error_count=len(errors),
        errors=errors[:100],
        success=not errors,
    )


# --------------------------------------------------------------------------- #
# PO/SO Orders
# --------------------------------------------------------------------------- #


@router.get(
    "/po-so-orders/deleted",
    response_model=list[OrderOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_deleted_orders(db: Db, user: Current) -> list[OrderOut]:
    orders = db.scalars(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.is_deleted.is_(True),
        )
        .order_by(PurchaseOrder.deleted_at.desc(), PurchaseOrder.order_number)
    ).all()
    order_ids = [order.id for order in orders]
    documents = _document_counts(db, user.organization_id, order_ids)
    line_items = _line_item_counts(db, user.organization_id, order_ids)
    revisions = _revision_counts(db, user.organization_id, [order.order_number for order in orders])
    return [
        _order_out(
            order,
            document_count=documents.get(order.id, 0),
            line_item_count=line_items.get(order.id, 0),
            revision_count=revisions.get(order.order_number, 0),
        )
        for order in orders
    ]


@router.get(
    "/po-so-orders",
    response_model=list[OrderOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_orders(db: Db, user: Current) -> list[OrderOut]:
    """Every active PO/SO revision in the workspace, with vendor, line-item and file counts."""
    orders = db.scalars(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.is_deleted.is_(False),
        )
        .order_by(PurchaseOrder.order_number, PurchaseOrder.revision_number)
    ).all()
    order_ids = [order.id for order in orders]
    documents = _document_counts(db, user.organization_id, order_ids)
    line_items = _line_item_counts(db, user.organization_id, order_ids)
    revisions = _revision_counts(db, user.organization_id, [order.order_number for order in orders])
    return [
        _order_out(
            order,
            document_count=documents.get(order.id, 0),
            line_item_count=line_items.get(order.id, 0),
            revision_count=revisions.get(order.order_number, 1),
        )
        for order in orders
    ]


@router.get(
    "/po-so-orders/{order_id}/revisions",
    response_model=list[OrderRevisionOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_order_revisions(order_id: str, db: Db, user: Current) -> list[OrderRevisionOut]:
    """The amendment history of one order number, oldest first."""
    order = _order_or_404(db, order_id, user.organization_id)
    family = db.scalars(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == order.order_number,
        )
        .order_by(PurchaseOrder.revision_number)
    ).all()
    family_ids = [row.id for row in family]
    documents = _document_counts(db, user.organization_id, family_ids)
    line_items = _line_item_counts(db, user.organization_id, family_ids)
    return [
        OrderRevisionOut(
            id=row.id,
            revision_number=row.revision_number,
            is_current=row.is_current,
            revision_note=row.revision_note or "",
            issue_date=row.issue_date,
            status=row.status,
            document_count=documents.get(row.id, 0),
            line_item_count=line_items.get(row.id, 0),
            created_at=row.created_at,
            updated_at=row.updated_at,
            is_deleted=row.is_deleted,
        )
        for row in family
    ]


def _order_values(payload: dict[str, Any]) -> dict[str, Any]:
    values = dict(payload)
    number = str(values.get("order_number") or "").strip().upper()
    if not number:
        raise ValueError("PO/SO number is required")
    values["order_number"] = number
    order_type = values.get("order_type") or "PO"
    if order_type not in ORDER_TYPES:
        raise ValueError(f"Order type must be one of {', '.join(ORDER_TYPES)}")
    values["order_type"] = order_type
    status = values.get("status") or "open"
    if status not in ORDER_STATUSES:
        raise ValueError(f"Status must be one of {', '.join(ORDER_STATUSES)}")
    values["status"] = status
    values["description"] = str(values.get("description") or "").strip()
    issue, expiry = values.get("issue_date"), values.get("expiry_date")
    if issue and expiry and expiry < issue:
        raise ValueError("Expiry date cannot be earlier than the issue date")
    return values


def _active_vendor(db: Session, vendor_id: str, organization_id: str) -> Vendor:
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == vendor_id,
            Vendor.organization_id == organization_id,
            Vendor.is_deleted.is_(False),
        )
    )
    if vendor is None:
        raise ValueError("Select a vendor that exists in this workspace")
    return vendor


@router.post(
    "/po-so-orders",
    response_model=OrderOut,
    status_code=201,
    dependencies=[Depends(require("master-data:create"))],
)
def create_order(data: OrderCreate, request: Request, db: Db, user: Current) -> OrderOut:
    """Create the original (revision 0) of a PO/SO order."""
    try:
        payload = _order_values(data.model_dump())
        vendor = _active_vendor(db, payload["vendor_id"], user.organization_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if vendor.status == "blocked":
        raise HTTPException(
            status_code=409,
            detail=f"Vendor {vendor.vendor_code} is blocked. Unblock it before adding new PO/SO orders.",
        )
    number = payload["order_number"]
    existing = db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == number,
            PurchaseOrder.revision_number == 0,
        )
    )
    if existing is not None:
        detail = (
            f"'{number}' already exists in this workspace. Use Create amendment to add a revision."
            if not existing.is_deleted
            else f"A deleted original of '{number}' exists. Restore it from Deleted Entries first."
        )
        raise HTTPException(status_code=409, detail=detail)

    order = PurchaseOrder(
        organization_id=user.organization_id,
        revision_number=0,
        is_current=True,
        **payload,
    )
    db.add(order)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This PO/SO number and revision already exists") from error
    _audit(
        db,
        user=user,
        action=MasterDataAction.CREATE,
        entity_type=ORDER_ENTITY,
        entity_id=order.id,
        entity_label=_order_label(order),
        summary=f"Created {order.order_type} {order.order_number} for vendor {vendor.vendor_code}",
        request=request,
    )
    _commit(db)
    db.refresh(order)
    return _order_out(order, revision_count=1)


@router.post(
    "/po-so-orders/import",
    response_model=MasterDataImportResponse,
    dependencies=[Depends(require("master-data:import"))],
)
def import_orders(
    data: MasterDataImportRequest, request: Request, db: Db, user: Current
) -> MasterDataImportResponse:
    """Upsert original PO/SO revisions from a previewed spreadsheet.

    Amendments are never created by import — they need an explicit revision note
    and lineage, so they are raised with Create amendment in the UI.
    """
    imported = 0
    errors: list[str] = []
    seen: set[str] = set()
    vendors = {
        vendor.vendor_code.upper(): vendor
        for vendor in db.scalars(
            select(Vendor).where(
                Vendor.organization_id == user.organization_id, Vendor.is_deleted.is_(False)
            )
        ).all()
    }

    for row_number, row in enumerate(data.rows, start=1):
        normalized = _normalize_import_row(row, ORDER_IMPORT_ALIASES)
        vendor_code = str(normalized.get("vendor_code") or "").strip().upper()
        vendor = vendors.get(vendor_code)
        if vendor is None:
            errors.append(f"Row {row_number}: vendor '{vendor_code or '(blank)'}' is not an active vendor in this workspace")
            continue
        if vendor.status == "blocked":
            errors.append(f"Row {row_number}: vendor '{vendor_code}' is blocked; unblock it before importing orders")
            continue
        type_text = str(normalized.get("order_type") or "").strip().lower()
        if type_text and type_text not in ORDER_TYPE_ALIASES:
            errors.append(f"Row {row_number}: order type '{type_text}' is not recognized (use PO, SO, Callout or Others)")
            continue
        status_text = str(normalized.get("status") or "").strip().lower()
        if status_text and status_text not in ORDER_STATUS_ALIASES:
            errors.append(f"Row {row_number}: status '{status_text}' is not recognized (use open, closed or cancelled)")
            continue
        try:
            payload = _order_values(
                OrderCreate.model_validate(
                    {
                        "order_number": normalized.get("order_number"),
                        "order_type": ORDER_TYPE_ALIASES.get(type_text, "PO"),
                        "vendor_id": vendor.id,
                        "status": ORDER_STATUS_ALIASES.get(status_text, "open"),
                        "description": normalized.get("description") or "",
                    }
                ).model_dump()
            )
            payload["issue_date"] = _parse_import_date(normalized.get("issue_date"))
            payload["expiry_date"] = _parse_import_date(normalized.get("expiry_date"))
            payload = _order_values(payload)
        except ValidationError as error:
            errors.append(f"Row {row_number}: {_validation_message(error)}")
            continue
        except ValueError as error:
            errors.append(f"Row {row_number}: {error}")
            continue

        number = payload["order_number"]
        if number in seen:
            errors.append(f"Row {row_number} ({number}): duplicate PO/SO number in this import file")
            continue
        seen.add(number)

        order = db.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.organization_id == user.organization_id,
                PurchaseOrder.order_number == number,
                PurchaseOrder.revision_number == 0,
            )
        )
        if order is None:
            order = PurchaseOrder(
                organization_id=user.organization_id, revision_number=0, is_current=True, **payload
            )
            db.add(order)
            try:
                db.flush()
            except IntegrityError as error:
                db.rollback()
                errors.append(f"Row {row_number} ({number}): PO/SO number already exists")
                continue
            action = MasterDataAction.CREATE
            summary = f"Created {order.order_type} {number} from import"
        else:
            for field, value in payload.items():
                setattr(order, field, value)
            if order.is_deleted:
                order.is_deleted = False
                order.deleted_at = None
                action = MasterDataAction.RESTORE
                summary = f"Restored and updated {order.order_type} {number} from import"
            else:
                action = MasterDataAction.UPDATE
                summary = f"Updated {order.order_type} {number} from import"
        _audit(
            db,
            user=user,
            action=action,
            entity_type=ORDER_ENTITY,
            entity_id=order.id,
            entity_label=_order_label(order),
            summary=summary,
            request=request,
        )
        imported += 1

    _audit(
        db,
        user=user,
        action=MasterDataAction.IMPORT,
        entity_type=ORDER_ENTITY,
        entity_label=ORDER_LABEL,
        summary=f"Imported {imported} PO/SO orders with {len(errors)} validation errors",
        request=request,
    )
    _commit(db)
    return MasterDataImportResponse(
        imported_count=imported,
        error_count=len(errors),
        errors=errors[:100],
        success=not errors,
    )


@router.post(
    "/po-so-orders/{order_id}/amendment",
    response_model=OrderOut,
    status_code=201,
    dependencies=[Depends(require("master-data:create"))],
)
def create_amendment(
    order_id: str,
    data: OrderAmendmentCreate,
    request: Request,
    db: Db,
    user: Current,
) -> OrderOut:
    """Raise the next revision of an order, optionally carrying its files forward."""
    source = _order_or_404(db, order_id, user.organization_id, include_deleted=False)
    highest = db.scalar(
        select(func.max(PurchaseOrder.revision_number)).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == source.order_number,
        )
    ) or 0
    next_revision = highest + 1
    if next_revision > 200:
        raise HTTPException(status_code=409, detail="This order already has 200 revisions; close it instead")

    payload = {
        "order_number": source.order_number,
        "order_type": data.order_type or source.order_type,
        "vendor_id": source.vendor_id,
        "issue_date": data.issue_date if data.issue_date is not None else source.issue_date,
        "expiry_date": data.expiry_date if data.expiry_date is not None else source.expiry_date,
        "status": data.status or source.status,
        "description": source.description if data.description is None else data.description,
        "revision_note": data.revision_note,
    }
    try:
        payload = _order_values(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    payload["revision_note"] = data.revision_note

    amendment = PurchaseOrder(
        organization_id=user.organization_id,
        parent_order_id=source.id,
        revision_number=next_revision,
        is_current=True,
        **payload,
    )
    db.add(amendment)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This PO/SO number and revision already exists") from error

    siblings = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == source.order_number,
            PurchaseOrder.is_deleted.is_(False),
            PurchaseOrder.id != amendment.id,
        )
    ).all()
    for sibling in siblings:
        sibling.is_current = False

    copied = 0
    if data.copy_documents:
        for document in db.scalars(
            select(OrderDocument).where(
                OrderDocument.order_id == source.id,
                OrderDocument.organization_id == user.organization_id,
                OrderDocument.is_deleted.is_(False),
            )
        ).all():
            db.add(
                OrderDocument(
                    organization_id=user.organization_id,
                    order_id=amendment.id,
                    file_name=document.file_name,
                    content_type=document.content_type,
                    size_bytes=document.size_bytes,
                    checksum_sha256=document.checksum_sha256,
                    document_kind="amendment_copy" if document.document_kind == "po_copy" else document.document_kind,
                    label=document.label,
                    description=document.description,
                    revision_number=amendment.revision_number,
                    content=bytes(document.content),
                    uploaded_by_user_id=user.id,
                    uploaded_by_name=user.full_name,
                )
            )
            copied += 1

    copied_items = 0
    if data.copy_line_items:
        actor = (user.full_name or user.email or "")[:255]
        effective_default = amendment.issue_date or _today()
        carry_reason = f"Carried forward to order Rev {amendment.revision_number}: {amendment.revision_note}"[:500]
        for source_item in db.scalars(
            select(PurchaseOrderLineItem)
            .where(
                PurchaseOrderLineItem.order_id == source.id,
                PurchaseOrderLineItem.organization_id == user.organization_id,
                PurchaseOrderLineItem.is_deleted.is_(False),
            )
            .order_by(PurchaseOrderLineItem.sort_order, PurchaseOrderLineItem.line_item_code)
        ).all():
            cloned = PurchaseOrderLineItem(
                organization_id=user.organization_id,
                order_id=amendment.id,
                parent_line_item_id=source_item.id,
                line_item_code=source_item.line_item_code,
                vendor_code=source_item.vendor_code or "",
                description=source_item.description,
                unit_rate=source_item.unit_rate,
                currency=source_item.currency,
                effective_date=source_item.effective_date or effective_default,
                current_revision_number=1,
                added_in_order_revision=source_item.added_in_order_revision,
                sort_order=source_item.sort_order,
                created_by=actor,
                updated_by=actor,
            )
            db.add(cloned)
            db.flush()
            db.add(
                PurchaseOrderLineItemRevision(
                    organization_id=user.organization_id,
                    line_item_id=cloned.id,
                    revision_number=1,
                    change_type="order_amendment_copy",
                    unit_rate=source_item.unit_rate,
                    previous_unit_rate=source_item.unit_rate,
                    currency=source_item.currency,
                    previous_currency=source_item.currency,
                    vendor_code=source_item.vendor_code or "",
                    description=source_item.description,
                    previous_description=source_item.description,
                    effective_date=cloned.effective_date or effective_default,
                    reason=carry_reason,
                    recorded_by=actor,
                )
            )
            copied_items += 1

    _audit(
        db,
        user=user,
        action=MasterDataAction.AMEND,
        entity_type=ORDER_ENTITY,
        entity_id=amendment.id,
        entity_label=_order_label(amendment),
        summary=(
            f"Created revision {amendment.revision_number} of {amendment.order_type} "
            f"{amendment.order_number}: {amendment.revision_note}"
        ),
        request=request,
    )
    if copied:
        _audit(
            db,
            user=user,
            action=MasterDataAction.DOCUMENT_UPLOAD,
            entity_type=DOCUMENT_ENTITY,
            entity_id=amendment.id,
            entity_label=_order_label(amendment),
            summary=f"Carried {copied} file(s) forward from revision {source.revision_number} of {amendment.order_number}",
            request=request,
        )
    if copied_items:
        _audit(
            db,
            user=user,
            action=MasterDataAction.AMEND,
            entity_type=LINE_ITEM_ENTITY,
            entity_id=amendment.id,
            entity_label=_order_label(amendment),
            summary=f"Carried {copied_items} line item(s) forward from revision {source.revision_number} of {amendment.order_number}",
            request=request,
        )
    _commit(db)
    db.refresh(amendment)
    documents = _document_counts(db, user.organization_id, [amendment.id])
    line_items = _line_item_counts(db, user.organization_id, [amendment.id])
    return _order_out(
        amendment,
        document_count=documents.get(amendment.id, 0),
        line_item_count=line_items.get(amendment.id, 0),
        revision_count=next_revision + 1,
    )


@router.patch(
    "/po-so-orders/{order_id}",
    response_model=OrderOut,
    dependencies=[Depends(require("master-data:update"))],
)
def update_order(
    order_id: str,
    data: OrderUpdate,
    request: Request,
    db: Db,
    user: Current,
) -> OrderOut:
    order = _order_or_404(db, order_id, user.organization_id)
    supplied = data.model_dump(exclude_unset=True)
    if not supplied:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    merged = {
        field: getattr(order, field)
        for field in ("order_number", "order_type", "vendor_id", "issue_date", "expiry_date", "status", "description")
    }
    merged.update(supplied)
    try:
        payload = _order_values(merged)
        # The vendor is only re-checked when it actually changes, so editing the
        # description of an order keeps working whatever the vendor's state is.
        if "vendor_id" in supplied:
            _active_vendor(db, payload["vendor_id"], user.organization_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    family = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == order.order_number,
            PurchaseOrder.is_deleted.is_(False),
        )
    ).all()
    if payload["vendor_id"] != order.vendor_id and len(family) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"This order has {len(family)} revisions; the vendor of an amendment chain cannot change",
        )
    if payload["vendor_id"] != order.vendor_id:
        new_vendor = db.get(Vendor, payload["vendor_id"])
        if new_vendor is not None and new_vendor.status == "blocked":
            raise HTTPException(
                status_code=409,
                detail=f"Vendor {new_vendor.vendor_code} is blocked. Unblock it before moving orders to this vendor.",
            )

    # Work out what changed before the chain rename touches this row.
    changed = [field for field in supplied if getattr(order, field) != payload[field]]
    renamed_to = payload["order_number"] if payload["order_number"] != order.order_number else None
    if renamed_to:
        clash = db.scalar(
            select(PurchaseOrder).where(
                PurchaseOrder.organization_id == user.organization_id,
                PurchaseOrder.order_number == renamed_to,
                PurchaseOrder.id != order.id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail=f"'{renamed_to}' already exists in this workspace (revision {clash.revision_number})",
            )
        # Renaming keeps the whole amendment chain together.
        for member in family:
            member.order_number = renamed_to

    for field in supplied:
        setattr(order, field, payload[field])
    if changed:
        summary = f"Updated {order.order_type} {order.order_number} (Rev {order.revision_number}): {', '.join(sorted(changed))}"
        if renamed_to:
            summary += f" (renamed across {len(family)} revisions)"
        _audit(
            db,
            user=user,
            action=MasterDataAction.UPDATE,
            entity_type=ORDER_ENTITY,
            entity_id=order.id,
            entity_label=_order_label(order),
            summary=summary,
            request=request,
        )
        _commit(db)
        db.refresh(order)
    documents = _document_counts(db, user.organization_id, [order.id])
    line_items = _line_item_counts(db, user.organization_id, [order.id])
    revisions = _revision_counts(db, user.organization_id, [order.order_number])
    return _order_out(
        order,
        document_count=documents.get(order.id, 0),
        line_item_count=line_items.get(order.id, 0),
        revision_count=revisions.get(order.order_number, 1),
    )


@router.delete(
    "/po-so-orders/{order_id}",
    response_model=OrderOut,
    dependencies=[Depends(require("master-data:delete"))],
)
def soft_delete_order(order_id: str, request: Request, db: Db, user: Current) -> OrderOut:
    order = _order_or_404(db, order_id, user.organization_id, include_deleted=False)
    order.is_deleted = True
    order.deleted_at = datetime.now(timezone.utc)
    order.is_current = False
    _audit(
        db,
        user=user,
        action=MasterDataAction.SOFT_DELETE,
        entity_type=ORDER_ENTITY,
        entity_id=order.id,
        entity_label=_order_label(order),
        summary=f"Moved {order.order_type} {order.order_number} (Rev {order.revision_number}) to deleted entries",
        request=request,
    )
    _commit(db)
    db.refresh(order)
    line_items = _line_item_counts(db, user.organization_id, [order.id])
    return _order_out(order, line_item_count=line_items.get(order.id, 0))


@router.post(
    "/po-so-orders/{order_id}/restore",
    response_model=OrderOut,
    dependencies=[Depends(require("master-data:restore"))],
)
def restore_order(order_id: str, request: Request, db: Db, user: Current) -> OrderOut:
    order = _order_or_404(db, order_id, user.organization_id)
    if not order.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted PO/SO order can be restored")
    order.is_deleted = False
    order.deleted_at = None
    # Only the highest live revision of a number is the one to quote.
    highest = db.scalar(
        select(func.max(PurchaseOrder.revision_number)).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.order_number == order.order_number,
            PurchaseOrder.is_deleted.is_(False),
            PurchaseOrder.id != order.id,
        )
    )
    order.is_current = highest is None or order.revision_number > highest
    if order.is_current:
        for sibling in db.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.organization_id == user.organization_id,
                PurchaseOrder.order_number == order.order_number,
                PurchaseOrder.is_deleted.is_(False),
                PurchaseOrder.id != order.id,
            )
        ).all():
            sibling.is_current = False
    _audit(
        db,
        user=user,
        action=MasterDataAction.RESTORE,
        entity_type=ORDER_ENTITY,
        entity_id=order.id,
        entity_label=_order_label(order),
        summary=f"Restored {order.order_type} {order.order_number} (Rev {order.revision_number})",
        request=request,
    )
    _commit(db)
    db.refresh(order)
    documents = _document_counts(db, user.organization_id, [order.id])
    line_items = _line_item_counts(db, user.organization_id, [order.id])
    revisions = _revision_counts(db, user.organization_id, [order.order_number])
    return _order_out(
        order,
        document_count=documents.get(order.id, 0),
        line_item_count=line_items.get(order.id, 0),
        revision_count=revisions.get(order.order_number, 1),
    )


def _assert_order_purgeable(db: Session, order: PurchaseOrder, organization_id: str) -> None:
    assert_no_dependencies(db, order, organization_id, entity_label=_order_label(order))
    for item in db.scalars(
        select(PurchaseOrderLineItem).where(
            PurchaseOrderLineItem.order_id == order.id,
            PurchaseOrderLineItem.organization_id == organization_id,
        )
    ).all():
        assert_no_dependencies(
            db,
            item,
            organization_id,
            entity_label=f"{LINE_ITEM_LABEL} · {item.line_item_code} ({order.order_number})",
        )


@router.delete(
    "/po-so-orders/{order_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("master-data:permanent-delete"))],
)
def permanently_delete_order(order_id: str, request: Request, db: Db, user: Current) -> None:
    order = _order_or_404(db, order_id, user.organization_id)
    if not order.is_deleted:
        raise HTTPException(status_code=409, detail="Only a deleted PO/SO order can be permanently deleted")
    _assert_order_purgeable(db, order, user.organization_id)
    document_total = db.scalar(
        select(func.count(OrderDocument.id)).where(OrderDocument.order_id == order.id)
    ) or 0
    line_total = db.scalar(
        select(func.count(PurchaseOrderLineItem.id)).where(PurchaseOrderLineItem.order_id == order.id)
    ) or 0
    details: list[str] = []
    if line_total:
        details.append(f"{line_total} line item(s)")
    if document_total:
        details.append(f"{document_total} attached file(s)")
    _audit(
        db,
        user=user,
        action=MasterDataAction.PERMANENT_DELETE,
        entity_type=ORDER_ENTITY,
        entity_id=order.id,
        entity_label=_order_label(order),
        summary=(
            f"Permanently deleted {order.order_type} {order.order_number} (Rev {order.revision_number})"
            + (f" with {' and '.join(details)}" if details else "")
        ),
        request=request,
    )
    db.delete(order)
    _commit(db)
    return None


def _orders_for_ids(db: Session, ids: list[str], organization_id: str, *, deleted: bool) -> list[PurchaseOrder]:
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Duplicate order IDs are not allowed")
    orders = list(
        db.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.organization_id == organization_id, PurchaseOrder.id.in_(ids)
            )
        ).all()
    )
    if len(orders) != len(ids):
        raise HTTPException(status_code=404, detail="One or more PO/SO orders were not found in this workspace")
    if any(order.is_deleted is not deleted for order in orders):
        expected = "deleted" if deleted else "active"
        raise HTTPException(status_code=409, detail=f"Bulk action requires only {expected} PO/SO orders")
    return orders


@router.post(
    "/po-so-orders/bulk-delete",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:delete"))],
)
def bulk_soft_delete_orders(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    orders = _orders_for_ids(db, data.ids, user.organization_id, deleted=False)
    deleted_at = datetime.now(timezone.utc)
    for order in orders:
        order.is_deleted = True
        order.deleted_at = deleted_at
        order.is_current = False
        _audit(
            db,
            user=user,
            action=MasterDataAction.SOFT_DELETE,
            entity_type=ORDER_ENTITY,
            entity_id=order.id,
            entity_label=_order_label(order),
            summary=(
                f"Moved {order.order_type} {order.order_number} (Rev {order.revision_number}) "
                "to deleted entries (bulk action)"
            ),
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(orders))


@router.post(
    "/po-so-orders/bulk-restore",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:restore"))],
)
def bulk_restore_orders(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    orders = _orders_for_ids(db, data.ids, user.organization_id, deleted=True)
    for order in orders:
        order.is_deleted = False
        order.deleted_at = None
        _audit(
            db,
            user=user,
            action=MasterDataAction.RESTORE,
            entity_type=ORDER_ENTITY,
            entity_id=order.id,
            entity_label=_order_label(order),
            summary=f"Restored {order.order_type} {order.order_number} (Rev {order.revision_number}) (bulk action)",
            request=request,
        )
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(orders))


@router.post(
    "/po-so-orders/bulk-permanent-delete",
    response_model=MasterDataBulkActionResponse,
    dependencies=[Depends(require("master-data:permanent-delete"))],
)
def bulk_permanent_delete_orders(
    data: MasterDataIDs, request: Request, db: Db, user: Current
) -> MasterDataBulkActionResponse:
    orders = _orders_for_ids(db, data.ids, user.organization_id, deleted=True)
    for order in orders:
        _assert_order_purgeable(db, order, user.organization_id)
    for order in orders:
        _audit(
            db,
            user=user,
            action=MasterDataAction.PERMANENT_DELETE,
            entity_type=ORDER_ENTITY,
            entity_id=order.id,
            entity_label=_order_label(order),
            summary=f"Permanently deleted {order.order_type} {order.order_number} (Rev {order.revision_number}) (bulk action)",
            request=request,
        )
        db.delete(order)
    _commit(db)
    return MasterDataBulkActionResponse(affected_count=len(orders))


# --------------------------------------------------------------------------- #
# PO/SO Schedule Line Items & Rate Amendments
# --------------------------------------------------------------------------- #


def _actor_name(user: Any) -> str:
    return (getattr(user, "full_name", "") or getattr(user, "email", "") or "")[:255]


def _line_item_entity_label(item: PurchaseOrderLineItem, order: PurchaseOrder | None = None) -> str:
    order = order or item.order
    prefix = f"{order.order_number} (Rev {order.revision_number})" if order else item.order_id
    return f"{LINE_ITEM_LABEL} · {prefix} · {item.line_item_code}"


def _active_currency_map(db: Session, organization_id: str) -> dict[str, str]:
    rows = db.scalars(
        select(Currency).where(
            Currency.organization_id == organization_id,
            Currency.is_deleted.is_(False),
        )
    ).all()
    return {row.currency_code.upper(): row.currency_code for row in rows}


def _default_currency_code(db: Session, organization_id: str) -> str:
    default_code = db.scalar(
        select(Currency.currency_code).where(
            Currency.organization_id == organization_id,
            Currency.is_deleted.is_(False),
            Currency.is_default.is_(True),
        )
    )
    if default_code:
        return default_code
    any_code = db.scalar(
        select(Currency.currency_code)
        .where(Currency.organization_id == organization_id, Currency.is_deleted.is_(False))
        .order_by(Currency.currency_code)
    )
    return any_code or "USD"


def _resolve_currency(raw: Any, currencies: dict[str, str], *, fallback: str = "") -> str:
    text = str(raw or fallback or "").strip().upper()
    if not text:
        raise ValueError("Currency is required")
    if currencies:
        matched = currencies.get(text)
        if not matched:
            raise ValueError(f"Currency '{text}' is not in Currency master data")
        return matched
    if not re.fullmatch(r"[A-Z]{2,10}", text):
        raise ValueError(f"Currency '{text}' is invalid")
    return text


def _parse_rate_decimal(raw: Any, label: str = "Unit rate") -> Decimal:
    if raw in (None, ""):
        raise ValueError(f"{label} is required")
    text = str(raw).strip().replace(",", "")
    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label} '{raw}' is not a valid number") from error
    if not dec.is_finite():
        raise ValueError(f"{label} must be a finite number")
    quantized = dec.quantize(DECIMAL_QUANT, rounding=ROUND_HALF_UP)
    if quantized < Decimal("0") or quantized > MAX_RATE:
        raise ValueError(f"{label} must be between 0 and {MAX_RATE}")
    return quantized


def _next_line_sort_order(db: Session, order_id: str) -> int:
    highest = db.scalar(
        select(func.max(PurchaseOrderLineItem.sort_order)).where(
            PurchaseOrderLineItem.order_id == order_id,
        )
    )
    return (highest or 0) + 1


def _resolve_order_from_row(
    normalized: dict[str, Any],
    by_number: dict[str, list[PurchaseOrder]],
    fixed_order: PurchaseOrder | None,
) -> PurchaseOrder:
    if fixed_order is not None:
        raw_num = str(normalized.get("order_number") or "").strip().upper()
        if raw_num and raw_num != fixed_order.order_number.upper():
            raise ValueError(
                f"PO/SO number '{raw_num}' does not match selected order '{fixed_order.order_number}'"
            )
        return fixed_order
    raw_num = str(normalized.get("order_number") or "").strip().upper()
    if not raw_num:
        raise ValueError("PO/SO number is required for cross-order schedule import")
    family = by_number.get(raw_num)
    if not family:
        raise ValueError(f"PO/SO order '{raw_num}' is not an active order in this workspace")
    rev_raw = normalized.get("order_revision")
    if rev_raw not in (None, ""):
        rev_digits = re.sub(r"[^0-9]", "", str(rev_raw))
        if rev_digits == "":
            raise ValueError(f"Order revision '{rev_raw}' is not a valid revision number")
        rev_no = int(rev_digits)
        matched = next((row for row in family if row.revision_number == rev_no), None)
        if matched is None:
            raise ValueError(f"PO/SO '{raw_num}' has no active revision {rev_no}")
        return matched
    return next((row for row in family if row.is_current), None) or family[-1]


def _import_order_line_items(
    db: Session,
    *,
    user: Any,
    request: Request,
    rows: list[dict[str, Any]],
    fixed_order: PurchaseOrder | None = None,
) -> OrderLineItemImportResponse:
    organization_id = user.organization_id
    currencies = _active_currency_map(db, organization_id)
    default_currency = _default_currency_code(db, organization_id)
    actor = _actor_name(user)

    orders = (
        [fixed_order]
        if fixed_order is not None
        else list(
            db.scalars(
                select(PurchaseOrder).where(
                    PurchaseOrder.organization_id == organization_id,
                    PurchaseOrder.is_deleted.is_(False),
                )
            ).all()
        )
    )
    by_number: dict[str, list[PurchaseOrder]] = {}
    for order in orders:
        by_number.setdefault(order.order_number.upper(), []).append(order)

    created_count = 0
    revised_count = 0
    unchanged_count = 0
    errors: list[str] = []
    seen_keys: set[tuple[str, str]] = set()
    next_sort_by_order: dict[str, int] = {}

    for row_number, raw_row in enumerate(rows, start=1):
        normalized = _normalize_import_row(raw_row, LINE_ITEM_IMPORT_ALIASES)
        if not normalized:
            continue
        try:
            target_order = _resolve_order_from_row(normalized, by_number, fixed_order)
            code = str(normalized.get("line_item_code") or "").strip().upper()
            if not code:
                raise ValueError("Line item code is required")
            if len(code) > 80:
                raise ValueError("Line item code must be at most 80 characters")
            vendor_code = str(normalized.get("vendor_code") or "").strip()[:80]
            description = str(normalized.get("description") or "").strip()
            if not description:
                raise ValueError("Description is required")
            if len(description) > 2000:
                raise ValueError("Description must be at most 2000 characters")
            raw_rate = (
                normalized.get("new_unit_rate")
                if normalized.get("new_unit_rate") not in (None, "")
                else normalized.get("unit_rate")
            )
            unit_rate = _parse_rate_decimal(raw_rate, "Unit rate")
            raw_ccy = (
                normalized.get("new_currency")
                if normalized.get("new_currency") not in (None, "")
                else normalized.get("currency")
            )
            currency = _resolve_currency(raw_ccy, currencies, fallback=default_currency)
            effective_date = _parse_import_date(normalized.get("effective_date")) or target_order.issue_date or _today()
            reason = str(normalized.get("reason") or "").strip()[:500]
            sort_raw = normalized.get("sort_order")
            sort_order: int | None = None
            if sort_raw not in (None, ""):
                digits = re.sub(r"[^0-9]", "", str(sort_raw))
                if digits:
                    sort_order = max(1, min(100_000, int(digits)))
        except ValueError as error:
            errors.append(f"Row {row_number}: {error}")
            continue

        dedup_key = (target_order.id, code)
        if dedup_key in seen_keys:
            errors.append(
                f"Row {row_number} ({target_order.order_number} · {code}): duplicate line item code in this import file"
            )
            continue
        seen_keys.add(dedup_key)

        existing = db.scalar(
            select(PurchaseOrderLineItem).where(
                PurchaseOrderLineItem.organization_id == organization_id,
                PurchaseOrderLineItem.order_id == target_order.id,
                func.upper(PurchaseOrderLineItem.line_item_code) == code,
            )
        )
        if existing is None:
            if sort_order is None:
                current_next = next_sort_by_order.get(target_order.id)
                if current_next is None:
                    current_next = _next_line_sort_order(db, target_order.id)
                sort_order = current_next
                next_sort_by_order[target_order.id] = current_next + 1
            item = PurchaseOrderLineItem(
                organization_id=organization_id,
                order_id=target_order.id,
                line_item_code=code,
                vendor_code=vendor_code,
                description=description,
                unit_rate=unit_rate,
                currency=currency,
                effective_date=effective_date,
                current_revision_number=1,
                added_in_order_revision=target_order.revision_number,
                sort_order=sort_order,
                created_by=actor,
                updated_by=actor,
            )
            db.add(item)
            db.flush()
            db.add(
                PurchaseOrderLineItemRevision(
                    organization_id=organization_id,
                    line_item_id=item.id,
                    revision_number=1,
                    change_type="initial",
                    unit_rate=unit_rate,
                    previous_unit_rate=unit_rate,
                    currency=currency,
                    previous_currency=currency,
                    vendor_code=vendor_code,
                    description=description,
                    previous_description=description,
                    effective_date=effective_date,
                    reason=reason or "Imported PO/SO schedule",
                    recorded_by=actor,
                )
            )
            _audit(
                db,
                user=user,
                action=MasterDataAction.CREATE,
                entity_type=LINE_ITEM_ENTITY,
                entity_id=item.id,
                entity_label=_line_item_entity_label(item, target_order),
                summary=f"Created line item {code} ({currency} {unit_rate}) on {target_order.order_number} from import",
                request=request,
            )
            created_count += 1
        else:
            was_deleted = existing.is_deleted
            price_changed = existing.unit_rate != unit_rate or existing.currency != currency
            detail_changed = (existing.description or "") != description or (existing.vendor_code or "") != vendor_code
            if was_deleted:
                existing.is_deleted = False
                existing.deleted_at = None
            if sort_order is not None:
                existing.sort_order = sort_order
            if price_changed or detail_changed:
                prev_rate = existing.unit_rate
                prev_ccy = existing.currency
                prev_desc = existing.description or ""
                next_rev = existing.current_revision_number + 1
                existing.unit_rate = unit_rate
                existing.currency = currency
                existing.vendor_code = vendor_code
                existing.description = description
                existing.effective_date = effective_date
                existing.current_revision_number = next_rev
                existing.updated_by = actor
                db.add(
                    PurchaseOrderLineItemRevision(
                        organization_id=organization_id,
                        line_item_id=existing.id,
                        revision_number=next_rev,
                        change_type="price_revision" if price_changed else "detail_amendment",
                        unit_rate=unit_rate,
                        previous_unit_rate=prev_rate,
                        currency=currency,
                        previous_currency=prev_ccy,
                        vendor_code=vendor_code,
                        description=description,
                        previous_description=prev_desc,
                        effective_date=effective_date,
                        reason=reason or "Amended via spreadsheet schedule import",
                        recorded_by=actor,
                    )
                )
                _audit(
                    db,
                    user=user,
                    action=MasterDataAction.AMEND,
                    entity_type=LINE_ITEM_ENTITY,
                    entity_id=existing.id,
                    entity_label=_line_item_entity_label(existing, target_order),
                    summary=(
                        f"Amended line item {code} on {target_order.order_number} from import "
                        f"(Rev {next_rev}: {prev_ccy} {prev_rate} -> {currency} {unit_rate})"
                    ),
                    request=request,
                )
                revised_count += 1
            elif was_deleted:
                existing.updated_by = actor
                _audit(
                    db,
                    user=user,
                    action=MasterDataAction.RESTORE,
                    entity_type=LINE_ITEM_ENTITY,
                    entity_id=existing.id,
                    entity_label=_line_item_entity_label(existing, target_order),
                    summary=f"Restored line item {code} on {target_order.order_number} from import",
                    request=request,
                )
                revised_count += 1
            else:
                unchanged_count += 1

    imported_total = created_count + revised_count
    scope_label = _order_label(fixed_order) if fixed_order else LINE_ITEM_LABEL
    _audit(
        db,
        user=user,
        action=MasterDataAction.IMPORT,
        entity_type=LINE_ITEM_ENTITY,
        entity_id=fixed_order.id if fixed_order else None,
        entity_label=scope_label,
        summary=(
            f"Imported PO/SO line items ({created_count} created, {revised_count} amended, "
            f"{unchanged_count} unchanged, {len(errors)} errors)"
        ),
        request=request,
    )
    _commit(db)
    return OrderLineItemImportResponse(
        imported_count=imported_total,
        created_count=created_count,
        revised_count=revised_count,
        unchanged_count=unchanged_count,
        error_count=len(errors),
        errors=errors[:100],
        success=not errors,
    )


def _bulk_revise_order_line_items(
    db: Session,
    *,
    user: Any,
    request: Request,
    data: OrderLineItemBulkReviseRequest,
    fixed_order: PurchaseOrder | None = None,
) -> OrderLineItemBulkReviseResponse:
    """Atomic all-or-nothing bulk rate/schedule amendment across one or many PO/SO orders."""
    organization_id = user.organization_id
    currencies = _active_currency_map(db, organization_id)
    default_currency = _default_currency_code(db, organization_id)
    default_effective = data.effective_date or _today()
    actor = _actor_name(user)

    orders = (
        [fixed_order]
        if fixed_order is not None
        else list(
            db.scalars(
                select(PurchaseOrder).where(
                    PurchaseOrder.organization_id == organization_id,
                    PurchaseOrder.is_deleted.is_(False),
                )
            ).all()
        )
    )
    by_number: dict[str, list[PurchaseOrder]] = {}
    for order in orders:
        by_number.setdefault(order.order_number.upper(), []).append(order)

    order_ids = [order.id for order in orders]
    existing_items = (
        list(
            db.scalars(
                select(PurchaseOrderLineItem).where(
                    PurchaseOrderLineItem.organization_id == organization_id,
                    PurchaseOrderLineItem.order_id.in_(order_ids),
                    PurchaseOrderLineItem.is_deleted.is_(False),
                )
            ).all()
        )
        if order_ids
        else []
    )
    items_by_key = {(item.order_id, item.line_item_code.upper()): item for item in existing_items}

    staged: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    seen_keys: set[tuple[str, str]] = set()
    skipped_count = 0

    for row_number, raw_row in enumerate(data.rows, start=2):
        normalized = _normalize_import_row(raw_row, LINE_ITEM_IMPORT_ALIASES)
        if not normalized:
            skipped_count += 1
            continue
        # If a template row left new_unit_rate blank, skip it cleanly (matches catalogue bulk revise).
        has_explicit_new = "new_unit_rate" in normalized
        raw_rate = normalized.get("new_unit_rate") if has_explicit_new else normalized.get("unit_rate")
        if raw_rate in (None, ""):
            skipped_count += 1
            continue
        try:
            target_order = _resolve_order_from_row(normalized, by_number, fixed_order)
            code = str(normalized.get("line_item_code") or "").strip().upper()
            if not code:
                raise ValueError("Line item code is required")
            key = (target_order.id, code)
            if key in seen_keys:
                raise ValueError(f"Duplicate line item '{code}' for {target_order.order_number} in this file")
            seen_keys.add(key)

            existing = items_by_key.get(key)
            if existing is None and not data.allow_new_items:
                raise ValueError(
                    f"Line item '{code}' was not found on {target_order.order_number} (Rev {target_order.revision_number})"
                )

            unit_rate = _parse_rate_decimal(raw_rate, "New unit rate")
            raw_ccy = normalized.get("new_currency") or normalized.get("currency")
            fallback_ccy = existing.currency if existing is not None else default_currency
            currency = _resolve_currency(raw_ccy, currencies, fallback=fallback_ccy)
            effective_date = _parse_import_date(normalized.get("effective_date")) or default_effective
            row_reason = str(normalized.get("reason") or "").strip()[:500] or data.reason
            description = str(normalized.get("description") or "").strip()
            vendor_code_supplied = "vendor_code" in normalized
            vendor_code = str(normalized.get("vendor_code") or "").strip()[:80]
            if existing is None and not description:
                raise ValueError(f"Description is required when adding new line item '{code}'")
        except ValueError as error:
            errors.append(f"Row {row_number}: {error}")
            continue

        staged.append(
            {
                "order": target_order,
                "existing": existing,
                "code": code,
                "unit_rate": unit_rate,
                "currency": currency,
                "effective_date": effective_date,
                "reason": row_reason,
                "description": description,
                "vendor_code_supplied": vendor_code_supplied,
                "vendor_code": vendor_code,
            }
        )

    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Bulk rate revision rejected: {len(errors)} validation error(s); no line items were changed.",
                "errors": errors[:100],
                "warnings": warnings[:50],
            },
        )

    revised_count = 0
    added_count = 0
    unchanged_count = 0
    next_sort_by_order: dict[str, int] = {}

    for entry in staged:
        target_order = entry["order"]
        existing = entry["existing"]
        code = entry["code"]
        unit_rate = entry["unit_rate"]
        currency = entry["currency"]
        effective_date = entry["effective_date"]
        row_reason = entry["reason"]

        if existing is None:
            current_next = next_sort_by_order.get(target_order.id)
            if current_next is None:
                current_next = _next_line_sort_order(db, target_order.id)
            next_sort_by_order[target_order.id] = current_next + 1
            item = PurchaseOrderLineItem(
                organization_id=organization_id,
                order_id=target_order.id,
                line_item_code=code,
                vendor_code=entry["vendor_code"],
                description=entry["description"],
                unit_rate=unit_rate,
                currency=currency,
                effective_date=effective_date,
                current_revision_number=1,
                added_in_order_revision=target_order.revision_number,
                sort_order=current_next,
                created_by=actor,
                updated_by=actor,
            )
            db.add(item)
            db.flush()
            db.add(
                PurchaseOrderLineItemRevision(
                    organization_id=organization_id,
                    line_item_id=item.id,
                    revision_number=1,
                    change_type="initial",
                    unit_rate=unit_rate,
                    previous_unit_rate=unit_rate,
                    currency=currency,
                    previous_currency=currency,
                    vendor_code=item.vendor_code,
                    description=item.description,
                    previous_description=item.description,
                    effective_date=effective_date,
                    reason=row_reason,
                    recorded_by=actor,
                )
            )
            added_count += 1
            continue

        new_desc = entry["description"] or existing.description
        new_vendor_code = entry["vendor_code"] if entry["vendor_code_supplied"] else (existing.vendor_code or "")
        price_changed = existing.unit_rate != unit_rate or existing.currency != currency
        detail_changed = (existing.description or "") != new_desc or (existing.vendor_code or "") != new_vendor_code
        if not price_changed and not detail_changed:
            unchanged_count += 1
            continue

        prev_rate = existing.unit_rate
        prev_ccy = existing.currency
        prev_desc = existing.description or ""
        next_rev = existing.current_revision_number + 1
        existing.unit_rate = unit_rate
        existing.currency = currency
        existing.description = new_desc
        existing.vendor_code = new_vendor_code
        existing.effective_date = effective_date
        existing.current_revision_number = next_rev
        existing.updated_by = actor
        db.add(
            PurchaseOrderLineItemRevision(
                organization_id=organization_id,
                line_item_id=existing.id,
                revision_number=next_rev,
                change_type="price_revision" if price_changed else "detail_amendment",
                unit_rate=unit_rate,
                previous_unit_rate=prev_rate,
                currency=currency,
                previous_currency=prev_ccy,
                vendor_code=new_vendor_code,
                description=new_desc,
                previous_description=prev_desc,
                effective_date=effective_date,
                reason=row_reason,
                recorded_by=actor,
            )
        )
        revised_count += 1

    scope_label = _order_label(fixed_order) if fixed_order else LINE_ITEM_LABEL
    _audit(
        db,
        user=user,
        action=MasterDataAction.AMEND,
        entity_type=LINE_ITEM_ENTITY,
        entity_id=fixed_order.id if fixed_order else None,
        entity_label=scope_label,
        summary=(
            f"Bulk revised PO/SO schedule ({revised_count} revised, {added_count} added, "
            f"{unchanged_count} unchanged): {data.reason}"
        ),
        request=request,
    )
    _commit(db)
    return OrderLineItemBulkReviseResponse(
        revised_count=revised_count,
        added_count=added_count,
        unchanged_count=unchanged_count,
        skipped_count=skipped_count,
        error_count=0,
        effective_date=default_effective,
        errors=[],
        warnings=warnings,
    )


@router.get(
    "/po-so-orders/line-items",
    response_model=list[OrderLineItemOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_all_order_line_items(
    db: Db,
    user: Current,
    order_id: str | None = None,
    vendor_id: str | None = None,
    current_orders_only: bool = True,
    include_deleted: bool = False,
) -> list[OrderLineItemOut]:
    """List PO/SO schedule line items across one or all orders for export and audit."""
    statement = (
        select(PurchaseOrderLineItem)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLineItem.order_id)
        .where(
            PurchaseOrderLineItem.organization_id == user.organization_id,
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.is_deleted.is_(False),
        )
    )
    if order_id:
        statement = statement.where(PurchaseOrderLineItem.order_id == order_id)
    elif current_orders_only:
        statement = statement.where(PurchaseOrder.is_current.is_(True))
    if vendor_id:
        statement = statement.where(PurchaseOrder.vendor_id == vendor_id)
    if not include_deleted:
        statement = statement.where(PurchaseOrderLineItem.is_deleted.is_(False))

    items = db.scalars(
        statement.order_by(
            PurchaseOrder.order_number,
            PurchaseOrder.revision_number.desc(),
            PurchaseOrderLineItem.sort_order,
            PurchaseOrderLineItem.line_item_code,
        )
    ).all()
    return [_line_item_out(item, item.order) for item in items]


@router.get(
    "/po-so-orders/line-items/price-revision-template",
    dependencies=[Depends(require("master-data:read"))],
)
def download_line_item_price_revision_template(
    db: Db,
    user: Current,
    order_id: str | None = None,
    current_orders_only: bool = True,
) -> Response:
    """Download a pre-populated CSV template for bulk PO/SO schedule price revisions."""
    statement = (
        select(PurchaseOrderLineItem)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLineItem.order_id)
        .where(
            PurchaseOrderLineItem.organization_id == user.organization_id,
            PurchaseOrderLineItem.is_deleted.is_(False),
            PurchaseOrder.is_deleted.is_(False),
        )
    )
    target_order: PurchaseOrder | None = None
    if order_id:
        target_order = _order_or_404(db, order_id, user.organization_id, include_deleted=False)
        statement = statement.where(PurchaseOrderLineItem.order_id == target_order.id)
    elif current_orders_only:
        statement = statement.where(PurchaseOrder.is_current.is_(True))

    items = db.scalars(
        statement.order_by(
            PurchaseOrder.order_number,
            PurchaseOrderLineItem.sort_order,
            PurchaseOrderLineItem.line_item_code,
        )
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "order_number",
            "order_revision",
            "order_vendor_code",
            "line_item_code",
            "vendor_code",
            "description",
            "current_unit_rate",
            "currency",
            "new_unit_rate",
            "new_currency",
            "effective_date",
            "reason",
        ]
    )
    if items:
        for item in items:
            order = item.order
            vendor = order.vendor if order else None
            writer.writerow(
                [
                    safe_csv_cell(order.order_number if order else ""),
                    order.revision_number if order else 0,
                    safe_csv_cell(vendor.vendor_code if vendor else ""),
                    safe_csv_cell(item.line_item_code),
                    safe_csv_cell(item.vendor_code or ""),
                    safe_csv_cell(item.description or ""),
                    f"{item.unit_rate:.3f}",
                    safe_csv_cell(item.currency),
                    "",
                    "",
                    _today().isoformat(),
                    "",
                ]
            )
    elif target_order is not None:
        vendor = target_order.vendor
        ccy = _default_currency_code(db, user.organization_id)
        writer.writerow(
            [
                safe_csv_cell(target_order.order_number),
                target_order.revision_number,
                safe_csv_cell(vendor.vendor_code if vendor else ""),
                "LINE-001",
                "",
                "Sample PO/SO schedule item description",
                "0.000",
                ccy,
                "100.000",
                ccy,
                _today().isoformat(),
                "Initial schedule rate",
            ]
        )

    filename = (
        f"{target_order.order_number}_Rev{target_order.revision_number}_schedule_rates.csv"
        if target_order is not None
        else "po_so_line_items_price_revision_template.csv"
    )
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": _content_disposition("attachment", filename),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/po-so-orders/line-items/import",
    response_model=OrderLineItemImportResponse,
    dependencies=[Depends(require("master-data:import"))],
)
def import_all_order_line_items(
    data: MasterDataImportRequest,
    request: Request,
    db: Db,
    user: Current,
) -> OrderLineItemImportResponse:
    return _import_order_line_items(db, user=user, request=request, rows=data.rows, fixed_order=None)


@router.post(
    "/po-so-orders/line-items/bulk-revise",
    response_model=OrderLineItemBulkReviseResponse,
    dependencies=[Depends(require("master-data:import"))],
)
def bulk_revise_all_order_line_items(
    data: OrderLineItemBulkReviseRequest,
    request: Request,
    db: Db,
    user: Current,
) -> OrderLineItemBulkReviseResponse:
    return _bulk_revise_order_line_items(db, user=user, request=request, data=data, fixed_order=None)


@router.get(
    "/po-so-orders/{order_id}/line-items",
    response_model=list[OrderLineItemOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_order_line_items(
    order_id: str,
    db: Db,
    user: Current,
    include_deleted: bool = False,
) -> list[OrderLineItemOut]:
    order = _order_or_404(db, order_id, user.organization_id)
    statement = select(PurchaseOrderLineItem).where(
        PurchaseOrderLineItem.order_id == order.id,
        PurchaseOrderLineItem.organization_id == user.organization_id,
    )
    if not include_deleted:
        statement = statement.where(PurchaseOrderLineItem.is_deleted.is_(False))
    items = db.scalars(
        statement.order_by(PurchaseOrderLineItem.sort_order, PurchaseOrderLineItem.line_item_code)
    ).all()
    return [_line_item_out(item, order) for item in items]


@router.post(
    "/po-so-orders/{order_id}/line-items",
    response_model=OrderLineItemOut,
    status_code=201,
    dependencies=[Depends(require("master-data:create"))],
)
def create_order_line_item(
    order_id: str,
    data: OrderLineItemCreate,
    request: Request,
    db: Db,
    user: Current,
) -> OrderLineItemOut:
    order = _order_or_404(db, order_id, user.organization_id, include_deleted=False)
    currencies = _active_currency_map(db, user.organization_id)
    code = data.line_item_code.strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail="Line item code is required")
    try:
        currency = _resolve_currency(data.currency, currencies)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    duplicate = db.scalar(
        select(PurchaseOrderLineItem).where(
            PurchaseOrderLineItem.organization_id == user.organization_id,
            PurchaseOrderLineItem.order_id == order.id,
            func.upper(PurchaseOrderLineItem.line_item_code) == code,
        )
    )
    if duplicate is not None:
        detail = (
            f"Line item code '{code}' already exists on {order.order_number} (Rev {order.revision_number})."
            if not duplicate.is_deleted
            else f"A removed line item '{code}' exists on {order.order_number}; restore it first."
        )
        raise HTTPException(status_code=409, detail=detail)

    actor = _actor_name(user)
    effective = data.effective_date or order.issue_date or _today()
    sort_order = data.sort_order if data.sort_order is not None else _next_line_sort_order(db, order.id)
    item = PurchaseOrderLineItem(
        organization_id=user.organization_id,
        order_id=order.id,
        line_item_code=code,
        vendor_code=data.vendor_code or "",
        description=data.description,
        unit_rate=data.unit_rate,
        currency=currency,
        effective_date=effective,
        current_revision_number=1,
        added_in_order_revision=order.revision_number,
        sort_order=sort_order,
        created_by=actor,
        updated_by=actor,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Line item code '{code}' already exists on this order") from error

    db.add(
        PurchaseOrderLineItemRevision(
            organization_id=user.organization_id,
            line_item_id=item.id,
            revision_number=1,
            change_type="initial",
            unit_rate=item.unit_rate,
            previous_unit_rate=item.unit_rate,
            currency=item.currency,
            previous_currency=item.currency,
            vendor_code=item.vendor_code,
            description=item.description,
            previous_description=item.description,
            effective_date=effective,
            reason="Initial PO/SO schedule rate",
            recorded_by=actor,
        )
    )
    _audit(
        db,
        user=user,
        action=MasterDataAction.CREATE,
        entity_type=LINE_ITEM_ENTITY,
        entity_id=item.id,
        entity_label=_line_item_entity_label(item, order),
        summary=f"Added line item {item.line_item_code} ({item.currency} {item.unit_rate}) to {order.order_number} (Rev {order.revision_number})",
        request=request,
    )
    _commit(db)
    db.refresh(item)
    return _line_item_out(item, order)


@router.post(
    "/po-so-orders/{order_id}/line-items/import",
    response_model=OrderLineItemImportResponse,
    dependencies=[Depends(require("master-data:import"))],
)
def import_single_order_line_items(
    order_id: str,
    data: MasterDataImportRequest,
    request: Request,
    db: Db,
    user: Current,
) -> OrderLineItemImportResponse:
    order = _order_or_404(db, order_id, user.organization_id, include_deleted=False)
    return _import_order_line_items(db, user=user, request=request, rows=data.rows, fixed_order=order)


@router.post(
    "/po-so-orders/{order_id}/line-items/bulk-revise",
    response_model=OrderLineItemBulkReviseResponse,
    dependencies=[Depends(require("master-data:import"))],
)
def bulk_revise_single_order_line_items(
    order_id: str,
    data: OrderLineItemBulkReviseRequest,
    request: Request,
    db: Db,
    user: Current,
) -> OrderLineItemBulkReviseResponse:
    order = _order_or_404(db, order_id, user.organization_id, include_deleted=False)
    return _bulk_revise_order_line_items(db, user=user, request=request, data=data, fixed_order=order)


@router.patch(
    "/po-so-orders/line-items/{line_item_id}",
    response_model=OrderLineItemOut,
    dependencies=[Depends(require("master-data:update"))],
)
def update_order_line_item(
    line_item_id: str,
    data: OrderLineItemUpdate,
    request: Request,
    db: Db,
    user: Current,
) -> OrderLineItemOut:
    item = _line_item_or_404(db, line_item_id, user.organization_id, include_deleted=False)
    order = item.order
    supplied = data.model_dump(exclude_unset=True)
    if not supplied:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")

    changed: list[str] = []
    if "line_item_code" in supplied and supplied["line_item_code"] is not None:
        new_code = supplied["line_item_code"].strip().upper()
        if not new_code:
            raise HTTPException(status_code=422, detail="Line item code cannot be blank")
        if new_code != item.line_item_code:
            clash = db.scalar(
                select(PurchaseOrderLineItem).where(
                    PurchaseOrderLineItem.organization_id == user.organization_id,
                    PurchaseOrderLineItem.order_id == item.order_id,
                    func.upper(PurchaseOrderLineItem.line_item_code) == new_code,
                    PurchaseOrderLineItem.id != item.id,
                )
            )
            if clash is not None:
                raise HTTPException(status_code=409, detail=f"Line item code '{new_code}' already exists on this order")
            item.line_item_code = new_code
            changed.append("line_item_code")
    if "vendor_code" in supplied and supplied["vendor_code"] is not None:
        clean_vc = supplied["vendor_code"].strip()
        if clean_vc != (item.vendor_code or ""):
            item.vendor_code = clean_vc
            changed.append("vendor_code")
    if "description" in supplied and supplied["description"] is not None:
        clean_desc = supplied["description"].strip()
        if not clean_desc:
            raise HTTPException(status_code=422, detail="Description cannot be blank")
        if clean_desc != (item.description or ""):
            item.description = clean_desc
            changed.append("description")
    if "sort_order" in supplied and supplied["sort_order"] is not None:
        if supplied["sort_order"] != item.sort_order:
            item.sort_order = supplied["sort_order"]
            changed.append("sort_order")

    if changed:
        item.updated_by = _actor_name(user)
        _audit(
            db,
            user=user,
            action=MasterDataAction.UPDATE,
            entity_type=LINE_ITEM_ENTITY,
            entity_id=item.id,
            entity_label=_line_item_entity_label(item, order),
            summary=f"Updated line item {item.line_item_code} on {order.order_number}: {', '.join(sorted(changed))}",
            request=request,
        )
        _commit(db)
        db.refresh(item)
    return _line_item_out(item, order)


@router.post(
    "/po-so-orders/line-items/{line_item_id}/amend",
    response_model=OrderLineItemOut,
    dependencies=[Depends(require("master-data:update"))],
)
def amend_order_line_item(
    line_item_id: str,
    data: OrderLineItemAmend,
    request: Request,
    db: Db,
    user: Current,
) -> OrderLineItemOut:
    """Record an audited rate, currency or schedule amendment on a PO/SO line item."""
    item = _line_item_or_404(db, line_item_id, user.organization_id, include_deleted=False)
    order = item.order
    currencies = _active_currency_map(db, user.organization_id)
    try:
        currency = _resolve_currency(data.currency, currencies)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    new_desc = data.description.strip() if data.description is not None else item.description
    new_vendor_code = data.vendor_code.strip() if data.vendor_code is not None else (item.vendor_code or "")
    price_changed = item.unit_rate != data.unit_rate or item.currency != currency
    detail_changed = (item.description or "") != new_desc or (item.vendor_code or "") != new_vendor_code
    if not price_changed and not detail_changed:
        raise HTTPException(
            status_code=422,
            detail="No change detected in unit rate, currency, vendor code or description",
        )

    actor = _actor_name(user)
    prev_rate = item.unit_rate
    prev_ccy = item.currency
    prev_desc = item.description or ""
    effective = data.effective_date or _today()
    next_rev = item.current_revision_number + 1

    item.unit_rate = data.unit_rate
    item.currency = currency
    item.description = new_desc
    item.vendor_code = new_vendor_code
    item.effective_date = effective
    item.current_revision_number = next_rev
    item.updated_by = actor

    db.add(
        PurchaseOrderLineItemRevision(
            organization_id=user.organization_id,
            line_item_id=item.id,
            revision_number=next_rev,
            change_type="price_revision" if price_changed else "detail_amendment",
            unit_rate=item.unit_rate,
            previous_unit_rate=prev_rate,
            currency=item.currency,
            previous_currency=prev_ccy,
            vendor_code=item.vendor_code,
            description=item.description,
            previous_description=prev_desc,
            effective_date=effective,
            reason=data.reason,
            recorded_by=actor,
        )
    )
    _audit(
        db,
        user=user,
        action=MasterDataAction.AMEND,
        entity_type=LINE_ITEM_ENTITY,
        entity_id=item.id,
        entity_label=_line_item_entity_label(item, order),
        summary=(
            f"Amended line item {item.line_item_code} on {order.order_number} "
            f"(Rev {next_rev}: {prev_ccy} {prev_rate} -> {item.currency} {item.unit_rate}; {data.reason})"
        ),
        request=request,
    )
    _commit(db)
    db.refresh(item)
    return _line_item_out(item, order)


@router.get(
    "/po-so-orders/line-items/{line_item_id}/revisions",
    response_model=list[OrderLineItemRevisionOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_order_line_item_revisions(
    line_item_id: str,
    db: Db,
    user: Current,
) -> list[OrderLineItemRevisionOut]:
    item = _line_item_or_404(db, line_item_id, user.organization_id)
    revisions = db.scalars(
        select(PurchaseOrderLineItemRevision)
        .where(
            PurchaseOrderLineItemRevision.line_item_id == item.id,
            PurchaseOrderLineItemRevision.organization_id == user.organization_id,
        )
        .order_by(PurchaseOrderLineItemRevision.revision_number.desc())
    ).all()
    return [_line_item_revision_out(row) for row in revisions]


@router.delete(
    "/po-so-orders/line-items/{line_item_id}",
    response_model=OrderLineItemOut,
    dependencies=[Depends(require("master-data:delete"))],
)
def soft_delete_order_line_item(
    line_item_id: str,
    request: Request,
    db: Db,
    user: Current,
) -> OrderLineItemOut:
    item = _line_item_or_404(db, line_item_id, user.organization_id, include_deleted=False)
    order = item.order
    item.is_deleted = True
    item.deleted_at = datetime.now(timezone.utc)
    item.updated_by = _actor_name(user)
    _audit(
        db,
        user=user,
        action=MasterDataAction.SOFT_DELETE,
        entity_type=LINE_ITEM_ENTITY,
        entity_id=item.id,
        entity_label=_line_item_entity_label(item, order),
        summary=f"Removed line item {item.line_item_code} from {order.order_number} (Rev {order.revision_number})",
        request=request,
    )
    _commit(db)
    db.refresh(item)
    return _line_item_out(item, order)


@router.post(
    "/po-so-orders/line-items/{line_item_id}/restore",
    response_model=OrderLineItemOut,
    dependencies=[Depends(require("master-data:restore"))],
)
def restore_order_line_item(
    line_item_id: str,
    request: Request,
    db: Db,
    user: Current,
) -> OrderLineItemOut:
    item = _line_item_or_404(db, line_item_id, user.organization_id)
    if not item.is_deleted:
        raise HTTPException(status_code=409, detail="Only a removed PO/SO line item can be restored")
    order = item.order
    item.is_deleted = False
    item.deleted_at = None
    item.updated_by = _actor_name(user)
    _audit(
        db,
        user=user,
        action=MasterDataAction.RESTORE,
        entity_type=LINE_ITEM_ENTITY,
        entity_id=item.id,
        entity_label=_line_item_entity_label(item, order),
        summary=f"Restored line item {item.line_item_code} to {order.order_number} (Rev {order.revision_number})",
        request=request,
    )
    _commit(db)
    db.refresh(item)
    return _line_item_out(item, order)


@router.delete(
    "/po-so-orders/line-items/{line_item_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("master-data:permanent-delete"))],
)
def permanently_delete_order_line_item(
    line_item_id: str,
    request: Request,
    db: Db,
    user: Current,
) -> None:
    item = _line_item_or_404(db, line_item_id, user.organization_id)
    if not item.is_deleted:
        raise HTTPException(status_code=409, detail="Only a removed PO/SO line item can be permanently deleted")
    order = item.order
    label = _line_item_entity_label(item, order)
    assert_no_dependencies(db, item, user.organization_id, entity_label=label)
    _audit(
        db,
        user=user,
        action=MasterDataAction.PERMANENT_DELETE,
        entity_type=LINE_ITEM_ENTITY,
        entity_id=item.id,
        entity_label=label,
        summary=f"Permanently deleted line item {item.line_item_code} from {order.order_number} (Rev {order.revision_number})",
        request=request,
    )
    db.delete(item)
    _commit(db)
    return None


# --------------------------------------------------------------------------- #
# Documents attached to a PO/SO revision
# --------------------------------------------------------------------------- #


@router.post(
    "/po-so-orders/documents/bulk",
    response_model=DocumentUploadResult,
    dependencies=[Depends(require("master-data:document-upload"))],
)
async def bulk_upload_documents(
    request: Request,
    db: Db,
    user: Current,
    files: list[UploadFile] = File(...),
    document_kind: str = Form("po_copy"),
) -> DocumentUploadResult:
    """Attach many files at once, matching each file name to an order number.

    File names are read as ``<ORDER NUMBER>`` or ``<ORDER NUMBER>_Rev2``
    (``_2`` and ``__2`` also work); an unmatched file is reported, never guessed.
    """
    if document_kind not in DOCUMENT_KINDS:
        raise HTTPException(status_code=422, detail=f"Document kind must be one of {', '.join(DOCUMENT_KINDS)}")
    orders = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.organization_id == user.organization_id,
            PurchaseOrder.is_deleted.is_(False),
        )
    ).all()
    by_number: dict[str, list[PurchaseOrder]] = {}
    for order in orders:
        by_number.setdefault(order.order_number.upper(), []).append(order)

    items: list[DocumentUploadItem] = []
    uploaded = 0
    for upload in files:
        filename = (upload.filename or "").strip()
        try:
            content, filename = _read_upload(upload)
        except ValueError as error:
            items.append(DocumentUploadItem(file_name=filename or "(unnamed)", accepted=False, message=str(error)))
            continue

        hint, revision_hint = _split_revision_hint(filename)
        family = by_number.get(hint.upper())
        matched_revision = revision_hint
        if family is None:
            # Fall back to the longest order number that appears in the file name.
            candidates = [
                number for number in by_number if number and number.upper() in filename.upper()
            ]
            if not candidates:
                items.append(
                    DocumentUploadItem(
                        file_name=filename,
                        accepted=False,
                        message="No active PO/SO number matches this file name",
                    )
                )
                continue
            family = by_number[max(candidates, key=len)]
            matched_revision = None

        target = None
        if matched_revision is not None:
            target = next((row for row in family if row.revision_number == matched_revision), None)
        if target is None:
            target = next((row for row in family if row.is_current), None) or family[-1]
        try:
            document = _store_document(
                db,
                order=target,
                user=user,
                content=content,
                filename=filename,
                content_type=upload.content_type or "application/octet-stream",
                document_kind=document_kind,
                label="",
                notes="Attached by bulk upload",
            )
            db.flush()
        except ValueError as error:
            items.append(
                DocumentUploadItem(
                    file_name=filename,
                    order_number=target.order_number,
                    revision_number=target.revision_number,
                    accepted=False,
                    message=str(error),
                )
            )
            continue

        _audit(
            db,
            user=user,
            action=MasterDataAction.DOCUMENT_UPLOAD,
            entity_type=DOCUMENT_ENTITY,
            entity_id=document.id,
            entity_label=f"{DOCUMENT_LABEL} · {filename}",
            summary=(
                f"Attached {filename} ({_human_size(len(content))}) to {target.order_type} "
                f"{target.order_number} (Rev {target.revision_number}) by bulk upload"
            ),
            request=request,
        )
        uploaded += 1
        items.append(
            DocumentUploadItem(
                file_name=filename,
                order_number=target.order_number,
                revision_number=target.revision_number,
                document_id=document.id,
                accepted=True,
                message=f"Attached to {target.order_number} (Rev {target.revision_number})",
            )
        )

    _commit(db)
    return DocumentUploadResult(
        uploaded_count=uploaded,
        rejected_count=len(items) - uploaded,
        items=items,
    )


@router.get(
    "/po-so-orders/{order_id}/documents",
    response_model=list[DocumentOut],
    dependencies=[Depends(require("master-data:read"))],
)
def list_documents(order_id: str, db: Db, user: Current, include_deleted: bool = False) -> list[DocumentOut]:
    order = _order_or_404(db, order_id, user.organization_id)
    statement = select(OrderDocument).where(
        OrderDocument.order_id == order.id, OrderDocument.organization_id == user.organization_id
    )
    if not include_deleted:
        statement = statement.where(OrderDocument.is_deleted.is_(False))
    documents = db.scalars(statement.order_by(OrderDocument.created_at, OrderDocument.id)).all()
    return [_document_out(document, order) for document in documents]


@router.post(
    "/po-so-orders/{order_id}/documents",
    response_model=DocumentUploadResult,
    status_code=201,
    dependencies=[Depends(require("master-data:document-upload"))],
)
async def upload_documents(
    order_id: str,
    request: Request,
    db: Db,
    user: Current,
    files: list[UploadFile] = File(...),
    document_kind: str = Form("po_copy"),
    label: str = Form(""),
    notes: str = Form(""),
) -> DocumentUploadResult:
    """Attach one or more scanned copies to a PO/SO revision.

    Each file is reported on its own, so one rejected file (wrong type, empty,
    duplicate) never hides behind the files that were accepted.
    """
    order = _order_or_404(db, order_id, user.organization_id, include_deleted=False)
    if document_kind not in DOCUMENT_KINDS:
        raise HTTPException(status_code=422, detail=f"Document kind must be one of {', '.join(DOCUMENT_KINDS)}")

    items: list[DocumentUploadItem] = []
    uploaded = 0
    for upload in files:
        filename = (upload.filename or "").strip()
        try:
            content, filename = _read_upload(upload)
            document = _store_document(
                db,
                order=order,
                user=user,
                content=content,
                filename=filename,
                content_type=upload.content_type or "application/octet-stream",
                document_kind=document_kind,
                label=label.strip(),
                notes=notes.strip(),
            )
            db.flush()
            _audit(
                db,
                user=user,
                action=MasterDataAction.DOCUMENT_UPLOAD,
                entity_type=DOCUMENT_ENTITY,
                entity_id=document.id,
                entity_label=f"{DOCUMENT_LABEL} · {filename}",
                summary=(
                    f"Attached {filename} ({_human_size(len(content))}) to {order.order_type} "
                    f"{order.order_number} (Rev {order.revision_number})"
                ),
                request=request,
            )
        except ValueError as error:
            items.append(
                DocumentUploadItem(
                    file_name=filename or "(unnamed)",
                    order_number=order.order_number,
                    revision_number=order.revision_number,
                    accepted=False,
                    message=str(error),
                )
            )
            continue

        uploaded += 1
        items.append(
            DocumentUploadItem(
                file_name=filename,
                order_number=order.order_number,
                revision_number=order.revision_number,
                document_id=document.id,
                accepted=True,
                message=f"Attached to {order.order_number} (Rev {order.revision_number})",
            )
        )

    if not uploaded:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="; ".join(f"{item.file_name}: {item.message}" for item in items) or "No file was attached",
        )
    _commit(db)
    # Per-file results, so one rejected file never hides behind the successful ones.
    return DocumentUploadResult(uploaded_count=uploaded, rejected_count=len(items) - uploaded, items=items)


@router.get(
    "/po-so-orders/documents/{document_id}",
    dependencies=[Depends(require("master-data:document-download"))],
)
def download_document(document_id: str, db: Db, user: Current, request: Request, inline: bool = False) -> Response:
    """Serve the stored bytes; ``inline=1`` previews PDFs and images in the browser."""
    document = _document_or_404(db, document_id, user.organization_id)
    order = document.order
    _audit(
        db,
        user=user,
        action=MasterDataAction.DOCUMENT_DOWNLOAD,
        entity_type=DOCUMENT_ENTITY,
        entity_id=document.id,
        entity_label=f"{DOCUMENT_LABEL} · {document.file_name}",
        summary=(
            f"Downloaded {document.file_name} from {order.order_type} {order.order_number} "
            f"(Rev {document.revision_number})"
        ),
        request=request,
    )
    _commit(db)
    stored = bytes(document.content)
    served = _sniff_document_type(stored, document.file_name or "")
    # Never trust the stored header either: legacy rows may hold a client-supplied
    # type. Only a signature-verified PDF/image may be shown inline.
    preview = bool(inline) and served in INLINE_SAFE_TYPES
    return Response(
        content=stored,
        media_type=served,
        headers={
            "Content-Disposition": _content_disposition("inline" if preview else "attachment", document.file_name),
            "Content-Length": str(document.size_bytes),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.patch(
    "/po-so-orders/documents/{document_id}",
    response_model=DocumentOut,
    dependencies=[Depends(require("master-data:update"))],
)
def update_document(
    document_id: str,
    data: DocumentUpdate,
    request: Request,
    db: Db,
    user: Current,
) -> DocumentOut:
    document = _document_or_404(db, document_id, user.organization_id)
    supplied = data.model_dump(exclude_unset=True)
    if not supplied:
        raise HTTPException(status_code=422, detail="Provide at least one field to update")
    mapping = {"document_kind": "document_kind", "label": "label", "notes": "description"}
    changed: list[str] = []
    for field, value in supplied.items():
        column = mapping[field]
        clean = "" if value is None else str(value).strip()
        if getattr(document, column) != clean:
            setattr(document, column, clean)
            changed.append(field)
    if changed:
        _audit(
            db,
            user=user,
            action=MasterDataAction.UPDATE,
            entity_type=DOCUMENT_ENTITY,
            entity_id=document.id,
            entity_label=f"{DOCUMENT_LABEL} · {document.file_name}",
            summary=f"Updated document details for {document.file_name}: {', '.join(sorted(changed))}",
            request=request,
        )
        _commit(db)
        db.refresh(document)
    return _document_out(document)


@router.delete(
    "/po-so-orders/documents/{document_id}",
    response_model=DocumentOut,
    dependencies=[Depends(require("master-data:document-delete"))],
)
def soft_delete_document(document_id: str, request: Request, db: Db, user: Current) -> DocumentOut:
    document = _document_or_404(db, document_id, user.organization_id)
    if document.is_deleted:
        raise HTTPException(status_code=409, detail="This document is already in removed files")
    document.is_deleted = True
    document.deleted_at = datetime.now(timezone.utc)
    order = document.order
    _audit(
        db,
        user=user,
        action=MasterDataAction.DOCUMENT_DELETE,
        entity_type=DOCUMENT_ENTITY,
        entity_id=document.id,
        entity_label=f"{DOCUMENT_LABEL} · {document.file_name}",
        summary=(
            f"Removed {document.file_name} from {order.order_type} {order.order_number} "
            f"(Rev {document.revision_number}); it stays recoverable"
        ),
        request=request,
    )
    _commit(db)
    db.refresh(document)
    return _document_out(document)


@router.post(
    "/po-so-orders/documents/{document_id}/restore",
    response_model=DocumentOut,
    dependencies=[Depends(require("master-data:restore"))],
)
def restore_document(document_id: str, request: Request, db: Db, user: Current) -> DocumentOut:
    document = _document_or_404(db, document_id, user.organization_id)
    if not document.is_deleted:
        raise HTTPException(status_code=409, detail="Only a removed document can be restored")
    document.is_deleted = False
    document.deleted_at = None
    order = document.order
    _audit(
        db,
        user=user,
        action=MasterDataAction.DOCUMENT_RESTORE,
        entity_type=DOCUMENT_ENTITY,
        entity_id=document.id,
        entity_label=f"{DOCUMENT_LABEL} · {document.file_name}",
        summary=f"Restored {document.file_name} to {order.order_type} {order.order_number}",
        request=request,
    )
    _commit(db)
    db.refresh(document)
    return _document_out(document)


@router.delete(
    "/po-so-orders/documents/{document_id}/permanent",
    status_code=204,
    dependencies=[Depends(require("master-data:permanent-delete"))],
)
def permanently_delete_document(document_id: str, request: Request, db: Db, user: Current) -> None:
    document = _document_or_404(db, document_id, user.organization_id)
    if not document.is_deleted:
        raise HTTPException(status_code=409, detail="Only a removed document can be permanently deleted")
    order = document.order
    _audit(
        db,
        user=user,
        action=MasterDataAction.DOCUMENT_PERMANENT_DELETE,
        entity_type=DOCUMENT_ENTITY,
        entity_id=document.id,
        entity_label=f"{DOCUMENT_LABEL} · {document.file_name}",
        summary=(
            f"Permanently deleted {document.file_name} ({_human_size(document.size_bytes)}) "
            f"from {order.order_type} {order.order_number}"
        ),
        request=request,
    )
    db.delete(document)
    _commit(db)
    return None
