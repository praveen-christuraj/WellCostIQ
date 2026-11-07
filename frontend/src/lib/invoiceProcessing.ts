import type { ImportRow } from './export'

export type InvoiceStatus = 'draft' | 'submitted' | 'sent_to_accounts' | 'epicor_pending' | 'approved'
export type InvoiceDisplayStatus = InvoiceStatus | 'paid'
export type WorkflowAction = 'submit' | 'send_to_accounts' | 'receive_epicor' | 'approve_epicor'
export type TaxDirection = 'addition' | 'deduction'
export type SignatureRole = 'prepared' | 'checked' | 'verified' | 'approved'

export type ConfigItem = {
  id: string; name: string; description: string; is_active: boolean; is_deleted?: boolean
  created_by?: string; updated_by?: string; created_at?: string; updated_at?: string
}
export type CurrencyOption = { currency_code: string; currency_name: string; currency_symbol: string; is_default: boolean }
export type VendorOption = {
  id: string; vendor_code: string; vendor_name: string; label: string; status: string; credit_terms_days: number | null
  payment_term_id: string | null; payment_term_name: string
}
export type OrderOption = { id: string; vendor_id: string; order_number: string; order_type: string; status: string; label: string }
export type BlockOption = { id: string; block_code: string; block_name: string; label: string; category: 'own' | 'jv' | '' }
export type RigOption = { id: string; rig_code: string; rig_name: string; label: string }
export type WellOption = { id: string; rig_id: string; block_id: string; well_code: string; well_name: string; label: string }
export type PaymentSplitInput = { currency_code: string; percentage: string; exchange_rate?: string | null }
export type PaymentTerm = {
  id: string; term_code: string; term_name: string; payment_days: number; description: string
  is_active: boolean; is_deleted?: boolean; splits: { currency_code: string; percentage: string }[]
  vendor_ids: string[]
}
export type TaxConfiguration = {
  id: string; tax_code: string; tax_name: string; rate_percent: string; direction: TaxDirection
  is_report_visible: boolean; is_net_payable: boolean
  is_common: boolean; description: string; is_active: boolean; is_deleted?: boolean; vendor_ids: string[]
}
export type ExchangeRate = { id: string; base_currency: string; quote_currency: string; rate: string; description: string; is_active: boolean; is_deleted?: boolean }
export type BlockSetting = { block_id: string; block_code: string; block_name: string; category: 'own' | 'jv' | '' }
export type Signatory = {
  id: string; signatory_role: SignatureRole; full_name: string; designation: string; is_active: boolean
  is_deleted?: boolean; deleted_at?: string | null; created_at?: string; updated_at?: string
}
export type SignatoryOption = { id: string; signatory_role: SignatureRole; full_name: string; designation: string; label: string }
export type InvoiceReference = {
  vendors: VendorOption[]; orders: OrderOption[]; currencies: CurrencyOption[]
  rigs: RigOption[]; blocks: BlockOption[]; wells: WellOption[]
  descriptions: ConfigItem[]
  locations: ConfigItem[]; categories: ConfigItem[]; payment_terms: PaymentTerm[]
  taxes: TaxConfiguration[]; exchange_rates: ExchangeRate[]; signatories: SignatoryOption[]
}
export type InvoiceConfiguration = {
  vendors: VendorOption[]; currencies: CurrencyOption[]
  descriptions: ConfigItem[]
  locations: ConfigItem[]; categories: ConfigItem[]; payment_terms: PaymentTerm[]
  taxes: TaxConfiguration[]; exchange_rates: ExchangeRate[]; blocks: BlockSetting[]; signatories: Signatory[]
}
export type InvoiceLine = {
  id?: string; description: string; invoice_quantity: string; invoice_days: string; invoice_unit_price: string
  invoice_total?: string; verified_quantity: string; verified_days: string; verified_unit_price: string
  verified_total?: string; difference_amount?: string; remarks: string; sort_order?: number
}
export type InvoiceSignature = { role: SignatureRole; signatory_id: string | null; name: string; designation: string }
export type InvoiceTax = {
  id?: string; tax_configuration_id: string | null; tax_name: string; rate_percent: string
  direction: TaxDirection
  /** Printed on the IDVS report, so it moves the report's total. */
  is_report_visible: boolean
  /** Applied to the register's Net payable amount. */
  is_net_payable: boolean
  source?: 'common' | 'vendor' | 'manual'; invoice_amount?: string; verified_amount?: string
}
export type InvoicePaymentSplit = {
  id?: string; currency_code: string; percentage: string; exchange_rate: string; amount?: string
}
export type WorkflowHistory = {
  id: string; action: string; action_label: string; status_after: string; action_date: string
  remarks: string; actor_name: string; created_at: string
}
export type InvoiceAttachment = {
  id: string; file_name: string; content_type: string; size_bytes: number; checksum_sha256: string
  label: string; notes: string; uploaded_by_name: string; created_at: string; is_pdf: boolean; can_inline: boolean
}
export type Invoice = {
  id: string; idvs_number: string; idvs_date: string; revision: number
  invoice_number: string; invoice_date: string; invoice_received_date: string
  vendor_id: string; vendor_code: string; vendor_name: string
  order_id: string | null; order_number: string; order_type: string
  block_id: string | null; block_code: string; block_name: string; block_category: 'own' | 'jv' | ''
  rig_id: string | null; rig_code: string; rig_name: string; well_id: string | null; well_code: string; well_name: string
  location_id: string; location_name: string; field_name: string; phase: string; day_count_enabled: boolean
  description_category_id: string | null; description_category: string
  service_description: string; detailed_description: string; concerned_person: string
  service_from: string | null; service_to: string | null; currency_code: string
  payment_term_id: string | null; payment_term_name: string; payment_tenure_days: number; due_date: string
  disallowed_amount: string; advance_amount: string; invoice_subtotal: string; verified_subtotal: string
  invoice_tax_total: string; verified_tax_total: string; invoice_total: string; verified_total: string
  adjusted_verified_amount: string; net_payable_amount: string
  signature_space_mm: number; difference_amount: string
  status: InvoiceStatus; display_status: InvoiceDisplayStatus; is_overdue: boolean
  submitted_date: string | null; sent_to_accounts_date: string | null
  epicor_received_date: string | null; epicor_approved_date: string | null; paid_date: string | null
  payment_reference: string; remarks: string; line_count: number; attachment_count: number
  payment_splits: InvoicePaymentSplit[]; is_deleted: boolean; deleted_at: string | null
  created_by: string; updated_by: string; created_at: string; updated_at: string
}
export type InvoiceDetail = Invoice & {
  lines: InvoiceLine[]; taxes: InvoiceTax[]; history: WorkflowHistory[]; attachments: InvoiceAttachment[]; signatures: InvoiceSignature[]
}
export type InvoiceSignatureSpace = { min: number; max: number; default: number }
/** Mirrors the server's check constraint on invoice_idvs.signature_space_mm. */
export const SIGNATURE_SPACE: InvoiceSignatureSpace = { min: 0, max: 60, default: 15 }
/** Reported when the IDVS has no Block, Rig or Well: the invoice is common material. */
export const COMMON_SCOPE_LABEL = 'Common for All Blocks'
export type InvoiceSaveInput = {
  block_category?: 'own' | 'jv' | ''
  idvs_number?: string; idvs_date: string; expected_revision?: number; day_count_enabled: boolean
  invoice_number: string; invoice_date: string; invoice_received_date: string
  vendor_id: string; order_id: string | null; block_id: string | null; rig_id: string | null; well_id: string | null
  location_id: string; field_name: string; phase: string; description_category_id: string | null
  service_description: string; detailed_description: string; concerned_person: string
  service_from: string | null; service_to: string | null; currency_code: string
  payment_term_id: string | null; payment_tenure_days: number | null
  disallowed_amount: string; advance_amount: string; remarks: string
  lines: (Omit<InvoiceLine, 'id' | 'invoice_total' | 'verified_total' | 'difference_amount' | 'sort_order' | 'invoice_days' | 'verified_days'> & { invoice_days: string | null; verified_days: string | null })[]
  taxes: Pick<InvoiceTax, 'tax_configuration_id' | 'tax_name' | 'rate_percent' | 'direction'>[] | null
  payment_splits: PaymentSplitInput[] | null
  signatures: { role: SignatureRole; signatory_id: string }[] | null
  /** Blank signing space printed above the sign-off names, in millimetres (0-60). */
  signature_space_mm?: number
}
export type CurrencyTotals = {
  currency_code: string; invoice_total: string; verified_total: string; adjusted_verified_amount: string
  net_payable_amount: string; difference_amount: string
  invoice_count: number; outstanding_count: number; overdue_count: number
}
export type StatusCount = { status: string; label: string; count: number }
export type VendorDashboardRow = { vendor_id: string; vendor_name: string; currency_code: string; invoice_count: number; invoice_total: string; verified_total: string; difference_amount: string; approved_count: number }
export type BlockDashboardRow = { block_id: string; block_code: string; block_name: string; block_category: string; currency_code: string; invoice_count: number; invoice_total: string; verified_total: string }
export type AgeingRow = { bucket: string; currency_code: string; invoice_count: number; adjusted_verified_amount: string; net_payable_amount: string }
export type RecentActivity = { id: string; invoice_id: string; idvs_number: string; invoice_number: string; vendor_name: string; action_label: string; action_date: string; actor_name: string; remarks: string; created_at: string }
export type InvoiceDashboard = {
  as_of: string; total_invoices: number; draft_count: number; verification_count: number; epicor_count: number
  approved_count: number; paid_count: number; overdue_count: number; unclassified_block_count: number
  own_block_count: number; jv_block_count: number; attachment_count: number; currency_totals: CurrencyTotals[]
  status_counts: StatusCount[]; vendor_rows: VendorDashboardRow[]; block_rows: BlockDashboardRow[]
  ageing_rows: AgeingRow[]; recent_activity: RecentActivity[]
}
export type InvoiceImportResult = { imported_count: number; invoice_count: number; errors: string[]; success: boolean }

export const INVOICE_STATUS_LABEL: Record<InvoiceDisplayStatus, string> = {
  draft: 'Draft', submitted: 'Submitted for verification', sent_to_accounts: 'Verified & sent to Accounts',
  epicor_pending: 'Received for EPICOR approval', approved: 'Approved in EPICOR', paid: 'Paid',
}
export const WORKFLOW_ACTION: Partial<Record<InvoiceStatus, { action: WorkflowAction; label: string; permission: string }>> = {
  draft: { action: 'submit', label: 'Submit', permission: 'invoice-processing:submit' },
  submitted: { action: 'send_to_accounts', label: 'Verified & sent to Accounts', permission: 'invoice-processing:verify' },
  sent_to_accounts: { action: 'receive_epicor', label: 'Received for EPICOR approval', permission: 'invoice-processing:epicor' },
  epicor_pending: { action: 'approve_epicor', label: 'Approved in EPICOR', permission: 'invoice-processing:approve' },
}
export const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
export const SIGNATURE_ROLES: SignatureRole[] = ['prepared', 'checked', 'verified', 'approved']
export const SIGNATURE_LABELS: Record<SignatureRole, string> = {
  prepared: 'Prepared By', checked: 'Checked By', verified: 'Verified By', approved: 'Approved By',
}
export const INVOICE_IMPORT_HEADERS = ['Vendor Code', 'Invoice Number', 'Invoice Date', 'Invoice Received Date', 'IDVS Date', 'Location', 'Service Description', 'Currency Code', 'Line Description', 'Invoice Quantity', 'Invoice Unit Price']
export const INVOICE_IMPORT_OPTIONAL = ['IDVS Number', 'PO/SO Number', 'Block Category', 'Block Code', 'Rig Code', 'Well Code', 'Description Category', 'Detailed Description', 'Concerned Person', 'Field Name', 'Phase', 'Service From', 'Service To', 'Payment Term Code', 'Payment Tenure Days', 'Disallowed Amount', 'Advance Amount', 'Invoice Days', 'Verified Quantity', 'Verified Days', 'Verified Unit Price', 'Line Remarks', 'Remarks']
export const INVOICE_IMPORT_SAMPLE: ImportRow = {
  'Vendor Code': 'VEND-01', 'Invoice Number': 'INV-001', 'Invoice Date': '2026-01-01', 'Invoice Received Date': '2026-01-03',
  'IDVS Date': '2026-01-03', Location: 'Port Harcourt', 'Service Description': 'Completion services', 'Currency Code': 'USD',
  'Line Description': 'Packers', 'Invoice Quantity': '2', 'Invoice Unit Price': '100', 'PO/SO Number': 'PO-001',
  'Block Code': 'OML-01', 'Rig Code': 'RIG-01', 'Well Code': 'WELL-01', 'Description Category': 'Completion Services',
  'Payment Term Code': '30-60-40', 'Verified Quantity': '2', 'Verified Unit Price': '90',
}
export function importInvoiceRow(row: ImportRow) {
  return {
    idvs_number: row['IDVS Number']?.trim() || '', idvs_date: row['IDVS Date'], invoice_received_date: row['Invoice Received Date'],
    vendor_code: row['Vendor Code']?.trim(), order_number: row['PO/SO Number']?.trim() || '', invoice_number: row['Invoice Number']?.trim(),
    block_category: row['Block Category']?.trim().toLowerCase() || null,
    invoice_date: row['Invoice Date'], block_code: row['Block Code']?.trim() || '', rig_code: row['Rig Code']?.trim() || '', well_code: row['Well Code']?.trim() || '',
    location: row.Location?.trim(), description_category: row['Description Category']?.trim() || '', service_description: row['Service Description']?.trim(),
    detailed_description: row['Detailed Description']?.trim() || '', concerned_person: row['Concerned Person']?.trim() || '', field_name: row['Field Name']?.trim() || '',
    phase: row.Phase?.trim() || '', service_from: row['Service From'] || '', service_to: row['Service To'] || '', currency_code: row['Currency Code']?.trim().toUpperCase(),
    payment_term_code: row['Payment Term Code']?.trim() || '', payment_tenure_days: row['Payment Tenure Days'] || '', disallowed_amount: row['Disallowed Amount'] || 0,
    advance_amount: row['Advance Amount'] || 0, description: row['Line Description']?.trim(), invoice_quantity: row['Invoice Quantity'],
    invoice_days: row['Invoice Days'] ?? '', invoice_unit_price: row['Invoice Unit Price'], verified_quantity: row['Verified Quantity'] ?? '',
    verified_days: row['Verified Days'] ?? '', verified_unit_price: row['Verified Unit Price'] ?? '',
    line_remarks: row['Line Remarks']?.trim() || '', remarks: row.Remarks?.trim() || '',
  }
}
export function downloadInvoiceTemplate(): string[][] {
  return [INVOICE_IMPORT_HEADERS, INVOICE_IMPORT_HEADERS.map(header => String(INVOICE_IMPORT_SAMPLE[header] ?? ''))]
}
export const formatFileSize = (bytes: number) => bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
