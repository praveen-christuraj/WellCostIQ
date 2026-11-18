import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Box, Button, MenuItem, TextField, Typography } from '@mui/material'
import { ChartPanel } from '../../components/ui/ChartPanel'
import { InteractiveChart } from '../../components/ui/InteractiveChart'
import { SectionCard } from '../../components/ui/SectionCard'
import { StatCard } from '../../components/ui/StatCard'
import { ErrorMessage, PageHeading } from '../../components/Common'
import { useAuth } from '../../context/AuthContext'
import { useColorMode } from '../../context/ThemeContext'
import { chartPalette } from '../../designSystem'
import { opsDashboard, opsScopeReference, type OpsDashboard, type OpsScopeReference } from '../../lib/operations'

export default function OperationsOverview() {
  const { can } = useAuth(),
    { mode } = useColorMode(),
    colors = chartPalette(mode)
  const [ref, setRef] = useState<OpsScopeReference | null>(null),
    [data, setData] = useState<OpsDashboard | null>(null),
    [error, setError] = useState('')
  const [rig, setRig] = useState(''),
    [well, setWell] = useState(''),
    [scope, setScope] = useState(''),
    [from, setFrom] = useState(''),
    [to, setTo] = useState('')
  useEffect(() => {
    opsScopeReference()
      .then(setRef)
      .catch((e) => setError(e.message))
  }, [])
  useEffect(() => {
    let current = true
    setError('')
    setData(null)
    opsDashboard({ rig_id: rig, well_id: well, scope, from, to })
      .then((d) => {
        if (current) setData(d)
      })
      .catch((e) => {
        if (current) setError(e.message)
      })
    return () => {
      current = false
    }
  }, [well, rig, scope, from, to])
  const k = data?.kpis,
    trend = data?.daily_trend ?? [],
    codes = data?.npt_by_code ?? [],
    parties = data?.npt_by_agency ?? []
  const base = {
    animation: false,
    color: colors.series,
    textStyle: { color: colors.axis },
    tooltip: { trigger: 'axis', confine: true },
    grid: { left: 16, right: 28, top: 44, bottom: 20, containLabel: true },
  }
  const bars = (labels: string[], values: number[]) => ({
    ...base,
    xAxis: { type: 'value', name: 'h', nameGap: 4 },
    yAxis: {
      type: 'category',
      data: labels,
      inverse: true,
      axisLabel: { width: 110, overflow: 'truncate', hideOverlap: true },
    },
    series: [{ type: 'bar', data: values }],
  })
  return (
    <Box>
      <PageHeading
        eyebrow="Well Operations"
        title="Operations Dashboard"
        subtitle="Report coverage and verified drilling and completion performance (WAT UTC+1:00). Hours, penetration rates and schedule variance come from operations records only."
        action={
          <>
            {can('ops-plan:read') && (
              <Button variant="outlined" component={Link} to="/operations/plans">
                Plans & timeline
              </Button>
            )}
            {can('ops-report:read') && (
              <>
                <Button
                  variant="outlined"
                  component={Link}
                  to={`/operations/summary${well ? `?well=${encodeURIComponent(well)}${scope ? `&scope=${encodeURIComponent(scope)}` : ''}` : ''}`}
                >
                  Operation summary
                </Button>
                <Button variant="contained" component={Link} to="/operations/reports">
                  Daily reports
                </Button>
              </>
            )}
            {can('ops-analytics:read') && (
              <Button variant="outlined" component={Link} to="/operations/analytics">
                Analytics
              </Button>
            )}
          </>
        }
      />
      {error && <ErrorMessage message={error} />}
      <SectionCard title="Scope & reporting period">
        <Box
          display="grid"
          gap={2}
          gridTemplateColumns={{ xs: '1fr', sm: 'repeat(2,minmax(0,1fr))', lg: 'repeat(5,minmax(0,1fr))' }}
        >
          <TextField
            select
            label="Rig"
            value={rig}
            onChange={(e) => {
              setRig(e.target.value)
              setWell('')
            }}
          >
            <MenuItem value="">All rigs</MenuItem>
            {ref?.rigs.map((r) => (
              <MenuItem key={r.id} value={r.id}>
                {r.display_name}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label="Well" value={well} onChange={(e) => setWell(e.target.value)}>
            <MenuItem value="">All wells</MenuItem>
            {ref?.wells
              .filter((w) => !rig || w.rig_id === rig)
              .map((w) => (
                <MenuItem key={w.id} value={w.id}>
                  {w.display_name}
                </MenuItem>
              ))}
          </TextField>
          <TextField select label="Scope" value={scope} onChange={(e) => setScope(e.target.value)}>
            <MenuItem value="">Both</MenuItem>
            <MenuItem value="drilling">Drilling</MenuItem>
            <MenuItem value="completion">Completion</MenuItem>
          </TextField>
          <TextField
            type="date"
            label="From"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
          />
          <TextField
            type="date"
            label="To"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
          />
        </Box>
      </SectionCard>
      {k && (
        <Box display="grid" gap={2} my={2} gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr', lg: 'repeat(4,minmax(0,1fr))' }}>
          <StatCard
            label="Reports"
            value={k.total_reports}
            hint={`${k.reports_awaiting_review} awaiting source review · ${k.wells_covered} wells reporting`}
          />
          <StatCard
            label="Verified hours"
            value={k.total_logged_hours.toFixed(3)}
            hint={`${k.planned_hours} planned · ${k.upa_hours} UPA · ${k.npt_hours} NPT`}
          />
          <StatCard
            label="Weighted ROP"
            value={k.avg_rop === null ? '—' : `${k.avg_rop} m/h`}
            hint={`${k.productive_pct}% productive · ${k.npt_pct}% NPT of logged time`}
          />
          <StatCard
            label="Lead / lag"
            value={k.lag_days === null ? '—' : `${k.lag_days} d`}
            hint="Single well and scope · positive is behind"
          />
        </Box>
      )}
      <Box display="grid" gap={2} gridTemplateColumns="minmax(0,1fr)">
        <ChartPanel
          title="Activity hours by day"
          caption="Submitted and approved activity blocks. Drafts and deleted reports are excluded."
          empty={!trend.length}
          emptyMessage="Submit a reviewed time log to see the trend."
        >
          <InteractiveChart
            style={{ height: '100%' }}
            option={{
              ...base,
              legend: { top: 2, type: 'scroll', textStyle: { color: colors.axis } },
              xAxis: { type: 'category', data: trend.map((t) => t.date), axisLabel: { hideOverlap: true } },
              yAxis: { type: 'value', name: 'Hours' },
              series: (
                [
                  ['Planned', 'planned_hours'],
                  ['UPA', 'upa_hours'],
                  ['NPT', 'npt_hours'],
                ] as const
              ).map(([name, key]) => ({ name, type: 'bar', stack: 'time', data: trend.map((t) => t[key]) })),
            }}
          />
        </ChartPanel>
        <Box display="grid" gap={2} gridTemplateColumns={{ xs: 'minmax(0,1fr)', lg: 'repeat(2,minmax(0,1fr))' }}>
          <ChartPanel title="NPT by code" empty={!codes.length} emptyMessage="No verified NPT in this period.">
            <InteractiveChart
              style={{ height: '100%' }}
              option={bars(
                codes.map((c) => c.code),
                codes.map((c) => c.hours),
              )}
            />
          </ChartPanel>
          <ChartPanel title="NPT by responsible party" empty={!parties.length} emptyMessage="No verified NPT in this period.">
            <InteractiveChart
              style={{ height: '100%' }}
              option={bars(
                parties.map((c) => c.agency),
                parties.map((c) => c.hours),
              )}
            />
          </ChartPanel>
        </Box>
        {k && (
          <SectionCard
            title="Productivity & allocation"
            subtitle="Allocation is separate from the Planned / UPA / NPT time classification."
          >
            <Typography>
              {k.productive_hours} productive hours · {k.nonproductive_hours} nonproductive hours · {k.unaccounted_hours}{' '}
              unaccounted hours
            </Typography>
            <Typography variant="body2">
              {Object.entries(k.allocation_hours ?? {})
                .map(([k, h]) => `${k}: ${h} h`)
                .join(' · ')}
            </Typography>
          </SectionCard>
        )}
        {Boolean(data?.missing_reports.length) && (
          <SectionCard
            title="Missing daily logs"
            subtitle="Closed operating days in dated, active programmes. Last seven days by default; up to 31 selected days and 100 gaps."
          >
            {data?.missing_reports.map((g) => (
              <Typography key={`${g.well_code}-${g.date}-${g.scope}`} variant="body2">
                {g.date} · {g.well_code} / {g.scope}
              </Typography>
            ))}
          </SectionCard>
        )}
        {can('ops-report:read') && (
          <SectionCard title="Recent reports">
            {data?.recent_reports.length ? (
              data.recent_reports.map((r) => (
                <Box
                  key={r.id}
                  py={1}
                  display="flex"
                  alignItems="center"
                  gap={1}
                  flexWrap="wrap"
                  justifyContent="space-between"
                  sx={{ borderBottom: 1, borderColor: 'divider' }}
                >
                  <Typography>
                    {r.report_date} · {r.rig_code_snapshot} / {r.well_code_snapshot} · {r.scope} · {r.report_type}{' '}
                    {r.report_no_text} · {r.status} ·{' '}
                    {Array.isArray(r.blocks) ? `${r.blocks.length} blocks` : 'Block count unavailable'}
                  </Typography>
                  {can('ops-report:read') && (
                    <Button component={Link} to={`/operations/reports/${r.id}`}>
                      Open report
                    </Button>
                  )}
                </Box>
              ))
            ) : (
              <Alert severity="info">No reports in this selection.</Alert>
            )}
          </SectionCard>
        )}
      </Box>
    </Box>
  )
}
