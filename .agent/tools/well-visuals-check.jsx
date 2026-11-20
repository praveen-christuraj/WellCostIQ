// Run with `make well-visuals-check`. Mount the well path page with a payload that
// contains every awkward case the design review calls out: a first station with no
// interval, a straight pair, a reported rate that disagrees with the calculation,
// a survey endpoint above the reported hole depth, and a bit depth that cannot be
// compared with it. The check asserts what the screen must *say*, not how it looks.
import assert from 'node:assert/strict'
import { JSDOM } from 'jsdom'

const { window } = new JSDOM('<div id="root"></div>', { url: 'http://localhost/operations/well-path?well=w1&scope=drilling', pretendToBeVisual: true })
for (const key of ['window', 'document', 'HTMLElement', 'DocumentFragment', 'Element', 'Node', 'getComputedStyle', 'SVGElement', 'Event', 'MouseEvent', 'MutationObserver', 'IntersectionObserver', 'ShadowRoot', 'requestAnimationFrame', 'cancelAnimationFrame', 'DOMRect', 'KeyboardEvent']) {
  globalThis[key] = window[key]
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = globalThis.ResizeObserver
window.matchMedia = window.matchMedia || (() => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, onchange: null, media: '', dispatchEvent: () => false }))

const { act } = await import('react')
const { MemoryRouter } = await import('react-router-dom')
const { createRoot } = await import('react-dom/client')
const { AuthProvider } = await import('../../frontend/src/context/AuthContext')
const { default: WellPathPage } = await import('../../frontend/src/pages/operations/WellPath')

const station = (md, inc, azi, dls, extra = {}) => ({
  md_m: md, inc_deg: inc, azi_deg: azi, tvd_m: md * 0.98, ns_m: md * 0.02, ew_m: md * 0.01, vsec_m: md * 0.021,
  dls_deg_per_30m: dls, build_deg_per_30m: dls === null ? null : 0.5, turn_deg_per_30m: dls === null ? null : 0.2,
  is_anchor: md === 0, interval_valid: dls !== null, interval_issue: md === 0 ? 'First station: no interval above it, so there is no dogleg severity.' : '',
  ...extra,
})
const lineage = (md, dls) => ({
  survey_id: `s-${md}`, station_no: 1, md_m: md, inc_deg: 20, azi_deg: 100, recorded_tvd_m: null,
  recorded_ns_m: null, recorded_ew_m: null, recorded_vsec_m: null, recorded_dls_deg_per_30m: dls,
  tool: 'MWD', source: 'manual', source_page: 2, confidence: 0.8, survey_at: null, report_id: 'r1',
  report_date: '2026-11-16', report_no: '13', report_status: 'submitted', computed_tvd_m: md * 0.98,
  tvd_difference_m: null, rows_at_md: 1,
})

const payload = {
  well_id: 'w1', well_code: 'OGUALI-19WD', well_name: 'Oguali 19', scope: 'drilling',
  datum: 'Rotary table as printed on the reports', vertical_section_azimuth_deg: 58.48,
  curve: [station(0, 0, 0, null), station(500, 0, 0, 0), station(873.47, 23.59, 113.98, 0.81), station(902.34, 23.62, 114.35, 0.157)],
  intervals: [
    { from_md_m: 0, to_md_m: 500, delta_md_m: 500, inc1_deg: 0, azi1_deg: 0, inc2_deg: 0, azi2_deg: 0, beta_deg: 0, dls_deg_per_30m: 0, recorded_dls_deg_per_30m: null, dls_difference_deg_per_30m: null, valid: true, issue: 'The stations are 500.0 m apart, so this is the average severity over that interval, not the curvature inside it.' },
    { from_md_m: 500, to_md_m: 873.47, delta_md_m: 373.47, inc1_deg: 0, azi1_deg: 0, inc2_deg: 23.59, azi2_deg: 113.98, beta_deg: 23.59, dls_deg_per_30m: 1.895, recorded_dls_deg_per_30m: null, dls_difference_deg_per_30m: null, valid: true, issue: '' },
    { from_md_m: 873.47, to_md_m: 902.34, delta_md_m: 28.87, inc1_deg: 23.59, azi1_deg: 113.98, inc2_deg: 23.62, azi2_deg: 114.35, beta_deg: 0.15117, dls_deg_per_30m: 0.1571, recorded_dls_deg_per_30m: 0.157, dls_difference_deg_per_30m: -0.0001, valid: true, issue: '' },
  ],
  survey_stations: [lineage(0, null), lineage(500, 0), lineage(873.47, null), lineage(902.34, 0.157)],
  survey: {
    stations: 4, first_md_m: 0, last_md_m: 902.34, first_survey_at: null, last_survey_at: null,
    sources: ['manual'], tools: ['MWD'], anchor: lineage(0, null), anchor_basis: 'printed first-station position',
    intervals: 3, invalid_intervals: 0, branch: 'drilling',
  },
  position: {
    marker_md_m: 950, marker_tvd_m: 905.1, marker_tvd_basis: 'report header', survey_end_md_m: 902.34,
    report_depth_md_m: 950, gap_m: 47.66, basis: 'latest verified report', comparable: false,
    note: 'The marker is the selected report\u2019s closing measured depth.',
  },
  snapshot: {
    hole_depth_m: 950, hole_tvd_m: 905.1, bit_depth_m: 880, off_bottom_m: 70,
    off_bottom_note: 'Both figures are from the same report; the difference is arithmetic, not a measurement.',
    report_id: 'r1', report_date: '2026-11-16', report_no: '13', status: 'submitted', verified: true,
    basis: 'latest verified report', current_status_text: 'LS TO 1770 M & SS TO 1526 M', tvd_source: 'survey',
    label: 'reported operating depth — unclassified',
  },
  summary: {
    stations: 4, md_m: 902.34, tvd_m: 881.85, departure_m: 134.75, displacement_m: 134.75,
    closure_azimuth_deg: 58.48, max_inc_deg: 23.62, max_dls_deg_per_30m: 1.895, max_dls_to_md_m: 873.47,
    intervals: 3, invalid_intervals: 0, vertical_section_m: 134.75, kickoff_md_m: 500,
    current_md_m: 950, current_tvd_m: 905.1, current_tvd_basis: 'report header', bit_depth_m: 880,
    latest_report_date: '2026-11-16', latest_report_status: 'submitted', depth_basis: 'latest verified report',
    casing_seats: 1, sections_drawn: 1, survey_end_md_m: 902.34, report_depth_md_m: 950,
    survey_to_report_gap_m: 47.66, position_basis: 'latest verified report',
  },
  sections: [{ from_depth_m: 0, to_depth_m: 500, length_m: 500, casing_size_in: 13.375, casing_label: '13-3/8"', source: 'report header', hole_size_in: 17.5, is_deepest: true }],
  open_hole: null,
  casing_seats: [{ size_in: 13.375, size_label: '13-3/8"', depth_m: 500, source: 'report header', report_date: '2026-11-16' }],
  planned: { label: '', version_no: null, points: [], planned_days: null, planned_start_at: null, items: 0 },
  depth: {
    md_m: 950, tvd_m: 905.1, bit_depth_m: 880, report_date: '2026-11-16', report_id: 'r1', status: 'submitted',
    basis: 'latest verified report', verified: true, report_no: '13', current_status: 'LS TO 1770 M & SS TO 1526 M',
    depth_start_m: 900, progress_m: 50, tvd_source: 'survey', last_casing_size_in: 13.375, last_casing_depth_m: 500,
  },
  survey_discrepancies: [],
  notes: ['The report closes at 950.00 m MD but the deepest survey station is 902.34 m.'],
  assumption: '',
  is_surveyed: true,
  generated_at: '2026-11-20T10:00:00+00:00',
}

globalThis.fetch = async (path) => {
  const url = String(path)
  if (url === '/api/v1/auth/refresh') return Response.json({ access_token: 'test' })
  if (url === '/api/v1/auth/me') return Response.json({ is_owner: false, permission_keys: ['ops-report:read', 'ops-dashboard:read', 'ops-analytics:read'] })
  if (url === '/api/v1/operations/scope-reference') return Response.json({ document_types: [], rigs: [], wells: [{ id: 'w1', display_name: 'OGUALI-19WD', rig_id: '', rig_code: '', rig_name: '', block_code: '', drilling_available: true, completion_available: false }] })
  if (url.startsWith('/api/v1/operations/well-path')) return Response.json(payload)
  throw new Error(`Unexpected request: ${url}`)
}

const root = createRoot(document.getElementById('root'))
await act(async () => root.render(<AuthProvider><MemoryRouter initialEntries={['/operations/well-path?well=w1&scope=drilling']}><WellPathPage /></MemoryRouter></AuthProvider>))

const text = () => document.body.textContent ?? ''
const has = (needle, why) => assert.ok(text().includes(needle), `${why} (missing "${needle}")`)

// The marker, the survey endpoint and the gap are three separate statements.
has('Survey endpoint', 'the survey endpoint has its own KPI card')
has('47.66', 'the gap between the last station and the hole bottom is stated')
has('unsurveyed', 'depth below the last station is annotated as unsurveyed')
// Severity is an interval fact: the anchor says so instead of printing zero.
has('— no interval', 'a station with no interval is not given a severity')
has('Max dogleg', 'the peak severity has a card')
// The divided drawing states both axes.
const diagram = document.querySelector('svg[aria-label*="casing and hole on measured depth"]')
assert.ok(diagram, 'the well diagram renders with both axis names in its accessible label')
assert.ok(diagram.textContent.includes('CASING & HOLE'), 'the construction drawing is labelled')
assert.ok(diagram.textContent.includes('VERTICAL SECTION'), 'the section drawing is labelled')
assert.ok(diagram.textContent.includes('measured depth'), 'the construction axis is measured depth')
assert.ok(diagram.textContent.includes('true vertical depth'), 'the section axis is true vertical depth')
assert.ok(diagram.textContent.includes('coverage unknown'), 'an unsupported open hole is not fabricated')
// The interval chart spans intervals, not stations, and names the recorded mark.
const dogleg = document.querySelector('svg[aria-label="Dogleg severity by survey interval"]')
assert.ok(dogleg, 'the dogleg chart renders')
assert.ok(dogleg.textContent.includes('no usable interval'), 'the legend names a missing interval')
assert.ok(dogleg.textContent.includes('recorded'), 'the reported rate is a separate legend entry')
// The three questions are kept apart on the page.
has('Report snapshot', 'the report snapshot has its own card')
has('A short string above the hole bottom is normal', 'the snapshot explains equipment vs hole')

// "Explain this" names the source and the rule, not just a number.
const click = async (label) => {
  const button = [...document.querySelectorAll('button')].find((node) => (node.textContent ?? '').trim() === label)
  assert.ok(button, `button "${label}" is present`)
  await act(async () => button.dispatchEvent(new window.MouseEvent('click', { bubbles: true })))
}
await click('Explain hole depth')
has('never replaced by the newest survey', 'the hole-depth drawer states the report rule')
await click('Close')
await click('Explain last shoe')
has('Only what the record describes is drawn', 'the shoe drawer states what is not fabricated')
await click('Close')

await act(async () => root.unmount())
window.close()
console.log('Well visuals: marker/survey separation, interval severity, split axes, snapshot and source drawer passed.')
process.exit(0)
