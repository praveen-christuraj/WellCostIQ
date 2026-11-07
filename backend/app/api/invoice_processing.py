"""Invoice Processing and IDVS APIs."""

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import Response as FileResponse

from app.api.deps import Current, Db, require
from app.schemas.invoice_processing import (
    InvoiceAttachmentOut,
    InvoiceBlockSettingIn,
    InvoiceBlockSettingOut,
    InvoiceBulkActionOut,
    InvoiceConfigItemIn,
    InvoiceConfigItemOut,
    InvoiceConfiguration,
    InvoiceDashboard,
    InvoiceDetailOut,
    InvoiceExchangeRateIn,
    InvoiceExchangeRateOut,
    InvoiceExportAudit,
    InvoiceIDs,
    InvoiceImportOut,
    InvoiceImportRequest,
    InvoicePaymentIn,
    InvoicePaymentTermIn,
    InvoicePaymentTermOut,
    InvoiceReference,
    InvoiceSave,
    InvoiceSummaryOut,
    InvoiceTaxConfigurationIn,
    InvoiceTaxConfigurationOut,
    InvoiceWorkflowIn,
)
from app.services import invoice_processing as service

router = APIRouter(prefix="/invoice-processing", tags=["Invoice Processing"])


@router.get("/reference", response_model=InvoiceReference, dependencies=[Depends(require("invoice-processing:read"))])
def reference(db: Db, user: Current):
    return service.reference_data(db, user.organization_id)


@router.get("/configuration", response_model=InvoiceConfiguration, dependencies=[Depends(require("invoice-processing:configure"))])
def configuration(db: Db, user: Current):
    return service.configuration_data(db, user.organization_id)


@router.get("/dashboard", response_model=InvoiceDashboard, dependencies=[Depends(require("invoice-processing:read"))])
def dashboard(db: Db, user: Current):
    return service.dashboard_data(db, user.organization_id)


# Configuration writes are deliberately separate from ordinary IDVS entry rights.
@router.post("/config/payment-terms", response_model=InvoicePaymentTermOut, status_code=201, dependencies=[Depends(require("invoice-processing:configure"))])
def create_payment_term(data: InvoicePaymentTermIn, request: Request, db: Db, user: Current):
    return service.save_payment_term(db, user.organization_id, data, user, request)


@router.patch("/config/payment-terms/{record_id}", response_model=InvoicePaymentTermOut, dependencies=[Depends(require("invoice-processing:configure"))])
def update_payment_term(record_id: str, data: InvoicePaymentTermIn, request: Request, db: Db, user: Current):
    return service.save_payment_term(db, user.organization_id, data, user, request, record_id)


@router.post("/config/taxes", response_model=InvoiceTaxConfigurationOut, status_code=201, dependencies=[Depends(require("invoice-processing:configure"))])
def create_tax(data: InvoiceTaxConfigurationIn, request: Request, db: Db, user: Current):
    return service.save_tax_configuration(db, user.organization_id, data, user, request)


@router.patch("/config/taxes/{record_id}", response_model=InvoiceTaxConfigurationOut, dependencies=[Depends(require("invoice-processing:configure"))])
def update_tax(record_id: str, data: InvoiceTaxConfigurationIn, request: Request, db: Db, user: Current):
    return service.save_tax_configuration(db, user.organization_id, data, user, request, record_id)


@router.post("/config/exchange-rates", response_model=InvoiceExchangeRateOut, status_code=201, dependencies=[Depends(require("invoice-processing:configure"))])
def create_exchange_rate(data: InvoiceExchangeRateIn, request: Request, db: Db, user: Current):
    return service.save_exchange_rate(db, user.organization_id, data, user, request)


@router.patch("/config/exchange-rates/{record_id}", response_model=InvoiceExchangeRateOut, dependencies=[Depends(require("invoice-processing:configure"))])
def update_exchange_rate(record_id: str, data: InvoiceExchangeRateIn, request: Request, db: Db, user: Current):
    return service.save_exchange_rate(db, user.organization_id, data, user, request, record_id)


@router.put("/config/blocks/{block_id}", response_model=InvoiceBlockSettingOut, dependencies=[Depends(require("invoice-processing:configure"))])
def configure_block(block_id: str, data: InvoiceBlockSettingIn, request: Request, db: Db, user: Current):
    return service.set_block_category(db, user.organization_id, block_id, data, user, request)


@router.post("/config/{kind}", response_model=InvoiceConfigItemOut, status_code=201, dependencies=[Depends(require("invoice-processing:configure"))])
def create_config_item(kind: str, data: InvoiceConfigItemIn, request: Request, db: Db, user: Current):
    return service.save_config_item(db, user.organization_id, kind, data, user, request)


@router.patch("/config/{kind}/{record_id}", response_model=InvoiceConfigItemOut, dependencies=[Depends(require("invoice-processing:configure"))])
def update_config_item(kind: str, record_id: str, data: InvoiceConfigItemIn, request: Request, db: Db, user: Current):
    return service.save_config_item(db, user.organization_id, kind, data, user, request, record_id)


@router.post("/config/{kind}/bulk-delete", response_model=InvoiceBulkActionOut, dependencies=[Depends(require("invoice-processing:configure"))])
def delete_config(kind: str, data: InvoiceIDs, request: Request, db: Db, user: Current):
    return service.bulk_configuration(db, user.organization_id, kind, data.ids, "delete", user, request)


@router.post("/config/{kind}/bulk-restore", response_model=InvoiceBulkActionOut, dependencies=[Depends(require("invoice-processing:configure"))])
def restore_config(kind: str, data: InvoiceIDs, request: Request, db: Db, user: Current):
    return service.bulk_configuration(db, user.organization_id, kind, data.ids, "restore", user, request)


@router.post("/config/{kind}/bulk-permanent-delete", response_model=InvoiceBulkActionOut, dependencies=[Depends(require("invoice-processing:configure"))])
def purge_config(kind: str, data: InvoiceIDs, request: Request, db: Db, user: Current):
    return service.bulk_configuration(db, user.organization_id, kind, data.ids, "permanent-delete", user, request)


# Register and full-page editor.
@router.get("/invoices/deleted", response_model=list[InvoiceSummaryOut], dependencies=[Depends(require("invoice-processing:read"))])
def deleted_invoices(
    db: Db, user: Current, status: str = "", vendor_id: str = "", block_id: str = "",
    rig_id: str = "", well_id: str = "", currency_code: str = "", location_id: str = "",
    overdue: bool = False, date_field: str = "invoice_received_date",
    date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
):
    return service.list_invoices(
        db, user.organization_id, deleted=True, status=status, vendor_id=vendor_id, block_id=block_id,
        rig_id=rig_id, well_id=well_id, currency_code=currency_code, location_id=location_id,
        overdue=overdue, date_field=date_field, date_from=date_from, date_to=date_to,
    )


@router.get("/invoices", response_model=list[InvoiceSummaryOut], dependencies=[Depends(require("invoice-processing:read"))])
def invoices(
    db: Db, user: Current, status: str = "", vendor_id: str = "", block_id: str = "",
    rig_id: str = "", well_id: str = "", currency_code: str = "", location_id: str = "",
    overdue: bool = False, date_field: str = "invoice_received_date",
    date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
):
    return service.list_invoices(
        db, user.organization_id, status=status, vendor_id=vendor_id, block_id=block_id,
        rig_id=rig_id, well_id=well_id, currency_code=currency_code, location_id=location_id,
        overdue=overdue, date_field=date_field, date_from=date_from, date_to=date_to,
    )


@router.post("/invoices", response_model=InvoiceDetailOut, status_code=201, dependencies=[Depends(require("invoice-processing:create"))])
def create_invoice(data: InvoiceSave, request: Request, db: Db, user: Current):
    return service.create_invoice(db, user.organization_id, data, user, request)


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailOut, dependencies=[Depends(require("invoice-processing:read"))])
def get_invoice(invoice_id: str, db: Db, user: Current):
    return service.get_invoice(db, user.organization_id, invoice_id)


@router.put("/invoices/{invoice_id}", response_model=InvoiceDetailOut, dependencies=[Depends(require("invoice-processing:update"))])
def update_invoice(invoice_id: str, data: InvoiceSave, request: Request, db: Db, user: Current):
    return service.update_invoice(db, user.organization_id, invoice_id, data, user, request)


@router.post("/invoices/{invoice_id}/workflow", response_model=InvoiceDetailOut, dependencies=[Depends(require("invoice-processing:read"))])
def workflow(invoice_id: str, data: InvoiceWorkflowIn, request: Request, db: Db, user: Current):
    # Each transition has its own grant; the API, not the visibility of a button,
    # remains the authority. Keeping one route avoids four duplicated validators.
    from app.api.deps import owner, granted
    required = {
        "submit": "invoice-processing:submit",
        "send_to_accounts": "invoice-processing:verify",
        "receive_epicor": "invoice-processing:epicor",
        "approve_epicor": "invoice-processing:approve",
    }[data.action]
    if not owner(user) and required not in granted(user):
        from fastapi import HTTPException
        raise HTTPException(403, f"Permission denied. This action needs {required}.")
    return service.transition_invoice(db, user.organization_id, invoice_id, data, user, request)


@router.post("/invoices/{invoice_id}/payment", response_model=InvoiceDetailOut, dependencies=[Depends(require("invoice-processing:payment"))])
def payment(invoice_id: str, data: InvoicePaymentIn, request: Request, db: Db, user: Current):
    return service.record_payment(db, user.organization_id, invoice_id, data, user, request)


@router.post("/invoices/bulk-delete", response_model=InvoiceBulkActionOut, dependencies=[Depends(require("invoice-processing:delete"))])
def delete_invoices(data: InvoiceIDs, request: Request, db: Db, user: Current):
    return service.bulk_invoices(db, user.organization_id, data.ids, "delete", user, request)


@router.post("/invoices/bulk-restore", response_model=InvoiceBulkActionOut, dependencies=[Depends(require("invoice-processing:restore"))])
def restore_invoices(data: InvoiceIDs, request: Request, db: Db, user: Current):
    return service.bulk_invoices(db, user.organization_id, data.ids, "restore", user, request)


@router.post("/invoices/bulk-permanent-delete", response_model=InvoiceBulkActionOut, dependencies=[Depends(require("invoice-processing:permanent-delete"))])
def purge_invoices(data: InvoiceIDs, request: Request, db: Db, user: Current):
    return service.bulk_invoices(db, user.organization_id, data.ids, "permanent-delete", user, request)


@router.post("/import", response_model=InvoiceImportOut, dependencies=[Depends(require("invoice-processing:import"))])
def import_invoices(data: InvoiceImportRequest, request: Request, db: Db, user: Current):
    return service.import_invoices(db, user.organization_id, data, user, request)


@router.post("/export-audit", status_code=204, dependencies=[Depends(require("invoice-processing:export"))])
def export_audit(data: InvoiceExportAudit, request: Request, db: Db, user: Current):
    service.audit_export(db, user.organization_id, data, user, request)
    return Response(status_code=204)


# Supporting-document custody.
@router.post("/invoices/{invoice_id}/attachments", response_model=list[InvoiceAttachmentOut], status_code=201, dependencies=[Depends(require("invoice-processing:document-upload"))])
async def upload_attachments(
    invoice_id: str, request: Request, db: Db, user: Current,
    files: list[UploadFile] = File(...), label: str = Form(""), notes: str = Form(""),
):
    rows = await service.upload_attachments(db, user.organization_id, invoice_id, files, label, notes, user, request)
    return [row.model_dump(mode="json") for row in rows]


@router.get("/attachments/{attachment_id}/content", dependencies=[Depends(require("invoice-processing:document-download"))])
def download_attachment(attachment_id: str, request: Request, db: Db, user: Current, inline: bool = False):
    row = service.download_attachment(db, user.organization_id, attachment_id, user, request)
    preview = inline and row.content_type == "application/pdf"
    disposition = "inline" if preview else "attachment"
    encoded = quote(row.file_name)
    return FileResponse(
        content=row.content, media_type=row.content_type,
        headers={"Content-Disposition": f"{disposition}; filename=\"{encoded}\"; filename*=UTF-8''{encoded}"},
    )


@router.delete("/attachments/{attachment_id}", status_code=204, dependencies=[Depends(require("invoice-processing:document-delete"))])
def delete_attachment(attachment_id: str, request: Request, db: Db, user: Current):
    service.delete_attachment(db, user.organization_id, attachment_id, user, request)
    return Response(status_code=204)
