import { useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { AutoAwesomeOutlined, WifiFindRounded } from '@mui/icons-material'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControlLabel,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import { SectionCard } from '../ui/SectionCard'
import { AiStatusAlert } from '../assistant/AiStatusAlert'
import type { AiConnectionStatus } from '../../lib/ai'
import {
  opsAiStatus,
  runOpsAiReview,
  type OpsAiReview,
  type Scope,
} from '../../lib/operations'
import { formatWatDateTime } from '../../lib/time'

const SEVERITY_COLOR: Record<string, 'error' | 'warning' | 'info' | 'default'> = {
  high: 'error',
  medium: 'warning',
  low: 'info',
  info: 'default',
}

export function OpsAiReviewPanel({
  wellId,
  rigId,
  scope,
  dateFrom,
  dateTo,
}: {
  wellId?: string
  rigId?: string
  scope?: string
  dateFrom?: string
  dateTo?: string
}) {
  const [useAi, setUseAi] = useState(true)
  const [focus, setFocus] = useState('')
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const [review, setReview] = useState<OpsAiReview | null>(null)
  const [status, setStatus] = useState<AiConnectionStatus | null>(null)
  const [error, setError] = useState('')

  const run = async (withAi = useAi) => {
    setBusy(true)
    setError('')
    try {
      const normalizedScope: Scope | null =
        scope === 'drilling' || scope === 'completion' ? scope : null
      const result = await runOpsAiReview({
        well_id: wellId || null,
        rig_id: rigId || null,
        scope: normalizedScope,
        date_from: dateFrom || null,
        date_to: dateTo || null,
        focus: focus.trim(),
        use_ai: withAi,
      })
      setReview(result)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const checkAi = async () => {
    setChecking(true)
    setError('')
    try {
      setStatus(await opsAiStatus())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setChecking(false)
    }
  }

  return (
    <SectionCard
      title="Drilling & Completion AI Operations Review"
      subtitle="Grounded operational, NPT/UPA, ROP, schedule-lag and data-quality diagnostics powered by rule-based engineering checks and your offline LAN Ollama model."
    >
      <Stack spacing={1.75}>
        <Stack direction={{ xs: 'column', md: 'row' }} gap={1.25} alignItems={{ md: 'center' }} flexWrap="wrap">
          <TextField
            size="small"
            label="Optional engineer focus (e.g. NPT drivers, ROP, missing TVDs, tripping delays)"
            value={focus}
            onChange={(e) => setFocus(e.target.value)}
            sx={{ flex: 1, minWidth: { xs: '100%', md: 280 } }}
            disabled={busy}
          />
          <FormControlLabel
            control={<Switch size="small" checked={useAi} onChange={(_, v) => setUseAi(v)} disabled={busy} />}
            label={<Typography fontSize={12.5} fontWeight={600}>Use Offline AI (Ollama)</Typography>}
          />
          <Button
            variant="contained"
            startIcon={busy ? <CircularProgress size={14} color="inherit" /> : <AutoAwesomeOutlined fontSize="small" />}
            onClick={() => void run(useAi)}
            disabled={busy}
          >
            {busy ? 'Analysing operations…' : useAi ? 'Run AI Operations Review' : 'Run Rule-Based Review'}
          </Button>
          <Button
            variant="outlined"
            size="small"
            startIcon={checking ? <CircularProgress size={13} color="inherit" /> : <WifiFindRounded fontSize="small" />}
            onClick={() => void checkAi()}
            disabled={checking || busy}
          >
            {checking ? 'Checking…' : 'Check AI'}
          </Button>
        </Stack>

        {status && status.reachable && status.model_available && (
          <Alert severity="success" onClose={() => setStatus(null)}>
            Offline AI ready — model <strong>{status.model}</strong> connected at <code>{status.endpoint}</code>.
          </Alert>
        )}
        {status && (!status.reachable || !status.model_available) && (
          <AiStatusAlert
            message={status.message}
            errorCode={status.error_code}
            model={status.model}
            endpoint={status.endpoint}
            busy={checking}
            onCheckConnection={() => void checkAi()}
            onDismiss={() => setStatus(null)}
          />
        )}
        {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}

        {review && (
          <Stack spacing={1.5}>
            {review.ai_error && (
              <AiStatusAlert
                message={review.ai_error}
                errorCode={review.ai_error_code}
                model={review.ai_model}
                endpoint={review.ai_endpoint}
                busy={busy}
                fallbackNote="Rule-based D&C engineering findings are displayed below using verified workspace records."
                onRetry={() => void run(true)}
                onCheckConnection={() => void checkAi()}
              />
            )}

            <Box
              sx={{
                p: 2,
                borderRadius: 1.5,
                border: '1px solid',
                borderColor: 'divider',
                bgcolor: 'background.default',
              }}
            >
              <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap" mb={1}>
                <Chip
                  size="small"
                  color={review.ai_used ? 'primary' : 'default'}
                  label={review.ai_used ? `Offline AI · ${review.ai_model}` : 'Verified rule-based D&C review'}
                />
                {review.scope_label && <Chip size="small" variant="outlined" label={review.scope_label} />}
                <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                  Generated {formatWatDateTime(review.generated_at)} · Engineering review support only
                </Typography>
              </Stack>
              <Typography fontSize={13} sx={{ lineHeight: 1.65, whiteSpace: 'pre-line' }}>
                {review.executive_summary || review.deterministic_summary}
              </Typography>
            </Box>

            {review.highlights.length > 0 && (
              <Box>
                <Typography fontSize={12} fontWeight={800} color="text.secondary" textTransform="uppercase" mb={0.75}>
                  Key Performance & Wellbore Highlights
                </Typography>
                <Box component="ul" sx={{ m: 0, pl: 2.5, display: 'grid', gap: 0.45 }}>
                  {review.highlights.map((item, idx) => (
                    <Typography component="li" key={idx} fontSize={12.5} sx={{ lineHeight: 1.5 }}>
                      {item}
                    </Typography>
                  ))}
                </Box>
              </Box>
            )}

            {review.anomalies.length > 0 && (
              <Box>
                <Typography fontSize={12} fontWeight={800} color="text.secondary" textTransform="uppercase" mb={0.75}>
                  Operational Risks, NPT Drivers & Data-Quality Checks ({review.anomalies.length})
                </Typography>
                <TableContainer sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1.25 }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Severity</TableCell>
                        <TableCell>Category</TableCell>
                        <TableCell>Finding</TableCell>
                        <TableCell>Detail</TableCell>
                        <TableCell>Report</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {review.anomalies.map((a, idx) => (
                        <TableRow key={idx}>
                          <TableCell>
                            <Chip size="small" color={SEVERITY_COLOR[a.severity] ?? 'default'} label={a.severity.toUpperCase()} />
                          </TableCell>
                          <TableCell>{a.category || 'Operations'}</TableCell>
                          <TableCell sx={{ fontWeight: 700 }}>{a.title}</TableCell>
                          <TableCell>{a.detail}</TableCell>
                          <TableCell>
                            {a.report_id ? (
                              <Button component={RouterLink} to={`/operations/reports/${a.report_id}`} size="small">
                                {a.report_date || 'Open'}
                              </Button>
                            ) : (
                              a.report_date || '—'
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Box>
            )}

            {review.recommended_actions.length > 0 && (
              <Box>
                <Typography fontSize={12} fontWeight={800} color="text.secondary" textTransform="uppercase" mb={0.75}>
                  Recommended Engineering Review Actions
                </Typography>
                <Box component="ol" sx={{ m: 0, pl: 2.5, display: 'grid', gap: 0.45 }}>
                  {review.recommended_actions.map((step, idx) => (
                    <Typography component="li" key={idx} fontSize={12.5} sx={{ lineHeight: 1.5 }}>
                      {step}
                    </Typography>
                  ))}
                </Box>
              </Box>
            )}
          </Stack>
        )}
      </Stack>
    </SectionCard>
  )
}
