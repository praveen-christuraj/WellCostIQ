// Offline LAN Ollama AI check: Guide AI answers, Cost Intelligence opt-in toggle
// panel, communication error alerts (inline + global pop-up), and light/dark
// theme token discipline.
//
// Run:
//   cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/ollama-ai-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
//     --outfile=node_modules/.cache/ollama-ai-check.mjs --loader:.jsx=jsx --log-level=error \
//     --external:jsdom && node node_modules/.cache/ollama-ai-check.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  pretendToBeVisual: true,
  url: 'http://localhost/',
})
const w = dom.window
w.matchMedia = query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MouseEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment',
  'ShadowRoot', 'CustomEvent', 'DOMRect', 'HTMLInputElement', 'HTMLTextAreaElement', 'localStorage', 'sessionStorage',
]) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let passed = 0
const check = (condition, message) => { assert.ok(condition, message); passed += 1 }
const tick = () => new Promise(resolve => setTimeout(resolve, 20))

const apiCalls = []
let mockAiStatus = {
  enabled: true,
  status: 'ready',
  model: 'qwen3:4b-q4_K_M',
  endpoint: 'http://192.168.1.50:11434',
  api_path: '/api/chat',
  reachable: true,
  model_available: true,
  latency_ms: 42,
  error_code: '',
  message: 'Connected to offline Ollama model qwen3:4b-q4_K_M at http://192.168.1.50:11434.',
  installed_models: ['qwen3:4b-q4_K_M'],
}
let failReview = false

globalThis.fetch = async (input, init = {}) => {
  const url = String(input)
  const method = (init.method ?? 'GET').toUpperCase()
  apiCalls.push({ method, url, body: init.body ? JSON.parse(String(init.body)) : null })

  if (url.includes('/cost-intelligence/ai-status') || url.includes('/assistant/ai-status')) {
    return new Response(JSON.stringify(mockAiStatus), { status: 200, headers: { 'content-type': 'application/json' } })
  }
  if (url.includes('/cost-intelligence/ai-review')) {
    if (failReview) {
      return new Response(
        JSON.stringify({
          detail: 'AI communication error: connection refused by http://192.168.1.50:11434. Verify Ollama is running with OLLAMA_HOST=0.0.0.0:11434 and check OLLAMA_BASE_URL in .env.',
        }),
        { status: 503, headers: { 'content-type': 'application/json' } },
      )
    }
    const reqBody = init.body ? JSON.parse(String(init.body)) : {}
    return new Response(
      JSON.stringify({
        generated_at: '2026-11-16T08:00:00Z',
        model: 'qwen3:4b-q4_K_M',
        endpoint: 'http://192.168.1.50:11434',
        duration_ms: 1420,
        scope: reqBody.scope ?? 'portfolio',
        focus: reqBody.focus ?? 'full',
        currency: 'USD',
        well_id: reqBody.well_id ?? '',
        well_code: reqBody.scope === 'well' ? 'WELL-X' : '',
        well_name: reqBody.scope === 'well' ? 'Well X' : '',
        risk_posture: 'at-risk',
        executive_summary: 'WELL-X exhibits a 10x single-day Mud logging rate spike on 2026-10-09 (USD 25,000 vs USD 2,500 baseline).',
        findings: [
          {
            severity: 'critical',
            category: 'entry-mistake',
            well_id: 'w-x',
            well_code: 'WELL-X',
            reference: '2026-10-09',
            title: 'Suspected 10x digit slip on Mud logging day rate',
            detail: 'Day rate jumped from USD 2,500 to USD 25,000 on one sheet.',
            recommendation: 'Inspect sheet DC-009 and confirm the vendor ticket before submitting.',
            action_path: '/daily-cost/analysis/w-x',
          },
        ],
        entry_signals_count: 1,
        entry_signals: [
          {
            well_id: 'w-x',
            well_code: 'WELL-X',
            entry_id: 'e-9',
            daily_cost_code: 'DC-009',
            cost_date: '2026-10-09',
            severity: 'warning',
            title: 'Rate is 10x AFE baseline',
            message: 'Override rate USD 25,000 exceeds locked AFE rate USD 2,500 by 10x.',
            current_display: 'USD 25,000.00',
            suggested_display: 'USD 2,500.00',
            action_path: '/daily-cost/entries/e-9',
          },
        ],
        recommendations: [
          'Correct or justify the USD 25,000 override on DC-009.',
          'Raise a SOW adjustment if the call-out charge is confirmed.',
        ],
        data_quality_notes: ['2 draft daily cost sheets are awaiting submission on WELL-X.'],
        basis_note: 'Generated by offline LAN Ollama model qwen3:4b-q4_K_M over verified tenant records.',
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    )
  }
  throw new Error(`Unexpected fetch in ollama-ai-check: ${method} ${url}`)
}

const { act, createElement } = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { CssBaseline, ThemeProvider } = await import('@mui/material')
const { buildTheme } = await import('../../frontend/src/theme')
const { AnswerCard } = await import('../../frontend/src/components/assistant/AnswerCard')
const { AiStatusAlert } = await import('../../frontend/src/components/assistant/AiStatusAlert')
const { AiCostReviewPanel } = await import('../../frontend/src/components/costIntelligence/AiCostReviewPanel')

const globalErrors = []
const handleApiError = ev => globalErrors.push(ev.detail)
window.addEventListener('api-error', handleApiError)

const root = createRoot(document.getElementById('root'))
const mount = async (node, mode = 'light') => {
  await act(async () => {
    root.render(
      createElement(
        ThemeProvider,
        { theme: buildTheme(mode) },
        createElement(CssBaseline),
        createElement(
          MemoryRouter,
          { future: { v7_startTransition: true, v7_relativeSplatPath: true } },
          node,
        ),
      ),
    )
  })
  await act(async () => { await tick() })
}
const text = () => document.body.textContent ?? ''
const click = async el => {
  await act(async () => {
    el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }))
  })
  await act(async () => { await tick() })
}

// ---------------------------------------------------------------------------
// 1. AiStatusAlert renders distinct, actionable alerts for LAN failure codes.
// ---------------------------------------------------------------------------
let retryClicks = 0
for (const [code, expectedTitle, msg] of [
  ['connection_refused', 'AI model communication error · Connection refused', 'Connection refused by http://192.168.1.50:11434'],
  ['timeout', 'AI model communication error · Connection timeout', 'Timed out waiting for qwen3:4b-q4_K_M'],
  ['model_missing', 'AI model communication error · Model not installed', 'Run ollama pull qwen3:4b-q4_K_M'],
  ['auth_error', 'AI model communication error · Authentication rejected', 'Check OLLAMA_API_KEY in .env'],
  ['disabled', 'Offline AI model is not enabled', 'Set OLLAMA_ENABLED=true in .env'],
]) {
  await mount(
    createElement(AiStatusAlert, {
      message: msg,
      errorCode: code,
      endpoint: 'http://192.168.1.50:11434',
      model: 'qwen3:4b-q4_K_M',
      onRetry: () => { retryClicks += 1 },
    }),
  )
  check(document.querySelector('[role="alert"]') !== null, `error code ${code} renders an accessible role="alert"`)
  check(text().includes(expectedTitle) && text().includes(msg), `error code ${code} surfaces title and guidance`)
}
const retryBtn = [...document.querySelectorAll('button')].find(b => b.textContent?.includes('Retry AI request'))
check(Boolean(retryBtn), 'AiStatusAlert exposes a Retry AI request button')
await click(retryBtn)
check(retryClicks === 1, 'Retry connection invokes the handler')

// ---------------------------------------------------------------------------
// 2. AnswerCard displays Well X vs Well Y AI comparison AND communication error fallback.
// ---------------------------------------------------------------------------
await mount(
  createElement(AnswerCard, {
    answer: {
      answer: 'WELL-X total cost incl. LIH is USD 15,000.00 compared with WELL-Y at USD 8,500.00.\n- WELL-X is USD 6,500.00 (+76.5%) higher than WELL-Y.',
      intent: 'well_comparison',
      confidence: 'high',
      category: 'calculation',
      memory_key: '',
      facts: [
        { label: 'WELL-X total cost', value: 'USD 15,000.00', hint: 'Incl. USD 3,000.00 LIH', route: '/daily-cost/analysis/wx', permission: 'daily-cost:read' },
        { label: 'WELL-Y total cost', value: 'USD 8,500.00', hint: 'Well Y', route: '/daily-cost/analysis/wy', permission: 'daily-cost:read' },
        { label: 'Difference (X - Y)', value: '+USD 6,500.00', hint: '+76.5%', route: '/reports/well-cost-comparison', permission: 'daily-cost:read' },
      ],
      tables: [{
        title: 'Head-to-head cost comparison: WELL-X vs WELL-Y',
        columns: ['Metric', 'WELL-X', 'WELL-Y', 'Difference'],
        rows: [['Total cost (incl. LIH)', 'USD 15,000.00', 'USD 8,500.00', '+USD 6,500.00']],
        numeric: [1, 2, 3],
        footer: 'Includes draft daily cost sheets.',
      }],
      steps: [],
      sources: [{ label: 'Well cost comparison', route: '/reports/well-cost-comparison' }],
      follow_ups: ['Break down WELL-X by cost group'],
      ai_used: true,
      ai_model: 'qwen3:4b-q4_K_M',
      ai_duration_ms: 950,
      ai_error: '',
      ai_error_code: '',
    },
    onAsk: () => {},
  }),
)
check(text().includes('AI · qwen3:4b-q4_K_M'), 'AI answer badges the offline Ollama model')
check(text().includes('Live data'), 'well_comparison intent badges Live data')
check(text().includes('Head-to-head cost comparison: WELL-X vs WELL-Y'), 'comparison table renders cleanly')
check(text().includes('+USD 6,500.00'), 'exact comparison difference renders verbatim')

// Communication error fallback preserves verified comparison while displaying role="alert".
await mount(
  createElement(AnswerCard, {
    answer: {
      answer: 'WELL-X total cost is USD 15,000.00 vs WELL-Y USD 8,500.00 (difference +USD 6,500.00).',
      intent: 'well_comparison',
      confidence: 'high',
      category: 'calculation',
      memory_key: '',
      facts: [],
      tables: [],
      steps: [],
      sources: [],
      follow_ups: [],
      ai_used: false,
      ai_model: 'qwen3:4b-q4_K_M',
      ai_duration_ms: null,
      ai_error: 'AI communication error: LAN Ollama host http://192.168.1.50:11434 refused connection.',
      ai_error_code: 'connection_refused',
    },
    onAsk: () => {},
  }),
)
check(document.querySelector('[role="alert"]') !== null, 'Guide fallback renders inline alert on LAN outage')
check(text().includes('AI model communication error · Connection refused') && text().includes('USD 15,000.00'),
  'Guide shows both the communication error alert and the verified fallback comparison')

// ---------------------------------------------------------------------------
// 3. AiCostReviewPanel: opt-in toggle OFF by default, live review ON, comm alerts.
// ---------------------------------------------------------------------------
let latestReview = null
const navigated = []
const selectedWell = {
  well_id: 'w-x',
  well_code: 'WELL-X',
  well_name: 'Well X',
}
for (const themeMode of ['light', 'dark']) {
  apiCalls.length = 0
  latestReview = null
  failReview = false
  navigated.length = 0
  await mount(
    createElement(AiCostReviewPanel, {
      key: themeMode,
      wells: [selectedWell],
      selectedWell,
      dateFrom: '',
      dateTo: '',
      wellStatus: '',
      currency: 'USD',
      onNavigate: path => navigated.push(path),
      onReviewChange: rev => { latestReview = rev },
    }),
    themeMode,
  )
  check(apiCalls.length === 0, `${themeMode}: AI toggle defaults to OFF and makes ZERO network calls on mount`)
  check(text().includes('Off · statistical analysis only') && text().includes('Engage AI model'),
    `${themeMode}: OFF state confirms deterministic-only Cost Intelligence`)

  // Engage the user toggle switch!
  const toggleInput = document.querySelector('input[aria-label="Engage AI model for cost analysis"]')
  check(Boolean(toggleInput), `${themeMode}: accessible Engage AI model toggle switch is present`)
  await click(toggleInput)
  await act(async () => { await tick() })

  check(apiCalls.some(c => c.url.includes('/cost-intelligence/ai-status?probe=true')),
    `${themeMode}: turning on the AI toggle probes LAN Ollama readiness`)
  check(apiCalls.some(c => c.url.includes('/cost-intelligence/ai-review')),
    `${themeMode}: turning on a healthy AI host executes the automated cost review`)
  check(text().includes('AI engaged') && text().includes('Connected · qwen3:4b-q4_K_M'),
    `${themeMode}: connected model status badge is visible`)
  check(latestReview !== null && latestReview.risk_posture === 'at-risk',
    `${themeMode}: AI review callback delivers structured review for PDF/Excel export`)
  check(text().includes('Suspected 10x digit slip on Mud logging day rate'),
    `${themeMode}: anomaly/mistake finding renders`)
  check(text().includes('DC-009') && text().includes('USD 25,000.00') && text().includes('USD 2,500.00'),
    `${themeMode}: daily-sheet entry-check signal renders current and suggested figures`)
  check(text().includes('Correct or justify the USD 25,000 override'),
    `${themeMode}: prioritized recommendations render`)
  check(text().includes('2 draft daily cost sheets are awaiting submission'),
    `${themeMode}: data quality notes render`)
}

// Simulate LAN communication drop during Re-run AI review: verify BOTH inline alert and global pop-up alert.
globalErrors.length = 0
failReview = true
const runAgainBtn = [...document.querySelectorAll('button')].find(b => b.textContent?.includes('Re-run AI review') || b.textContent?.includes('Run AI review'))
check(Boolean(runAgainBtn), 'Re-run AI review button is available while engaged')
await click(runAgainBtn)
check(document.querySelector('[role="alert"]') !== null && text().includes('AI communication error'),
  'Cost Intelligence AI panel renders inline communication error alert on 503')
check(globalErrors.length >= 1 && globalErrors[0].message.includes('192.168.1.50:11434'),
  'Cost Intelligence AI failure triggers the global persistent pop-up error channel')

// Simulate model missing on Test connection: verify proactive error alert + pop-up alert.
globalErrors.length = 0
mockAiStatus = {
  ...mockAiStatus,
  status: 'error',
  model_available: false,
  error_code: 'model_missing',
  message: "Model 'qwen3:4b-q4_K_M' is not installed on http://192.168.1.50:11434. Run `ollama pull qwen3:4b-q4_K_M`.",
}
const checkConnBtn = [...document.querySelectorAll('button')].find(b => b.textContent?.includes('connection') || b.textContent?.includes('Connection'))
check(Boolean(checkConnBtn), 'Check connection button is rendered')
await click(checkConnBtn)
check(text().includes('ollama pull qwen3:4b-q4_K_M') && globalErrors.length >= 1,
  'Connection check alerts inline and via global pop-up when qwen3:4b-q4_K_M is missing on the LAN PC')

// Disengaging the toggle returns cleanly to statistical-only mode and clears export review state.
const toggleOff = document.querySelector('input[aria-label="Engage AI model for cost analysis"]')
await click(toggleOff)
check(text().includes('Off · statistical analysis only') && latestReview === null,
  'Disengaging AI toggle returns to deterministic mode cleanly')

// ---------------------------------------------------------------------------
// 4. Static guardrails: opt-in default OFF + zero hard-coded hex colours.
// ---------------------------------------------------------------------------
const ciSource = readFileSync('src/pages/CostIntelligence.tsx', 'utf8')
const aiPanelSource = readFileSync('src/components/costIntelligence/AiCostReviewPanel.tsx', 'utf8')
const aiAlertSource = readFileSync('src/components/assistant/AiStatusAlert.tsx', 'utf8')

check(aiPanelSource.includes('const [engaged, setEngaged] = useState(false)'),
  'AiCostReviewPanel toggle defaults to OFF so deterministic analytics never call Ollama unasked')
check(!/#[0-9a-fA-F]{3,8}\b/.test(ciSource), 'CostIntelligence.tsx uses theme tokens only (no raw hex)')
check(!/#[0-9a-fA-F]{3,8}\b/.test(aiPanelSource), 'AiCostReviewPanel.tsx uses theme tokens only (no raw hex)')
check(!/#[0-9a-fA-F]{3,8}\b/.test(aiAlertSource), 'AiStatusAlert.tsx uses theme tokens only (no raw hex)')

window.removeEventListener('api-error', handleApiError)
await act(async () => root.unmount())
dom.window.close()
console.log(`ollama-ai-check: ${passed} assertions passed`)
process.exit(0)
