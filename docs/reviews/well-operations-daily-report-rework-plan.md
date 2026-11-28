# Well Operations — daily report, sequence budget and lead / lag

**Review plan — for approval before any code changes**
**Date:** 28 November 2026 · **Branch:** `arena/16522199-wellsenseiq` · **Base:** `b309fd3` · **API:** 0.26.0
**Read with:** [`docs/operations/daily-workflow.md`](../operations/daily-workflow.md) (what ships today), [`docs/reviews/sequence-code-lead-lag-implementation-plan.md`](sequence-code-lead-lag-implementation-plan.md) §13 (what the current ledger implements), `.agent/memory/design-system.md`.

> **Status:** proposal and change plan only. No code, schema, migration, page or test was changed to produce it. Pytest, `gh` checks and the UI check suite were **not** run (user instruction). The five mock-ups referenced below are wireframes generated for review — they are not screenshots of a running build.

| Figure | What it shows |
| --- | --- |
| [01 · daily-report-workspace.png](well-operations-figures/01-daily-report-workspace.png) | The report editor after compaction: 9 columns, one scroll region, inspector rail. |
| [02 · sequence-assignment-budget.png](well-operations-figures/02-sequence-assignment-budget.png) | Assigning a line to a sequence **with the hours left visible before and after** (budget · logged · left before · this line · left after). |
| [03 · skip-decisions.png](well-operations-figures/03-skip-decisions.png) | The programme strip (4 planned, 3 done, 1 skipped) and the three meanings of “skipped”, each with its effect printed before the write. |
| [04 · calculation-model.png](well-operations-figures/04-calculation-model.png) | The whole arithmetic on one page, including slow progress. |
| [05 · reports-register.png](well-operations-figures/05-reports-register.png) | The reports register: today’s 17-column row set vs. the same data grouped by programme activity, with the outcome and schedule position side by side. |

---

## 1. The request, restated as a contract

| # | Your words | What it becomes in the module |
| --- | --- | --- |
| **R1** | “Still assigning the activities against the sequence is giving more confusions.” | Assigning a line to a sequence shows the **budget** of that sequence — planned, already logged, hours left, hours left after this line — before anything is written. |
| **R2** | “If the selected sequence has 8 hours, the user assigned activity was 3 hours… then 4 hours… balance of 1 hour… it will be taken into account for lead or lag.” | A sequence is a **budget that carries forward**: every logged hour consumes it; the remainder belongs to the sequence until the sequence is closed or skipped. |
| **R3** | “If hours saved, it is lead and if consumed more from the planned, then it is lag.” | Closing a sequence yields `planned − logged`: **positive = lead, negative = lag**, in hours and hours ÷ 24 days. |
| **R4** | “4 sequences were planned, but actually 3 activities were done. The 4th sequence was skipped… skipping means 2 things.” | **Skipped** is an explicit state with **three dispositions** (§4.4), each with its own effect on the arithmetic. |
| **R5** | “Lag will not come only from NPT and UPA. 10 hours planned may take 12 hours… the lag is because of Slow Progress… not NPT or UPA. NPT and UPA will be clearly allocated by the user.” | Lag has **four provenance buckets** — planned overrun, slow progress, NPT, UPA/unplanned. Only the last three are user statements; the first is inferred from hours. Slow progress is never counted twice. |
| **R6** | “The UI should be more easy… even in separate pop-up dialog boxes, the view is not full and there are many scrolling. Compaction without diminishing the UX & views.” | The report editor goes from **22 columns / one screen plus three nested dialogs / four scroll regions to 9 columns / one always-visible inspector / one scroll region**, with no field, action, export or permission removed (§4.1). |

Everything else in the module — extraction, documents, submissions, approvals, well path, analytics — keeps working unchanged.

---

## 2. What the module does today, measured

I read the module end to end. This is the behaviour as written, with the file that decides it.

### 2.1 The arithmetic already in place

`backend/app/domain/operations/sequence.py` is a pure ledger. For each programme row (`ops_plan_items`) it sums every contributing line (`ops_activity_blocks`, split-aware through `ops_activity_block_codes`) and derives one state:

| State | Condition (`_state`, line ~262) | Verdict printed |
| --- | --- | --- |
| `not_started` | no hours | none — “not started” |
| `in_progress` | `0 < logged < planned` | none — progress % and hours owed |
| `overrun_open` | `logged > planned`, not closed | none — “over plan by X h, still open” |
| `complete` | closed by an engineer (or `auto_close` policy) | `planned − logged` = +lead / −lag, ÷24 days |
| `skipped` | explicit skip | none — hours released as saved |

`reports_svc._recompute_baseline()` writes those verdicts onto every line as `timeline_*` columns; `seq_codes.timeline_rollup()` prints them per code; `Plans.tsx` shows them in the sequence register. **This part is sound and stays.**

### 2.2 Where it breaks — the confusion you are seeing

| # | Defect | Evidence in the code | Effect on a user |
| --- | --- | --- | --- |
| **G1** | **The sequence has no visible budget.** The sequence picker shows `seq — description · 6.00 h · in progress`. It never shows **hours left**, nor what this line will leave behind. | `SeqCodeDialog.tsx` state sentence prints `planned/actual/remaining` only after a code is chosen; `report_codes()` (`seq_codes.py`) returns `planned_hours`, `actual_hours`, `remaining_hours` **only for a code that is already counted** — nothing shows “left after this line”. | You cannot answer “does this line fit in sequence 12?” before assigning it. This is R1/R2 and it is the root of the confusion. |
| **G2** | **Leftovers are invisible.** `remaining_hours` exists on `CodeRow`, but the reports side never shows it: the register column says “Plan / actual” and the review dialog prints an in-progress sentence only. | `ReportDetail.tsx` column `timeline_planned_hours`; `TimelineHoursReview.tsx` `stateSentence()`. | The 1 h left on sequence 12 from your example is nowhere on the daily-report screen. |
| **G3** | **The review dialog’s verdict disagrees with the programme register.** The dialog is handed `rows={selected.length ? selected : blocks}` — **this report’s lines**, or just the selected ones — and then prints `planned − Σ those rows` as the code’s verdict. The register prints `planned − Σ every line in the scope` from `_ledger()`. | `ReportDetail.tsx` line 1523 (`rows={…}`) + `TimelineHoursReview.tsx` `groups` memo (`variance = planned − actualSum`) vs `reports.py` `_ledger()` → `sequence.build_ledger()`. | A three-day activity closed on day 3 shows a *different* lead/lag in the report than in Plans; selecting two of ten lines shows a third figure. This is the single largest source of “more confusions”. |
| **G4** | **A submitted month can end with no verdict at all.** A report can be submitted while a code is `overrun_open` (submission only checks blocks, not codes). The code then stays open for ever unless someone visits Plans. | `submit_refusals()` has no sequence-state check; `close_item()` requires an explicit act and `ops-report:review`. | Every such day contributes **nothing** to `totals.realised_variance`; the month reads “no activity finished yet — no lead or lag”. |
| **G5** | **Skipping has one meaning and is often refused.** `set_item_state()` refuses a skip while **any** line is coded to the activity (`409`, “Hours are already logged against this activity. Move them to the activity that did the work, then skip it”). There is no way to say “the time still belongs to the record” and no way to say “it was done inside another sequence”. | `seq_codes.set_item_state()` lines ~561–585; `Policy.skipped_credit` only accepts `separate`/`net`. | Your second skipping case (“add that skipped time to take account in lead”) cannot be recorded, and the first (“not done, counts as lead”) can only be recorded on an untouched activity. |
| **G6** | **Slow progress exists but never reaches the lag.** `SP` is a stored allocation, is counted in the KPI strip (`sp_minutes`, `summary.sp_hours`), and is **ignored by the ledger**: `_contributions()` carries `allocation`, and `build_ledger()` uses it only to split *unplanned* NPT/UPA/other. | `sequence.py` `NPT_ALLOCATIONS`, `_allocation_hours`; `reports.py` `_line_contribution`. | “It took 12 h instead of 10 h, and it was SP” reads identically to a plain overrun; the report cannot say the lag was slow progress rather than an event. (R5.) |
| **G7** | **Two numbers share the name “Lead / lag”.** `Overview` and `Summary` print the time-vs-depth figure; `Plans` prints the sequence figure. | `Overview.tsx` KPI `Lead / lag` ← `analytics.dashboard().lag_days`; `Plans.tsx` chips ← `timeline_rollup().totals`. | The dashboard and the programme disagree on screen, both labelled the same. |
| **G8** | **A code-wide verdict is copied onto every line of the code.** When a code closes, `_recompute_baseline()` writes the **same** `variance_hours`/`variance_days` onto each block that points at it. | `reports.py` 549–552 (`if state_row.state == sequence.COMPLETE: … timeline_variance_hours = state_row.variance_hours`), repeated in `review_timeline()` at 1416. | Three lines of one closed code each print “Lead 3.500 h” and read as 10.5 h of lead; the number belongs to the code, not the line. |
| **G9** | **The editor is a 22-column grid inside a full-screen dialog inside a report register.** Sum of the declared `minWidth`s: **3,450 px** of grid against a 1,440 px viewport, plus a 3-tab shell, a block dialog of **14 inputs plus 19 menu items across 9 selects** (~60 controls) and three more `FormDialog`s opened from the same screen. | `ReportDetail.tsx` columns at lines 884–1046; `FormDialog` block editor at 1557–1931. | Horizontal scrolling while editing, and dialogs that open over dialogs. R6. |
| **G10** | **Four scroll regions for one day’s work.** panel (report editor) → tab → grid → row dialog → “Review hours & lead / lag” panel → “Apply sequence code” dialog, each with its own scrollbar. | `ReportDetail.tsx` `PanelDialog` + 3 tabs + `FormDialog` + `TimelineHoursReview` (`PanelDialog`) + `SeqCodeDialog` (`FormDialog`). | Nested scrollbars in the top two surfaces hide content under their fixed footers. |
| **G11** | **Skip/close decisions live only on the programme screen**, so the engineer reviewing a day has to leave the report, find the version, find the row, then come back. | `Plans.tsx` `openAction()`; the report editor has no sequence-state action. | The workflow is fragile exactly where it matters. |
| **G12** | **The reports register hides the outcome.** 17 columns — date, rig, well, scope, type, no., four depths, progress, MW, logged hours, status, summary, remarks, actions — and **not one programme figure**: no sequence outcome, no schedule position, no unplanned hours. | `Reports.tsx` lines 165–194 (`columns={[…]}`). | A month cannot be scanned; you must open each report and read its strip. |
| **G13** | `OpsDailyMetric.pt_minutes` and `sp_minutes` are **never written** (`_compute_metrics` sets six other fields). | `reports.py` `_compute_metrics()`. | The SP/PT split is missing from every daily metric, so nothing downstream can show slow progress per day. |
| **G14** | `_CODE_ITEM_CACHE` is a **module-level dict** cleared only inside `_recompute_baseline`. | `reports.py` line ~334. | A read-only page (`report_codes`) can serve a stale code→item mapping after a draft timeline save in the same worker. Low frequency, wrong when it happens. |
| **G15** | The block dialog **cannot assign a sequence at all**: `timeline_code` is in the save payload (`editFields`, line 118) but not in the dialog’s fields, and **`addBlock()` (line 481) does not initialise it** — so a brand-new line is saved with `timeline_code: undefined`. | `ReportDetail.tsx` 118, 481–526, 1557–1931. | A new line can never be coded when it is created, and a new line saved through the dialog is undefined-coded until someone uses the grid column or the dialog. Sequence assignment feels bolted on because it is. |
| **G16** | **An inspector cannot be built from today’s API.** `_block_out()` returns the `timeline_*` comparison fields but **no** `timeline_split_state` and no resolved code budget, so a page cannot distinguish “split between codes” from “never coded”, and cannot show the row’s before/after budget without client-side arithmetic. | `api/operations.py` `_block_out()`; `models/operations.py` `timeline_split_state`. | The row cannot say “these hours are shared” — the reader has to open the split dialog to find out. |
| **G17** | **The acceptance gate does not mention the sequence.** A block is “reviewed” when its *criteria* are complete; whether it is coded to the programme is a separate, optional switch (`sequence_require_code_on_submit`, default off). | `requirements.describe_missing()`; `submit_refusals()`. | Nothing tells the engineer that the line’s hours will land in “Unplanned activity” until the rollup says so. |

**What is already correct and must not regress:** only a closed code carries a verdict; unplanned hours are a first-class bucket and can only lag; a skipped activity’s hours are released and the effective curve (not the signed baseline) moves; drafts never vote on a submitted month; the ledger is pure and deterministic; closing is audited.

---

## 3. The model this plan adopts

### 3.1 Three numbers, three questions, never mixed

See [figure 04](well-operations-figures/04-calculation-model.png).

| Question | Measure | Basis | Where it appears |
| --- | --- | --- | --- |
| “Does this line fit in that sequence?” | **Sequence budget** — planned, logged, **hours left**, hours left after this line | `planned − Σ logged` for one code | Assignment picker, report inspector, programme rail |
| “Are we ahead or behind the programme today?” | **Schedule position** (keep the name) | planned cumulative days at the confirmed checkpoint **on the effective curve** − elapsed days | Overview, Summary, programme rail |
| “Did the work we finished cost what the programme allowed?” | **Sequence outcome** (renamed from “sequence variance”) | Σ over **closed** codes of `(planned − logged)`, minus unplanned hours; days = hours ÷ 24, once | Reports strip, programme register, export |

**Naming change (display only, no column or API rename):** “Sequence variance” becomes **“Sequence outcome”**, and a skipped code’s effect is printed as **“released”/“credited”**, never as a “lead” it did not earn. The existing `variance_*` JSON keys stay for compatibility.

### 3.2 The budget carries forward

This is R2, stated as arithmetic. A sequence is a **spend**, not a per-line allocation:

```
balance_before  = planned − Σ logged(confirmed, all days, all lines on the code)
left_after_line = balance_before − hours(this line)
```

| Step | Line | Sequence 12 (8.000 h planned) |
| --- | --- | --- |
| 1 | Line A, 3.000 h | logged 3.000 · **5.000 h left** |
| 2 | Line B, 4.000 h, same sequence | logged 7.000 · **1.000 h left** |
| 3 | Line C assigned to sequence 14 | sequence 12 keeps **1.000 h left** — it is not spent on sequence 14 |
| 4 | Sequence 12 is closed at 7.000 h | outcome **+1.000 h = +0.042 d** (lead) |
| 4′ | …or a later line logs 2.000 h on sequence 12 first | logged 9.000 → **over by 2.000 h** (lag −0.083 d when closed) |

Rules that follow, and that the UI must state:

- The remainder is **never** implicitly transferred to “the next sequence”. It stays on its own code until that code is closed or skipped. This is the fix for G1/G2.
- An overrun is **not** an event. It is the same planned activity finishing late (§3.5), so it cannot be NPT or UPA unless the engineer says so on the line.

### 3.3 Sequence states, closure, and the auto-confirm policy

States stay as they are (`not_started`, `in_progress`, `overrun_open`, `complete`, `skipped`). The change is **who closes a code and when** (G4):

| Situation | Today | Proposal |
| --- | --- | --- |
| Code finishes under its plan | engineer closes it in Plans | unchanged: **explicit close** (a lead is a claim about how the job went) |
| Code runs **over** its plan and the lines are accepted on a submitted report | stays `overrun_open` for ever | **auto-confirm on submit** (workspace policy, default **on**): the report that accepted the overrunning lines is the human act; the close is recorded as `close_source = "system-overrun"` with the report id in `close_note`, and the outcome is a lag |
| Code over plan but its report is still a draft | `overrun_open` | unchanged — **nothing auto-confirms on a draft** |
| Code has hours but no plan figure | `in_progress`, nothing to compare | unchanged, with a finding |

`sequence_auto_close` / `sequence_auto_close_tolerance_pct` already exist and stay; the new switch is `sequence_auto_confirm_overrun` (default `true`). A code that becomes confirmed can be re-opened exactly as today, with a reason.

### 3.4 Skipped: three meanings (R4)

Today a skip is refused as soon as any line is coded to the activity (G5). Replace the single flag with a **disposition** chosen at skip time (figure 03):

| Disposition | When it is right | Arithmetic |
| --- | --- | --- |
| **A — not needed** (pre-selected; D3) | Nothing was done and nothing replaces it | planned hours leave the plan (`planned_in_scope −= p`); reported once as `planned_saved`; the effective curve of every later code moves earlier by `p ÷ 24`; outcome unchanged unless the workspace chooses `net` |
| **B — done inside another sequence** | The work happened, but under a different programme row | A releases the plan; the chosen lines (this sequence’s coded lines) are **re-coded to the named receiving sequence**, whose logged hours rise accordingly — so a receiver that had budget left now consumes it, and one that had none now overruns |
| **C — skipped, time still counts** | The sequence will not be done but the shift time was spent and must stay on record | A releases the plan; the chosen lines stay on record as **unplanned** (`timeline_code` cleared, `timeline_split_state = "unplanned-only"`), so their hours become lag — NPT/UPA **only if the engineer allocates them so**, otherwise plain overrun (R5) |

Stored on the plan row: `skip_disposition ∈ {'not_needed','completed_elsewhere','charge_time'}`, plus `skip_relief_item_id` (B’s receiver) and the existing `skip_reason`. Un-skip clears all three. Option B and C require at least one coded line; Option A requires **no** coded lines (the current refusal becomes a precondition of A, not of every skip).

Policy: `sequence_skipped_credit` keeps its meaning (`separate` | `net`). New, per disposition *and* workspace default: whether A/B credit the released hours into the outcome. Recommended default stays **`separate`** — the saving reaches the schedule through the curve, and the outcome is not flattered by work nobody did.

### 3.5 Lag provenance — four buckets (R5)

| Bucket | Source | Counted in the outcome | How it reaches the screen |
| --- | --- | --- | --- |
| **Planned overrun** | logged > planned on a PT line | yes, when the code is closed | `overrun_hours` per code; “over plan” chip |
| **Slow progress (SP)** | engineer sets allocation `SP` on the line(s) | yes — **as the same lag**, not added again | `slow_progress_hours` per code and in the unplanned row; “lag, slow progress” label |
| **NPT** | engineer sets Activity type NPT / allocation NPT | yes; can never be productive | NPT bucket, never inferred |
| **UPA / unplanned** | Activity type UPA, or a line with no sequence | yes | unplanned row (with `sp_hours` added to its split so an unplanned SP hour is not lost) |

**No double counting is possible**, by construction: every logged hour belongs to exactly one line, one allocation and one sequence (or none). SP is a *property of hours already in the sum*, so it is a label on the lag, not a second subtraction. Two consequences to state explicitly on screen:

- A planned activity that took 12 h of 10 h is **lag 2 h = 0.083 d** whether or not it is flagged SP; flagging it changes the *reason*, not the size.
- “Accumulated” lag is only ever the accumulation **of days already measured** (`Σ day variances`), or `Σ variance hours ÷ 24` — never both.

### 3.6 What does not change

Signed months are never rewritten. `hours ÷ 24` stays the only conversion. NPT and UPA are only ever user statements. The domain ledger stays pure (no DB, no clock). Permissions are unchanged: `ops-report:update` to code lines, `ops-report:review` to close/reopen and to see confirmations applied, `ops-plan:update` for the programme, `ops-plan:read` for the register.

---

## 4. The interface

### 4.1 The report workspace — figure 01

| Today | After |
| --- | --- |
| A full-screen `PanelDialog` (94 vh) opened **from** the register, holding a 3-tab shell | The **existing route** `/operations/reports/:id` becomes the working surface (it already renders outside the register); the dialog is kept for a read-only peek |
| 22 columns, ~3,450 px, horizontal scroll | **9 columns, 1,050 px**: #, time, duration, activity, **sequence · hours left**, **line ÷ code plan**, allocation, state, ⋯ |
| Every field in a modal of ~60 controls | A **persistent inspector rail**: 6 field pairs (classification, placement, responsibility, progress, hours, programme) + note, always visible, never scrolling on its own |
| Totals as 5 chips above the grid | A pinned **action strip** with the same numbers and the assignment actions, plus a pinned footer |
| Sequence assignment is a separate dialog | The sequence is edited **in the inspector**, with the budget shown live; the bulk picker (figure 02) is for many lines |
| In-progress state shown only as a sentence in the hours dialog | The rail carries **“after this line”** — the sequence’s hours including this line — and the **programme outcome** (outcome, schedule position, unplanned / released / SP) |

Compaction rules, so the review is not a matter of taste:

- **No information is lost**: the block dialog’s **25 editable fields** are each accounted for in **Appendix C** — **13 visible in the rail** (seven field pairs), **10 one disclosure below it** in the same rail (“More fields”), and **2 in the grid** as an inline time popover. Every action button survives, in the action strip or the row’s ⋯ menu.
- **One scroll region per surface**: the grid scrolls; the header, strip, footer and the first screen of the rail are pinned. The assignment picker is a popover anchored to the sequence cell, not a dialog; skip / close / split open **in the rail** and replace its content, with a back link — never a second scrollbar. The live-verified check is *“at 1440 × 900 with nine lines, the report editor shows at most one scrollable area.”*
- **Two rules keep the grid honest** and are visible in figure 01. The **“hours left”** under the sequence is the **code’s** balance, not this line’s. The **“line ÷ code plan”** cell is this row’s own hours against the code’s budget (3.500 / 8.000) — never the code’s verdict, which belongs to the code (G8) and appears once, in the rail.
- **Tokens only**: navy (`brand[700]`) for action, brass for logged, status tones for state. No new colours, radii, type sizes or motion; all from `frontend/src/designSystem.ts`.
- **Accessibility kept**: labels on every field, `aria-label` on the ⋯ menu, focus ring, 44 px hit areas under `pointer: coarse`, warnings as `role="alert"` beside the data, and an unsaved-changes guard on the route.

### 4.2 Assignment with the budget visible — figure 02

The picker lists programme lines grouped by phase, **open lines first**, with five numbers per row: budget, logged, **left before**, **this line**, and — for the row under the pointer — **left after** if the assignment is applied. Each row carries a mini budget bar, so “nearly spent” is visible before the digits are read. An overrun turns the “after” cell red and says so in words (“would overrun by 0.500 h”). Skipped and finished codes are visible but disabled with the reason (“skipped — 3.000 h released”, “finished — reopen it first”). The footer restates the arithmetic before the write: *“Sequence 12 · 8.000 h planned · 6.500 h logged · this line 2.000 h → 8.500 h, 0.500 h over plan.”*

The bulk “Assign criteria” dialog is compacted from 9 stacked fields into 3 steps (What · Where · Preview) with the same preview-before-write behaviour it has today.

### 4.3 The programme — figure 03 (strip on the left, skip form on the right)

`Plans & timeline` keeps its register but gains a **programme strip** (finish marks, skipped hatch, today line) above it, because a table cannot show “4 planned, 3 done, 1 skipped” at a glance. The register keeps state, progress, remaining and outcome; the **cumulative days** column shows `saved (effective)` only where they differ.

Skip and close open a **three-option form** (figure 03 right) instead of a one-line text box; each option shows its own effect on the three numbers before the button is pressed. Close gains the same treatment: the form prints `planned − logged`, in hours and days, and the words the outcome will use.

### 4.4 The reports register — figure 05

The register gains a second view, **“By programme activity”**, default for a well/scope with a baseline: one row per sequence (budget, logged, left, outcome, state), a row for unplanned, and a totals strip showing sequence outcome and schedule position side by side. The existing flat register stays for header data and is still the export surface. Same `DataTable`: search, advanced + date filters, 20/50/100, CSV/XLSX/PDF, checked-row export.

---

## 5. Backend changes

### 5.1 One additive migration

`backend/alembic/versions/…_well_operations_sequence_budget.py` (revision after the current head; downgrade drops what it adds):

| Table | Column | Type / default | Why |
| --- | --- | --- | --- |
| `ops_plan_items` | `skip_disposition` | `String(24)`, `''` | §3.4 — A / B / C |
| `ops_plan_items` | `skip_relief_item_id` | `String(36)` FK → `ops_plan_items.id` `ON DELETE SET NULL`, nullable | B’s receiving sequence, for audit and re-display |
| `ops_settings` | `sequence_auto_confirm_overrun` | `Boolean`, `true` | §3.3 |
| `ops_settings` | `sequence_lag_provenance` | `String(12)`, `'shown'` (`shown`/`hidden`) | whether the SP/NPT/UPA split is printed beside the outcome |

No JSON column, no change to existing columns, no data migration. Three-decimal precision and the tenant/soft-delete/audit conventions are inherited.

### 5.2 The domain (`backend/app/domain/operations/sequence.py`) — still pure

- `PlanRow` gains `skip_disposition`, `skip_relief_item_id`.
- `CodeRow` gains `overrun_hours`, `balance_hours` (signed left), `slow_progress_hours`, `auto_confirmed` (bool + source), so pages never re-derive arithmetic.
- `_state()` gains the **overrun auto-confirm** branch: `overrun_open` → `complete` when the code’s hours come only from confirmed reports and the workspace policy is on; `close_source = "system-overrun"`.
- `Totals` gains `slow_progress_hours`, `planned_released`, and `outcome_basis` (a small enum: `finished_codes` / `plus_released` / `npt_excluded` / `uncoded_excluded`) so a printed number always states its rule. NPT and UPA totals already live on `UnplannedRow` (`npt_hours`, `upa_hours`) and are not duplicated on `Totals`.
- `UnplannedRow` gains `sp_hours`.
- Skip findings: a code with disposition C and hours still coded is a finding (`hours_on_skipped_activity`, already present, extended to name the disposition).

### 5.3 The services

| Function | Change |
| --- | --- |
| `seq_codes.report_codes()` / new `budget()` | Return **per open code**: `planned, logged, left, projected_left, state, lines_today`; the projected figure is this report’s uncommitted selection. One query set, cached per (baseline, report). |
| `seq_codes.set_item_state()` | Accept `disposition`; today’s 409 becomes **A’s precondition** instead of the only path. B re-codes the chosen lines (via `timeline_plan_item_id` and the split rows in `OpsActivityBlockCode`, whichever holds the link) onto the named receiver and re-runs `_recompute_baseline()` once for both codes; C clears the code, writes `timeline_split_state = 'unplanned-only'` and records the decision; all three audited with the disposition in the summary. |
| `seq_codes.close_item()` | Unchanged rules; adds the computed preview to the response (`planned`, `logged`, `variance`, `days`, `provenance`). |
| `reports.submit_report()` | After the report is confirmed, run `seq_codes.auto_confirm_overruns(baseline)` when the policy is on; write `close_source="system-overrun"` + the report id; one audit entry per code, not per line. |
| `reports._recompute_baseline()` / `review_timeline()` | **Stop writing the code-wide variance onto every line** (G8, two write sites: 549–552 and 1416): keep the verdict on the code (`ops_plan_items` already holds state) and write the **line’s own contribution** on the block (`timeline_contribution_hours`, hours only, display). The row then reads “of this code’s +3.500 h”, never “lead 3.500 h” three times. |
| `reports._compute_metrics()` | Write `pt_minutes` and `sp_minutes` (G13); add `outcome_days` and `slow_progress_minutes` to the daily metric. |
| `reports._CODE_ITEM_CACHE` | Move to a per-session cache or key it on `baseline.updated_at` (G14). |
| `seq_codes.timeline_rollup()` | Add `budget` block per code and the three provenance buckets to `totals`; keep every existing key. |

### 5.4 Endpoints (all under `/api/v1/operations`)

| Method | Path | State | Permission |
| --- | --- | --- | --- |
| GET | `/reports/{id}/timeline-codes` | **extended** with budget fields | `ops-report:read` |
| POST | `/reports/timeline-codes/preview` | **extended**: per-line `left_before`/`left_after` | `ops-report:update` |
| POST | `/reports/timeline-codes/apply` \| `/split` \| `/clear` | unchanged | `ops-report:update` |
| POST | `/plans/{id}/items/{item_id}/state` | **extended** with `disposition`, `relief_item_id`, `block_ids` | `ops-plan:update` |
| POST | `/plans/{id}/items/{item_id}/close` \| `/reopen` | unchanged behaviour | `ops-plan:update` + `ops-report:review` |
| GET | `/plans/{id}/timeline-rollup` | **extended** with provenance + budget | `ops-plan:read` |
| GET | `/reports/summary?group=sequence&well=&scope=` | **new**, additive | `ops-report:read` |

No permission is renamed or widened; no route changes behaviour for an existing client.

### 5.5 Frontend files

| File | Work |
| --- | --- |
| `pages/operations/ReportDetail.tsx` (2,077 lines) | Split into `ReportDetail.tsx` (loads, guards, save/submit — keeps its current props) + `components/operations/report/ActivityGrid.tsx`, `RowInspector.tsx`, `AssignmentPopover.tsx`, `ProgrammeRail.tsx`, `ReportHeaderSections.tsx`. The dialog keeps a read-only mode. |
| `components/operations/TimelineHoursReview.tsx` | Read the **code-wide** figures from the server (G3); show provenance; no local sums in the verdict. |
| `components/operations/SeqCodeDialog.tsx` | Replaced by `AssignmentPopover` + the bulk variant; the split editor moves inside it. |
| `components/operations/TimelineEditor.tsx` | Keep; the 48 vh internal scroll becomes a full-height region. |
| `pages/operations/Plans.tsx` | Programme strip component; skip/close forms with dispositions. |
| `pages/operations/Reports.tsx` | Grouped view (`ReportSequenceSummary.tsx`). |
| `pages/operations/Settings.tsx` | Two new switches + the disposition default, in the existing “Lead and lag” section. |
| `lib/operations.ts` | Types for the new fields; no endpoint renamed. |
| `api/operations.py` `_block_out()` | Add `timeline_split_state` and the code’s resolved budget (`left_before`, `left_after` for the current line) so the grid and inspector need no client-side arithmetic (G16). |

No new design tokens; the only new primitive is a **segmented control**, which the design system already documents (the consumable category picker) — re-used, not re-invented.

---

## 6. Implementation phases

| Phase | Content | Files | Exit condition |
| --- | --- | --- | --- |
| **P0 — arithmetic** | Domain budget/provenance fields, overrun auto-confirm, metrics fix, cache fix; no UI | `domain/operations/sequence.py`, `services/operations/{reports,seq_codes}.py`, `schemas/operations.py` | The three acceptance scenarios of §7 pass as service-level examples with the exact numbers printed |
| **P1 — schema** | The one migration in §5.1 + model columns | `models/operations.py`, one Alembic revision | `alembic upgrade head` / `downgrade -1` clean on SQLite and PostgreSQL |
| **P2 — assignment** | Budget endpoint, popover, split inside it, bulk dialog compaction | `seq_codes.py`, `api/operations.py`, `AssignmentPopover.tsx`, `BulkAssignDialog.tsx` | A line cannot be assigned without the hours-left arithmetic on screen; two lines of one code never both print the code’s verdict |
| **P3 — workspace** | The route, grid, inspector, rail, sections; keep the dialog read-only | `ReportDetail.tsx` split + `report/*` components | 9 columns, 1 scroll region, every field and action reachable; keyboard and theme pass |
| **P4 — programme** | Strip, dispositions, close preview | `Plans.tsx`, `set_item_state` | All three skip dispositions demonstrable on a draft plan |
| **P5 — register** | Grouped reports view, totals strip | `Reports.tsx`, `reports/summary` | The month reads without opening a report; exports unchanged |

Each phase is independently shippable; P0+P1 can go first and change no screen.

---

## 7. Acceptance criteria

Numbered so they can be ticked, and each one is a test we will write in the phase that lands it (not yet run — user instruction):

1. **Carry-forward (R2).** Seq 12 at 8.000 h: 3.000 h line → left 5.000; 4.000 h line → left 1.000. Assigning the next line to seq 14 leaves seq 12 at **1.000 h left**; nothing is silently moved.
2. **Lead on close (R3).** Seq 12 closed at 7.000 h → outcome **+1.000 h = +0.042 d**, printed as lead.
3. **Lag without NPT/UPA (R5).** A 10.000 h planned activity closed at 12.000 h with allocation PT → **−2.000 h = −0.083 d**, no NPT, no UPA, no cause required. Flagging the 2.000 h as SP changes the label to “slow progress”, **not** the size.
4. **No double count.** SP + overrun on one code counts once in `totals.realised_variance`; the buckets sum to the lag (`planned overrun + SP + NPT + UPA = total lag`) in every fixture.
5. **Skip A.** 8.000 h released; `planned_in_scope` −8.000; `planned_saved` +8.000; every later code’s effective cumulative days moves **0.333 d** earlier; the saved baseline is unchanged.
6. **Skip B.** Release + the receiving code’s logged rises by the transferred hours; the receiver may become `overrun_open` from a legal transfer.
7. **Skip C.** Release + the chosen lines become unplanned; the outcome falls by their hours ÷ 24; NPT/UPA only where allocated.
8. **Assignment budget.** The picker shows `left_before` and `left_after`; an overrun is red and worded; a skipped/finished code is disabled with its reason.
9. **One verdict per code.** Two lines of one code print “of this code’s +3.500 h” each; neither prints a verdict of its own; the review dialog equals the programme register to three decimals.
10. **Submission.** With auto-confirm on, submitting a report whose lines overrun a code closes that code with `close_source = "system-overrun"` and one audit entry; with it off, the code stays open and the readiness checklist says so **before** submit.
11. **Nothing signed moves.** Drafts never change confirmed totals; reopening withdraws a verdict and keeps the hours.
12. **Compaction.** No route, permission, filter, pagination option, import/export path or dialog rule changes; `make ui-check` and the light/dark pass hold; no page-level horizontal scroll at 1440 / 1024 / 768.

---

## 8. Decisions I need from you

| # | Decision | Options | My recommendation |
| --- | --- | --- | --- |
| **D1** | Wording | (a) keep “sequence variance” everywhere; (b) rename the printed figure to **“sequence outcome”** and skipped effects to “released/credited” | **(b)** — three numbers with three names is the cure for G7 |
| **D2** | Auto-confirm an overrun on submit | (a) **on by default**; (b) off, and only *suggest* on the report; (c) as today: only manual close in Plans | **(a)** with a workspace switch — an open code means the month has no verdict (G4) |
| **D3** | Skip default disposition | (a) **A — not needed**; (b) C — time still counts; (c) ask every time with no default | **(c)** for the first release on a live well, with A pre-selected; the form always shows all three (§4.3) |
| **D4** | Slow progress storage | (a) **SP stays a line allocation**, surfaced as lag provenance; (b) also store a `lag_class` on the programme row | **(a)** — one owner for the fact; no schema for a label |
| **D5** | Report editor as a route | (a) **route + read-only dialog**; (b) keep everything in the dialog and compact inside it | **(a)** — a dialog cannot be “full” while the register sits behind it (R6) |

If you approve D1–D5 as recommended, P0–P2 can start on this branch immediately; P3–P5 follow in the same branch with a review point after P3.

---

## 9. Risks, and how they are controlled

| Risk | Control |
| --- | --- |
| Historical months read differently | Nothing is recomputed for submitted/approved reports beyond the fields they already carry; auto-confirm only fires on future submits; the release/outcome wording is a display change |
| A disposition is mis-clicked | Reversible (un-skip clears it); audited with reason; B names its receiver in the audit and on the row |
| Sequence assignment gets faster and therefore sloppier | The budget must be on screen before the write; overruns are labelled; the `sequence_require_code_on_submit` switch is unchanged |
| Performance of the grouped register | One aggregate query per well/scope; if it is slow on a real dataset, the cached `timeline_*` columns are already there and P5 falls back to them without a schema change |
| Editor rewrite regresses a rule | The block rules (`requirements.py`), submit checklist and `reports.save_report()` validation are **not** touched; the rewrite moves presentation only, and the phases keep the old dialog until the new one is complete |

---

## 10. Deliberately not in this scope

- Extraction, documents, surveys, well path, analytics charts.
- Costing integration in any direction.
- Rewriting the saved baseline curve.
- New permissions or tenancy changes.
- PDF layout of the report print (only its figures’ labels change).

---

## Appendix A — where each defect lives

`G1` `SeqCodeDialog.tsx` (`stateSentence`, ~line 57) · `G2` `ReportDetail.tsx` 992–1026 · `G3` `TimelineHoursReview.tsx` 195–260 vs `reports.py` `_ledger` · `G4` `reports.py` `submit_refusals` 1511–1615 · `G5` `seq_codes.py` 552–585 · `G6` `sequence.py` 64, 537–560 · `G7` `Overview.tsx` 199–201 vs `Plans.tsx` 680–710 · `G8` `reports.py` 549–552, 1416 · `G9` `ReportDetail.tsx` 884–1046 (22 headers; Σ minWidth = 3,450 px) · `G10` `ReportDetail.tsx` 612, 1464–1506 · `G11` `Plans.tsx` 541 · `G12` `Reports.tsx` 165–194 · `G13` `reports.py` 677–741 · `G14` `reports.py` 334 · `G15` `ReportDetail.tsx` 116, 481–526, 1557–1931 · `G16` `api/operations.py` `_block_out()` · `G17` `domain/operations/requirements.py` `describe_missing` + `reports.py` `submit_refusals`.

## Appendix B — how the figures were made

`docs/reviews/well-operations-figures/_generate_mockups.py` (Pillow, light-theme tokens from `designSystem.ts`, DejaVu Sans). Re-run it to regenerate the PNGs; it deliberately contains no product logic, only layout.

---

## Appendix C — field-by-field accounting for the compaction (R6)

The block dialog today holds **25 editable fields** plus 5 read-only facts (`ReportDetail.tsx` 1557–1931). Figure 01 shows 12 of them; this table says where all 25 live afterwards, so “nothing was lost” can be checked field by field.

| # | Field today | After | Where |
| --- | --- | --- | --- |
| 1 | Activity | same control | Rail, Line tab, pair 1 |
| 2 | Allocation (PT / NPT / UPA / SP) | same control | Rail, Line tab, pair 1 |
| 3 | Hole section | same control | Rail, pair 2 |
| 4 | Phase | same control, still clears an orphaned sub-phase | Rail, pair 2 |
| 5 | Sub-phase | same control | Rail, pair 3 |
| 6 | Cause | same control | Rail, pair 3 |
| 7 | Agency / Service Vendor | same control | Rail, pair 4 |
| 8 | Responsible agency label | same control, still independent of the vendor | Rail, pair 4 |
| 9 | From MD | one combined field | Rail, pair 5 (`2,760 / 2,818`) |
| 10 | To MD | one combined field | Rail, pair 5 |
| 11 | Rotating hours | same control | Rail, pair 6 |
| 12 | ROP (m/h) | same control, still `N/A` for completion scope | Rail, pair 6 |
| 13 | From (WAT) | inline time popover on the grid’s Time cell | Grid, Time column |
| 14 | To (WAT) | same popover; duration recomputed and validated (≤ 1,440 min) | Grid, Time column |
| 15 | Sequence code | split button + picker (**new: budget visible**, G1/G15) — the only field with two entry points: the grid column and the rail | Grid, Sequence column + rail pair 6; the rail also states “after this line” |
| 16 | Operations (operation code) | same control | Rail, **More** |
| 17 | Printed phase token | same control | Rail, **More** |
| 18 | Productive time (checkbox) | same control, same NPT lock | Rail, **More** |
| 19 | NPT / delay reason | same control | Rail, **More** |
| 20 | Activity narrative | same control (multiline) | Rail, **More** |
| 21 | From TVD | same control | Rail, **More** |
| 22 | To TVD | same control | Rail, **More** |
| 23 | Bit depth | same control | Rail, **More** |
| 24 | Mud weight (ppg) | same control | Rail, **More** |
| 25 | Footage (m) | same control | Rail, **More** |
| R1 | Printed codes (read-only) | same text | Rail, **More** |
| R2 | Source (`source_bbox`) | link to the source page | Rail, **More** + ⋯ menu |
| R3 | Evidence (`classification_evidence`) | same text | Rail, **More** |
| R4 | Classification source | same text | Rail, **More** |
| R5 | Confidence | same text | Rail, **More** |
| R6 | Duration (derived) | rail subtitle + grid Duration column | Rail header, Grid |
| — | “Restore logged hours” | same action | Rail, note area |
| — | Review note (`timeline_note`) | same action | Row ⋯ menu |
| — | Split / clear / unplanned | same actions | Row ⋯ menu |
| — | Add / delete line | same actions | Action strip and ⋯ menu |

**Counts:** 13 visible (7 pairs, sequence among them) + 10 under **More** + 2 in the grid (From / To) = 25 editable fields — no field removed, none promoted to a dialog, and **no new scroll container**: **More** expands inside the rail and pushes nothing off screen, and the note area it covers is restored when it collapses.

Two fields move *towards* the user rather than away: the **sequence code** becomes visible in the grid with its budget (it was reachable only from the dialog today, and not even there — G15), and **From / To** become an inline edit on the row the user is already looking at instead of a modal.
