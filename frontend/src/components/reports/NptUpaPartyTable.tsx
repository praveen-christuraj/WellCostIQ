import { useState } from 'react'
import { Alert, Box, Paper, Tab, Tabs, Typography } from '@mui/material'
import { formatMoney, formatQuantity, type NptUpaPartyRow, type NptUpaReport } from '../../lib/usageReports'

const cellSx = {
  border: '1px solid',
  borderColor: 'divider',
  px: 1,
  py: 0.75,
  fontSize: 11.5,
  whiteSpace: 'nowrap',
} as const

type PartyView = 'parties' | 'subcategories'

const partyLabel = (row: NptUpaPartyRow) => row.vendor_name || row.party_name || 'Unassigned'

/**
 * NPT/UPA by responsible party (vendor) and, per vendor, by its service
 * subcategories. Both views come from the same deduplicated allocations as the
 * well matrix, so the vendor column adds back up to the well totals, and the
 * subcategory rows split one vendor's figures rather than adding to them.
 */
export default function NptUpaPartyTable({ report, currency }: {
  report: NptUpaReport
  currency: string
}) {
  const [view, setView] = useState<PartyView>('parties')
  const rows = view === 'parties' ? report.parties : report.party_subcategories
  const linesFor = (vendorId: string) => report.party_subcategories.filter(
    row => row.vendor_id === vendorId && row.vendor_subcategory_id,
  ).length
  const unlinked = report.parties.filter(row => !row.is_linked && row.party_name !== 'Unassigned')
  const unassigned = report.parties.find(row => !row.is_linked && row.party_name === 'Unassigned')

  return <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, mb: 1.7, overflowX: 'auto' }}>
    <Box display="flex" alignItems="flex-end" justifyContent="space-between" gap={1.5} mb={1.1} flexWrap="wrap">
      <Box>
        <Typography fontWeight={800} fontSize={14}>NPT / UPA by responsible party</Typography>
        <Typography color="text.secondary" fontSize={11.2}>
          Vendor totals and, per vendor, the service subcategory totals configured on the well sub activities. Costs are in {currency}; allocated duration is deduplicated exactly like the well matrix.
        </Typography>
      </Box>
      <Tabs value={view} onChange={(_event, next) => setView(next as PartyView)} sx={{ minHeight: 34 }}>
        <Tab value="parties" label="By vendor" sx={{ minHeight: 34, fontSize: 11.5 }}/>
        <Tab value="subcategories" label="By vendor service" sx={{ minHeight: 34, fontSize: 11.5 }}/>
      </Tabs>
    </Box>

    {unlinked.length > 0 && <Alert severity="info" sx={{ mb: 1.2 }}>
      {unlinked.length} responsible {unlinked.length === 1 ? 'party is' : 'parties are'} still recorded as free text rather than a Master Data vendor
      ({unlinked.slice(0, 3).map(row => row.party_name).join(', ')}{unlinked.length > 3 ? '…' : ''}). Link them on the well sub activities so that vendor's costs and NPT/UPA days stay together.
    </Alert>}
    {unassigned && <Alert severity="warning" sx={{ mb: 1.2 }}>
      Some NPT/UPA lines carry no responsible party at all. Assign the vendor (and its service subcategory) on the sub activity or on the daily cost line.
    </Alert>}

    {!rows.length ? (
      <Alert severity="info">
        {report.entry_count
          ? `No NPT/UPA ${view === 'parties' ? 'responsible party' : 'vendor service'} rows match these filters.`
          : 'No cost sheets match the selected filters.'}
      </Alert>
    ) : (
      <Box
        component="table"
        sx={{
          borderCollapse: 'collapse', width: '100%', minWidth: 980,
          '& th, & td': cellSx,
          '& thead th': { bgcolor: 'action.hover', textAlign: 'right', fontWeight: 800 },
          '& thead th:first-of-type, & thead th:nth-of-type(2)': { textAlign: 'left' },
          '& tbody th': { textAlign: 'left' },
          '& td': { textAlign: 'right', fontVariantNumeric: 'tabular-nums' },
          '& tr[data-total="true"]': { bgcolor: 'action.hover', fontWeight: 800 },
        }}
      >
        <thead>
          <tr>
            <th>Responsible party</th>
            <th>{view === 'parties' ? 'Vendor code' : 'Service subcategory'}</th>
            <th>Wells</th>
            <th>NPT days</th>
            <th>NPT hours</th>
            <th>NPT dates</th>
            <th>NPT cost</th>
            <th>UPA days</th>
            <th>UPA hours</th>
            <th>UPA dates</th>
            <th>UPA cost</th>
            <th>Total cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => <tr key={`${view}:${row.party_key}`} data-total={row.is_linked ? 'true' : null}>
            <th>
              {partyLabel(row)}
              {!row.is_linked && <Typography component="span" display="block" color="text.secondary" fontSize={10.5}>
                Free-text party — not linked to a vendor
              </Typography>}
              {row.is_linked && view === 'parties' && linesFor(row.vendor_id) > 0 && (
                <Typography component="span" display="block" color="text.secondary" fontSize={10.5}>
                  {linesFor(row.vendor_id)} service subcategor{linesFor(row.vendor_id) === 1 ? 'y' : 'ies'} in this period
                </Typography>
              )}
            </th>
            <td style={{ textAlign: 'left' }}>
              {view === 'parties'
                ? (row.vendor_code || '—')
                : (row.vendor_subcategory_code
                    ? `${row.vendor_subcategory_code} — ${row.vendor_subcategory_name}`
                    : 'No service subcategory')}
            </td>
            <td>{row.well_count}</td>
            <td>{formatQuantity(row.npt_days)}</td>
            <td>{formatQuantity(row.npt_hours)}</td>
            <td>{row.npt_affected_dates}</td>
            <td>{formatMoney(row.npt_amount, currency)}</td>
            <td>{formatQuantity(row.upa_days)}</td>
            <td>{formatQuantity(row.upa_hours)}</td>
            <td>{row.upa_affected_dates}</td>
            <td>{formatMoney(row.upa_amount, currency)}</td>
            <td>{formatMoney(row.total_amount, currency)}</td>
          </tr>)}
        </tbody>
      </Box>
    )}
    <Typography color="text.secondary" fontSize={11} mt={1}>
      A vendor's NPT/UPA equals the sum of its service subcategory rows. Lines with no configured service subcategory appear under “No service subcategory”.
    </Typography>
  </Paper>
}
