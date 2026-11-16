import { RefreshRounded, WifiFindRounded } from '@mui/icons-material'
import { Alert, AlertTitle, Box, Button, Typography } from '@mui/material'
import { AI_ERROR_LABEL, type AiErrorCode } from '../../lib/ai'

/**
 * Explicit, accessible communication error alert whenever the offline LAN
 * Ollama host cannot be reached, times out, lacks the model, or rejects a call.
 */
export function AiStatusAlert({
  message,
  errorCode = '',
  model = '',
  endpoint = '',
  busy = false,
  fallbackNote = '',
  onRetry,
  onCheckConnection,
  onDismiss,
}: {
  message: string
  errorCode?: AiErrorCode
  model?: string
  endpoint?: string
  busy?: boolean
  fallbackNote?: string
  onRetry?: () => void
  onCheckConnection?: () => void
  onDismiss?: () => void
}) {
  if (!message) return null
  const codeLabel = errorCode ? AI_ERROR_LABEL[errorCode] : ''
  const title = errorCode === 'disabled'
    ? 'Offline AI model is not enabled'
    : `AI model communication error${codeLabel ? ` · ${codeLabel}` : ''}`
  const meta = [
    model ? `Model: ${model}` : '',
    endpoint ? `Host: ${endpoint}` : '',
  ].filter(Boolean).join(' · ')

  return (
    <Alert
      severity={errorCode === 'disabled' ? 'warning' : 'error'}
      role="alert"
      onClose={onDismiss}
      sx={{ alignItems: 'flex-start' }}
    >
      <AlertTitle sx={{ fontWeight: 800, fontSize: 12.8, mb: 0.4 }}>{title}</AlertTitle>
      <Typography fontSize={12.3} sx={{ lineHeight: 1.55 }}>{message}</Typography>
      {meta && (
        <Typography fontSize={11.3} color="text.secondary" fontFamily="monospace" sx={{ mt: 0.5 }}>
          {meta}
        </Typography>
      )}
      {fallbackNote && (
        <Typography fontSize={11.5} color="text.secondary" sx={{ mt: 0.55 }}>
          {fallbackNote}
        </Typography>
      )}
      {(onRetry || onCheckConnection) && (
        <Box display="flex" gap={1} flexWrap="wrap" mt={1}>
          {onRetry && (
            <Button size="small" variant="outlined" color="inherit" startIcon={<RefreshRounded fontSize="small"/>} disabled={busy} onClick={onRetry}>
              Retry AI request
            </Button>
          )}
          {onCheckConnection && (
            <Button size="small" variant="outlined" color="inherit" startIcon={<WifiFindRounded fontSize="small"/>} disabled={busy} onClick={onCheckConnection}>
              Check connection
            </Button>
          )}
        </Box>
      )}
    </Alert>
  )
}
