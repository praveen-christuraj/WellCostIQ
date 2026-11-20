# Reading a well from its reports — implementation notes

*Implementation of the approved review in `well-visuals-engineering-plan.md` · 20 November 2026 · API 0.22.0*

The first release described in the plan is implemented as **additive** work: the existing repositories, extraction, exports, permissions and routes are unchanged, and no database migration was needed. Everything below consumes the same `GET /api/v1/operations/well-path` payload, so a card, a chart, a drawer and an export cannot disagree about a number.

## What shipped

| Plan section | Implementation |
| --- | --- |
| **02 · One trajectory, three ways to see it** | `WellTrajectory.tsx` renders the **plan view** (north up, equal north/east scale, square plot) and the **vertical section** (the shadow on the plane facing the stated bearing) from exactly the same stations. A station selected in either projection is marked in both, in the schematic and in the table. Below the last station the line stops. |
| **03 · DLS is an interval** | `trajectory.py` exposes `dogleg_interval(...)` and `interval_table(...)`. `DoglegIntervals.tsx` draws one rectangle per measured-depth interval, the reported rate as a separate brass tick, an explicit “no usable interval” band, and the worked example (β and DLS) on the selected interval. First station prints **— no interval**, a straight pair prints `0`. |
| **04 · Construction versus moving strings** | `WellDiagram.tsx` now splits the **measured-depth construction** from the **true-vertical-depth section** into two labelled axes. Hole depth is a dashed rule, the bit/string is a distinct triangle, recorded shoes get a wedge and a label, and below the last shoe the drawing says *coverage unknown* unless the record supports open hole. A small symbol key carries the meaning by shape as well as colour. |
| **05 · Where each mark gets its data** | Every mark opens `WellSourceDialog.tsx` (*Explain this*): recorded values with report, date, status and page; calculated values with the formula and its numbers; configured values; and what the record does not contain. Facts are tagged **recorded / calculated / configured / missing**. The drawer is keyed by station or interval identity, never by a chart pixel. |
| **06 · Upload only when a survey exists** | Not in this release (see deferred). The existing *Add station* and report extraction paths are untouched. |
| **07 · How geometry becomes a chart** | One service supplies the curve, intervals, positions and provenance. The anchor basis is stated (printed first-station position, or an explicit surface tie-on); a deviated station with no azimuth is excluded instead of being pointed north; near-opposed directions and coarse spacing are named; a reported °/100 ft rate is converted with `30 / 30.48`. |
| **08 · What to reuse and where to intervene** | `trajectory.py` keeps the stable zero-dogleg minimum curvature and gains interval validity and nullable display facts. `well_path.py` separates the **survey endpoint**, the **report closing depth** (the marker) and the **report snapshot**, instead of `max(report, survey)`. The frontend keeps the existing SVG, ECharts hosts, table, compact cards and chart export. |
| **09 · Explain, scroll, inspect, export** | *Window from/to*, **Zoom in / Zoom out** and **Fit well** clip the plots only and state the window in the caption; a **Jump to a mark** list reaches the hole, the bit, every shoe and every station. Selection is shared across charts, the table and the keyboard. Existing XLSX/CSV/PDF paths are unchanged, and the PDF capture still rasterises the full drawing. |
| **10 · Guide** | `guide.py` gains the `well-path` topic (plan vs section, interval severity, construction, marker basis, *Explain this*). |
| **11 · Delivery gates** | Gate 3 arithmetic reproduces the plan's Oguali worked example at printed precision (β 0.15117°, DLS 0.1571 °/30 m against a printed 0.157). Gate 4 is met for the positions this release draws: a draft cannot move the marker past a verified report, a survey deeper than the report does not rewrite it, and a bit deeper than the same report's hole is shown as *not comparable*. The plan's separate long- and short-string markers need typed observation records and are listed under deferred. |

### Payload additions (old keys unchanged)

- `intervals[]` — both stations, ΔMD, β, calculated/recorded/difference severity, validity and the reason.
- `survey_stations[]` — the stored row (page, report, date, status), the printed TVD/N/E/DLS, the calculated TVD and their difference.
- `survey` — endpoints, sources, tools, anchor and anchor basis, interval counts.
- `position` — marker, marker TVD and its basis, survey endpoint, report depth, gap, comparability.
- `snapshot` — hole depth, printed TVD, bit/string depth, off-bottom when comparable, the report and its status, and the printed current-status text as evidence.
- `OpsWellPathStation.dls_deg_per_30m` / `build` / `turn` are **nullable** (`null` = no interval); `is_anchor`, `interval_valid`, `interval_issue` are added.
- `OpsWellPathSummary` adds `max_dls_to_md_m`, `intervals`, `invalid_intervals`, `survey_end_md_m`, `report_depth_md_m`, `survey_to_report_gap_m`, `position_basis`.

## Deliberately not changed

- Existing pages, registers, extraction, review/submit workflow, permissions, exports and the dashboard's compact `well_visual`.
- The report editor's survey rows and *Add station*. It gains a read-only **Report snapshot** strip (closing MD, printed TVD, bit/string, last casing) that does not parse the narrative into invented positions.
- No JSON columns, no new permission, no migration. API and frontend version move together to `0.22.0`.

## Deferred to later gates

1. **Survey workbook attach / preview / apply** in *Sources & surveys* (gate 2): a bounded legacy `.xls`/OOXML reader, column-role confirmation, new/identical/conflicting counts and an idempotent apply. This needs its own parser and migration review.
2. **Typed depth observations and equipment intervals** (gate 4, partial): separate long/short string and tool records with type, time, string id and evidence — which is also what the plan's DCR #13 example needs — plus liner/cement/tieback/packer layers and as-run tallies. Until then the snapshot shows the report's printed status text as evidence, draws only recorded shoes, and says that separate string positions are not fabricated.
3. **Rotatable 3D** (gate 6, optional): another view of the same stations, feature-gated with the 2D fallback retained.
4. **Guide memory and routing** through the authorised snapshot service (gate 5, partial): the deterministic topic ships; well-specific Q&A over the snapshot is not wired.

## Verification

```bash
cd frontend && npx tsc -b --noEmit && npm run build
make well-visuals-check
```

`make well-visuals-check` mounts the page in jsdom with the awkward cases the plan calls out (anchor with no interval, straight pair, printed-vs-calculated rate, survey endpoint above the hole, a bit deeper than the hole) and asserts what the screen must *say*. A service-level smoke run validated the payload against `OpsWellPathOut` and reproduced the Oguali example. Pytest and a browser pass were not run in this session.
