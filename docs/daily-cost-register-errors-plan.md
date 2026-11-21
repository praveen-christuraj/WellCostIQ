# Daily Cost register — three console errors: root cause and implementation plan

Scope: the three errors seen while adding services to a daily cost sheet.

1. `blob:http://192.168.101.63:8081/…` "was loaded over an insecure connection"
2. `POST /api/v1/operations/reports/{id}/submit` → **422**
3. `PUT /api/v1/daily-cost/entries/{id}/preview` → **500**

Only (3) is an application defect that can be fixed outright. (2) is a
validation answer, not a crash — the plan makes it explainable and unreachable
blind. (1) is a Chromium notice about insecure origins; per your instruction no
HTTPS work is included.

---

## 1. `PUT /daily-cost/entries/{id}/preview` → 500 — a real regression, one file

### Root cause (proved, not inferred)

Commit `6100d3d` *"Group daily service cost items with component detail"*
rewrote `_normalise_service()` to price a service line from a list of locked
AFE components. While rewriting it, **four helper functions were deleted and
their call sites kept**:

```
git show 6100d3d -- backend/app/services/daily_cost.py   # shows "-def …" for all four
```

| helper | still called at | 
|---|---|
| `_service_budgets_for` | `daily_cost.py:1771`, `:1775` |
| `_match_service_budget` | `:1776` |
| `_budget_for_scope` | `:1779` |
| `_weighted_rate` | `:1943` |

An AST scan of every `backend/app/**/*.py` reports unbound call names in exactly
one file (`daily_cost.py`); everything else it lists is a `except … as exc`
binding, not a defect.

Consequences:

* `_normalise_service` is on the path of **every** service line, so adding a
  service raises `NameError` inside `_normalize_payload`.
* `preview_day()` (`daily_cost.py:3523`) has no try/except → FastAPI's generic
  handler in `main.py:279` logs it and returns **500** with a reference id.
  That is the console line the user sees.
* `DailyCostSheet.tsx` sets `previewError` on any failed preview and **disables
  Save** while it is set, so the whole "add a service" workflow is blocked — and
  `save_day()` reaches the same `NameError`, so even a direct save fails.
* `_weighted_rate` is also called from `_normalise_catalogue_line` (`:1943`), so
  drill-bit/tangible consumables are broken by the same omission.

The guard for this already exists and was simply not run:
`backend/tests/test_daily_cost.py::test_scoped_day_rate_allowances_fan_out_once_per_section_and_club_actuals`
(:2230) exercises two section-scoped allowances, two distinct `budget_key`s, the
200.00/600.00 amounts and the 800.00 clubbed row. Its contract is what the
restoration must satisfy.

### Fix

Restore the four functions **verbatim** from `6100d3d^` (they are pure — no
schema, session or model change), inserted after `_budget_by_key` (`:1605`) and
before `_service_rate_or_422`, which is where they lived before the regression:

* `_service_budgets_for(budgets, source_line_id)` — the plain
  `service:<line id>` allowance when the line has a single scope, else every
  `service:<line id>~<scope>` allowance of a fanned-out line.
* `_budget_for_scope(matching, section_id, phase_id)` — the exact
  (section, phase) allowance wins; a single section-only allowance is the
  fallback; anything ambiguous returns `None` so an actual is never clubbed to
  the wrong scope.
* `_match_service_budget(candidates, line, fallback_key)` — resolves a revised
  AFE service back to its original locked allowance only when the scope
  identifies exactly one.
* `_weighted_rate(lines)` — quantity-weighted unit rate for a clubbed allowance,
  falling back to the single unit rate when total quantity is zero.

`Sequence` is already imported (`daily_cost.py:27`); `DailyCostServiceLineIn`
and `DailyCostBaselineBudgetLine` are already imported. No new imports.

### Verification available without pytest

* `python3 -m py_compile` of the module (parses without importing FastAPI).
* Re-run the AST unbound-name scan → `daily_cost.py` must drop out of the list.
* `make daily-cost-check` (jsdom, frontend only) is unaffected but can be run.

The existing pytest test is the real regression guard; per your instruction it
is **not** run here, and it should be run in CI.

---

## 2. `POST /operations/reports/{id}/submit` → 422

### What the 422 actually is

`submit_report()` (`services/operations/reports.py:1489`) is a chain of
deliberate refusals. In order:

1. status not draft/in_review/rejected → **409**
2. no time blocks, and not a measurement-only DMR → 422
3. `extraction_status == "needs_review"`, or any block `review_state` not
   `accepted`/`edited` → 422
4. `Σ block minutes > settings.max_daily_hours × 60` → 422
5. `|Σ block minutes − period_minutes| > completeness_tolerance_minutes` (2) →
   422 `Logged {total} minutes; expected {period}. Correct the log or the report period.`
6. `_validate_blocks()` — a block outside the period → 422, overlapping blocks
   → **409**
7. `describe_missing(block)` — hole section, phase, activity, allocation (plus
   cause for NPT/UPA) → 422
8. NPT/UPA without an Operations code (`require_operations`, default on) → 422
9. NPT/UPA without an agency / reason → 422
10. uncoded blocks when `sequence_require_code_on_submit` is on → 422

Every one of these returns a readable sentence in `detail`, and the page already
renders it (`transition()` → `setError` → `<ErrorMessage/>`). The `422` line in
the browser console is Chrome's own network log entry for a 4xx response — it
will print for *any* refusal, even a correct one.

Note the two settings that look like gates but are **dead** — declared on
`OpsSettings` and never read anywhere in `backend/app`:
`require_review_before_submit`, `allow_block_spill`. Do not expect them to
change submit behaviour.

The most common genuine cause for a hand-built report is (5): the period is a
full 1440-minute day and the engineer has logged only part of it. The gate is
contractual (tests assert 422 for partial logs and for unreviewed blocks), so
loosening it is not the fix.

### Fix — make the gate explainable *before* the request

1. **One source of truth.** Extract steps 2–10 into
   `submit_blockers(db, report, blocks, settings, *, measurement_only) ->
   list[str]` in `services/operations/reports.py`, returning every blocker in
   the order above with today's exact wording. `submit_report()` raises
   `HTTPException(422, "\n".join(blockers))` (or the first, for single-block
   messages) so wording can never drift between the preflight and the refusal.
2. **Preflight endpoint.** `GET /operations/reports/{report_id}/submit-readiness`
   → `{"ready": bool, "blockers": [str, …]}` (`ops-report:read`), thin wrapper
   over `submit_blockers`.
3. **Frontend.** `ReportDetail.tsx`:
   * fetch readiness alongside the report / after every save;
   * render the blockers in a `Caution`/`Alert` beside the toolbar;
   * keep Submit enabled (so the reason is reachable) but show the blocker count
     in the tooltip — or, once the list is empty, enable it and say "Ready to
     submit";
   * on a failed submit, show the whole returned list rather than only the first.
4. **Message fix.** Step 5's message names both figures but not the direction;
   add "over/under by N minutes" so the correction is obvious.

Result: the user either submits successfully or sees a checklist of exactly what
is missing, before the 422 is ever sent.

---

## 3. `blob:…` "was loaded over an insecure connection"

This is emitted by Chromium for object URLs created on an **insecure (http)
origin** — most visibly for downloads/previews. It is a browser notice, not an
application error: the file still renders/downloads. Four places create object
URLs:

* `frontend/src/lib/api.ts:319` — `downloadFile` (a → `link.click()`)
* `frontend/src/lib/api.ts:337` — `previewFile` (opens a tab, navigates it to a
  `blob:` URL)
* `frontend/src/lib/export.ts:48` — CSV/XLSX/template downloads
* `frontend/src/pages/CostIntelligence.tsx:359` — findings CSV

The PDF export path (`reportPdf.ts` → `doc.save()`, `matrixWorkbook.ts` →
`toFile()`) hands off to library code that builds its own blob link, so it
carries the same notice.

There is no way to suppress this notice from application code on an http origin
— Chromium ties it to the origin's scheme. Options:

* **A. Leave it.** Nothing is broken; the notice is cosmetic. (Recommended,
  given "I don't need HTTPS".)
* **B. Remove `blob:` from the two authenticated document flows** by serving
  those bytes from the API over a short-lived, single-use download ticket
  (`HMAC` over path + user + expiry, reusing `core/request_security.py`
  primitives), and navigating the preview tab / download link straight at that
  same-origin URL. The console would then name a normal `/api/…` URL instead of
  a `blob:` one. Touches `core/security.py` plus each download route
  (`operations`, `invoice_processing`, `vendor_master`, `catalogue_items`,
  `backup`, `report_builder`) — the widest of the three changes.
* **C. Narrow B** to the two flows reachable from the Daily Cost / Operations
  pages the user is actually working in.

**No TLS work is included under any option.**

---

## Order of work

1. Restore the four helpers (item 1) — unblocks adding services and saving.
2. `submit_blockers()` + readiness route + editor panel (item 2).
3. Item 3 per your choice (default: no change).
4. `python3 -m py_compile` the touched modules, re-run the AST scan, run
   `make daily-cost-check` and the frontend build locally if `npm ci` succeeds;
   update `.agent/memory/project.md` with the regression and `make graph` after
   the structural change.

No pytest and no `gh` checks, per your instruction.
