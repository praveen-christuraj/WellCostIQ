import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { Box, Button, Typography } from '@mui/material'
import {
  ArrowForwardRounded, BackupOutlined, HistoryOutlined, StorageOutlined, TableRowsOutlined, TaskAltOutlined,
} from '@mui/icons-material'
import { api } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { ErrorMessage, PageHeading, Tag } from '../components/Common'
import { DatasetState } from '../components/ui/DatasetState'
import { SectionCard } from '../components/ui/SectionCard'
import { StatCard } from '../components/ui/StatCard'
import type { AuditPage } from '../lib/types'
import type { TableCatalogue } from '../lib/databaseBrowser'
import type { TaskOverview } from '../lib/workflowTypes'

// Module dashboard for Other Managements. Each figure comes from an endpoint the user is
// allowed to call; the API stays the authority, so a missing permission simply hides the card.
export default function OtherManagementOverview() {
  const { can } = useAuth()
  const canAudit = can('audit:read')
  const canBrowse = can('database-browser:read')
  const canTasks = can('tasks:read')
  const canBackup = can('backup:read')
  const [audit, setAudit] = useState<AuditPage | null>(null)
  const [weekTotal, setWeekTotal] = useState<number | undefined>(undefined)
  const [catalogue, setCatalogue] = useState<TableCatalogue | null>(null)
  const [backup, setBackup] = useState<{ completed: number; latest_completed_at: string | null } | null>(null)
  const [tasks, setTasks] = useState<TaskOverview | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const weekAgo = new Date(Date.now() - 6 * 24 * 60 * 60 * 1000)
    const from = `${weekAgo.getFullYear()}-${String(weekAgo.getMonth() + 1).padStart(2, '0')}-${String(weekAgo.getDate()).padStart(2, '0')}`
    const tasks: Promise<void>[] = []
    if (canAudit) {
      tasks.push(api<AuditPage>('/audit?page=1&page_size=20').then(page => { if (active) setAudit(page) }))
      tasks.push(api<AuditPage>(`/audit?page=1&page_size=20&date_from=${from}`).then(page => { if (active) setWeekTotal(page.total) }))
    }
    if (canBrowse) tasks.push(api<TableCatalogue>('/database-browser/tables').then(data => { if (active) setCatalogue(data) }))
    if (canBackup) tasks.push(api<{ completed: number; latest_completed_at: string | null }>('/backup/overview')
      .then(data => { if (active) setBackup(data) }))
    if (canTasks) tasks.push(api<TaskOverview>('/tasks/overview')
      .then(data => { if (active) setTasks(data) }))
    Promise.all(tasks)
      .catch(caught => { if (active) setError(caught instanceof Error ? caught.message : 'The module summary could not be loaded') })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [canAudit, canBrowse, canBackup, canTasks])

  const tools = [
    canTasks && { label: 'Task Manager', detail: 'Approval requests and manual work items, with priority, assignment and due dates.', to: '/other-management/tasks', icon: TaskAltOutlined, cta: 'Open queue' },
    canAudit && { label: 'Audit Log', detail: 'Every recorded action, actor, object and time — read-only evidence.', to: '/other-management/audit', icon: HistoryOutlined, cta: 'Open audit log' },
    canBrowse && { label: 'Database Browser', detail: 'Read-only table catalogue and row detail for this workspace.', to: '/other-management/database', icon: StorageOutlined, cta: 'Browse tables' },
    canBackup && { label: 'Backup & Recovery', detail: 'Verified archives, retention and the two-person restore workflow.', to: '/other-management/backup', icon: BackupOutlined, cta: 'Open backups' },
  ].filter(Boolean) as { label: string; detail: string; to: string; icon: typeof HistoryOutlined; cta: string }[]

  return <>
    <PageHeading
      eyebrow="ADMINISTRATION / OTHER MANAGEMENTS"
      title="Administration"
      subtitle="Work queues and the workspace controls: assigned tasks, notifications, the audit trail, read-only database tools, and verified backup and recovery."
      action={<Box display="flex" gap={1} flexWrap="wrap">
        {canAudit && <Button component={RouterLink} to="/other-management/audit" variant="outlined" endIcon={<ArrowForwardRounded/>}>Audit Log</Button>}
        {canBrowse && <Button component={RouterLink} to="/other-management/database" variant="contained" endIcon={<ArrowForwardRounded/>}>Database Browser</Button>}
      </Box>}
    />
    <ErrorMessage message={error}/>
    {busy ? <DatasetState kind="loading" title="Loading administration figures…"/> : <>
      <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: 'repeat(2, minmax(0,1fr))', lg: 'repeat(4, minmax(0,1fr))' } }}>
        {canAudit && <StatCard label="Audit entries" value={audit?.total?.toLocaleString() ?? '—'} hint="Recorded actions in this workspace" icon={<HistoryOutlined fontSize="small"/>}/>}
        {canAudit && <StatCard label="Last 7 days" value={weekTotal?.toLocaleString() ?? '—'} hint="Actions recorded this week" icon={<HistoryOutlined fontSize="small"/>}/>}
        {canBrowse && <StatCard label="Database tables" value={catalogue?.total_tables?.toLocaleString() ?? '—'} hint="Tables available to browse" icon={<StorageOutlined fontSize="small"/>}/>}
        {canBrowse && <StatCard label="Database records" value={catalogue?.total_rows?.toLocaleString() ?? '—'} hint="Rows across the workspace tables" icon={<TableRowsOutlined fontSize="small"/>}/>}
        {canTasks && <StatCard
          label="Open tasks"
          value={tasks ? (tasks.open + tasks.in_progress).toLocaleString() : '—'}
          hint={tasks
            ? `${tasks.overdue} overdue · ${tasks.due_today} due today${tasks.mine ? ` · ${tasks.mine} assigned to you` : ''}`
            : 'Approval and manual work items'}
          icon={<TaskAltOutlined fontSize="small"/>}
          tone={tasks && tasks.overdue ? 'error' : tasks && tasks.due_today ? 'warning' : 'default'}
        />}
        {canBackup && <StatCard label="Backups" value={backup?.completed !== undefined ? backup.completed.toLocaleString() : '—'} hint={backup?.latest_completed_at ? `Last completed ${new Date(backup.latest_completed_at).toLocaleDateString()}` : 'No archive taken yet'} icon={<BackupOutlined fontSize="small"/>}/>}
      </Box>

      <Box display="grid" gap={2} sx={{ mt: 2, gridTemplateColumns: { xs: '1fr', lg: canAudit ? 'minmax(0, 1.35fr) minmax(0, 1fr)' : '1fr' } }}>
        {canAudit && <SectionCard
          title="Recent activity"
          subtitle="The latest actions across the workspace, from the audit trail."
          meta={<Tag tone="info">Read-only</Tag>}
          action={<Button component={RouterLink} to="/other-management/audit" size="small" endIcon={<ArrowForwardRounded sx={{ fontSize: 15 }}/>}>Open log</Button>}
          bodyPadding={0}
        >
          {audit && audit.items.length === 0 && <DatasetState compact kind="empty" title="No actions recorded yet" message="Audited actions will appear here as users work in the workspace."/>}
          {audit?.items.slice(0, 8).map(entry => <Box key={entry.id} display="grid" gridTemplateColumns={{ xs: '1fr', md: '170px 1fr 180px' }} gap={1.2} alignItems="center" sx={{ px: 2.25, py: 1.1, borderBottom: '1px solid', borderColor: 'divider', '&:last-of-type': { borderBottom: 0 } }}>
            <Typography fontSize={11.5} color="text.secondary" className="tnum">{new Date(entry.created_at).toLocaleString()}</Typography>
            <Typography fontSize={12.5} noWrap>{entry.summary || `${entry.action} ${entry.entity_type}`}</Typography>
            <Typography fontSize={11.5} color="text.secondary" noWrap>{entry.actor_name || 'System'} · {entry.entity_type.replace(/_/g, ' ')}</Typography>
          </Box>)}
        </SectionCard>}

        <SectionCard title="Administration tools" subtitle="Each destination is gated by its own capability.">
          <Box sx={{ display: 'grid', gap: 1 }}>
            {tools.map(tool => <Box key={tool.label} sx={{ display: 'flex', alignItems: 'center', gap: 1.2, border: '1px solid', borderColor: 'divider', borderRadius: 1.5, px: 1.5, py: 1.15, '&:hover': { borderColor: 'text.disabled' } }}>
              <Box className="table-icon"><tool.icon sx={{ fontSize: 17 }}/></Box>
              <Box flex={1} minWidth={0}>
                <Typography fontSize={12.5} fontWeight={650}>{tool.label}</Typography>
                <Typography fontSize={11} color="text.secondary" sx={{ lineHeight: 1.4 }}>{tool.detail}</Typography>
              </Box>
              <Button component={RouterLink} to={tool.to} size="small">{tool.cta}</Button>
            </Box>)}
            {!tools.length && <Typography color="text.secondary" fontSize={12.5}>No administration tools are assigned to your role.</Typography>}
          </Box>
        </SectionCard>
      </Box>
    </>}
  </>
}
