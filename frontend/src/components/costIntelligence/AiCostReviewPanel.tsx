import { useCallback, useEffect, useRef, useState } from 'react'
import {
  OpenInNewRounded, PlayArrowRounded, PsychologyOutlined, WifiFindRounded,
} from '@mui/icons-material'
import {
  Box, Button, CircularProgress, Divider, FormControlLabel, MenuItem, Paper,
  Switch, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  TextField, Typography,
} from '@mui/material'
import { Tag } from '../Common'
import { SectionCard } from '../ui/SectionCard'
import { AiStatusAlert } from '../assistant/AiStatusAlert'
import { aiStatusBadge, formatAiDuration, type AiConnectionStatus, type AiErrorCode } from '../../lib/ai'
import { reportApiError } from '../../lib/api'
import {
  AI_CATEGORY_LABEL, AI_FOCUS_OPTIONS, BAND_LABEL, BAND_TONE, SEVERITY_LABEL, SEVERITY_TONE,
  costIntelligenceAiStatus, requestCostIntelligenceAiReview,
  type AiReviewFocus, type AiReviewScope, type IntelligenceAiReview, type IntelligenceWell,
} from '../../lib/costIntelligence'
import { formatWatClock } from '../../lib/time'

export function AiCostReviewPanel({
  wells,
  selectedWell,
  dateFrom,
  dateTo,
  wellStatus,
  currency,
  onNavigate,
  onReviewChange,
}: {
  wells: IntelligenceWell[]
  selectedWell?: IntelligenceWell
  dateFrom: string
  dateTo: string
  wellStatus: string
  currency: string
  onNavigate: (path: string) => void
  onReviewChange?: (review: IntelligenceAiReview | null) => void
}) {
  const [engaged, setEngaged] = useState(false)
  const [scope, setScope] = useState<AiReviewScope>('portfolio')
  const [focus, setFocus] = useState<AiReviewFocus>('full')
  const [question, setQuestion] = useState('')
  const [aiStatus, setAiStatus] = useState<AiConnectionStatus | null>(null)
  const [checking, setChecking] = useState(false)
  const [running, setRunning] = useState(false)
  const [review, setReview] = useState<IntelligenceAiReview | null>(null)
  const [commError, setCommError] = useState<{ message: string; code: AiErrorCode }>({ message: '', code: '' })
  const activeRun = useRef(0)

  // Keep scope valid when the well list changes.
  useEffect(() => {
    if (scope === 'well' && !selectedWell) setScope('portfolio')
  }, [scope, selectedWell])

  const updateReview = useCallback((next: IntelligenceAiReview | null) => {
    setReview(next)
    onReviewChange?.(next)
  }, [onReviewChange])

  const checkConnection = useCallback(async (notifyOnFailure = true): Promise<AiConnectionStatus | null> => {
    setChecking(true)
    try {
      const status = await costIntelligenceAiStatus(true)
      setAiStatus(status)
      if (status.status === 'ready') {
        setCommError({ message: '', code: '' })
      } else if (status.message) {
        setCommError({ message: status.message, code: status.error_code })
        if (notifyOnFailure) reportApiError(status.message, status.error_code === 'disabled' ? 503 : 503)
      }
      return status
    } catch (failure) {
      const msg = (failure as Error).message || 'AI communication error: unable to contact the Ollama service.'
      setCommError({ message: msg, code: 'unreachable' })
      setAiStatus(prev => ({
        enabled: prev?.enabled ?? true,
        provider: 'ollama',
        model: prev?.model ?? '',
        endpoint: prev?.endpoint ?? '',
        api_path: prev?.api_path ?? '/api/chat',
        timeout_seconds: prev?.timeout_seconds ?? 90,
        status: 'error',
        probed: true,
        reachable: false,
        model_available: null,
        installed_models: [],
        latency_ms: null,
        error_code: 'unreachable',
        message: msg,
      }))
      if (notifyOnFailure) reportApiError(msg, 503)
      return null
    } finally {
      setChecking(false)
    }
  }, [])

  const runReview = useCallback(async (overrideScope?: AiReviewScope, overrideFocus?: AiReviewFocus) => {
    const token = ++activeRun.current
    const targetScope = overrideScope ?? scope
    const targetFocus = overrideFocus ?? focus
    const targetWellId = targetScope === 'well' ? (selectedWell?.well_id ?? '') : ''
    setRunning(true)
    setCommError({ message: '', code: '' })
    try {
      const result = await requestCostIntelligenceAiReview({
        scope: targetScope,
        focus: targetFocus,
        date_from: dateFrom || null,
        date_to: dateTo || null,
        well_id: targetWellId,
        well_status: wellStatus,
        currency,
        include_draft: true,
        question: question.trim(),
      })
      if (token !== activeRun.current) return
      updateReview(result)
      setAiStatus(prev => ({
        enabled: true,
        provider: 'ollama',
        model: result.model,
        endpoint: result.endpoint || prev?.endpoint || '',
        api_path: prev?.api_path ?? '/api/chat',
        timeout_seconds: prev?.timeout_seconds ?? 90,
        status: 'ready',
        probed: true,
        reachable: true,
        model_available: true,
        installed_models: prev?.installed_models ?? [],
        latency_ms: prev?.latency_ms ?? null,
        error_code: '',
        message: `Connected · reviewed by ${result.model}`,
      }))
    } catch (failure) {
      if (token !== activeRun.current) return
      const msg = (failure as Error).message || 'AI communication error: failed to communicate with the Ollama host.'
      const lower = msg.toLowerCase()
      const inferred: AiErrorCode = lower.includes('not enabled') ? 'disabled'
        : lower.includes('refused') ? 'connection_refused'
        : lower.includes('timed out') || lower.includes('within ') ? 'timeout'
        : lower.includes('not installed') || lower.includes('not found') ? 'model_missing'
        : lower.includes('authentication') ? 'auth_error'
        : lower.includes('resolve host') ? 'dns_error'
        : 'unreachable'
      setCommError({ message: msg, code: inferred })
      setAiStatus(prev => prev ? {
        ...prev,
        enabled: inferred !== 'disabled',
        status: inferred === 'disabled' ? 'disabled' : 'error',
        probed: true,
        reachable: false,
        error_code: inferred,
        message: msg,
      } : null)
    } finally {
      if (token === activeRun.current) setRunning(false)
    }
  }, [scope, focus, selectedWell, dateFrom, dateTo, wellStatus, currency, question, updateReview])

  const handleToggle = useCallback(async (checked: boolean) => {
    activeRun.current += 1
    setEngaged(checked)
    if (!checked) {
      setRunning(false)
      setChecking(false)
      setCommError({ message: '', code: '' })
      updateReview(null)
      return
    }
    const status = await checkConnection(true)
    if (status && status.status === 'ready') {
      void runReview()
    }
  }, [checkConnection, runReview, updateReview])

  const badge = engaged
    ? aiStatusBadge(aiStatus, checking)
    : { label: 'Off · statistical analysis only', tone: 'neutral' as const }

  return (
    <SectionCard
      title="AI Cost Analytic Review"
      subtitle={engaged
        ? 'Offline LAN Ollama model engaged to inspect anomalies, suspected data-entry mistakes and budget risks across your permitted records.'
        : 'Optional. Switch on only when you want the configured offline Ollama model to review anomalies, entry mistakes and cost performance.'}
      sx={{ mb: 2 }}
      meta={
        <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
          <Tag tone={badge.tone}>{badge.label}</Tag>
          <FormControlLabel
            sx={{ m: 0, gap: 0.6 }}
            control={
              <Switch
                size="small"
                checked={engaged}
                onChange={event => void handleToggle(event.target.checked)}
                slotProps={{ input: { 'aria-label': 'Engage AI model for cost analysis' } }}
              />
            }
            label={<Typography fontSize={12.5} fontWeight={700}>{engaged ? 'AI engaged' : 'Engage AI model'}</Typography>}
          />
        </Box>
      }
    >
      {!engaged && (
        <Box display="flex" alignItems="center" gap={1}>
          <PsychologyOutlined sx={{ fontSize: 18, color: 'text.secondary', flexShrink: 0 }}/>
          <Typography fontSize={12.3} color="text.secondary">
            Deterministic Cost Intelligence runs without any model by default. Enable the toggle above to run an on-demand review using the LAN Ollama model configured in <Box component="span" fontFamily="monospace">.env</Box>.
          </Typography>
        </Box>
      )}

      {engaged && (
        <Box display="grid" gap={2}>
          <Box
            component="form"
            onSubmit={event => { event.preventDefault(); void runReview() }}
            display="flex"
            gap={1.4}
            flexWrap="wrap"
            alignItems="center"
          >
            <TextField
              select
              size="small"
              label="Review scope"
              value={scope}
              onChange={event => setScope(event.target.value as AiReviewScope)}
              sx={{ minWidth: 210 }}
              disabled={running}
            >
              <MenuItem value="portfolio">{`Portfolio (${wells.length} well${wells.length === 1 ? '' : 's'})`}</MenuItem>
              {selectedWell && (
                <MenuItem value="well">{`Selected well (${selectedWell.well_code})`}</MenuItem>
              )}
            </TextField>

            <TextField
              select
              size="small"
              label="Analytic focus"
              value={focus}
              onChange={event => setFocus(event.target.value as AiReviewFocus)}
              sx={{ minWidth: 235 }}
              disabled={running}
            >
              {AI_FOCUS_OPTIONS.map(opt => (
                <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>
              ))}
            </TextField>

            <TextField
              size="small"
              label="Optional question or audit focus"
              placeholder="e.g. Check for mistyped rates, duplicate lines, or explain top overruns"
              value={question}
              onChange={event => setQuestion(event.target.value)}
              inputProps={{ maxLength: 500 }}
              sx={{ flex: '1 1 260px', minWidth: 220 }}
              disabled={running}
            />

            <Button
              type="submit"
              variant="contained"
              startIcon={running ? <CircularProgress size={14} color="inherit"/> : <PlayArrowRounded/>}
              disabled={running || checking || !wells.length}
            >
              {running ? 'Reviewing…' : review ? 'Re-run AI review' : 'Run AI review'}
            </Button>

            <Button
              type="button"
              variant="outlined"
              startIcon={checking ? <CircularProgress size={14}/> : <WifiFindRounded/>}
              disabled={checking || running}
              onClick={() => void checkConnection(true)}
            >
              {checking ? 'Checking…' : 'Check connection'}
            </Button>
          </Box>

          {commError.message && (
            <AiStatusAlert
              message={commError.message}
              errorCode={commError.code}
              model={aiStatus?.model}
              endpoint={aiStatus?.endpoint}
              busy={running || checking}
              fallbackNote="All standard Cost Intelligence scores, forecasts, charts and findings on this page remain active and unaffected."
              onRetry={() => void runReview()}
              onCheckConnection={() => void checkConnection(true)}
            />
          )}

          {running && (
            <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, display: 'flex', alignItems: 'center', gap: 1.4 }}>
              <CircularProgress size={18}/>
              <Box>
                <Typography fontSize={12.8} fontWeight={700}>
                  Running automated cost analytic review{scope === 'well' && selectedWell ? ` on ${selectedWell.well_code}` : ` across ${wells.length} well(s)`}…
                </Typography>
                <Typography fontSize={11.5} color="text.secondary">
                  Inspecting statistical findings, daily-sheet entry checks and budget balances via {aiStatus?.model || 'Ollama'}.
                </Typography>
              </Box>
            </Paper>
          )}

          {!running && review && (
            <Box display="grid" gap={2}>
              <Divider/>
              <Box display="flex" alignItems="center" justifyContent="space-between" gap={1} flexWrap="wrap">
                <Box display="flex" alignItems="center" gap={0.8} flexWrap="wrap">
                  <Tag tone={BAND_TONE[review.risk_posture]}>{`AI posture · ${BAND_LABEL[review.risk_posture]}`}</Tag>
                  <Tag tone="info">{`Model · ${review.model}`}</Tag>
                  <Tag tone="neutral">
                    {review.scope === 'well' && review.well_code
                      ? `Well ${review.well_code}`
                      : `${review.inspected_wells} well${review.inspected_wells === 1 ? '' : 's'} reviewed`}
                  </Tag>
                  <Tag tone="neutral">{`${review.statistical_findings_count} statistical · ${review.entry_signals_count} entry check${review.entry_signals_count === 1 ? '' : 's'}`}</Tag>
                </Box>
                <Typography fontSize={11.5} color="text.secondary">
                  Generated {formatWatClock(review.generated_at, true)}{review.duration_ms ? ` in ${formatAiDuration(review.duration_ms)}` : ''} · advice only
                </Typography>
              </Box>

              <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                <Typography className="eyebrow" sx={{ mb: 0.6 }}>Executive analytic summary</Typography>
                <Typography fontSize={13} lineHeight={1.65} sx={{ whiteSpace: 'pre-line' }}>
                  {review.executive_summary}
                </Typography>
              </Paper>

              {review.findings.length > 0 && (
                <Box>
                  <Typography className="eyebrow" sx={{ mb: 0.7 }}>
                    AI-flagged anomalies, potential mistakes & cost risks ({review.findings.length})
                  </Typography>
                  <TableContainer sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Severity</TableCell>
                          <TableCell>Category</TableCell>
                          <TableCell>Well / Ref</TableCell>
                          <TableCell>Observation & evidence</TableCell>
                          <TableCell>Recommended check / action</TableCell>
                          <TableCell align="right">Verify</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {review.findings.map((item, idx) => (
                          <TableRow key={`${item.well_code}-${item.title}-${idx}`} hover>
                            <TableCell><Tag tone={SEVERITY_TONE[item.severity]}>{SEVERITY_LABEL[item.severity]}</Tag></TableCell>
                            <TableCell sx={{ whiteSpace: 'nowrap', fontSize: 12 }}>{AI_CATEGORY_LABEL[item.category] ?? item.category}</TableCell>
                            <TableCell sx={{ whiteSpace: 'nowrap' }}>
                              <Typography fontSize={12.2} fontWeight={700}>{item.well_code || 'Portfolio'}</Typography>
                              {item.reference && <Typography fontSize={11.2} color="text.secondary">{item.reference}</Typography>}
                            </TableCell>
                            <TableCell sx={{ maxWidth: 400 }}>
                              <Typography fontSize={12.4} fontWeight={700}>{item.title}</Typography>
                              <Typography fontSize={12} color="text.secondary" sx={{ mt: 0.25 }}>{item.detail}</Typography>
                            </TableCell>
                            <TableCell sx={{ maxWidth: 320 }}>
                              <Typography fontSize={12}>{item.recommendation || '—'}</Typography>
                            </TableCell>
                            <TableCell align="right">
                              {item.action_path ? (
                                <Button
                                  size="small"
                                  endIcon={<OpenInNewRounded fontSize="small"/>}
                                  onClick={() => onNavigate(item.action_path)}
                                >
                                  {item.action_label || 'Open'}
                                </Button>
                              ) : '—'}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              )}

              {review.entry_signals.length > 0 && (
                <Box>
                  <Typography className="eyebrow" sx={{ mb: 0.7 }}>
                    Unreviewed daily-sheet entry checks inspected ({review.entry_signals.length}{review.entry_signals_count > review.entry_signals.length ? ` of ${review.entry_signals_count}` : ''})
                  </Typography>
                  <TableContainer sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Level</TableCell>
                          <TableCell>Well / Sheet</TableCell>
                          <TableCell>Date</TableCell>
                          <TableCell>Potential entry mistake</TableCell>
                          <TableCell>Entered vs suggested</TableCell>
                          <TableCell align="right">Sheet</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {review.entry_signals.map((sig, idx) => (
                          <TableRow key={`${sig.entry_id}-${idx}`} hover>
                            <TableCell>
                              <Tag tone={sig.severity === 'warning' ? 'warning' : 'info'}>
                                {sig.severity === 'warning' ? 'Warning' : 'Notice'}
                              </Tag>
                            </TableCell>
                            <TableCell sx={{ whiteSpace: 'nowrap' }}>
                              <Typography fontSize={12.2} fontWeight={700}>{sig.well_code}</Typography>
                              <Typography fontSize={11.2} color="text.secondary" fontFamily="monospace">{sig.daily_cost_code}</Typography>
                            </TableCell>
                            <TableCell sx={{ whiteSpace: 'nowrap', fontSize: 12 }}>{sig.cost_date}</TableCell>
                            <TableCell sx={{ maxWidth: 380 }}>
                              <Typography fontSize={12.4} fontWeight={700}>{sig.title}</Typography>
                              <Typography fontSize={12} color="text.secondary">{sig.message}</Typography>
                            </TableCell>
                            <TableCell sx={{ fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
                              {sig.current_display || '—'}
                              {sig.suggested_display ? ` → ${sig.suggested_display}` : ''}
                            </TableCell>
                            <TableCell align="right">
                              <Button size="small" endIcon={<OpenInNewRounded fontSize="small"/>} onClick={() => onNavigate(sig.action_path)}>
                                Inspect
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              )}

              {(review.recommendations.length > 0 || review.data_quality_notes.length > 0) && (
                <Box display="grid" gap={2} sx={{ gridTemplateColumns: { xs: '1fr', md: review.recommendations.length > 0 && review.data_quality_notes.length > 0 ? '1fr 1fr' : '1fr' } }}>
                  {review.recommendations.length > 0 && (
                    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                      <Typography className="eyebrow" sx={{ mb: 0.8 }}>Recommended cost-control actions</Typography>
                      <Box component="ol" sx={{ m: 0, pl: 2.2, display: 'grid', gap: 0.6 }}>
                        {review.recommendations.map((rec, idx) => (
                          <Typography key={idx} component="li" fontSize={12.4} lineHeight={1.55}>{rec}</Typography>
                        ))}
                      </Box>
                    </Paper>
                  )}
                  {review.data_quality_notes.length > 0 && (
                    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                      <Typography className="eyebrow" sx={{ mb: 0.8 }}>Data quality & audit notes</Typography>
                      <Box component="ul" sx={{ m: 0, pl: 2.2, display: 'grid', gap: 0.6 }}>
                        {review.data_quality_notes.map((note, idx) => (
                          <Typography key={idx} component="li" fontSize={12.4} lineHeight={1.55}>{note}</Typography>
                        ))}
                      </Box>
                    </Paper>
                  )}
                </Box>
              )}
            </Box>
          )}
        </Box>
      )}
    </SectionCard>
  )
}
