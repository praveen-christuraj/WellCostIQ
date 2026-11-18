# Well Operations — study of the model reports and the current manual workflow

**Status:** study complete, no code changed.
**Date:** 2026-11-17
**Sources studied**

| Source | What it is |
| --- | --- |
| `MODEL REPORTS/operation reports/*.pdf` (21 files) | OpenWells daily reports: 17 DDR, 3 DCR, 1 RMR, all dated 14–16 Nov 2026 |
| `MODEL REPORTS/operation reports/*.xlsx` (6 files) | 4 drilling/completion **Operations Summary** workbooks built by the operations engineers, 2 **DMR** (mud) workbooks |
| `MODEL REPORTS/WellCosting_Pro_BRD_v1.0.md` | the costing BRD, for the NPT/UPA and MIS constraints (OD-02, section 6.4) |
| Existing plans | `docs/operations-module-plan.md`, `docs/operations-implementation-plan.md`, `docs/operations-costing-decoupling.md` |
| Reference repositories | DrillDash, drilling-report-database, DrillMind, drilling-reports-ds-pipeline (verdicts in §8) |
| Application code | `models/rig_well.py`, `services/daily_cost.py`, `services/operational_time.py`, `services/provisioning.py`, `frontend/src/App.tsx`, `components/Layout.tsx`, invoice attachment storage |

Extracted data artefacts from this study:

- `docs/operations/activity-taxonomy-extracted.csv` — every code list found in the engineers' `Codes` sheet (256 activities, 37 activity codes, 75 plan/NPT codes, 30 agency codes, 17 cause codes, 20 operation codes, 10 phase codes, 25 rigs, 35 fields, 9 blocks), ready to become starter import templates.

---

## 1. What the reports actually are

### 1.1 The PDFs are one report family drawn from OpenWells

All 21 PDFs are page-for-page identical in structure. Section numbers shift by one depending on whether
the report carries a Customer Information block (DDR) or not (some RMR/boilerplate variants), but the
content is the same document:

| Section | Content | Usable for |
| --- | --- | --- |
| 1.1 Customer Information | Company, representative, address | operator/contractor identity |
| 1.2 Well/Wellbore Information | Well, wellbore, **report no.**, **report date**, project, site, rig, **event** (`ORIG DRILLING` / `ORIG COMPLETION`), start date, spud date, UWI, AFE no., datum, block, supervisor, engineer | report identity, scope, rig/well matching |
| 1.3 Depth Days | MD, TVD, progress, average ROP, rotating hours, cumulative rotating hours, **DFS**, est. days, MD auth, last casing | depth/time KPIs, plan comparison |
| 1.4 Status | Current status, **24 hr summary**, 24 hr forecast | the engineer's narrative; the existing Excel `Details of Activities` is a re-typed copy of this |
| 2.1 Operation Summary | **The time log**: From, To, Dur (hr), Phase, Code, Sub/Class, MD from, MD to, Operation (multi-line narrative per block) | the core of the whole module |
| 3.1 Hole Sections | Section name, type, effective hole diameter, MD top/base, section start/end date-time | section plan vs actual |
| 4.1 Fluids / Mud | mud description, density, viscosity, date/time, MD check, PV, YP, Cl⁻, Ca²⁺, pH, Pm, Pf, Mf | daily mud summary |
| 5 Drillstrings | BHA number, in/out date-time, bit no., weights, BHA length, components, bit operations (WOB, RPM, flow, SPP, bit hydraulics, hours, footage, ROP today/cumulative) | bit & ROP records |
| 6 Pump Operations | pumps, liner, efficiency, pressure, SPM, output | hydraulics |
| 7 Safety | DSLTI/DSLTA, STOP cards, safety moment, inspections/drills, BOP tests, pressure tests, incidents | HSE |
| 8 Personnel | total POB and per-company headcount | POB register |
| 9 Materials | product, unit, usage, closing quantity | material consumption |
| 10 Remarks | free remarks | narrative |

### 1.2 Scope is carried by the `Event` field, not the file name

`Event` values in the sample: `ORIG DRILLING` (17), `ORIG COMPLETION` (3). File naming is *not*
authoritative — one file is called `Daily Drilling Report 71 ABAM-AMA-1ST`, others `DDR 03 …`,
`DCR-13 …`, `RMR 36 …`, and the "RMR" sample is an ordinary drilling-day report (`Event = ORIG DRILLING`,
report date two days earlier). **Rule for the engine: scope comes from `Event` (with the file-name prefix
as a weaker secondary signal), and RMR is a report *purpose* (rig-move day) on the drilling scope, not a
separate scope.**

### 1.3 The 24-hour window is midnight-to-midnight

Every report's operation summary starts at `0:00` and closes at `23:59`/`0:00`. Several reports continue
into the next calendar date inside the last block (`23:59 → 6:00 … **17/11/2026**`). Durations sum to
23.98 h, not 24.00 h, merely because `23:59` is used as end-of-day.

Consequences for the design:

- default report period = **00:00 → 24:00 local**, configurable per workspace (the earlier plan's
  06:00-to-06:00 default is not what these reports do);
- a 1-minute tolerance (23.98 vs 24.00) must be treated as *complete*, not as missing time;
- the last block may legitimately spill past midnight, so block timestamps must carry full dates and the
  completeness rule must allow a documented spill of up to one block.

### 1.4 Report inventory (16 Nov 2026 campaign)

| Well | Rig | Scope | Report no. | DFS | MD | Est. days |
| --- | --- | --- | --- | --- | --- | --- |
| OGINI-34 | (blank) | Drilling | 28 | 28.00 | 6,323 ft | — |
| UTA 64 | Durga 4 | Drilling | 24 | 23.46 | 5,248 ft | — |
| AKATA 12 | DURGA/20 | Drilling | 43 | 42.00 | 9,856 ft | — |
| AKATA 11ST | DURGA #6 | Drilling | 22 | 21.29 | 10,500 ft | 47.50 |
| SAKA-CREEK-3 | Durga 15 | Drilling | 81 | 76.00 | 3,930 m | — |
| SAKA CREEK 4 | DURGA #7 | Drilling | 22 | 22.00 | 1,600 m | — |
| OKW-93 | DURGA/RIG19 | Drilling | 19 | 19.00 | 1,940 m | — |
| ACHARA-8 | DURGA/10 | Drilling | 3 | 3.00 | 575 m | — |
| ACHARA-EAST-4 | DURGA/9 | Drilling | 61 | 54.00 | 4,127 m | — |
| AGU-DEEP-1ST | DURGA/8 | Drilling | 31 | 94.00 | 3,060 m | — |
| IKAKI-S-14 | DURGA #2 | Drilling | 70 | 64.38 | 3,885 m | 67.50 |
| ETE SOUTH-09 | DURGA 1 | Drilling | 69 | 64.51 | 13,000 ft | — |
| OGUALI-19 WD | (blank) | Drilling | `DDR1` | 5.00 | 236 m | — |
| ENYIE SW-7ST | DURGA-5 | Drilling | 4 | 60.50 | 2,589 m | — |
| AKUOYIBO-4 | DURGA-12 | Drilling | 15 | 14.58 | 1,968 m | 70.00 |
| OGINI 33PH | DURGA/#14 | Drilling | 41 | 40.75 | 3,100 ft | — |
| ABAM-AMA-1ST | Durga #18 | Drilling | 71 | 71.00 | 5,280 m | — |
| IKAKI-S-8 | DURGA/11 | Completion | 3 | 3.00 | — | 20.00 |
| ACHARA-SOUTH-4PH | DURGA/17 | Completion | 13 | 13.00 | 3,240 m | 21.00 |
| AKOBU SOUTH-11 | DURGA #13 | Completion | 24 | 85.62 | 3,290 m | — |
| ACHARA-8 (RMR) | (blank) | Drilling (rig move) | blank | — | — | — |

**17 drilling wells, 3 completion wells, 1 rig-move report, 18 distinct rigs.** Depths are mixed `m`/`ft`
across (and within) the portfolio; two reports carry no rig; one carries report number `DDR1`; one carries
none; two use `mm/dd/yyyy` while the rest use `dd/mm/yyyy` and `dd-mm-yyyy`.

### 1.5 Operation Summary — measured extraction fidelity

A layout-aware extraction of the 21 PDFs (words → y-grouped lines → column assignment from the header
x-positions) recovered **166 time blocks and 487.6 logged hours**:

| Measure | Result |
| --- | --- |
| Blocks per report | 2 – 14 (median 8) |
| Hours recovered per report | 23.65 – 24.00 (RMR 8.50, it is a part-day report) |
| Reports reconciling to 24 h within 0.05 | 18 of 21 (the other three are the RMR part-day and two 23.65–23.73 reports) |
| Classification (`Sub/Class`) | `P` 129 (77.7 %), `U` 24 (14.5 %), `D` 4 (2.4 %), blank 9 (5.4 %) |
| Observed `Phase` codes | `DRLPRO` 65, `DRLSUR` 22, `CSGIN2` 14, `EVAL` 12, `DRLIN1` 11, `CSGPRO` 10, `CSGSUR` 8, `DRLIN2` 6, `CSGDRV` 3, `DRLIN3` 2, `EVALPR` 2, `CSGCON` 2 |
| Observed `Code` values | `06` 46, `25` 39, `05` 22, `02` 14, `12` 9, `11` 6, `15` 5, `19` 4, `01`, `03`, `07`, `08`, `10`, `21`, `24` |

Reading it against the engineers' `Codes` sheet:

- `Phase` is the **OpenWells drilling-phase abbreviation** (`DRLPRO` = drilling production hole,
  `DRLSUR` = drilling surface hole, `CSGIN2` = intermediate casing, `EVAL` = evaluation/logging). Twelve
  distinct values; the operations workbooks instead key on **hole size** (`16"`, `12 ¼"`, `8 ½"`) and on a
  **phase code** (`DRILL`, `COMP`, `MOB`, `PREP`, `ABAN`, `W.O.`, `W.T.`, `SEC-WELL`, `RE-EN`, `PROD-MAN`).
  Three different "phase" vocabularies exist, so the module must own a mapping table, not a single field.
- OpenWells prints a numeric `Code`, but the supplied PDFs do not define those numbers. The engineers’ `Codes` sheet defines its own activity numbers (`02` = RIG MOVES, `06` = WIPER TRIP AND REAMING, `07` = CIRCULATION). Do not assume they are equivalent: the PDFs use `02` on drill-ahead rows, `06` on several kinds of trips and `07` on top-drive service. The app displays workbook definitions and PDF observations as separate references; neither implies a universal OpenWells codebook.
- `Sub/Class` behaves like the Excel `Plan` column (`P` planned, `U` unplanned) but also emits a third
  value `D` — present only on blocks whose narrative describes downtime (a dropped stabiliser sub, diesel
  engines tripping off). **`D` is almost certainly the crews' "down/NPT" mark.** 5.4 % of blocks carry no
  mark at all, so classification cannot be read from the PDF alone.

**The PDFs contain no NPT/UPA hours, no agency, no cause and no cost.** Those columns exist only in the
engineers' Excel summary. That single fact justifies the whole extraction-plus-review design: the engine
must *infer* classification and accountability from taxonomy + narrative + timeline, and the engineer must
confirm it.

### 1.6 Text geometry is the hard part, not the vocabulary

`pdfplumber.extract_text()` on a block that wraps over several lines interleaves columns
(`"2,323.0CONTINUE TO DRILL 8-1/2’’"`, `"15.00 DRLIN2"`, narrative fragments arriving before their
numbers). A robust parser must:

1. group words into lines by `top` (±2.5 pt),
2. bind columns from the header row's x-positions (`From To Dur. (hr) Phase Code Sub Class MD from MD to Operation`),
3. treat a line without a leading `H:MM` as continuation text of the previous block,
4. re-join the narrative in reading order, and
5. keep a page + bounding box for every block so the review screen can highlight the source.

### 1.7 Things the engineers already do — the real specification

The four Operations Summary workbooks are the module's functional specification. Each contains:

| Sheet | Role |
| --- | --- |
| `Summary` (protected) | one row per activity block: Block, Field, Rig, Well, Start, End, **Phase (hole size)**, **Operation** (Drilling/Casing/Cementing/Logging/Wellhead), **Activity** (from the 256-list), **Sub-Activity**, **Plan (P/U/NPT)**, Details, Mud Weight, Depth End, Bit Depth, Dur, Cum Dur (days), Planned Time, **Agency**, **Cause**, **NPT (hrs)**, **PT (hrs)**, Remarks, **ROP**, Planned hrs to drill |
| `PT-NPT DATASHEET` (protected) | the same columns as an empty MS-Query target (the pivot's source) |
| `PT-NPT Dashboard` | pivot: Agency × Operation × Phase × Cause → Sum NPT hrs, Sum PT hrs |
| `Input-lookahead` | plan item, predicted hrs, actual hrs, plan days, actual days, **Lag/lead**, cumulative start times |
| `<WELL>` (Timeline) | the forward plan: S.No, activity description, **depth m MD BRT**, **planned hours**, **cumulative planned days**, trip-speed assumptions, and a section-level timeline summary (planned hours and days per hole section) |
| `Data for Graph` | actual curve: well, depth, block hours, cumulative days (a live query on `Summary`) |
| `TIME VS DEPTH GRAPH` | chart: series **Plan** = Timeline (cum days vs depth) and **ACTUAL** = Data for Graph (cum days vs depth) |
| `Codes` | the whole picklist library (see §3) |
| Completion extra sheets | `DATA FOR GRAPH-COMPLETION` (per-major-activity planned vs actual hours and cumulative days), `Timeline (2)`, `STRING DIAGRAM` (completion string and perforation intervals) |

Charts observed in the workbook XML: one time-vs-depth chart with `Plan` and `ACTUAL` series, one
`Actual` vs `Plan` chart keyed on the Summary cumulative days, and the NPT/PT pivot chart.

### 1.8 How the plan (timeline) is actually produced — formulas matter

The Timeline is not typed hour by hour; it is **generated from rate assumptions**:

```
planned hours for a drilling item  = ROUNDUP((depth − previous depth) / ROP, 0) + 2      (contingency)
planned hours for a trip           = ROUNDUP(depth / 28.5 / 10, 0) + 2                   (28.5 m per stand, 10 stands/hr)
cumulative planned days            = previous cumulative + planned hours / 24
```

`Input-lookahead` then chains actual time:

```
start time(n) = start time(n−1) + (actual hours if present else predicted hours)/24
```

**And the workbook's lead/lag is wrong.** `Plan Days` is computed as
`=SUM(Summary!R2:R1159)/24` — the *whole file's* planned hours — while `Actual Days` is
`=D1/24` for the current item. The resulting `Lag/lead = Plan Days − Actual Days` therefore compares a
portfolio total against one activity. Any number the module produces must define lag/lead explicitly at
well, section, phase and plan-item level, and print the definition next to the figure.

Also observed:

- `ROP` in `Summary` is `(next row's bit depth − this row's bit depth) / this row's hours` — i.e. a
  **look-ahead** difference, which mis-states ROP on the last row and on any row where the next block is a
  trip. Correct definition: footage gained inside the block ÷ rotating (or drilling) hours of that block.
- `Cum Dur (Days)` is `previous + Dur/24` — fine, but it starts from the first logged block, not from spud,
  so it does not equal DFS. Both must exist: *campaign day* (from spud) and *logged time* (sum of blocks).
- `NPT (hrs)` is filled for NPT rows and `PT (hrs)` is left empty; the pivot then sums two columns where
  only one is populated. The module must store one `duration_minutes` plus a classification and derive both,
  never two competing hour columns.
- The protected sheets (`Summary`, `PT-NPT DATASHEET`, and all DMR sheets) are protected **without
  reading impediment** — Excel sheet protection is a UI lock, not encryption; `openpyxl` reads them
  normally and simply refuses to *write* while `ws.protection.sheet` is true. One DMR workbook has a
  hidden sheet (`Bit Depth Graph`). No workbook in the sample is password-encrypted at file level. The
  engine therefore needs: read regardless of sheet protection, detect *file-level* encryption
  (`msoffcrypto`) and surface "password required" to the user rather than failing, ignore hidden sheets
  unless a mapping targets them, and never round-trip a workbook by rewriting it.

### 1.9 The DMR workbook

`DMR-65 IKAKI SOUTH-14 OBM 6" HOLE` (and `DMR-4 ENYIE-SW-7`) are mud-report workbooks with sheets `OBM`,
`Inventory`, `Mud Volume`, `Mud Loss`, `OWR`, `OPR`, `Shaker screen`, `Mud Track`, `Traffic Light`.
`OBM` alone carries: hole/bit/TVD depth, inclination, spud date, mud type, hole section, casing scheme,
present activity, active/reserve/total circulating volume, string/BHA volumes, annular velocity, pump data
(liner, strokes, bbl/stroke, GPM, SPM, bottoms-up strokes/minutes), and IN/OUT mud properties (density,
funnel viscosity, PV, YP, gels 10 s/10 min/30 min, HTHP fluid loss, cake, ES, chlorides, lime, temperature),
plus ECD/gradient. This is a **different report family** with its own schema and its own KPIs; it must not
be forced into the DDR tables.

---

## 2. What the current manual workflow costs

| Manual step today | Consequence | Module replacement |
| --- | --- | --- |
| Engineer reads the PDF and re-types the 24 h summary into Excel | 15–40 min/well/day; transcription drift from the PDF | extraction drafts the `Summary` rows; engineer corrects |
| Engineer decides `Plan` = P/U/NPT, picks Agency and Cause | judgement is nowhere recorded or explainable; `D` marks in PDFs are lost | classification with stored rule, confidence and reviewer |
| Engineer computes depth/bit depth/hours/ROP by hand per row | ROP look-ahead defect (§1.8); trip rows produce nonsense | computed ROP from footage ÷ rotating hours, with the basis stored |
| Timeline built by hand from the drilling programme with rate assumptions | good method, trapped in one workbook per well | plan builder with rate assumptions per hole section, versioned |
| Lag/lead read from `Input-lookahead` | formula defect (§1.8) | explicit lead/lag service, definition printed |
| PT-NPT pivot refreshed through MS Query | data only as good as the typed sheet; no history; no audit | server aggregate + dashboard, audit-logged |
| Reports filed per rig in folders | no directory per well/scope, no dedupe, no version | document vault per well + scope, checksum, versions, extraction status |
| Workbook protection shared around the team | nobody knows which copy is authoritative | one record, audit trail, immutability after approval |

---

## 3. The taxonomy the organisation already uses

From the `Codes` sheet (all values captured in `docs/operations/activity-taxonomy-extracted.csv`):

| Register | Count | Examples / structure |
| --- | --- | --- |
| Block | 9 | `OPL-2004`, `OPL-2005`, `OPL-2006`, `OML-143`, `OML-146`, `OPL-809`, `OPL-810`, `OML-13`, `OML-26` |
| Field | 35 | `AGU`, `AMESHI`, `AKUBO`, `ENYIE`, `ANIEZE`, `OKWUIBOME`, `SGEPL`, `SEL`, `NOSL`, `UTAS`, `AKATA`, `OGINI`, … |
| Rig | 25 | `Rig-01` … `Rig-25` (in the PDFs: `DURGA/9`, `Durga 4/4`, `DURGA #13/13`, `DURGA-5 /RIG-5`, …) |
| Drilling phase / hole size | 6 | `20"`, `16"`, `12 ¼"`, `8 ½"`, `6"`, `26"` |
| Operation group | 12 | `Drilling`, `Casing`, `Cementing`, `Logging`, `Rig Released`, `Plug Back`, `Drilling-ST`, `Drilling-PH`, `Drilling-MH`, `Drilling-MH2`, `Drilling-ST2`, `wellhead` |
| Activity (fine) | 256 | `SPUD`, `CHC`, `RIH 16" SLICK BHA`, `DRILL 8 ½" DIR HOLE`, `POOH 12 ¼" C/O BHA-OH`, `PJSM`, `SLIP-CUT DRILLLINE`, … |
| Hole diameter / casing | 9 | `16"`, `13 3/8"`, `13 5/8" SOW`, `12 1/4"`, `9 5/8"`, `11" CHS`, `11" THS`, `8 1/2"`, `7"` |
| Phase code | 10 | `ABAN`, `COMP`, `DRILL`, `MOB`, `PREP`, `PROD-MAN`, `RE-EN`, `SEC-WELL`, `W.O.`, `W.T.` |
| Operation code | 20 | `A` MOVING, `B` SKIDDING, `C` WELL HEAD & BOP, `D` CONDUCTOR PIPE, `E` DRILLING, `F` SIDE TRACK, `G` CASING JOB, `H` CEMENTING JOB, `I` CORING, `J` LOGGING, `K` WELL COMPLETION, `L` WELL DECOMPLETION, `M` WELL PREPARATION, `N` SAND CONTROL, `O` WELLBORE TREATMENT, `P` WELL TEST & D.S.T., `Q` WELL ABANDONING, `R` SLICK LINE, `S` COILED TUBING, `T` ARTIFICIAL LIFT |
| Activity code | 37 | `1` PREPARATION … `37` HSE ISSUES |
| **Plan / NPT code** | 75 | `P` PLANNED, `U` UNPLANNED, plus a full trouble taxonomy: `TP01` circulating losses … `TP99`; `TR01` drawwork … `TR99`; `TD01` BHA/drill string … `TD99`; `TS01` wellhead … `TS99`; `TW01` weather … `TW99`; and the `X*` "Unplanned Trouble-" twins `XP/XR/XD/XS/XW`, plus `SP` slow progress, `TH` tubular handling, `CH` casing handling, `BHAH` BHA handling, `EQF` equipment failure, `CRW` crew, `OTH`, `UPA`, `TNA`, `WOE`, `DHP`, `HC`, `DLS` |
| Agency | 30 + 2 categories | `SEEPCO` (Operator), `SEEPCO-Sub Surface`, `SEEPCO-Production`, `SEEPCO-Weather`, `BOGEL` (Rig Contractor), `ALNL-GYRO`, `ALNL-DD`, `ALNL-MWD`, `ALNL-Wireline`, `ALNL-Slickline`, `CBNL-Cementing`, `CBNL-Completion`, `CBNL-Coil Tubing`, `CBNL-Well testing`, `NOSL-*`, `Geomud`, `Schlumberger`, `Halliburton`, `Baker Hughes`, `Weatherford`, `Cameron`, `Geoplex`, `Ujiro`, `Energy Quest`, `SEL` |
| Cause | 17 | `SP`, `TH`, `CH`, `BHAH`, `EQF`, `CRW`, `OTH`, `UPA`, `TNA`, `WOE`, `DHP`, `HC`, `DLS`, `TW01`–`TW99` |
| Plan/unplanned | 3 | `P`, `U`, `NPT` |
| **PT/NPT allocation** | 4 | `NPT`, `PT`, `UPA`, `SP` |
| Hole section no. | 6 | `16`, `12-1/4`, `8-1/2`, `6`, `20`, `26` |

**Conclusions the design must honour**

1. The organisation's classification vocabulary is **three-plus-one**: `Planned` / `Unplanned` / `NPT`
   as the plan mark, and `NPT` / `PT` / `UPA` / `SP` as the allocation. `UPA` (Unplanned Activity) is
   distinct from `Unplanned`, and `SP` (slow progress) is its own allocation. Do not collapse them.
2. **The NPT taxonomy already exists** and is richer than any IADC default — 75 codes with a
   `Trouble-…`/`Unplanned Trouble-…` pairing and a five-way family (well, rig, downhole, surface,
   waiting). This must be user-configurable master data, imported from a starter list, not hard-coded.
3. There are three parallel "phase" vocabularies (OpenWells `DRLxxx`, phase code `DRILL/COMP/…`, hole size
   `16"/12¼"/8½"`). A single `phase` column cannot serve them: the module needs *hole section* (depth
   interval + size) and *operation code* (A–T) as separate dimensions, with an explicit mapping table from
   the OpenWells abbreviation.
4. Rig and well identity are **not clean**: `DURGA/9` = `Durga 9` = `Rig-09`; `ACHARA SOUTH-4PH` =
   `ACHARA-SOUTH-4PH`; `Name AGU-DEEP-1` appears where the well name should be. The module needs alias
   tables seeded from the existing `rigs`/`wells` registers and a match-confidence on every extraction.

---

## 4. Discrepancies and data-quality findings (all must be handled, none may crash the engine)

| # | Finding | Example | Handling |
| --- | --- | --- | --- |
| Q1 | Date format ambiguity | `11/16/2026` (mm/dd) next to `16/11/2026` (dd/mm); `10/5/2026` ambiguous | parse both, validate against spud date, DFS and report number sequence, prefer workspace locale, require confirmation when both are valid |
| Q2 | Report number missing or non-numeric | `DDR1`; one RMR blank | accept, store as text, derive sequence where possible, flag |
| Q3 | Rig missing in header | OGINI-34, OGUALI-19, the RMR | resolve from file name / previous reports for the well, else ask the reviewer |
| Q4 | Well name malformed | `Name AGU-DEEP-1`, `Name ENYIE SW-7` | prefix-strip rule + alias table + confidence |
| Q5 | Depth unit mixed | `MD 6,323.0 (ft)` in an otherwise metric portfolio; DMRs give `ft` and `m` side by side | store entered value + unit + metres; never assume |
| Q6 | Spud date in the future or after report date | `Start date 11/12/2026` while reports run to 16/11/2026 | warn, do not block; day number cannot be computed from a future spud |
| Q7 | DFS ≠ report number | SAKA-CREEK-3: report no. 81, DFS 76.00 | store both; DFN (days from spud) is the schedule figure, report number is the document sequence |
| Q8 | Last casing string formatting | `16.000 in @ 247.0 ft`, `7.000 in @ 3,713.00 m` | parse size + depth + unit |
| Q9 | Operation summary sums to 23.98 h | every report | 1-minute tolerance; never report a false "58 minutes unaccounted" |
| Q10 | Block spills into the next day | last block `23:59 → 6:00` carrying `**17/11/2026**` | store dated timestamps, allow one spill block, flag the report |
| Q11 | Narrative interleaves columns | `"2,323.0CONTINUE TO DRILL 8-1/2’’"` | geometry-based column binding (§1.6) |
| Q12 | Same activity coded differently | POOH coded `06`; TDS saver-sub change coded `07` | classification is inferred + reviewed; the code is a feature, not a verdict |
| Q13 | `Sub/Class` blank | 9 of 166 blocks | engine proposes from narrative, reviewer confirms |
| Q14 | `Sub/Class = D` unexplained | 4 blocks, all downtime narratives | map `D` to NPT candidate; confirm with the client (§7, D2) |
| Q15 | Metric/imperial in the same portfolio | ft wells and m wells | all stored in metres (shared `depth_to_meters`), original kept |
| Q16 | Sheet protection and hidden sheets | `Summary`, `PT-NPT DATASHEET`, DMR sheets protected; `Bit Depth Graph` hidden | read-only access, never rewrite, ignore hidden unless mapped |
| Q17 | Pivot/query sheets carry no rows | `PT-NPT DATASHEET` has headers only | read the source sheet (`Summary`), never the query target |
| Q18 | Duplicate reports | possible re-uploads and amended reports | SHA-256 + identity key (well, scope, report date, report no.) + version chain |
| Q19 | Workbook formulas with look-ahead defects | ROP, Plan Days (§1.8) | compute server-side with stored definitions; import workbook values only as *evidence*, not as authority |
| Q20 | Survey tables partially blank | section 7.1 often has one row and shifted columns | parse geometry, store partial surveys, never fabricate |

---

## 5. What the reports give us for the requested features

| Requirement | What the material supports |
| --- | --- |
| Break down DDR/DCR/DMR/RMR | four families identified; DDR/DCR share one parser, DMR needs its own, RMR is a DDR variant with rig-move fields |
| Allocate Planned/NPT/UPA hours from any report | `Sub/Class` + `Code` + narrative + `Plan`/`Agency`/`Cause` practice + the 75-code taxonomy; inference required, review mandatory |
| Summarise uploads briefly | 24 h summary, current status, forecast, operation summary, mud/materials/POB/safety blocks are all extractable; a brief is a deterministic composition of extracted facts, optional AI rewrite |
| Time vs Depth (actual vs predicted) | both curves already exist as data: `Data for Graph` (actual) and the Timeline (plan); the module reproduces them from records, not from a workbook |
| User verification before save | natural: `draft → reviewed → submitted → approved`, with extraction confidence and per-field review state |
| Dashboard KPIs | coverage, hours by classification, NPT Pareto by code/agency/cause, ROP, days vs depth, lead/lag, data quality |
| Well position & depth & direction | header MD/TVD, hole sections, surveys (section 7.1 + narrative gyro/MWD surveys + `WELL POSITION` remarks), DMR inclination |
| Timeline as the base; lead/lag | Timeline sheet = the plan model; `DATA FOR GRAPH-COMPLETION` = the per-activity planned/actual pairing; formulas in §1.8 |
| ROP | bit-depth/time per block, plus cumulative bit records in section 5; compute on rotating hours |
| Excel too | 4 ops-summary workbooks + 2 DMR workbooks are the import formats the engineers already produce |
| Documents per well and scope | no such directory exists today; the vault is new |

---

## 6. Interaction design evidence

The engineers' own workbook shows what they need on screen: one row per block with classification chips,
NPT hours, agency and cause; a pivot; a plan-vs-actual lookahead with lag/lead; a time-vs-depth chart; a
section plan summary. The PDF shows what they need on paper: the 24-hour table, narrative, depth, and
signatures (supervisor, company man, toolpusher). Both must be reproducible by the module, and the review
screen should sit **between** them: PDF page on the left, parsed fields on the right.

---

## 7. Decisions this study forces (carried into the implementation plan)

| ID | Decision | Recommendation from the evidence |
| --- | --- | --- |
| S1 | Report day boundary | **00:00 → 24:00 local**, configurable |
| S2 | Scope source | `Event` field (`ORIG DRILLING` / `ORIG COMPLETION`) + file name as secondary |
| S3 | Meaning of `Sub/Class = D` | treat as NPT candidate pending client confirmation |
| S4 | Classification vocabulary | store `classification ∈ {Planned, UPA, NPT}` **and** `allocation ∈ {PT, NPT, UPA, SP}` (two columns, as the org uses both) |
| S5 | Phase dimension | store hole section (size + interval), operation code (A–T), and phase code (DRILL/COMP/…) as three dimensions with mapping |
| S6 | Plan generation | rate-based plan builder (ROP, trip speed, contingency) with manual override, versioned |
| S7 | Lead/lag sign convention | `Lag = actual − planned` (positive = behind), `Lead = planned − actual`, computed per well/section/phase/plan item, definition printed |
| S8 | ROP definition | footage gained within the block ÷ rotating hours of the block; averages over drilling-only hours; never a look-ahead |
| S9 | Source workbook trust | values imported as evidence; all computed figures recomputed server-side |
| S10 | NPT/UPA/cost boundary | hours only in this module; no cost, no AFE reference (keeps the 2026-11-17 decoupling) |

---

## 8. Reference repositories — what is worth taking

| Repo | What it is | Take | Do not take |
| --- | --- | --- | --- |
| **DrillDash** (Sky370) | WITSML 1.4.1 → parquet store → Flask + JS real-time drilling dashboard; Volve dataset; time/depth log tracks, rig-state classification, replay, days-vs-depth, ROP/footage per day, connection times, trajectory | the **analytics vocabulary** (days vs depth, footage & ROP per day, rig-state ribbon, connection times), the idea of an **overview column** that shows the whole well beside a time axis, and rule-based rig-state classification as a *second opinion* on activity type | the WITSML/parquet real-time stack, the 19 GB store, the no-build-step frontend — this app is not a real-time RTOC and has no WITSML feed |
| **drilling-report-database** (nmamzada) | FastAPI/Flask + SQLite; **pdfplumber layout-aware DDR parser** with label dictionary, section splitting, two-group table parsing; tables `reports`, `operations`, `personnel`, `materials`, `surveys`, `mud_properties`, `phase_breakdown`, `report_sections`; duplicate detection by SHA-256 and by report identity; Excel export; read-only SQL studio | the **parser architecture** (section titles → key/value labels → table row groups → per-family parse), the **child-table set**, duplicate detection by hash **and** identity, and storing raw section text for full-text search | SQLite/local-only architecture, free-text key/value storage, the "ask AI to write SQL" surface (this app's assistant is governed and must not generate SQL) |
| **DrillMind** (ArokyaMatthew) | FastAPI + ML (autoencoder, isolation forest, LSTM) anomaly detection on Volve; IADC-aligned **8-state rig classifier**; MSE and d-exponent KPIs; alerts with ack/resolve; hybrid RAG (Chroma + BM25) over DDRs; 4-agent assistant | the **rig-state/activity state taxonomy** (drilling, reaming, circulating, connection, tripping in/out, washing, static) as an optional derived attribute of a block, and MSE/d-exponent as later KPIs | the ML stack and vector DB — no scikit/torch in this backend, no new heavy dependencies, and anomaly scores must not replace deterministic rules |
| **drilling-reports-ds-pipeline** (aytacbie) | notebooks: PDF table-type detection and section parsers → SQLite; NDS event matching (TF-IDF, BM25, sentence-transformers); NLP analysis: NER for activities/equipment/measurements/problems, activity classification, NPT detection, severity | the **table-type detector** idea (recognise a table by its header signature), the **dictionary-driven NER** approach (build activity/equipment/measurement/problem dictionaries *from the client's own codes*), and the **problem-keyword → NPT cause** mapping | notebooks as production code, transformer models, the "match narrative to external NDS events" objective |

**Synthesis.** Take the *parser discipline* from drilling-report-database, the *analytics vocabulary* from
DrillDash, the *state/keyword dictionaries* from DrillMind and the ds-pipeline — and implement all of it
deterministically, in this repo's layering (`domain → services → api`), against this repo's conventions
(column-wise storage, tenant scope, audit, RBAC, soft delete, no new heavy dependencies).

---

## 9. Effort implied by the evidence

| Work package | Evidence of size |
| --- | --- |
| PDF family parser (DDR/DCR) | 10 sections, 166 blocks over 21 files, 20 documented discrepancies |
| Excel family parser | 4 ops workbooks × 9 sheets + 2 DMR workbooks × 9 sheets, protected and pivot-bearing |
| Taxonomy masters + mapping | 256 activities, 75 NPT codes, 30 agencies, 17 causes, 3 phase vocabularies |
| Plan/timeline engine | rate-based generation, versioning, per-item actuals, lead/lag |
| Review workspace | field-level accept/correct against page geometry, confidence |
| Dashboards & exports | 12+ KPIs, 3 chart types, PDF/XLSX/CSV, print of the DDR form |

This is what the following plan phases are sized against.
