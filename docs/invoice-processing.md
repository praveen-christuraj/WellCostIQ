# Invoice Processing / IDVS

Invoice Processing records an invoice and its verified commercial value, generates an Invoice Data Verification Sheet (IDVS), and tracks the dated hand-offs through Accounts and EPICOR. EPICOR approval and payment remain external events; WellCostIQ records their dates, references, actors, and remarks but does not claim to perform them inside EPICOR.

## Setup order

1. In **Master Data**, maintain the workspace currencies, vendors, and current PO/SO orders. Set the workspace default currency used to preload new IDVS records.
2. In **Rig & Well Management**, maintain blocks, rigs, and wells when invoices have operational scope. Block/rig/well are optional for common-material invoices.
3. In **Invoice Processing → Invoice Configuration**, maintain:
   - invoice locations and description categories;
   - reusable payment terms, including payment days and currency percentages;
   - vendor-linked payment terms and common or vendor-linked taxes;
   - explicit base/quote exchange rates;
   - sign-off signatories for the Prepared, Checked, Verified, and Approved By roles (name and designation); and
   - **Own Block** or **JV Block** classification for each applicable Rig & Well block.
4. Assign the required `invoice-processing:*` capabilities through User Management. Owner roles receive the baseline capabilities during provisioning and migration.

Selecting a vendor in the editor limits PO/SO choices to that vendor and applies its linked payment term. Selecting a well resolves its rig and block. The sign-off roles on an IDVS are chosen from the active signatories for each role. The invoice, vendor, order, operational scope, location, tax, payment-term, and exchange-rate details needed by the output are snapshotted when the IDVS is saved, so later configuration changes do not silently rewrite an existing sheet.

## Calculations

All authoritative calculations use Python `Decimal` and the application's `NUMERIC(28,10)` persistence contract. Browser calculations are immediate previews only.

For each line:

```text
Invoice total  = invoice quantity × invoice days × invoice unit price
Verified total = verified quantity × verified days × verified unit price
Difference     = invoice total − verified total
```

Days apply only when the IDVS **day count** is on. When it is off, every line's days are stored as 1, so the totals are quantity × unit price. With the day count on, a blank invoice day count is 1 and a blank verified day count follows the invoice days. Invoice days must be above zero, and verified days cannot be negative.

For the sheet:

```text
Invoice subtotal  = sum(line invoice totals)
Verified subtotal = sum(line verified totals)
Tax amount        = applicable subtotal × tax rate ÷ 100
Invoice total     = invoice subtotal + signed invoice tax amounts
Verified total    = verified subtotal + signed verified tax amounts
Adjusted payable  = verified total − disallowed amount − advance amount
Difference        = invoice total − verified total
Payment split     = adjusted payable × split percentage ÷ 100 × exchange rate
Due date          = invoice date + payment tenure days
```

The sheet's **Sub Total - Services** row shows `invoice subtotal − verified subtotal`; the commercial summary's **Difference** is the separate after-tax value shown above. A tax configured as an **addition** increases its total; a **deduction** decreases it. Split percentages must total exactly 100%. A missing cross-currency rate is an error, never an implicit rate of 1. Split amounts remain in their stated payment currencies and are not added to the invoice-currency total. Dashboard totals and charts likewise remain separated by currency.

## Entry, import, and output

The full-page IDVS editor supports up to 500 worksheet lines, direct AG Grid cell editing, keyboard/paste entry, common and vendor-linked taxes, manual invoice-specific taxes, disallowed/advance adjustments, and payment-currency splits. Save creates a Draft; editing is locked after submission. Optimistic revision checks reject overwriting a draft changed in another session.

**Saved IDVS & Tracking → Import XLSX / CSV** uses the shared spreadsheet preview and row-error flow. Repeat the invoice header on every line of a multi-line IDVS. Required columns are:

- Vendor Code, Invoice Number, Invoice Date, Invoice Received Date, IDVS Date;
- Location, Service Description, Currency Code;
- Line Description, Invoice Quantity, Invoice Unit Price.

Invoice Days and Verified Days are optional. They apply only when the IDVS day count is on: a repeated invoice header turns the day count on for the whole IDVS when any of its rows enables it.

Optional columns cover IDVS Number, PO/SO Number, operational scope, description details, service dates/person, payment term/tenure, adjustments, verified values, and remarks. Dates accept ISO `YYYY-MM-DD`, `DD/MM/YYYY`, and Excel date serials. Imports are atomic: any header/reference/calculation error rejects the batch. A repeated vendor + invoice number refreshes an existing Draft with the same IDVS number; submitted and deleted records cannot be replaced through import.

The saved record provides generated IDVS **PDF, XLSX, and CSV** output. The PDF and XLSX follow the RIG-11 reference layout: header block, Services table with invoice and as-per-contract columns (days columns appear only with the day count on), Difference and Remarks, subtotal, tax, total, payment-split and sign-off rows. The on-screen IDVS tab renders the same model. The register and dashboard also provide audited exports. Supporting documents can be uploaded in batches of up to 20 files, with a **25 MB per-file** limit. Content is stored in the tenant-scoped database with size, MIME type, SHA-256 checksum, uploader, label, and notes. PDFs can open inline; other formats download explicitly. Document upload, download, and delete have separate capabilities and audit events.

## Tracking and lifecycle

The only valid workflow sequence is:

```text
Draft
  → Submitted for verification
  → Verified & sent to Accounts
  → Received for EPICOR approval
  → Approved in EPICOR
  → Paid date recorded
```

Each transition records an action date, actor, optional remarks, and immutable workflow-history row. Dates cannot move backwards relative to the previous tracking milestone. Payment has its own capability and may be recorded only after EPICOR approval; its date cannot precede that approval.

Normal deletion moves the IDVS to **Deleted Entries**. Restore returns it to the active register. Permanent deletion is available only there, behind `invoice-processing:permanent-delete` and an explicit confirmation. Deleted records remain readable for output/history but do not offer workflow or document mutations in the UI.

## Dashboard and permissions

The dashboard includes workflow milestones, currency-separated financial totals, vendor exposure, own/JV/common block position, five due-date ageing buckets, overdue counts, attachment counts, and recent tracking activity. Paid is derived from the recorded paid date rather than replacing the underlying `approved` workflow status.

Capabilities cover `read`, `create`, `update`, `delete`, `restore`, `permanent-delete`, `import`, `export`, `configure`, `submit`, `verify`, `epicor`, `approve`, `payment`, `document-upload`, `document-download`, and `document-delete`. The API enforces each capability and organization boundary independently; hiding a button is not the authorization control.

## Database and verification

Migration `a1b2c3d4e5f6` adds the column-wise Invoice Processing tables and backfills all module permissions to existing owner roles without altering existing business records. Migration `b3c4d5e6f7a8` adds the day-count flag, line days, and sign-off signatory tables. Existing IDVS records keep the day count off, so their totals are unchanged. API contract version is `0.5.0`.

Each IDVS stores a snapshot of its sign-off names and designations. Deleting or renaming a signatory does not alter existing IDVS sign-offs. A deleted signatory is removed from new IDVS choices, and permanently removing it clears only the link, so the printed snapshot stays.

Focused regression coverage is in `backend/tests/test_invoice_processing.py`. It verifies workbook-equivalent calculations, term/due-date and FX splits, ordered transitions, payment chronology, import grouping and atomic errors, generated-document contracts, attachment size/disposition behavior, deleted-record safeguards, tenant isolation, and independent RBAC capabilities. Run:

```bash
cd backend
../.venv/bin/python -m pytest tests/test_invoice_processing.py -q

cd ../frontend
npm run build

cd ..
make graph
```
