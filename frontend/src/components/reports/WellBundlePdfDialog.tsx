import { useEffect, useId, useMemo, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, FormGroup, LinearProgress, MenuItem, Switch, TextField, Typography,
} from '@mui/material'
import { CloseRounded, PictureAsPdfOutlined } from '@mui/icons-material'
import { radius, space } from '../../designSystem'
import { api } from '../../lib/api'
import { localToday, type DailyCostReference, type DailyCostWellOption } from '../../lib/dailyCost'
import {
  BUNDLE_MODULES, exportWellBundlePdf, type BundleModuleKey, type BundleScope,
} from '../../lib/wellBundlePdf'

/**
 * Consolidated Well & Scope PDF Bundle Dialog.
 *
 * Allows exporting one continuous PDF covering all seven reports for a selected
 * well and scope (Drilling, Completion, or Drilling & Completion):
 * AFE Estimate, Daily Cost Report, Drill-In Report, Well Cost Analysis Visualized,
 * LIH Cost Register, NDT Inspection Register, and Mud Cost Analysis.
 */
export function WellBundlePdfDialog({
  open,
  onClose,
  wells: providedWells,
  initialWellId = '',
  initialDateFrom = '',
  initialDateTo = '',
  initialIncludeDraft = true,
}: {
  open: boolean
  onClose: () => void
  wells?: DailyCostWellOption[]
  initialWellId?: string
  initialDateFrom?: string
  initialDateTo?: string
  initialIncludeDraft?: boolean
}) {
  const titleId = useId()
  const [fetchedWells, setFetchedWells] = useState<DailyCostWellOption[]>([])
  const [loadingWells, setLoadingWells] = useState(false)
  const [wellId, setWellId] = useState(initialWellId)
  const [scope, setScope] = useState<BundleScope>('both')
  const [mode, setMode] = useState<'inception' | 'range'>(initialDateFrom ? 'range' : 'inception')
  const [dateFrom, setDateFrom] = useState(initialDateFrom)
  const [dateTo, setDateTo] = useState(initialDateTo || localToday())
  const [includeDraft, setIncludeDraft] = useState(initialIncludeDraft)
  const [orientation, setOrientation] = useState<'landscape' | 'portrait'>('landscape')
  const [selectedModules, setSelectedModules] = useState<BundleModuleKey[]>(BUNDLE_MODULES.map(m => m.key))
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')

  const wells = providedWells && providedWells.length ? providedWells : fetchedWells
  const selectedWell = useMemo(() => wells.find(w => w.id === wellId) ?? null, [wells, wellId])

  useEffect(() => {
    if (!open) return
    setError('')
    setProgress('')
    setSelectedModules(BUNDLE_MODULES.map(m => m.key))
    setOrientation('landscape')
    setIncludeDraft(initialIncludeDraft)
    setMode(initialDateFrom ? 'range' : 'inception')
    setDateFrom(initialDateFrom)
    setDateTo(initialDateTo || localToday())
    if (initialWellId) setWellId(initialWellId)
    if (!providedWells || !providedWells.length) {
      setLoadingWells(true)
      api<DailyCostReference>('/daily-cost/reference', { silent: true })
        .then(ref => {
          const active = (ref.wells ?? []).filter(w => !(w.drilling_is_deleted && w.completion_is_deleted))
          setFetchedWells(active)
          if (!initialWellId && active.length === 1) setWellId(active[0].id)
        })
        .catch(caught => setError(caught instanceof Error ? caught.message : 'Could not load wells'))
        .finally(() => setLoadingWells(false))
    }
  }, [open, providedWells, initialWellId, initialDateFrom, initialDateTo, initialIncludeDraft])

  // Auto-align scope options when a well only has Drilling or only Completion configured.
  const scopeOptions = useMemo(() => {
    const drillingAvailable = selectedWell
      ? (!selectedWell.drilling_is_deleted && ((selectedWell.sections?.length ?? 0) > 0 || Boolean(selectedWell.status)))
      : true
    const completionAvailable = selectedWell
      ? (!selectedWell.completion_is_deleted && ((selectedWell.completion_sections?.length ?? 0) > 0 || Boolean(selectedWell.completion_status)))
      : true
    const out: { value: BundleScope; label: string }[] = []
    if (drillingAvailable && completionAvailable) {
      out.push({ value: 'both', label: 'Drilling & Completion (Both)' })
    }
    if (drillingAvailable) out.push({ value: 'drilling', label: 'Drilling only' })
    if (completionAvailable) out.push({ value: 'completion', label: 'Completion only' })
    return out.length ? out : [{ value: 'both' as BundleScope, label: 'Drilling & Completion (Both)' }]
  }, [selectedWell])

  useEffect(() => {
    if (!scopeOptions.some(o => o.value === scope)) {
      setScope(scopeOptions[0].value)
    }
  }, [scopeOptions, scope])

  const invalidRange = mode === 'range' && (!dateFrom || !dateTo || dateFrom > dateTo)
  const toggleModule = (key: BundleModuleKey) => {
    setSelectedModules(current => (
      current.includes(key) ? current.filter(item => item !== key) : [...current, key]
    ))
  }

  const run = async () => {
    if (!selectedWell || invalidRange || !selectedModules.length) return
    setBusy(true)
    setError('')
    try {
      await exportWellBundlePdf({
        well: selectedWell,
        scope,
        dateFrom: mode === 'range' ? dateFrom : '',
        dateTo: mode === 'range' ? dateTo : localToday(),
        includeDraft,
        orientation,
        modules: selectedModules,
        onProgress: setProgress,
      })
      setProgress('')
      onClose()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The consolidated PDF bundle could not be built')
    } finally {
      setBusy(false)
    }
  }

  return <Dialog
    open={open}
    onClose={() => { if (!busy) onClose() }}
    fullWidth
    maxWidth="md"
    disableEscapeKeyDown
    aria-labelledby={titleId}
    slotProps={{ paper: { sx: { borderRadius: `${radius.lg}px` } } }}
  >
    <DialogTitle id={titleId} sx={{ px: `${space[6]}px`, pt: 2.5, pb: 1 }}>
      <Box component="span" sx={{ display: 'block', fontSize: 18, fontWeight: 800, letterSpacing: '-.2px' }}>
        Consolidated Well PDF Bundle
      </Box>
      <Box component="span" sx={{ display: 'block', mt: .5, fontSize: 12.5, fontWeight: 400, color: 'text.secondary', lineHeight: 1.5 }}>
        Export one continuous PDF dossier combining AFE Estimate, Daily Cost Report, Drill-In Report, Well Cost Analysis Visualized, LIH Cost Register, NDT Inspection Register and Mud Cost Analysis — strictly filtered to the chosen scope.
      </Box>
    </DialogTitle>
    <DialogContent sx={{ px: `${space[6]}px`, pb: 1.5 }}>
      <Box display="grid" gap={1.6} sx={{ mt: .5 }}>
        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1.35fr 1fr' } }}>
          <TextField
            select
            required
            size="small"
            label="Well"
            value={wellId}
            disabled={busy || loadingWells}
            onChange={event => setWellId(event.target.value)}
          >
            <MenuItem value="">{loadingWells ? 'Loading wells…' : 'Select a well'}</MenuItem>
            {wells.map(well => (
              <MenuItem key={well.id} value={well.id}>
                {well.well_code} · {well.well_name}{well.rig_code ? ` (${well.rig_code})` : ''}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label="Operation scope"
            value={scope}
            disabled={busy}
            onChange={event => setScope(event.target.value as BundleScope)}
          >
            {scopeOptions.map(opt => (
              <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>
            ))}
          </TextField>
        </Box>

        <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
          <TextField
            select
            size="small"
            label="Report period"
            value={mode}
            disabled={busy}
            onChange={event => setMode(event.target.value as 'inception' | 'range')}
          >
            <MenuItem value="inception">Inception to today</MenuItem>
            <MenuItem value="range">Custom date range</MenuItem>
          </TextField>
          <TextField
            select
            size="small"
            label="Page orientation"
            value={orientation}
            disabled={busy}
            onChange={event => setOrientation(event.target.value as 'landscape' | 'portrait')}
          >
            <MenuItem value="landscape">Landscape (recommended for tables &amp; charts)</MenuItem>
            <MenuItem value="portrait">Portrait</MenuItem>
          </TextField>
        </Box>

        {mode === 'range' && <Box display="grid" gap={1.5} sx={{ gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
          <TextField
            required
            size="small"
            type="date"
            label="From date"
            value={dateFrom}
            disabled={busy}
            onChange={event => setDateFrom(event.target.value)}
            InputLabelProps={{ shrink: true }}
          />
          <TextField
            required
            size="small"
            type="date"
            label="To date"
            value={dateTo}
            disabled={busy}
            onChange={event => setDateTo(event.target.value)}
            InputLabelProps={{ shrink: true }}
          />
        </Box>}
        {invalidRange && <Alert severity="warning" sx={{ py: .2 }}>Choose both dates with the start date on or before the end date.</Alert>}

        <FormControlLabel
          control={<Switch checked={includeDraft} disabled={busy} onChange={event => setIncludeDraft(event.target.checked)}/>}
          label={<Typography fontSize={12.5}>Include draft daily cost sheets</Typography>}
          sx={{ m: 0 }}
        />

        <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2, p: 1.4 }}>
          <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} mb={.6}>
            <Typography fontSize={12} fontWeight={800}>Reports included in bundle</Typography>
            <Box display="flex" gap={1} alignItems="center">
              <Typography fontSize={11} color="text.secondary">{selectedModules.length} of {BUNDLE_MODULES.length}</Typography>
              <Button
                size="small"
                disabled={busy}
                onClick={() => setSelectedModules(
                  selectedModules.length === BUNDLE_MODULES.length ? [] : BUNDLE_MODULES.map(m => m.key),
                )}
              >
                {selectedModules.length === BUNDLE_MODULES.length ? 'Clear all' : 'Select all'}
              </Button>
            </Box>
          </Box>
          <FormGroup sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: .25 }}>
            {BUNDLE_MODULES.map(mod => (
              <FormControlLabel
                key={mod.key}
                sx={{ mx: 0, alignItems: 'flex-start' }}
                control={
                  <Checkbox
                    size="small"
                    checked={selectedModules.includes(mod.key)}
                    disabled={busy}
                    onChange={() => toggleModule(mod.key)}
                    sx={{ py: .4 }}
                  />
                }
                label={
                  <Box sx={{ pt: .25 }}>
                    <Typography fontSize={12} fontWeight={700}>{mod.label}</Typography>
                    <Typography fontSize={10.8} color="text.secondary" sx={{ lineHeight: 1.35 }}>{mod.description}</Typography>
                  </Box>
                }
              />
            ))}
          </FormGroup>
        </Box>

        {busy && <Box>
          <LinearProgress/>
          <Typography fontSize={11.5} color="text.secondary" mt={.7}>{progress || 'Preparing bundle…'}</Typography>
        </Box>}
        {error && <Alert severity="error">{error}</Alert>}
      </Box>
    </DialogContent>
    <DialogActions sx={{ px: `${space[6]}px`, py: 1.75, gap: 1, borderTop: '1px solid', borderColor: 'divider' }}>
      <Button onClick={onClose} color="inherit" disabled={busy} startIcon={<CloseRounded/>}>Cancel</Button>
      <Button
        variant="contained"
        onClick={() => void run()}
        disabled={busy || !selectedWell || invalidRange || !selectedModules.length}
        startIcon={busy ? <CircularProgress size={14} color="inherit"/> : <PictureAsPdfOutlined/>}
      >
        {busy ? 'Generating bundle…' : 'Export Well PDF Bundle'}
      </Button>
    </DialogActions>
  </Dialog>
}
