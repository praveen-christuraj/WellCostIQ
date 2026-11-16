// Shared types and status helpers for the offline LAN Ollama integration.

export type AiStatusState = 'disabled' | 'configured' | 'ready' | 'error'

export type AiErrorCode =
  | ''
  | 'disabled'
  | 'misconfigured'
  | 'dns_error'
  | 'connection_refused'
  | 'timeout'
  | 'tls_error'
  | 'unreachable'
  | 'auth_error'
  | 'model_missing'
  | 'bad_endpoint'
  | 'server_error'
  | 'invalid_response'

export type AiConnectionStatus = {
  enabled: boolean
  provider: string
  model: string
  endpoint: string
  api_path: string
  timeout_seconds: number
  status: AiStatusState
  probed: boolean
  reachable: boolean
  model_available: boolean | null
  installed_models: string[]
  latency_ms: number | null
  error_code: AiErrorCode
  message: string
}

export const AI_ERROR_LABEL: Record<Exclude<AiErrorCode, ''>, string> = {
  disabled: 'Disabled in .env',
  misconfigured: 'Configuration error',
  dns_error: 'Host lookup failed',
  connection_refused: 'Connection refused',
  timeout: 'Connection timeout',
  tls_error: 'TLS error',
  unreachable: 'LAN host unreachable',
  auth_error: 'Authentication rejected',
  model_missing: 'Model not installed',
  bad_endpoint: 'Invalid API path',
  server_error: 'Remote server error',
  invalid_response: 'Invalid model reply',
}

export function aiStatusBadge(
  status: AiConnectionStatus | null | undefined,
  checking = false,
): { label: string; tone: 'success' | 'warning' | 'error' | 'info' | 'neutral' } {
  if (checking) return { label: 'Checking AI host…', tone: 'info' }
  if (!status) return { label: 'AI status unknown', tone: 'neutral' }
  if (!status.enabled || status.status === 'disabled') {
    return { label: 'AI not enabled in .env', tone: 'neutral' }
  }
  if (status.status === 'ready') {
    const latency = status.latency_ms != null ? ` · ${status.latency_ms} ms` : ''
    return { label: `Connected · ${status.model}${latency}`, tone: 'success' }
  }
  if (status.status === 'error') {
    const reason = status.error_code ? AI_ERROR_LABEL[status.error_code] : 'Communication error'
    return { label: `AI offline · ${reason}`, tone: 'error' }
  }
  return { label: `Configured · ${status.model}`, tone: 'info' }
}

export function formatAiDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return ''
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`
}
