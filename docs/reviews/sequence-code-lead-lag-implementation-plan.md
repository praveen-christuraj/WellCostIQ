# Sequence codes, plan-versus-actual hours, and lead / lag in days

**Implementation plan — for approval before any code changes**
**Date:** 21 November 2026 · **Branch:** `arena/0c8f5cd4-wellcostiq` · **Base:** `86534cc`
**Read with:** `docs/operations/daily-workflow.md` (§ What the figures mean), `docs/operations/implementation-plan.md` §7.3a, `.agent/memory/project.md` (standing conventions)

> **Status:** this document is a design proposal and a change plan. No code, schema, migration or test was changed to produce it. Pytest, `gh` checks and the full UI check suite were deliberately not run (user instruction).

---

## 1. What is asked for, restated as a contract

The organisation's own *Input-lookahead* sheet does this arithmetic:

```
variance (hours) = planned hours − actual hours      positive = lead, negative = lag
variance (days)  = variance (hours) / 24
```

The request adds three real-world behaviours that the current code either models incorrectly or does not model at all:

| # | Requirement | Meaning in one sentence |
| --- | --- | --- |
| R1 | **Skipped planned activities** | A programme line that will never be done has its planned hours removed from the plan, and those hours are accounted for as saved — visibly, once, never by accident. |
| R2 | **Unassigned daily-report lines** | Hours logged against no sequence code are *Unplanned Activity*: they raise actual hours, they do **not** raise planned hours, so they produce lag. They must be inside the arithmetic, not excluded from it. |
| R3 | **Partially logged / continuing activities** | An activity planned at 100 h that has 12 h logged against it is **in progress**, not "88 h early". Its remaining hours are work still to do. Continuation across days accumulates against the same code until the activity is completed. |
| R4 | **Days** | Every lead / lag figure is printed in days by dividing hours by 24. |

---

## 2. What the code does today (measured, not assumed)

### 2.1 The happy path already exists

`backend/app/services/operations/seq_codes.py`
* `report_codes()` — the codes a report may link to, from the report's pinned baseline (else the well/scope active version).
* `preview()` / `apply()` — bulk-link selected lines to **one** `sequence_no`, then `reports_svc._recompute_baseline()`.
* `timeline_rollup()` — per-code planned vs actual across the baseline's whole scope, `variance_days = variance / 24`.

`backend/app/services/operations/reports.py`
* `_scope_blocks()` — every non-deleted block of the same well/scope tied to the baseline version (drafts included; a superseded version owns only reports pinned to it).
* `_line_contribution()` — the engineer's corrected `timeline_actual_hours` when `timeline_actual_edited`, else `duration_minutes / 60`.
* `_recompute_baseline()` — writes `timeline_plan_*`, `timeline_planned_hours`, `timeline_actual_hours`, `timeline_variance_hours/days`, `timeline_comparison` on every non-rejected row, from the **group** sum per code.
* `review_timeline()` — accept / edit / reject per line with corrected hours and a note.

Modelled data: `ops_plan_items` (`sequence_no`, `planned_hours`, `cum_planned_days`), `ops_activity_blocks.timeline_code` (text) plus the `timeline_*` comparison columns, `ops_daily_reports.baseline_plan_id`.

**So per-code summation across days already works.** R3's *continuation* is therefore mostly a display/state problem, not a data problem. The defects are in **state, scope and the totals**.

### 2.2 Defect A — unassigned hours are silently excluded (fails R2)

`seq_codes.timeline_rollup()`:

```python
for block in scoped:
    code = (block.timeline_code or "").strip()
    if code:  members.setdefault(code, []).append(block)
    else:     uncoded += 1                    # ← counted, then dropped
```

and then `total_planned` / `total_actual` only accumulate inside `if group:`. The page prints *“N logged line(s) without a code — excluded”*. The result: an entire day of unassigned work makes **no** difference to the variance. That is the opposite of R2. `_recompute_baseline()` likewise clears every plan-derived field on an uncoded row, so the line shows `—` rather than a lag.

### 2.3 Defect B — remaining work is reported as a lead (fails R3, and it is the biggest one)

The per-code comparison is applied to **every** code the moment a single hour is logged:

```
planned 100 h, 12 h logged  →  variance = +88 h  →  "Lead +88.00 h · +3.667 d"
```

On day 1 of a well that has 8 days of programme left, the rollup can declare a multi-day lead on every started activity at once, and `total_variance = total_planned − total_actual` is printed over only the codes that happen to have logs. Nothing in the model distinguishes *“finished 88 h early”* from *“has not done 88 h of work yet”*. That distinction is exactly what R3 asks for.

### 2.4 Defect C — there is no way to say “this activity was skipped” (fails R1)

There is no skip state, no skip reason, no excluded-from-plan concept, and no saved-hours figure anywhere in `ops_plan_items`, the schemas, the services or the UI. A skipped activity simply never receives logs, so it sits in the project for ever at zero actual and zero variance. Its planned hours are neither earned nor released, and `cum_planned_days` on every later activity keeps counting them.

### 2.5 Defect D — one line can carry only one code

`OpsActivityBlock.timeline_code` is a single `String(20)` and `OpsSeqCodeIn` applies one `sequence_no` to many blocks. A real narrative line (“drill ahead and ream, then run casing”) that genuinely spans two programme rows cannot be attributed honestly; the engineer must pick one, and the other code's actual becomes wrong by construction.

### 2.6 Defect E — sequence numbers are not stable identities

`plans.replace_items()` (called by `PUT /plans/{id}/items`, i.e. every save in `TimelineEditor`) does:

```python
db.execute(delete(OpsPlanItem).where(...plan_version_id == plan.id))
for i, item in enumerate(items, 1): item.sequence_no = i
```

Every plan item gets a **new primary key** and a positional `sequence_no` on every save, while blocks hold `timeline_code` as *text* and `timeline_plan_item_id` as an FK with `ondelete="SET NULL"`. Inserting one activity at the top of a draft therefore re-points every historical link one code sideways, and every existing `timeline_plan_item_id` is nulled. With R1–R3 relying far more heavily on the code identity, this must be fixed first or the arithmetic will be confidently wrong.

### 2.7 Defect F — drafts vote on a submitted figure

`_scope_blocks()` includes `draft`, `in_review` and `rejected` reports in the same sum as `submitted`/`approved`. An engineer typing tomorrow's draft can change this month's reported lead/lag. There is no confirmed-versus-provisional split.

### 2.8 Defect G — two different lead/lag numbers with the same name

| Surface | Basis today |
| --- | --- |
| Plans rollup, report register, report review dialog | `Σ planned − Σ actual` hours, ÷ 24 (`seq_codes`, `_recompute_baseline`, `TimelineHoursReview`) |
| Dashboard KPI, Well Summary, Analytics `lag_series` | `planned_cum_days − elapsed_days` at the confirmed checkpoint or an interpolated depth (`analytics.time_depth`) |

Both are labelled “Lead / lag”. They can disagree on the same screen. One of them has to be named the *schedule position* and the other the *sequence variance*, and the labels must say so.

---

## 3. The model this plan adopts

### 3.1 Two different questions, two different numbers

The root of Defects B and G is that one number is asked to answer two questions.

| Question | Measure | Valid when |
| --- | --- | --- |
| “Did the work we finished take the hours the programme allowed?” | **Sequence variance** = `Σ planned(finished) − Σ actual(finished)` ÷ 24 days | Every code it covers is finished |
| “Are we ahead of or behind the programme today?” | **Schedule position** = `effective_planned_cum_days(at last finished code) − elapsed_days` | A programme start (or DFS) and a finished checkpoint exist |

Keep both, keep the existing sign convention (**positive = lead, negative = lag**), and never mix them in one figure.

### 3.2 A sequence code has exactly one state at any moment

Derived in a pure function, never hand-typed, never guessed:

| State | Condition | Planned hours | Lead / lag verdict |
| --- | --- | --- | --- |
| `not_started` | no contribution and not skipped | counted in the plan | **none** — “not started” |
| `in_progress` | `0 < actual < planned` and not closed | counted in the plan | **none** — progress %, remaining hours |
| `complete` | closed by the engineer, or auto-closed by `actual ≥ planned × (1 + tolerance)` | counted, earned | **yes** — `planned − actual` |
| `overrun_open` | `actual > planned` and not closed | counted, earned | none — “over plan by X h, still open” |
| `skipped` | explicit skip recorded | **removed**, reported as saved | **separate** line, netting per policy |

**Closing a code** is an explicit act (new endpoint, audited): `POST /operations/plans/{plan_id}/items/{item_id}/close` with `actual_hours` optional and a note. Auto-close is a *suggestion* surfaced to the reviewer (`close_source = "auto"`), applied silently only when the workspace enables it (`sequence_auto_close = true`, default **false**, because a plan of 100 h finished in 90 h and a plan of 100 h where 100 h were burned without finishing the hole are not the same event).

Completion is **never** inferred from a successor starting. A successor with an open predecessor is raised as a finding (`open predecessor`) so the reviewer can close or correct; it is not auto-filled.

### 3.3 Unplanned hours are a first-class bucket

The rollup gains a synthetic row, code `—` (**Unplanned**), with `planned_hours = 0`:

```
unplanned_actual = Σ contributions of every scoped line with no code (and any split remainder)
unplanned_variance = 0 − unplanned_actual          → always a lag
unplanned_days = unplanned_variance / 24
```

It enters **actual total** and therefore the schedule position, and it is shown in the per-code table (with the NPT / UPA split) instead of a footnote that says “excluded”. The block-level `timeline_basis` reads `unplanned activity — no sequence code` and its `timeline_comparison` is `behind`, so the report register tells the same truth as the rollup.

Policies live in `ops_settings` (see §5.2), so a workspace that does not want NPT to inflate the schedule number can exclude it — the choice is recorded and printed beside the figure, never silently applied.

### 3.4 Remaining work is reported, never credited (answers R3 directly)

For an `in_progress` code:

```
progress_pct  = min(100, actual / planned × 100)
remaining_h  = max(0, planned − actual)
```

`variance_hours`, `variance_days` and `comparison` are **NULL** on that row, and the UI prints **“In progress · 12.00 / 100.00 h (12%) · 88.00 h remaining”**. The 88 h can no longer be mistaken for a lead. When the engineer closes the code, the row switches to `planned − actual` and its days. This *is* the answer to “the 5th activity was recorded with only 12 hours against a 100 h code — it does not mean the operation was fully completed”.

### 3.5 Totals that cannot lie

```
planned_in_scope   = Σ planned of (not_started + in_progress + overrun_open + complete)
planned_saved      = Σ planned of skipped
actual_coded       = Σ contributions to every code
actual_unplanned   = Σ contributions with no code (incl. split remainders)
actual_total       = actual_coded + actual_unplanned

realised_variance  = Σ_complete(planned − actual) − actual_unplanned       ← the printed lead/lag
closed_coverage    = Σ_complete(planned) / planned_in_scope                 ← how much of the plan this covers
plan_coverage      = actual_total / planned_in_scope                        ← burn, NOT a verdict
= Σ planned_in_scope − actual_total                                         ← shown, explicitly NOT lead/lag
```

`plan_coverage` is the number the current code prints as the total variance. It stays visible because engineers use it, but it gets a name that cannot be read as a schedule verdict, plus the caveat “includes work not yet started”.

**Skipped hours (`planned_saved`) are shown on their own line and are not netted into `realised_variance` by default.** A skipped activity only gains calendar time once the programme is re-baselined; the plan therefore reports the saving, and shows the *effect* properly through §3.6, rather than adding a day of "lead" for work that was never going to be done.

### 3.6 Skipping shifts the effective programme curve (R1)

The saved `cum_planned_days` of an **active** version is never rewritten — history must stay readable. Instead the rollup computes, per code, an **effective** cumulative position that excludes skipped predecessors:

```
effective_cum_planned_days(item) = Σ planned_hours(rows ≤ item, not skipped) / 24
effective_cum_shift(item)        = saved_cum_planned_days(item) − effective_cum_planned_days(item)   → ≥ 0
```

Every later activity therefore shows the days it has moved earlier, the schedule position (§3.1) is computed on the effective curve, and the stored baseline is untouched. A row that is skipped keeps its recorded `cum_planned_days` for audit.

### 3.7 One line, several codes (answers R3's “4 activities to one code, the 5th to another”)

* The 4/1 case **already works** line by line; what is missing is a UI that makes it one gesture instead of four (`preview`/`apply` today take a single `sequence_no`).
* The genuinely mixed line gets explicit **splits**: a new child table

```
ops_activity_block_codes
  id, organization_id, block_id → ops_activity_blocks(id) CASCADE,
  plan_item_id → ops_plan_items(id) RESTRICT,
  sequence_no_snapshot (int), hours (Numeric 28,3),
  created_at, created_by, updated_at, updated_by
  UNIQUE (block_id, plan_item_id); INDEX (organization_id, plan_item_id); INDEX (organization_id, block_id)
```

  `Σ hours ≤ block contribution` (validated in the service, 3-dp exact — never “roughly”); any remainder stays in the unplanned bucket and is *named* in the response. A block with no split row keeps using its single `timeline_code`, unchanged, so nothing existing is rewritten.
* One **bulk** request assigns one code to many lines; a **split** request assigns hours of one line to several codes. Both are previewed first, both audited, both refuse submitted/approved reports.

### 3.8 Stable identity for codes (fixes Defect E)

* Sequence numbers are how engineers talk about the programme, so `sequence_no` stays in the UI and in `timeline_code` as a **display snapshot**.
* The **identity** of a code becomes `ops_plan_items.id`. `timeline_plan_item_id` is already stored on every block and already written by `apply()`; the rollup, the recompute and the review dialog key on it, not on the text.
* `replace_items()` stops deleting rows. It performs a positional **upsert**: an incoming row that carries `item_id` updates in place (description, depth, hours); a row without one is inserted; an existing row missing from the payload is refused while any block references it (`409`, listing the referencing reports) rather than being deleted and renumbered. A plan version referenced by any report cannot be renumbered — a renumbering must be a **new version** (the existing `create_plan` path).
* `timeline_code` continues to be written for readability and for exports; the service derives it from `timeline_plan_item_id` when they disagree, and reports the disagreement instead of trusting the text.

### 3.9 Confirmed versus provisional (fixes Defect F)

The aggregation selects blocks from reports in `draft`/`in_review`/`rejected` **and** `submitted`/`approved`, and partitions them:

```
confirmed   = submitted + approved
provisional = draft + in_review          (rejected excluded from both, as today)
```

The rollup returns both sets, and the printed verdict uses **confirmed** hours (with provisional hours shown beside them and a caution naming how many reports are unsubmitted). `report_codes`, `apply`, `review_timeline` keep operating on the report they are given, so a draft can still be reviewed — it simply does not vote on the confirmed figure.

---

## 4. The arithmetic, in full

Pure, DB-free, standard library only — the same layering as `domain/entry_statistics.py` → `domain/entry_rules.py` → `services/entry_checks.py`.

### 4.1 New pure module `backend/app/domain/operations/sequence.py`

```python
HOURS_PER_DAY = Decimal(24)          # R4, named once
@dataclass(frozen=True)
class PlanRow:  item_id, sequence_no, description, planned_hours,
                target_depth_m, saved_cum_days, state, skip_reason
@dataclass(frozen=True)
class Contribution: block_id, report_id, item_id | None, hours, confirmed, allocation
@dataclass(frozen=True)
class Policy:  uncoded="lag", npt="include", auto_close_tolerance_pct=Decimal(0),
               skipped_credit="separate", require_code_on_submit=False

def to_days(hours) -> Decimal                     # quantized to 3 dp
def sequence_states(rows, contributions, policy) -> dict[item_id, State]
def build_ledger(rows, contributions, *, confirmed_only=True) -> Ledger
def effective_cum_days(rows) -> dict[item_id, Decimal]
def frontier(rows, states) -> item_id | None
def findings(rows, states) -> list[Finding]        # open predecessor, split mismatch,
                                                   # code text vs plan item, negative remaining
```

`build_ledger()` returns:

```python
Ledger(
  codes=[CodeRow(sequence_no, item_id, description, state, planned_hours, actual_hours,
                 progress_pct, remaining_hours, variance_hours, variance_days,
                 comparison, closed_at, close_source, skip_reason, saved_planned_hours,
                 effective_cum_days, cum_shift_days, line_count, report_count,
                 provisional_actual_hours, line_ids[])],
  unplanned=UnplannedRow(code="—", actual_hours, npt_hours, upa_hours,
                         variance_hours, variance_days, line_count,
                         provisional_hours),
  totals=Totals(planned_in_scope, planned_saved, actual_coded, actual_unplanned,
                actual_total, realised_variance, realised_variance_days,
                closed_coverage, plan_coverage, plan_coverage_days,
                comparison, provisional_actual_hours, closed_code_count,
                open_code_count, not_started_count, skipped_count),
  findings=[...])
```

Rules encoded here, each with a written reason in the docstring:

1. A skipped code earns nothing and consumes nothing; its planned hours go to `planned_saved`; any actual hours coded to it are surfaced as a finding (they belong to the unplanned bucket or to another code) — never silently dropped.
2. A code with no contributions and not skipped is `not_started`; its planned hours stay in `planned_in_scope` and it emits **no** variance.
3. A code with contributions that is not closed is `in_progress` / `overrun_open`; **no** variance, progress and remaining instead.
4. Only `complete` contributes to `realised_variance`.
5. `realised_variance` subtracts `actual_unplanned` (R2). If `policy.npt == "exclude"`, NPT-allocated unplanned hours are still shown but not subtracted, and the figure says so.
6. `skipped_credit == "net"` adds `planned_saved` to `realised_variance`; the default `"separate"` does not.
7. All sums are `Decimal`; quantize once, at the result boundary, to 3 places (`core/precision.rounded`).
8. Empty is not zero: no logs → `actual = None`; no planned → `planned = None`; `None` never prints as `0.00`.

### 4.2 Schedule position (the dashboard number)

`analytics.time_depth()` already owns the elapsed-days basis (programme start → DFS → first submitted period) and `planned_at_depth()`. It gains one lookup: instead of `checkpoints[report.completed_plan_item_id]`, use `effective_cum_days()` from §3.6 when the report's `completed_plan_item_id` is set, and label the row `basis = "confirmed programme activity (sequence)"`. Nothing else changes; the depth-interpolation path stays for reports with no checkpoint. The `lag_series` and the dashboard KPI therefore move onto the same effective curve as the rollup, and their labels change from “Lead / lag” to **“Schedule position (days)”** while the rollup's figure is **“Sequence variance (days)”**.

### 4.3 Worked examples

Programme, P:

| Seq | Activity | Planned h |
| --- | --- | --- |
| 1 | Rig up and spud | 24 |
| 2 | Drill 12¼" hole to 2 800 m | 100 |
| 3 | Wiper trip to shoe | 24 |
| 4 | Run 9⅝" casing | 36 |
| 5 | Cement and WOC | 12 |
| | **Total** | **196 h = 8.167 d** |

**Day 1 — Defect B, exactly the reported scenario.** Five lines: four totalling 12 h → code 2; one of 8 h → code 1; 4 h with no code.

| | Today | Planned |
| --- | --- | --- |
| Code 1 | +16.00 h lead (+0.667 d) | In progress · 8/24 h (33%) · 16 h remaining |
| Code 2 | +88.00 h lead (+3.667 d) | In progress · 12/100 h (12%) · 88 h remaining |
| Codes 3–5 | omitted | Not started |
| Unassigned 4 h | excluded | Unplanned · 0 − 4 = −4.00 h (**lag 0.167 d**) |
| Total | **+104.00 h lead = +4.333 d** on day 1 | Sequence variance **—** (nothing finished) · Schedule position **−0.167 d** (lag) |

The honest day-1 answer is “half a shift behind, because 4 h were logged against no programme activity”, not “four days ahead”.

**Day 2 — R3 continuation.** Code 1 closes at 26 h (2 h over); code 2 logs 30 h more (42 total).

| Code | State | Planned | Actual | Variance | Days |
| --- | --- | --- | --- | --- | --- |
| 1 | complete | 24 | 26 | −2.00 h | **−0.083 d (lag)** |
| 2 | in progress | 100 | 42 | — | 42% · 58 h remaining |
| 3–5 | not started | 24 / 36 / 12 | — | — | — |
| — | unplanned | 0 | 0 | — | — |

`realised_variance = −2.00 h`; `closed_coverage = 24/196 = 12%`; `plan_coverage = 68/196 = 35%`.

**Day 9 — R1 skip.** The hole came in clean, so the wiper trip (code 3) is skipped with a reason.

| | Value |
| --- | --- |
| `planned_in_scope` | 172 h (196 − 24) |
| `planned_saved` | 24 h — printed as “Skipped · 24.00 h planned saved” |
| `realised_variance` | unchanged by the skip under `skipped_credit="separate"` |
| `effective_cum_days` of codes 4, 5 | 1.000 day earlier; `cum_shift = 1.000 d` |
| Schedule position | 1.000 day better than the un-adjusted curve would say |

The saving reaches the schedule, once, through the curve — and the reviewer can see both the row and its 1-day effect.

**Rounding.** `Decimal` throughout; `variance_days = (variance_hours / Decimal(24)).quantize(0.001, ROUND_HALF_UP)`, matching `core/precision.rounded`. `−0.001` never prints as `0.000`.

---

## 5. Data and configuration changes

All additive and column-wise — **no JSON columns** (standing convention 4).

### 5.1 New / changed columns

`ops_plan_items` (new):

| Column | Type | Purpose |
| --- | --- | --- |
| `state` | `String(16)` NOT NULL default `'planned'`, check in (`planned`,`skipped`) | explicit skip |
| `skipped_at` / `skipped_by` / `skip_reason` | timestamp / `String(255)` / `String(500)` | who voided the row, why |
| `closed_at` / `closed_by` / `close_source` / `close_note` | timestamp / `String(255)` / `String(12)` / `String(500)` | completion evidence (`confirmed` \| `auto`) |
| `closed_actual_hours` | `Numeric(28,3)` NULL | the actual the engineer confirmed at close, when it differs from the summed logs |

`ops_activity_blocks` (new):

| Column | Type | Purpose |
| --- | --- | --- |
| `timeline_split_state` | `String(12)` NOT NULL default `''` (`''` \| `split` \| `remainder`) | a line with splits, and whether part of it stayed unplanned |
| `timeline_sequence_state` | `String(16)` NOT NULL default `''` | cached display state: `in_progress`, `complete`, … (derived on recompute; readable in exports and the register) |

`ops_settings` (new, all with server defaults so existing rows migrate untouched):

| Column | Type | Default | Meaning |
| --- | --- | --- | --- |
| `sequence_uncoded_policy` | `String(12)` | `'lag'` | `lag` = R2 as asked · `exclude` = old behaviour |
| `sequence_npt_policy` | `String(12)` | `'include'` | NPT hours inside the unplanned lag, or shown only |
| `sequence_skipped_credit` | `String(12)` | `'separate'` | `separate` \| `net` (§4.1 rule 6) |
| `sequence_auto_close_tolerance_pct` | `Numeric(6,3)` | `0` | auto-close suggestion threshold |
| `sequence_auto_close` | `Boolean` | `false` | apply auto-close without a reviewer |
| `sequence_require_code_on_submit` | `Boolean` | `false` | submit refuses a line with no code and no explicit unplanned acknowledgement |
| `sequence_current_run_only` | `Boolean` | `true` | confirmed figure from the latest non-superseded report revision per date |

New table `ops_activity_block_codes` — §3.7.

### 5.2 Migration

`backend/alembic/versions/<rev>_ops_sequence_states_and_splits.py`, `down_revision = "9ac1f4e72b03"` (current single head — verified by scanning every `revision`/`down_revision` pair).

* Adds the columns above with `server_default` values; adds the table and its indexes.
* **Backfill, deliberately conservative:**
  * `ops_plan_items.state = 'planned'` for every row (no skip is inferred).
  * `ops_activity_blocks.timeline_sequence_state = ''` (unknown, recomputed on next save — a migration must not recompute a submitted day).
  * `timeline_plan_item_id` repaired where it is `NULL` but `timeline_code` matches exactly one row of the report's baseline (the `f7b3d1a95c80` style, but **per report baseline**, not globally), and where two candidates match the row is left `NULL` and listed in the migration log for manual attention. Nothing else is written.
* `downgrade()` drops the columns/table only. It cannot restore the auto-repaired links; that is stated in the docstring (the repo's convention: a downgrade that loses derived state says so).

### 5.3 Stable-identity migration for `replace_items`

No schema change; a service change plus a one-shot repair in the same revision:

```sql
-- blocks whose plan item was nulled by a previous renumbering, but whose
-- code text still matches exactly one row of that report's baseline
UPDATE ops_activity_blocks SET timeline_plan_item_id = (...)
WHERE timeline_plan_item_id IS NULL AND timeline_code IS NOT NULL AND <unique match>
```

and a log line per report where the match was ambiguous.

---

## 6. Backend changes, file by file

### 6.1 `backend/app/models/operations.py`
New columns and the `OpsActivityBlockCode` model (§5.1), each with a docstring explaining *why* the state exists — the file already documents the lead/lag contract this way, so the new fields join that narrative rather than appearing as bare columns.

### 6.2 `backend/app/schemas/operations.py`

| Class | Change |
| --- | --- |
| `OpsPlanItemIn` | `+ item_id: str \| None` (positional upsert, §3.8), `+ state`, `+ skip_reason`, `+ close_note` |
| `OpsPlanItemOut` (new, replaces `list[dict]` in `OpsPlanVersionOut.items`) | typed row incl. `id`, `state`, `closed_at`, `effective_cum_days` |
| `OpsPlanVersionOut` | `items: list[OpsPlanItemOut]`; `+ has_linked_reports: bool` so the editor can lock renumbering |
| `OpsTimelineCodeOut` | `+ item_id`, `+ state`, `+ remaining_hours`, `+ is_skipped`, `+ effective_cum_days` |
| `OpsSeqCodeIn` | keep; `sequence_no` becomes `sequence_no \| None` **only** when `item_id` is supplied |
| `OpsSeqCodeSplitIn` (new) | `block_id`, `allocations: list[{sequence_no \| item_id, hours}]`, `remainder_to_unplanned: bool = true` |
| `OpsSeqCodePreviewOut` | `+ per_line_after`, `+ remainder_hours`, `+ findings` |
| `OpsSequenceStateIn` (new) | `state: Literal["planned","skipped"]`, `reason`, `expected_updated_at` |
| `OpsSequenceCloseIn` (new) | `actual_hours: Decimal3 \| None`, `note`, `block_ids` optional, `expected_updated_at` |
| `OpsTimelineRollupCodeOut` | `+ item_id`, `+ state`, `+ progress_pct`, `+ remaining_hours`, `+ closed_at`, `+ close_source`, `+ saved_planned_hours`, `+ effective_cum_days`, `+ cum_shift_days`, `+ provisional_actual_hours`; `variance_hours/days` and `comparison` become `None`-able (already) and are `None` unless `state == "complete"` |
| `OpsTimelineRollupOut` | `+ unplanned: OpsTimelineUnplannedOut`, `+ totals` (typed), `+ policy`, `+ findings`, `+ confirmed_report_count`, `+ provisional_report_count`; keep `uncoded_lines` for compatibility (now = the unplanned line count) |
| `OpsSettingsIn/Out` | the seven settings of §5.1, each validated (`Literal`, `ge/le`), defaults matching the model |

`extra="forbid"` stays everywhere; new fields are additive, so a stale browser is unaffected while a stale server is refused by the existing `REQUIRED_API_VERSION` gate.

### 6.3 `backend/app/services/operations/reports.py`

| Function | Change |
| --- | --- |
| `_scope_blocks()` | return `(confirmed, provisional)` partitions, or add `_scope_partition()` beside it and keep `_scope_blocks()` as the union for callers that want everything |
| `_line_contribution()` | unchanged (still honours the engineer's corrected hours) |
| `_contributions()` (new) | flatten blocks **and their split rows** into `domain.sequence.Contribution`; a split changes a line's per-code hours, never the total |
| `_recompute_baseline()` | rewrite around `build_ledger()`: per block, write `timeline_sequence_state`, `timeline_planned_hours`, `timeline_actual_hours`, and the code's variance **only when that code is `complete`**; for `in_progress` write `timeline_variance_* = NULL`, `timeline_comparison = "on"`, and put progress/remaining in `timeline_basis` (extend `String(50)` → 80 or move prose to `timeline_note` — the column is 50 chars today and will truncate: use the note and keep `basis` to a short token such as `in progress`); for uncoded rows write `timeline_basis = "unplanned activity"` and `variance = −actual`, `comparison = "behind"` |
| `_suggest_comparison()` | same switch; also **suggests** the frontier code for a new line whose narrative matches the open code, as a `suggested` value only, never a write |
| `review_timeline()` | accept/close interplay: closing is a separate endpoint; this function keeps its corrected-hours contract, but refuses to write a variance on an open code and says why |
| `save_report()` | unchanged except that `_suggest_comparison()` now also writes `timeline_sequence_state`; the `timeline_code` ↔ `timeline_plan_item_id` reconciliation from §3.8 runs here |
| `submit_report()` | honours `sequence_require_code_on_submit`: an uncoded line needs an explicit acknowledgement (`classification == "UPA"` **and** a reason), otherwise 422 naming the line |

### 6.4 `backend/app/services/operations/seq_codes.py`
Becomes the orchestrator around the pure module:

```python
def report_codes(...)            # + item_id, state, remaining, skipped
def preview(...)                 # unchanged contract, richer body
def apply(...)                   # one code → many lines; keys on item_id; writes the display code
def apply_split(...)             # new: hours of one line → several codes; validates Σ ≤ line hours
def clear_codes(...)             # new: remove a code / all codes from lines (explicit unplanned)
def set_item_state(...)          # skip / un-skip, with reason + audit; refuses if hours are coded to it
def close_item(...)              # complete a code: confirmed or auto; writes closed_* and recomputes
def timeline_rollup(...)         # thin: gather rows + contributions + policy → build_ledger → dict
def schedule_position(...)       # new: the days figure from §4.2, one implementation for the dashboard
```

Every mutating entry point keeps today's guarantees: preview never writes; apply writes only `draft`/`in_review`/`rejected` reports (`409` naming the locked wells); one audit entry per action with the counts, the codes and the recompute.

### 6.5 `backend/app/services/operations/analytics.py`
`time_depth()` uses `effective_cum_days()` (§4.2), labels the basis, and returns `sequence_variance_days` beside `lag_days` so the dashboard can show both without recomputing either.

### 6.6 `backend/app/api/operations.py`
| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| `GET` | `/operations/plans/{plan_id}/timeline-rollup` | `ops-plan:read` | extended body |
| `GET` | `/operations/plans/{plan_id}/sequence-ledger` | `ops-plan:read` | the pure ledger, paged codes, `?policy=` overrides for previewing a policy |
| `POST` | `/operations/reports/timeline-codes/preview` | `ops-report:update` | unchanged, richer |
| `POST` | `/operations/reports/timeline-codes/apply` | `ops-report:update` | unchanged, `item_id` accepted |
| `POST` | `/operations/reports/timeline-codes/split` | `ops-report:update` | §3.7 splits |
| `POST` | `/operations/reports/timeline-codes/clear` | `ops-report:update` | explicit unplanned |
| `POST` | `/operations/plans/{plan_id}/items/{item_id}/state` | `ops-plan:update` | skip / un-skip |
| `POST` | `/operations/plans/{plan_id}/items/{item_id}/close` | `ops-plan:update` **and** `ops-report:review` | completion (hours are report facts) |
| `GET` | `/operations/plans/{plan_id}/sequence-export` | `ops-plan:export` | xlsx / csv / pdf, audited through the existing export audit |

No new capability is invented; `ops-plan:update` and `ops-report:review` already exist, so no RBAC migration is needed. (If a reviewer decides closing needs its own grant, add `ops-plan:close` in the same revision — the provisioning map is the single place capabilities are declared.)

### 6.7 Documents
* `docs/operations/daily-workflow.md` — a new subsection *Sequence codes, in-progress work and unplanned hours* with the state table, the two measures, and the policy settings.
* `docs/operations/implementation-plan.md` §7.3a — corrected: the old “planned − actual per code” is now explicitly a **realised** measure over finished codes.
* `backend/app/services/operations/guide.py` — the `timeline` and `calculations` topics gain the state model and the two figure names.
* `.agent/memory/project.md` — the durable decisions, the new `CAUTION_PAGE` usage on the Plans page, and the migration id.
* `API_VERSION` → `0.24.0` in `backend/app/main.py` and `REQUIRED_API_VERSION` in `frontend/src/lib/api.ts`, paired.

---

## 7. Frontend changes, file by file

Design-system rules apply: tokens only, light and dark, `FormDialog`/`PanelDialog` only, `Caution` rather than bare `Alert` for standing notes (convention 16), pagination 20/50/100, export on the table.

### 7.1 `frontend/src/lib/operations.ts`
* Types for every new/extended payload (`OpsPlanItemEx`, `OpsSequenceState`, `OpsSequenceSplit`, `OpsTimelineRollup` with `unplanned`, `totals`, `policy`, `findings`).
* New calls: `sequenceLedger`, `applySeqSplit`, `clearSeqCodes`, `setPlanItemState`, `closeSequence`.
* `timelinePayload()` passes `item_id` through (it currently strips `id`) — this is what makes §3.8 work from the editor.

### 7.2 `frontend/src/components/operations/SeqCodeDialog.tsx`
Three explicit modes in one dialog, each with its own preview:
1. **Assign one code to the selected lines** (today's behaviour, now showing each line's `before → after` and the code's state and remaining hours).
2. **Split one line across codes** — a small hours grid, a live “allocated / line hours / remainder → unplanned” meter that blocks on over-allocation, and the remainder named.
3. **Leave unplanned** — an explicit, audited acknowledgement that reads the hours it will add to the unplanned lag.
The dialog states the consequence in the user's own arithmetic: *“Code 2: 100.00 h planned · 12.00 h logged · 88.00 h remaining (in progress). This will not be reported as a lead until the activity is closed.”*

### 7.3 `frontend/src/pages/operations/Plans.tsx` — the rollup table
Per-code columns: `Sequence · Activity · State · Planned h · Actual h · Progress · Remaining h · Variance h · Variance days · Cumulative days (effective) · Saved days · Lines · Logs`. State is a chip (`Not started`, `In progress`, `Complete`, `Overrun open`, `Skipped`). The **Unplanned** row sits first with its NPT/UPA split and its lag in days. Above the table: four figure cards — **Sequence variance (days, finished work)**, **Schedule position (days)**, **Plan coverage (%, not a verdict)**, **Skipped: n activities · h saved** — each with a one-line basis. A `Caution` names how many reports are unsubmitted when provisional hours exist, and a `Caution` lists findings (open predecessor, code/plan mismatch). Row action **Close activity** (permission-gated) and **Skip / Un-skip**. Export includes the new columns.

### 7.4 `frontend/src/components/operations/TimelineHoursReview.tsx`
Grouping stays per code, but each group header shows state, progress, remaining, and variance only when the code is complete; the uncoded group becomes **“Unplanned — contributes lag n h (n d)”** instead of “excluded from lead/lag”. The totals strip splits `Planned (finished) / Actual (coded) / Actual (unplanned) / Sequence variance / Schedule position`. A **Close this activity** button appears on a complete-looking group.

### 7.5 `frontend/src/pages/operations/ReportDetail.tsx`
* The `Seq` column menu shows each code with its state and remaining hours, and offers “Split this line…”, “Clear code”, and “Mark unplanned”.
* A new `State` column beside `Lead (+/−)` so a reader sees `In progress` rather than a blank.
* `Plan / actual (h)` shows `planned / actual (remaining)`.
* `Lead (+/−)` renders `—` with the reason (`in progress`, `not started`, `unplanned`) instead of a misleading `On plan`.
* An unsaved-changes guard already covers the page; the natural code editor is now compatible with it.

### 7.6 `frontend/src/pages/operations/Settings.tsx`
A **Sequence and lead/lag** group: uncoded policy, NPT policy, skipped credit, auto-close toggle and tolerance, require-code-on-submit, current-run-only. Each has helper text quoting §3–§4 so the setting cannot be chosen without knowing what it does.

### 7.7 `frontend/src/pages/operations/Overview.tsx`, `Summary.tsx`, `Analytics.tsx`
Relabel `Lead / lag` → **Schedule position (days)** and, where the same card already exists, show **Sequence variance (days)** beside it with its coverage (`based on n of m finished activities`). No new chart is required; the existing `lag_series` simply carries the effective curve.

### 7.8 UI checks
Extend `.agent/tools/operations-overview-check.jsx` (or add `sequence-code-check.jsx` + a `make sequence-code-check` target) to mount: a rollup with not-started / in-progress / complete / skipped / unplanned rows; a Day-1 fixture proving **no lead is printed** for 12-of-100 h; an unplanned row proving lag; a split whose remainder is named; a mixed-policy render; light and dark. The check must assert the absence of a “Lead” label on an in-progress row — that is the whole point of the change and it is the easiest thing to regress.

---

## 8. Delivery in phases (each phase shippable on its own)

| Phase | Content | Why this order |
| --- | --- | --- |
| **P0 — identity** | §3.8 upsert in `replace_items`, `item_id` in `OpsPlanItemIn`/`TimelineEditor`, rollup keys on `timeline_plan_item_id`, migration repair | Every later number depends on a code meaning the same row tomorrow |
| **P1 — pure ledger** | `domain/operations/sequence.py` + unit tests; no API change yet | The arithmetic is testable in isolation, which is where the three scenarios live |
| **P2 — states and unplanned** | skip / close endpoints, unplanned bucket, `_recompute_baseline` rewrite, extended rollup, settings columns | Delivers R1 + R2 + R3 in the API |
| **P3 — splits** | `ops_activity_block_codes`, split endpoints, Σ validation | Delivers the mixed line honestly |
| **P4 — confirmed vs provisional** | partition in `_scope_blocks`, both figures in the payload, cautions | Stops a draft voting on a submitted month |
| **P5 — schedule position** | `analytics` effective curve, relabelling across Overview / Summary / Analytics | Removes Defect G |
| **P6 — UI** | Plans rollup, SeqCodeDialog modes, TimelineHoursReview, ReportDetail, Settings, export | Makes it usable |
| **P7 — docs, guide, memory, version bump** | §6.7 | A number nobody can explain is a liability |

Phases P1–P2 alone answer all three stated scenarios; P3–P5 answer the awkward cases the request itself raises (“4 to one code, the 5th to another”, “it might be recorded again the next day”).

---

## 9. Tests to add (written, not run — per instruction)

`backend/tests/test_operations_sequence_ledger.py` (pure domain, no DB):
1. 100 h planned / 12 h logged → `in_progress`, `remaining = 88`, `variance is None` — **the regression that matters**.
2. Two days of logs against one code accumulate; a third closes it → variance from the total.
3. Skip → `planned_saved` correct, `planned_in_scope` reduced, `effective_cum_days` of successors shifted by exactly the skipped days.
4. Unassigned 4 h → unplanned row variance `−4`, days `−0.167`; `uncoded_policy="exclude"` → not subtracted, still shown.
5. NPT policy include / exclude on the same input.
6. `skipped_credit` separate vs net.
7. Split 60/40 over a 100 h line; remainder 10 h to unplanned; over-allocation refused.
8. Closed code overrun (`actual > planned`) → negative variance, `overrun_open` before close.
9. Decimal edge: 1 h → `0.042` day at 3 dp; `−0.001` never `0.000`.
10. `None` never printed as `0`.

`backend/tests/test_operations_sequence_api.py` (API):
11. Apply one code to 5 lines; rollup shows it in progress, not a lead.
12. Close via the endpoint → audited, recompute, register fields follow.
13. Skip a code that still has hours → `409` naming the lines (or an explicit move), never a silent drop.
14. Submitted report refuses a code change (`409`), draft accepts.
15. Renumbering a draft that a report references → `409`; a new version is the offered path.
16. Confirmed vs provisional: a draft's 50 h does not change the confirmed variance.
17. Tenant isolation: another workspace's plan item id is refused, not found-and-used.
18. Permission: `ops-plan:update` without `ops-report:review` cannot close.
19. `sequence_require_code_on_submit` 422 names the line; UPA-with-reason passes.
20. Migration: upgrade on a DB with linked blocks leaves submitted rows byte-identical and repairs only unambiguous `timeline_plan_item_id`.

Frontend checks: `.agent/tools/sequence-code-check.jsx` per §7.8.

Existing suites that must stay green: `test_operations_timeline_hours.py` (its assertions on `timeline_planned_hours`, `timeline_actual_hours`, `timeline_variance_hours`, `timeline_comparison` and `timeline_basis == "no matching programme activity"` are contract), `test_operations_codes.py`, `test_operations_workflow.py`, `test_operations_dashboard.py`, `test_operations_enhancements.py`. Two expectations will have to change **deliberately and visibly**, not silently:
* `test_an_unmatched_block_reports_no_comparison_rather_than_a_wrong_activity` — under R2 an unmatched line is *unplanned*, so its basis becomes `unplanned activity — no sequence code` and its comparison `behind`, not `on`.
* Any assertion that an unmatched line contributes nothing to the total.
Both are listed here so the reviewer approves the semantic change before it happens.

---

## 10. Compatibility, rollout and risks

| Risk | Mitigation |
| --- | --- |
| Historical submitted days change because a code is now `in_progress` | The recompute is derived, not stored history; the report's own `timeline_review_state` and the audit trail are untouched. Migration writes no comparison field. |
| Renumbering still happens through the Excel import path | `replace_items` is the single entry point for `PUT /items`; `timeline_preview` only proposes rows. Force the upsert there and refuse a positional change while references exist. |
| A code referenced by an old version of the plan | Rollup is per `plan_version_id` and reports pin `baseline_plan_id`; a superseded version owns only its pinned reports (existing behaviour). |
| Policy change silently re-states past months | Policies are stored, audited, and returned in the payload (`policy`) so every figure carries the policy it was produced under. Changing a policy is an `ops-settings:update` action and is logged. |
| Closing an activity by habit, without evidence | Closing records actor, time, note and the summed actual; an auto-close is only a suggestion unless the workspace opts in; the review dialog shows the evidence it is closing on (∑ lines, hours, last report date). |
| 24-hour days versus calendar days | The request specifies `difference / 24`; the figure is labelled **hours ÷ 24** everywhere and the schedule position (which uses real elapsed days) is shown beside it, so a 24 h/day assumption that a partial day of standby does not hold is visible, not hidden. |
| Truncation of `timeline_basis` (50 chars) | The rewrite keeps `basis` to short tokens and moves prose to `timeline_note` (500 chars), or widens the column in the same migration — decided in P2, one of the two, never a silent truncation. |
| Performance | ≤2 000 items and a bounded set of blocks per well; the ledger is computed from one query per plan version. The existing `_scope_blocks` is unchanged in shape. A materialised `ops_plan_sequence_state` is **not** needed for this release and is deliberately left out. |

**Rollout:** migration → backend (`0.24.0`) → frontend (paired `REQUIRED_API_VERSION`). Defaults reproduce today's arithmetic exactly (`sequence_uncoded_policy` is the one deliberate change, and it is the requested one), so a workspace that never opens the new screen sees only the corrected `in_progress` display, which is the bug fix.

---

## 11. Decisions to confirm before implementation

Recommended values are marked. Each one changes a printed figure, so each is stated once here rather than buried in the code.

| # | Decision | Options | Recommended |
| --- | --- | --- | --- |
| 1 | Lead / lag on a partially logged code | (a) `planned − actual` now | (b) **no verdict until closed; show progress + remaining** |
| 2 | Unassigned hours | (a) excluded (today) | (b) **lag: add to actual, planned unchanged** |
| 3 | NPT inside the unplanned lag | (a) **include** | (b) show only |
| 4 | Skipped hours as a lead | (a) **reported separately, curve shifted** | (b) netted into the variance |
| 5 | Who closes a code | (a) **reviewer with `ops-report:review`** | (b) any `ops-plan:update` holder |
| 6 | Auto-close when actual ≥ planned | (a) suggestion only (**default**) | (b) automatic |
| 7 | Confirmed figure | (a) **submitted + approved** | (b) all non-deleted (today) |
| 8 | Require a code on submit | (a) off (**default**, warn only) | (b) on, with an explicit unplanned acknowledgement |
| 9 | One line across several codes | (a) **split with hours, remainder named** | (b) one code per line, unchanged |
| 10 | Renumbering a referenced version | (a) **refused; new version required** | (b) migration of links by description |

---

## 12. Acceptance criteria

1. Day 1 with 12 h against a 100 h code prints **no lead** anywhere — rollup, register, review dialog, export or dashboard.
2. 4 h with no code produces a lag of `0.167 d` in the unplanned row and in the sequence variance.
3. A skip removes the hours from `planned_in_scope`, reports them once as saved, and shifts every later activity's effective cumulative days by exactly the skipped days.
4. Closing a code makes its `planned − actual` and `/24` appear; nothing appears before that.
5. The same code keeps meaning the same programme row after any draft save.
6. Confirmed figures change only when a submitted or approved report changes.
7. Every figure printed in days states `hours ÷ 24`, and the schedule-position figure states its elapsed-days basis.
8. Each of the three scenarios has a named regression test and a mounted UI check.

---

## 13. Implementation record

This section records what was built, in the order it was built, and where each decision
from §11 landed. It is the map from the plan to the code; the code is the source of truth
for behaviour, and the tests named below are the executable version of §12.

### 13.1 The arithmetic, in one place

`backend/app/domain/operations/sequence.py` — pure, no database, no FastAPI. It owns the
states (`not_started`, `in_progress`, `overrun_open`, `complete`, `skipped`), the unplanned
bucket, the skip shift, the totals and the findings. Everything else calls
`build_ledger(rows, contributions, policy)` and prints what it returns.

Two results from that module are worth stating here because they are the whole point:

* `Day 1, 12 h against a 100 h code` → `in_progress`, `progress 12 %`, `remaining 88 h`,
  `variance None`. The 88 hours are work owed, and there is no API shape in which they can
  be read as a lead.
* `4 h with no code` → `unplanned_variance = -4.000 h = -0.167 d`. The hours are in actual
  hours and in the printed lag, not in a footnote.

`confirmed_only` is a **reporting** switch, not an arithmetic one: with it on, draft hours
are excluded from every figure and returned separately as what is waiting to be submitted.
That is how a draft can never move a month that was signed, while the engineer reviewing
the draft still sees the arithmetic of the hours actually recorded on their screen.

### 13.2 One identity for a sequence code

`ops_plan_items.id` is the identity. `ops_activity_blocks.timeline_code` remains the printed
snapshot an engineer types; `timeline_plan_item_id` is the link the arithmetic uses.
`_resolve_code_item()` is the single translation between them and is scoped to one baseline,
so a code can never resolve across wells, scopes or versions.

`plans.replace_items()` is a positional upsert keyed on `item_id` (Decision 10):
a row that carries one is updated in place, a row without one is new work, and a row that
disappears is deleted only when nothing references it. Two refusals make the record safe:

* an activity that disappears while a daily-report line is coded to it → `409` naming the
  reports, and the suggestion to *skip* it instead;
* an activity that **moves position** while a line is coded to it → `409`, because the code
  is a printed number and its row must not start pointing at a different activity.

### 13.3 The write side

* `POST /operations/plans/{id}/items/{item_id}/state` — skip / un-skip, with a kept reason
  and the optimistic `expected_updated_at` stamp. Skipping is refused while hours are coded
  to the activity (the hours would have nowhere to go) and refused on a closed activity.
* `POST /operations/plans/{id}/items/{item_id}/close` — the **only** route to a verdict,
  needing `ops-report:review` in addition to `ops-plan:update`. It refuses an activity with
  no evidence at all, and refuses hours that disagree with the log unless a note says where
  they are. Hours typed at a close are kept only for an activity with no report lines,
  because where lines exist **they** are the record — a later correction or submission must
  keep moving the verdict rather than being frozen behind it.
* `POST /operations/plans/{id}/items/{item_id}/reopen` — withdraws the verdict with a reason;
  the hours stay.
* `POST /operations/reports/timeline-codes/split` — allocates one line's hours to several
  codes, `Σ allocations ≤ the line's own hours`, the remainder named in the response. The
  line's single stored code is cleared, because the split *is* the assignment and two claims
  on the same hours are worse than none.
* `POST /operations/reports/timeline-codes/clear` — removes the code and records it as a
  decision (`timeline_split_state = "unplanned"`), so the suggestion engine cannot put it
  back on the next save.
* `GET /operations/plans/{id}/sequence-export` — the register as a self-describing download:
  one row per code plus the unplanned bucket, the totals, the policy and the four notes that
  say what the numbers mean.

### 13.4 The numbered defects

| | Defect | Where it is fixed |
| --- | --- | --- |
| A | Unassigned hours excluded from the rollup | `UnplannedRow` in the ledger; `unplanned` + `totals.actual_unplanned` in the rollup; its own row in the register, the review dialog and the export |
| B | Remaining work printed as a lead | `_state()`: `in_progress` / `overrun_open` yield `variance_hours = None`; the register prints progress and remaining hours instead |
| C | No skip state | `PlanRow.skipped`, the skip endpoint, `planned_saved`, and the effective curve (`effective_cum_days` / `cum_shift_days`) |
| D | One line, one code only | `OpsActivityBlockCode` + the split endpoint, with the remainder explicitly named |
| E | `replace_items` delete + renumber breaks identity | positional upsert on `item_id`, plus the two refusals above |
| F | Drafts vote on submitted figures | `confirmed_only` in the ledger; drafts returned as `provisional_*` |
| G | Two differently-based numbers both called "Lead / lag" | the rollup prints the **sequence variance**; `analytics.time_depth()` prints the **schedule position** on the effective curve and labels its basis; the UI labels both |

### 13.5 Suggestions are never assignments

`_suggested_items()` matches an uncoded line's narrative to the **open** part of the
programme only — never to a closed or skipped activity, because a fresh line cannot belong
to finished work. It is computed at read time, never stored, and two lines are never
suggested to the same code. A cleared line is left alone.

### 13.6 What the screens say

* `TimelineHoursReview` — the state is on the group header (`in progress · 12.00 / 100.00 h
  (12 %) · 88.00 h remaining`), the verdict column reads `no verdict` / `unplanned` /
  `skipped` where the old screen printed a number, and the header card says
  **no verdict yet** until something is finished.
* `SeqCodeDialog` — refuses to code work to a skipped or finished activity and explains why;
  offers "this line did two activities…" with per-code hour allocation; offers "clear the
  code" and states its cost (the hours become Unplanned Activity and read as lag).
* `Plans` — the register gained State, Progress, Remaining, and an ACTIONS cell for
  Skip / Restore / Finish / Reopen with their reasons; the summary chips separate
  **hours spent** (burn) from **lead / lag** (finished work only), and show saved and
  unplanned hours on their own.
* `Settings` — a "Lead and lag" section for the seven `sequence_*` settings, each with what
  it does to the figure it produces.

### 13.7 Tests

* `backend/tests/test_operations_timeline_hours.py` — rewritten for the state model: an open
  activity reports progress, not a lead; a correction is stored on an open code without a
  verdict and produces one when the activity is closed; an unmatched line is Unplanned
  Activity and can only lag.
* `backend/tests/test_operations_sequence_codes.py` — new: the three requested scenarios
  (skip, partial, unplanned), the split with its named remainder, the clear, the identity
  survival across a re-order, the two refusals, the optimistic stamp, the export, and the
  permission and evidence rules around closing.

### 13.8 Known limits, stated rather than hidden

* Auto-close remains a **suggestion** (`sequence_auto_close` defaults to off): a plan of
  100 h finished in 90 and a plan of 100 h burned without finishing the hole are not the
  same event.
* `sequence_current_run_only` is stored and shown, but the confirmed cohort is still
  "submitted or approved"; narrowing it to the latest revision per date is a separate change
  to the report lifecycle, not to this arithmetic.
* Finalising a `.xlsx` export of the sequence register is done client-side from the
  server's own JSON (`GET .../sequence-export`), so the file and the screen cannot disagree.
