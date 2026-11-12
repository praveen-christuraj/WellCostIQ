import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Box, Button, Chip, CircularProgress, Paper, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { AddRounded, CheckCircleOutlineRounded, RefreshRounded } from '@mui/icons-material'

import { FormDialog, Tag } from '../Common'
import { api, body } from '../../lib/api'
import {
  formatTemplateDate, TEMPLATE_KIND_LABEL,
  type TemplateApplyPreview, type TemplateKind, type TemplateSummary, type Template,
} from '../../lib/recordTemplates'

/**
 * Pick a starting point for a record.
 *
 * The picker never applies a template by surprise: it loads the preview first,
 * so the user sees the exact lines that will be added and every line that is no
 * longer available, then confirms. Applying still does not save the record — the
 * page the user is on does that with its ordinary save.
 */
export function TemplatePickerDialog({ open, kind, wellId = '', onClose, onApply }: {
  open: boolean
  kind: TemplateKind
  /** The well being configured, so a plan template can be matched against it. */
  wellId?: string
  onClose: () => void
  onApply: (template: Template, preview: TemplateApplyPreview) => void
}) {
  const [templates, setTemplates] = useState<TemplateSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState<Template | null>(null)
  const [preview, setPreview] = useState<TemplateApplyPreview | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [previewError, setPreviewError] = useState('')

  const selected = useMemo(() => templates.find(item => item.id === selectedId) ?? null, [templates, selectedId])

  const load = async () => {
    setLoading(true); setLoadError('')
    try {
      const rows = await api<TemplateSummary[]>(`/record-templates?kind=${kind}`)
      setTemplates(rows)
      setSelectedId(current => rows.some(row => row.id === current) ? current : (rows[0]?.id ?? ''))
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : 'The template library could not be loaded')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { if (open) { void load() } /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [open, kind])

  // Load the chosen template and its preview together: the lines and the
  // warnings always describe the same template.
  useEffect(() => {
    if (!open || !selectedId) { setDetail(null); setPreview(null); return }
    let cancelled = false
    const run = async () => {
      setPreviewing(true); setPreviewError('')
      try {
        const [full, nextPreview] = await Promise.all([
          api<Template>(`/record-templates/${selectedId}`),
          api<TemplateApplyPreview>(`/record-templates/${selectedId}/preview`, {
            method: 'POST', body: body({ well_id: wellId }),
          }),
        ])
        if (cancelled) return
        setDetail(full)
        setPreview(nextPreview)
      } catch (caught) {
        if (!cancelled) setPreviewError(caught instanceof Error ? caught.message : 'This template could not be read')
      } finally {
        if (!cancelled) setPreviewing(false)
      }
    }
    void run()
    return () => { cancelled = true }
  }, [open, selectedId, wellId])

  const apply = () => {
    if (detail && preview?.can_apply) onApply(detail, preview)
  }

  // A template of one kind only fills the lists that kind uses, and an older API
  // may omit the ones it has never heard of. Reading them defensively keeps the
  // picker open (with the lines it did get) instead of failing the whole page.
  const lines = preview
    ? [
      ...(preview.services ?? []), ...(preview.consumables ?? []),
      ...(preview.tangibles ?? []), ...(preview.sections ?? []),
    ]
    : []
  const availableCount = lines.filter(line => line.is_available).length
  const warnings = preview?.warnings ?? []

  return <FormDialog
    open={open}
    title={`Use a ${TEMPLATE_KIND_LABEL[kind]} template`}
    subtitle="Pick a saved starting point, check what it adds, then fill in only the values that change. The template itself is never changed by using it."
    onClose={onClose}
    onSubmit={apply}
    dirty={Boolean(selectedId)}
    busy={previewing}
    busyLabel="Reading template..."
    submitLabel={availableCount ? `Use ${availableCount} line${availableCount === 1 ? '' : 's'}` : 'Use template'}
    submitDisabled={!detail || !preview?.can_apply}
    maxWidth="md"
  >
    <Box display="grid" gap={1.8}>
      {loading && <Box display="flex" alignItems="center" gap={1}><CircularProgress size={18}/><Typography fontSize={12.5}>Loading templates…</Typography></Box>}
      {loadError && <Alert severity="error" action={<Button size="small" startIcon={<RefreshRounded/>} onClick={() => { void load() }}>Retry</Button>}>
        {loadError}
      </Alert>}

      {!loading && !loadError && !templates.length && <Alert severity="info">
        There is no {TEMPLATE_KIND_LABEL[kind].toLowerCase()} template yet. Build one from a record you already rate, then reuse it here.
        <Box mt={1}><Button component={RouterLink} to="/record-templates" size="small" startIcon={<AddRounded/>} onClick={onClose}>Manage templates</Button></Box>
      </Alert>}

      {templates.length > 0 && <TextField select label="Template" value={selectedId} onChange={event => setSelectedId(event.target.value)} SelectProps={{ native: true }}>
        {templates.map(template => <option key={template.id} value={template.id}>
          {template.name}
          {template.scope ? ` · ${template.scope}` : ''}
          {template.is_shared ? ' · shared' : ''}
          {` · ${template.line_count} line${template.line_count === 1 ? '' : 's'}`}
          {template.unavailable_count ? ` · ${template.unavailable_count} unavailable` : ''}
        </option>)}
      </TextField>}

      {selected && <Box display="flex" gap={.7} flexWrap="wrap" alignItems="center">
        {selected.scope && <Tag tone="info">{selected.scope}</Tag>}
        {selected.template_kind === 'afe' && <Tag tone="neutral">{selected.afe_type}</Tag>}
        {selected.standard_currency && <Tag tone="neutral">{selected.standard_currency}</Tag>}
        {selected.is_shared && <Tag tone="info">Shared by {selected.owner_name || 'the workspace'}</Tag>}
        {!selected.is_owner && <Tag tone="warning">Read-only: duplicate it in Manage templates to change it</Tag>}
        <Typography fontSize={11.5} color="text.secondary">
          {selected.use_count ? `Used ${selected.use_count} time${selected.use_count === 1 ? '' : 's'} · last ${formatTemplateDate(selected.last_used_at)}` : 'Never used yet'}
        </Typography>
      </Box>}

      {selected?.description && <Typography fontSize={12.5} color="text.secondary">{selected.description}</Typography>}

      {previewError && <Alert severity="error">{previewError}</Alert>}

      {previewing && !lines.length && <Box display="flex" alignItems="center" gap={1}><CircularProgress size={18}/><Typography fontSize={12.5}>Checking what this template adds…</Typography></Box>}

      {lines.length > 0 && <Paper variant="outlined" sx={{ borderRadius: 2, overflow: 'hidden' }}>
        <Box display="flex" alignItems="center" gap={1} px={1.5} py={1} sx={{ bgcolor: 'background.default', borderBottom: '1px solid', borderColor: 'divider', flexWrap: 'wrap' }}>
          <CheckCircleOutlineRounded sx={{ fontSize: 17, color: 'text.secondary' }}/>
          <Typography fontSize={12} fontWeight={800}>{availableCount} of {lines.length} lines ready to use</Typography>
          <Typography fontSize={11.5} color="text.secondary" ml="auto">Nothing is saved until you save the record.</Typography>
        </Box>
        <Box sx={{ maxHeight: 260, overflow: 'auto' }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 800, fontSize: 11, bgcolor: 'background.paper' }}>TYPE</TableCell>
                <TableCell sx={{ fontWeight: 800, fontSize: 11, bgcolor: 'background.paper' }}>LINE</TableCell>
                <TableCell sx={{ fontWeight: 800, fontSize: 11, bgcolor: 'background.paper' }}>SCOPE</TableCell>
                <TableCell sx={{ fontWeight: 800, fontSize: 11, bgcolor: 'background.paper' }}>STATUS</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {lines.map((line, index) => <TableRow key={`${line.kind}-${index}`} hover>
                <TableCell sx={{ fontSize: 12, whiteSpace: 'nowrap', textTransform: 'capitalize' }}>{line.kind}</TableCell>
                <TableCell sx={{ fontSize: 12 }}>{line.label}</TableCell>
                <TableCell sx={{ fontSize: 12, color: 'text.secondary' }}>{line.note || '—'}</TableCell>
                <TableCell sx={{ fontSize: 12 }}>
                  {line.is_available
                    ? <Typography component="span" fontSize={11.5} color="text.secondary">Ready</Typography>
                    : <Typography component="span" fontSize={11.5} fontWeight={800} color="warning.dark">Unavailable</Typography>}
                </TableCell>
              </TableRow>)}
            </TableBody>
          </Table>
        </Box>
      </Paper>}

      {warnings.length > 0 && <Alert severity="warning">
        <Typography fontSize={12.5} fontWeight={800} mb={.4}>Check before continuing</Typography>
        <Box component="ul" sx={{ m: 0, pl: 2.2 }}>
          {warnings.slice(0, 8).map((warning, index) => <li key={index}><Typography fontSize={12}>{warning}</Typography></li>)}
        </Box>
        {warnings.length > 8 && <Typography fontSize={11.5} mt={.4}>{warnings.length - 8} more.</Typography>}
      </Alert>}

      {preview && !preview.can_apply && <Alert severity="error">
        Every line in this template is unavailable, so it cannot be used. Restore the master data or edit the template in Manage templates.
      </Alert>}

      {!templates.length && !loading && !loadError && <Box display="flex" gap={1}>
        <Button component={RouterLink} to="/record-templates" size="small" onClick={onClose}>Open Manage templates</Button>
      </Box>}

      {templates.length > 0 && <Box display="flex" gap={1} alignItems="center">
        <Chip size="small" variant="outlined" label={`${templates.length} template${templates.length === 1 ? '' : 's'} available`}/>
        <Button component={RouterLink} to="/record-templates" size="small" onClick={onClose} sx={{ ml: 'auto' }}>Manage templates</Button>
      </Box>}
    </Box>
  </FormDialog>
}
