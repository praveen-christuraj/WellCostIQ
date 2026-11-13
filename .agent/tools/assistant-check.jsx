// In-application guide: the answer card renders exactly what the service sent.
//
// The backend decides what may be said (backend/tests/test_assistant.py). This
// check covers the promise on screen: an answer shows its sentence, its labelled
// figures, its steps and the pages that prove it; a refusal is styled as a
// refusal and never dressed up as a figure; an unknown answer says so; follow-up
// questions are buttons that ask again; and nothing in an answer is injected as
// markup.
//
// Run:
//   cd frontend && NODE_PATH="$PWD/node_modules" ./node_modules/.bin/esbuild \
//     ../.agent/tools/assistant-check.jsx --bundle --platform=node --format=esm --jsx=automatic \
//     --outfile=node_modules/.cache/assistant-check.mjs --loader:.jsx=jsx --log-level=error \
//     --external:jsdom && node node_modules/.cache/assistant-check.mjs
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<html><body><div id="root"></div></body></html>', { pretendToBeVisual: true, url: 'http://localhost/' })
const w = dom.window
w.matchMedia = query => ({ matches: false, media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} })
for (const key of [
  'window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'Event', 'KeyboardEvent', 'MouseEvent',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'CSS', 'SVGSVGElement', 'DocumentFragment',
  'ShadowRoot', 'CustomEvent', 'DOMRect', 'HTMLInputElement',
]) {
  Object.defineProperty(globalThis, key, { value: w[key], configurable: true, writable: true })
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let passed = 0
const check = (condition, message) => { assert.ok(condition, message); passed += 1 }
const same = (actual, expected, message) => { assert.deepEqual(actual, expected, message); passed += 1 }

const { act, createElement } = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { AnswerCard, GuideIntro } = await import('../../frontend/src/components/assistant/AnswerCard')

const root = createRoot(document.getElementById('root'))
const mount = async node => {
  await act(async () => root.render(createElement(MemoryRouter, { future: { v7_startTransition: true, v7_relativeSplatPath: true } }, node)))
}
const text = () => document.body.textContent ?? ''
const followUps = []

// ---------------------------------------------------------------------------
// 1. A memory answer: sentence, labelled figures, steps and the proving pages.
// ---------------------------------------------------------------------------
await mount(createElement(AnswerCard, {
  answer: {
    answer: 'Actual days are elapsed time, not a count of daily cost sheets.',
    intent: 'knowledge', confidence: 'high', category: 'calculation', memory_key: 'calc-actual-days',
    facts: [{ label: 'Actual days', value: '1.583', hint: 'Spud 19 Oct 2026 10:00', route: '/daily-cost/analysis', permission: 'daily-cost:read' }],
    steps: ['Enter the Well Spud Date & Time.', 'Enter the Progress Completed Date & Time.'],
    sources: [{ label: 'How actual days are calculated', route: '/daily-cost' }],
    follow_ups: ['How are NPT and UPA days calculated?'],
  },
  onAsk: question => followUps.push(question),
}))
check(text().includes('elapsed time, not a count'), 'the answer sentence is shown verbatim')
check(text().includes('From recorded memory'), 'a confident answer says its source is recorded memory')
check(text().includes('calc-actual-days'), 'the memory key is visible, so an answer can be traced to the entry that produced it')
check(text().includes('1.583'), 'the computed figure is shown, not rounded away')
check(text().includes('Spud 19 Oct 2026 10:00'), 'the figure keeps its hint')
check(text().includes('Enter the Well Spud Date & Time.'), 'the steps are listed')
check(text().includes('How actual days are calculated'), 'the page that proves the answer is offered')
const links = [...document.querySelectorAll('a')].map(node => node.getAttribute('href'))
check(links.includes('/daily-cost') && links.includes('/daily-cost/analysis'), 'sources and facts link to their pages')
check([...document.querySelectorAll('title')].some(node => node.textContent === 'Requires daily-cost:read'),
  'a fact states the capability that guards it instead of hiding the requirement')

// A follow-up question is a real button, not decoration.
const chip = [...document.querySelectorAll('[role="button"], button')].find(node => node.textContent?.includes('How are NPT and UPA days calculated?'))
check(Boolean(chip), 'the follow-up question is rendered as a control')
await act(async () => { chip.dispatchEvent(new w.MouseEvent('click', { bubbles: true })) })
same(followUps, ['How are NPT and UPA days calculated?'], 'clicking a follow-up asks it again')

// ---------------------------------------------------------------------------
// 2. A refusal is a refusal: no figure, the missing capability named.
// ---------------------------------------------------------------------------
await mount(createElement(AnswerCard, {
  answer: {
    answer: 'You do not have the capability needed for that figure (daily-cost:read). Ask an administrator to grant it.',
    intent: 'permission', confidence: 'medium', category: 'faq', memory_key: '',
    facts: [], steps: [], sources: [], follow_ups: [],
  },
}))
check(text().includes('Not permitted'), 'a refusal is labelled "Not permitted"')
check(text().includes('daily-cost:read'), 'the refusal names the exact capability that is missing')
check(!text().includes('From recorded memory') && !text().includes('Best match'), 'a refusal is never presented as an answer')
check(document.querySelectorAll('a').length === 0, 'a refusal offers no page to open as if it held the figure')

// ---------------------------------------------------------------------------
// 3. An unknown question says so, loudly.
// ---------------------------------------------------------------------------
await mount(createElement(AnswerCard, {
  answer: {
    answer: 'I could not match that to the application memory I am allowed to use.',
    intent: 'knowledge', confidence: 'low', category: 'faq', memory_key: '',
    facts: [], steps: [], sources: [], follow_ups: ['What is missing in my workspace?'],
  },
}))
check(text().includes('Not sure'), 'an unmatched question is labelled "Not sure"')
check(text().includes('could not match'), 'the sentence says it does not know')

// ---------------------------------------------------------------------------
// 4. Nothing in an answer is injected as markup — memory is text, not HTML.
// ---------------------------------------------------------------------------
await mount(createElement(AnswerCard, {
  answer: {
    answer: '<img src=x onerror=alert(1)> and <script>alert(2)</script> stay text.',
    intent: 'knowledge', confidence: 'medium', category: 'policy', memory_key: 'local-rule',
    facts: [{ label: 'Rule', value: '<b>bold</b>', hint: '', route: '', permission: '' }],
    steps: ['<i>step</i>'], sources: [], follow_ups: [],
  },
}))
check(text().includes('<img src=x onerror=alert(1)>'), 'markup in an answer is shown as text')
check(document.querySelectorAll('script, img, b, i').length === 0, 'no element from answer text reaches the DOM')

// ---------------------------------------------------------------------------
// 5. The empty state offers the questions worth asking.
// ---------------------------------------------------------------------------
const asked = []
await mount(createElement(GuideIntro, {
  prompts: ['How are actual days calculated?', 'What is missing in my workspace?'],
  onAsk: question => asked.push(question),
}))
check(text().includes('recorded memory, not from guesses'), 'the empty state says where answers come from')
check(text().includes('No model is called'), 'the empty state says the guide cannot invent an answer')
const prompt = [...document.querySelectorAll('[role="button"], button')].find(node => node.textContent?.includes('What is missing in my workspace?'))
check(Boolean(prompt), 'the quick prompts are controls')
await act(async () => { prompt.dispatchEvent(new w.MouseEvent('click', { bubbles: true })) })
same(asked, ['What is missing in my workspace?'], 'clicking a quick prompt asks it')

await act(async () => root.unmount())
dom.window.close()
console.log(`Assistant checks passed (${passed}): answer sentence, figures with their capability, steps, proving pages, follow-up buttons, refusal styling, unknown answers, no markup injection, quick prompts.`)
process.exit(0)
