import { useEffect, useRef, useState } from 'react'
import { Box, Button, FormControlLabel, Stack, Switch, Typography } from '@mui/material'
import { AiStatusAlert } from '../assistant/AiStatusAlert'
import { ErrorMessage, Tag } from '../Common'
import { aiStatusBadge, type AiConnectionStatus } from '../../lib/ai'
import { opsAiStatus, type OpsStudy } from '../../lib/operations'

/** AI adds an optional paragraph, never replaces the calculated brief. */
export function StudyPanel({
  summary,
  disabled,
  runLabel,
  run,
  revision,
}: {
  summary?: string
  disabled?: boolean
  runLabel: string
  revision?: unknown
  run: (useAi: boolean) => Promise<OpsStudy>
}) {
  const [useAi, setUseAi] = useState(false)
  const [status, setStatus] = useState<AiConnectionStatus | null>(null)
  const [checking, setChecking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [study, setStudy] = useState<OpsStudy | null>(null)
  const [error, setError] = useState('')
  const [statusError, setStatusError] = useState('')
  const runId = useRef(0)
  useEffect(() => {
    runId.current++
    setStudy(null)
    setBusy(false)
    setError('')
  }, [revision])
  const check = async () => {
    setChecking(true)
    setStatus(null)
    setStatusError('')
    try {
      setStatus(await opsAiStatus())
    } catch (e) {
      setStatusError((e as Error).message)
    } finally {
      setChecking(false)
    }
  }
  const generate = async () => {
    const id = ++runId.current
    setBusy(true)
    setError('')
    setStudy(null)
    try {
      const result = await run(useAi)
      if (id === runId.current) setStudy(result)
    } catch (e) {
      if (id === runId.current) setError((e as Error).message)
    } finally {
      if (id === runId.current) setBusy(false)
    }
  }
  const badge = aiStatusBadge(status, checking)
  const connectionError = status && ['disabled', 'error'].includes(status.status) ? status.message : statusError
  const displayed = study?.summary || summary
  return (
    <Stack spacing={1.25}>
      {displayed && (
        <Typography whiteSpace="pre-line" variant="body2">
          {displayed}
        </Typography>
      )}
      {study?.warnings.length ? (
        <Box component="ul" sx={{ my: 0, pl: 2.5, color: 'text.secondary' }}>
          {study.warnings.map((w) => (
            <Typography variant="body2" component="li" key={w}>
              {w}
            </Typography>
          ))}
        </Box>
      ) : null}
      <Box display="flex" flexWrap="wrap" alignItems="center" gap={1}>
        <FormControlLabel
          label="Use offline AI"
          control={
            <Switch
              checked={useAi}
              disabled={busy}
              onChange={(e) => {
                setUseAi(e.target.checked)
                setError('')
                if (e.target.checked) void check()
              }}
            />
          }
        />
        {useAi && <Tag tone={badge.tone}>{badge.label}</Tag>}
        {(!summary || useAi) && (
          <Button size="small" variant="outlined" onClick={() => void generate()} disabled={disabled || busy}>
            {busy ? 'Working…' : summary ? 'Generate AI narrative' : runLabel}
          </Button>
        )}
      </Box>
      {useAi && (
        <Typography variant="caption" color="text.secondary">
          Sends the brief to the configured LAN model for wording only. It never edits records or changes calculations.
        </Typography>
      )}
      {useAi && !study?.ai_text && (study?.ai_error || connectionError) && (
        <AiStatusAlert
          message={study?.ai_error || connectionError || ''}
          errorCode={study?.ai_error_code || status?.error_code}
          fallbackNote={study?.ai_error_code === 'invalid_response' ? undefined : 'The rule-based brief remains available.'}
          onRetry={disabled ? undefined : generate}
          onCheckConnection={check}
          busy={busy || checking}
        />
      )}
      {useAi && study?.ai_text && (
        <Box sx={{ borderLeft: 2, borderColor: 'divider', pl: 1.5 }}>
          <Typography variant="subtitle2">AI narrative · {study.ai_model}</Typography>
          <Typography variant="caption" color="text.secondary">
            Draft wording — verify against the source.
          </Typography>
          <Typography variant="body2">{study.ai_text}</Typography>
        </Box>
      )}
      {error && <ErrorMessage message={error} />}
    </Stack>
  )
}
