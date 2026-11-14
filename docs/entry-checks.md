# Entry checks on the daily cost sheet

A daily cost sheet is keyed by hand, every day. The entry checks read each sheet the
way a careful colleague would and point out a value that looks mistyped: one zero too
many, 24 entered as days instead of hours, feet entered as metres, an exchange rate
entered the other way round, the same line entered twice.

Three properties hold everywhere and are covered by tests:

- **Advice only.** A check never stops a save or a submission and never changes a
  figure by itself. A failure inside the checks returns "no findings"; the sheet, its
  preview and its totals are unaffected.
- **Explainable.** Every finding quotes the figures it was derived from and what it
  was compared with. The same sheet and history always produce the same findings.
- **No model, no new dependency.** It is arithmetic over the workspace's own sheets:
  medians and spreads from the Python standard library. Nothing leaves the server and
  nothing is read across a workspace boundary.

## What the user sees

**On the sheet** (`/daily-cost/entries/{id}`), an **Entry checks** section sits above
the Services table, directly under the unsaved-changes notice.

- The heading carries the counts as tags: **N to check** (probable slips), **N to
  note** (unusual, no slip recognised), **N kept as entered**, or **Nothing unusual**.
  Beside them the section says whether it describes *your unsaved changes* or *the
  saved sheet*.
- Each check shows a title, one sentence with the figures, the basis ("The 12 nearest
  sheets of this AFE usually carry 6 MT each (most between 5 MT and 8 MT).") and the
  lines concerned. On a Draft the line names are buttons that open the line editor.
- **Apply <value>** writes the suggested value into the *unsaved* sheet. The user
  still reviews the preview and saves. A suggestion that no longer matches the sheet
  (the line was edited or removed meanwhile) is refused and says so.
- **Keep as entered** records that the value is right. It is offered on a saved Draft
  only, asks for an optional note (300 characters), and is written to the audit log
  with the user's name. It accepts that exact value: when the value changes, the check
  is open again.
- **Reopen** withdraws a "kept as entered" decision while the sheet is a Draft.
- While the page is recalculating, the buttons wait: nobody acts on a finding that
  describes an earlier state of the sheet.
- The **Submit** dialog names the open checks. They do not stop the submission.
- A submitted sheet still shows its checks, read-only.

**On the well cost analysis page**, an **Entry checks** card lists the sheets of the
well that still carry an open check, newest first, each linking to its sheet. It
covers every sheet of the well whatever period or draft filter is chosen on the page
(the newest 120 sheets when a well has more).

## What is checked

| Code | Raised when | Offers |
| --- | --- | --- |
| `unusual-quantity` | The day's quantity of an item is far from what that item usually carries on a sheet. All lines of one item on the sheet are added first, so splitting a day over several activities is not a finding. | The corrected quantity, or the other unit (hours ↔ days) when the figure is right and the unit is wrong |
| `more-than-a-day` | A Day Rate line carries more than one day and the item has no history yet. `24 days` is a warning; anything else is a note. | Change the unit to hours |
| `unusual-rate` | A daily rate override is far from the rate locked for that line. Without a locked rate (an unplanned line) it is compared with the rates the item was priced at before, in the same currency. | The corrected rate |
| `unusual-fx` | A line's exchange rate disagrees with **both** the AFE estimate rate and the other sheets of the AFE. | The corrected rate, applied to every line using it |
| `fx-inconsistent` | One currency is converted at two rates more than 2% apart on the same sheet, and neither was flagged above. | The rate most lines use |
| `unusual-sheet-fx` | The sheet's own conversion from its standard currency to USD disagrees with the estimate and the other sheets. | The corrected rate |
| `depth-outside-plan` | An actual depth is outside its planned section (or the planned well) by more than 5% of the section length, at least 15 m, and does not continue the depth of a neighbouring sheet. | The other unit (m ↔ ft), or the depth ×10 / ÷10, when that puts it inside |
| `depth-decreased` | The depth of a drilling section is more than 1 m shallower than the nearest earlier sheet recorded. Always a warning. | As above |
| `depth-ahead` | The depth is deeper than the nearest later sheet recorded (a sheet entered late, out of order). | As above |
| `duplicate-line` | Two consumable, tangible or other-expense lines carry the same item, scope, quantity and rate (for other expenses, also the same description). Always a warning. | — (remove the extra line) |
| `usual-line-missing` | An item was on each of the 5 preceding sheets and is not on this one. A note. | — |
| `unusual-day-total` | The day costs at least 4 times the usual and no single line was already flagged as the reason. A note; it names the largest line when that line is half the day or more. | — |

Deliberately not checked: one-time charges (Mobilization, Demobilization, Fixed
Charge) by quantity, because their quantity is not what prices them; lines priced
from itemised amounts by rate; depth order on Completion AFEs, where work visits
depths in any order; and a repeated service line, which the sheet itself already
refuses.

A wrong exchange rate produces one finding, not two: a rate override on a line whose
exchange rate is itself in doubt is not also reported as an unusual rate.

## How "unusual" is decided

**What a value is compared with.** The nearest 30 other sheets of the same AFE and
well, before or after the sheet's date (`ENTRY_CHECK_HISTORY_SHEETS`). Deleted sheets
do not count; Draft and Submitted sheets both do. An item needs **5** values on
those sheets before any opinion is given. Below that, the item's **workspace
profile** is used instead: the same item on every well of the same workspace over
the last 730 days (its newest 120 values). The basis sentence always says which of
the two was used, and on how many sheets and wells it rests.

**The profile** of an item is its median and its spread, measured on a ratio scale so
that "ten times too much" and "a tenth of the usual" are treated alike. The spread is
the larger of two robust estimates (the median absolute deviation, and the observed
range with the one-in-eight most extreme values set aside), so an earlier mistake in
the history does not hide the next one, and an item that genuinely varies a lot is
given room. It is never taken as smaller than about 12%, and it is widened for a
short history: twice as wide at five values, 1.4 times at eight, 1.1 times at twenty.

**A note** needs a value at least **2.5 times** away from the median *and* at least
3.5 spreads away. **A warning** needs either a keying slip that explains the value
(below) at 4 spreads or more, or a value at least 5 times away and 6 spreads out.

**Keying slips.** When a value is that far out, a short list of slips is tried; when
one of them turns it into a usual value, that value is offered:

- one, two or three zeros too many or too few (or the decimal point moved);
- a digit keyed twice (`66` for `6`); two neighbouring digits swapped;
- hours entered as days, or days as hours, on Day Rate lines;
- feet entered as metres, or metres as feet, on depths;
- an exchange rate entered the other way round (`1540` for `0.00065`).

A digit-level correction must reproduce the item's recurring value or land within 5%
of the usual value, because such corrections are otherwise easy to find by accident.
When two slips fit, the one that reproduces the item's recurring value wins; failing
that, the more frequent kind wins (one zero before a doubled digit) and closeness
decides between two of the same kind.

**Against a single reference** (a locked rate, an AFE estimate rate) there is no
spread to measure, so plain ratios decide: 3 times away is a note; a recognised slip
or 20 times away is a warning. An exchange rate within 2.5 times of the estimate *or*
of the other sheets is silent, so a currency that moved since the estimate was made
raises nothing.

The constants are named and commented at the top of
`backend/app/domain/entry_statistics.py` and `backend/app/domain/entry_rules.py`.

## What it catches, and what it does not

`make entry-checks-simulation` measures this (4,000 seeded trials per cell, standard
library only, about a minute; the same code always prints the same two tables). An
item is given a usual level and a day-to-day spread, `n` earlier values are drawn,
and a fresh value is judged once as keyed correctly and again after each slip. Every
figure below is read from that output.

**Detection.** "Flagged" counts warnings and notes together.

| Day-to-day variation of the item | Earlier values | ×10 slip flagged | ×100 slip flagged | Correct value flagged |
| --- | --- | --- | --- | --- |
| None (the same value every day) | 5 or more | 100% | 100% | 0% |
| About ±10% | 5 or more | 100% | 100% | 0% |
| About ±30% | 5 | 56% | 98% | 0% |
| About ±30% | 8 | 93% | 100% | 0.05% |
| About ±30% | 20 | 99.7% | 100% | 0.15% |
| Routinely doubles or halves | 5 | 11% | 55% | 0.2% |
| Routinely doubles or halves | 8 | 36% | 93% | 0.25% |
| Routinely doubles or halves | 20 | 51% | 99.6% | 0.3% |

- On steady items (a rig day rate, a fixed crew, a standard daily consumption) every
  order-of-magnitude slip is caught.
- On items that vary, a ×10 slip is caught reliably only once the item has about
  eight earlier values. An item that routinely doubles or halves cannot have a ×10
  slip told apart from a busy day; a ×100 slip is still caught.
- A correct value is flagged at most about once in 300 values on these items (once
  in 180 on items that vary by several times from day to day), and not once on
  steady items in this simulation.

**The offered correction.** A correction is offered only when one of the slips above
turns the value into a usual one; otherwise the value is pointed out without a
suggestion (about one flagged decimal slip in eight on items that vary ±30%). When a
correction is offered, this is how often it is the value that was meant:

| Slip that was made | Steady | Varies ±10% | Varies ±30% | Doubles or halves | Varies by several times |
| --- | --- | --- | --- | --- | --- |
| One zero (×10, ÷10) | 100% | 100% | 100% | 96% | 50% |
| Two zeros (×100) | 100% | 100% | 100% | 96% | 85% |
| Three zeros, or a unit (×1000) | 100% | 100% | 99.8% | 90% | 70% |
| A digit keyed twice | 100% | 19% | 17% | 18% | 10% |
| Two digits swapped | 80% | 64% | 22% | 9% | 5% |

- **Zeros and decimal points** are corrected reliably, except on an item whose daily
  figure itself varies by several times: there the history cannot tell one zero from
  two, and no rule could.
- **A digit keyed twice** on an item that varies is flagged, but the figure offered
  is usually not the intended one: `1123` keyed for `123` reads equally well as
  `112.3` with the decimal point dropped, and the more frequent slip is assumed. The
  figure offered is within 10% of the intended one in about 9 cases in 10 (94%, 91%
  and 87% in the three middle columns), so it is close, but it is not right.
- **Swapped digits** are recognised only on steady items. Elsewhere the rare
  suggestion is a decimal reading that happens to fit, and it is usually wrong.
- The same holds for a mistake that is not on the list at all: on an item that
  varies, it can be given a "one zero too many" reading by accident.

So: the sentence of a check names the slip it assumed and the button shows the figure
it will write. Read both. Applying only edits the unsaved sheet; the preview then
judges the new value, and nothing is saved until the user saves.

**Not caught at all:** a slip that stays inside the usual range. One wrong digit (`6`
for `8`), most swapped digits (`57` for `75`), a doubled digit that changes the value
by less than 2.5 times (`0.55` for `0.5`), a value keyed on the wrong line, a wrong
date. The checks remove a class of mistakes; they do not replace the review before
submission.

## Keeping a value as entered

A decision is stored in `daily_cost_check_reviews`: one typed row per sheet and
finding, with the finding's fingerprint (a hash of the exact value judged), what was
kept, the optional note, who and when.

- Only a finding that the **saved** sheet still carries, with the value the user saw,
  can be kept. Anything else is answered with **409** and the instruction to save and
  refresh. The stored row therefore always describes the ledger, never what a client
  sent.
- Draft sheets only (**409** otherwise): a submitted sheet is frozen, reviews
  included, until it is reopened through the usual workflow.
- Both actions are audited as `update` on `daily_cost`, with the values kept or
  reopened and the note in the summary.
- When the value changes, the fingerprint no longer matches and the finding is open
  again. The old row is replaced the next time the finding is kept.
- Rows are removed with their sheet (`ON DELETE CASCADE`).

## API

All under `/api/v1/daily-cost`, tenant-scoped like every other route. No new
capability was added: reading uses `daily-cost:read`, deciding uses
`daily-cost:update`.

| Route | Capability | Answer |
| --- | --- | --- |
| `PUT /entries/{id}/preview` | `daily-cost:read` (unchanged) | The existing preview gains `entry_checks`: the findings for the unsaved state |
| `GET /entries/{id}/checks` | `daily-cost:read` | `entry_id`, `enabled`, `checks[]`, `open_warnings`, `open_notices`, `reviewed`, `history_sheets` for the saved state |
| `POST /entries/{id}/checks/review` | `daily-cost:update` | Body `{items: [{key, fingerprint}], note}`; keeps the values as entered |
| `POST /entries/{id}/checks/reopen` | `daily-cost:update` | Body `{keys: []}`; withdraws those decisions |
| `GET /wells/{well_id}/checks?afe_id=` | `daily-cost:read` | Every sheet of the well with a finding: `sheets[]`, totals, `sheets_checked`, `truncated` |

A finding carries `key`, `code`, `severity` (`warning` or `info`), `title`, `message`,
`basis`, `scope` (`afe`, `workspace`, `baseline`, `plan` or `sheet`), `subject_label`,
`lines[{group, index}]`, `field`, `current_value`, `current_display`,
`suggested_value`, `suggested_display`, `apply_to[]`, `usual_display`,
`history_count`, `fingerprint`, and the review (`reviewed`, `reviewed_by`,
`reviewed_at`, `review_note`).

The API contract is **0.10.0**; the frontend requires it, so a browser tab older than
the deployed API says so instead of showing a sheet without its checks.

## Storage and migration

Revision `b7d3e9f25a41` (after `a2c5d8f14b30`) adds two tables and changes no existing
row:

- `daily_cost_check_reviews`: the decisions above. Unique on
  (`entry_id`, `check_key`); removed with their sheet.
- `daily_cost_item_profiles`: the workspace profiles. One typed row per item, way of
  charging, metric (quantity or rate) and unit: the sample count, how many wells it
  spans, median, spread, usual range, recurring value, the last date observed and
  when it was rebuilt. No JSON is stored.

Both carry `organization_id` and cascade with their workspace; both appear in the
Database Browser under Daily Cost Management. `alembic downgrade a2c5d8f14b30` drops
them and loses only the decisions and the cached profiles.

**Workspace profiles are a cache, rebuilt from the ledger, never adjusted in place.**
When a sheet needs a profile that is missing or older than 24 hours, the request
answers with what it has and the rebuild runs after the response, in its own database
session. A deleted or corrected sheet simply stops counting at the next rebuild. The
first sheet of a brand-new AFE may therefore show its workspace-based findings one
preview later than the others.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENTRY_CHECKS_ENABLED` | `true` | `false` removes the section from the sheet and the card from the well page; the preview returns no findings and the review routes answer 409 |
| `ENTRY_CHECK_HISTORY_SHEETS` | `30` (5-120) | How many neighbouring sheets a sheet is compared with |
| `ENTRY_CHECK_PROFILE_WINDOW_DAYS` | `730` (30-3650) | How far back the workspace profiles look |
| `ENTRY_CHECK_PROFILE_MAX_AGE_HOURS` | `24` (1-720) | How old a workspace profile may be before it is rebuilt |

## Cost

Measured in the development sandbox (2 vCPU, synthetic data: 30 history sheets of 63
lines each, requests through the test client, medians of 10-15 calls). Timings moved
by a third between runs on the same code, so read them as indicative, not as a
benchmark of the production host.

| Request | Without checks | With checks |
| --- | --- | --- |
| Sheet preview, SQLite | 233-238 ms | 276-292 ms |
| Sheet preview, PostgreSQL 16 | 418 ms | 455 ms |
| `GET /entries/{id}/checks` | — | 51-60 ms |
| `GET /wells/{id}/checks`, 31 sheets | — | 105-110 ms |
| `GET /wells/{id}/checks`, 120 sheets | — | 390-430 ms |

Across all runs the checks added about 30-60 ms to a preview (9-25%). Almost all of
it is reading the lines of the neighbouring sheets (about 1,900 rows here); the
arithmetic is a few milliseconds. Peak extra memory while a request runs: about
4.5 MB for a preview and 24 MB for the largest well review (120 sheets of 63 lines).
No history is cached between requests. Lowering `ENTRY_CHECK_HISTORY_SHEETS` reduces
the cost on a preview roughly in proportion.

**Why no machine-learning library.** The production host has 512 MB and the API idles
at about 140 MB. Measured in the same sandbox, a gradient-boosting library with its
numeric dependencies adds about 230 MB on disk and about 43 MB of memory on import,
before it has learned anything; the backend lockfile has no numeric package today;
and a model's verdict cannot be explained to the person who keyed the value. A median
and a spread per item need none of that and give every finding a sentence a cost
engineer can check. Should a workspace accumulate thousands of sheets and want
subtler patterns, the decisions recorded in `daily_cost_check_reviews` are the
labelled examples such a model would need.

## Verification

- `backend/tests/test_entry_checks.py`: the statistics (profiles, short histories,
  each keying slip, the early dismissal agreeing with the full measurement), every
  rule on its own, and the API: findings in the preview, a finding never blocking a
  save, keep/reopen with audit entries and lapsing when the value changes, 404 across
  workspaces, 403 without the capability, 409 on submitted sheets and stale findings,
  a new AFE judged by its own workspace and no other, the well review, a failure
  inside the checks leaving the sheet intact, reviews removed with their sheet, and
  the migration applied, reverted and re-applied by revision.
- `make entry-checks-check`: renders the real daily sheet page and the well card
  against a stubbed API: counts, wording, the disclosure, line buttons opening the
  editor, **Apply** editing only the unsaved sheet, the keep dialog and its note,
  **Reopen**, a refused review staying in the dialog with its reason, a submitted
  sheet and a read-only user seeing the checks without actions, every action waiting
  while the findings are out of date, a failed read shown
  inside the section with Retry, the section absent when the checks are turned off,
  the submit dialog, and the well card. The section and the card are then rendered
  under the light and the dark theme and must show the same words and the same
  actions, with colours taken from the design tokens.
- `make entry-checks-simulation`: the detection and correction figures above.
- The backend suite also runs against PostgreSQL with `TEST_DATABASE_URL`.
