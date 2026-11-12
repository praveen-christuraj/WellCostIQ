# Reusable templates (AFE estimate, well configuration, daily cost sheet)

A template is a **starting point**, not a record. You save the way this workspace
costs a standard well once, then pick it on every new record and change only the
values that differ. Nothing is retyped and no Excel file is needed.

Open **AFE Management → Reusable templates** (`/record-templates`).

## The three kinds

| Kind | Holds | Used on |
|---|---|---|
| AFE estimate template | Service, consumable and tangible lines, each with its charging basis and hole section / phase scope | *AFE cost estimate* → **Use a template** |
| Well configuration template | Hole sections, their phases and planned days | *Rig & Well Management* → **Configure** a well → **Use a template** |
| Daily cost sheet template | The service, drill-bit and tangible lines a rig repeats | *Daily cost sheet* → **Use a template** |

## How it behaves

- **A template never carries a price.** Rates and amounts always come from Master
  Data and from the AFE's locked baseline at the moment the record is priced. A
  price revision can therefore never leave a stale price inside a template.
- **Scope is stored as codes, not ids.** An AFE template written for hole section
  `17-1/2`, phase `DRILL` applies to any well whose plan names the same section
  and phase. Where the plan does not have them, the line is reported as skipped
  rather than guessed at.
- **Applying never saves.** The picker shows exactly what will be added and what
  is missing, then fills the editor. You still review and press Save, so every
  existing rule — validation, rate locks, audit — runs as usual.
- **Unavailable lines are visible, not silent.** If a service is later deleted
  from Master Data, the template still opens and marks that line unavailable; it
  is skipped with a warning and the template keeps working.
- **Private or shared.** A template is private to its owner unless **Share with
  the whole workspace** is ticked. Other users can read and use a shared template
  but must **Copy** it to change it. Sharing never crosses a workspace boundary.
- **Edits are safe.** Updating a template changes what *future* records start
  from. AFEs, well plans and daily sheets already created are untouched. Deleting
  a template moves it to deleted entries and affects nothing already created.

Every create, update, delete, copy, export and apply is written to the audit
trail, including how many lines each template holds.

## Related: bulk price revision

Master Data → Tangibles / Consumables → **Bulk price revision** downloads the
current price list, so an operator edits only the prices that moved and uploads
the same file back. The batch is all-or-nothing: a row that names an unknown or
duplicate code rejects the whole file and lists every bad row, so one upload
either revises every price or none of them. Each revised item keeps its own
revision history and reason.

## Exporting the library

**Export library** writes one row per line for the selected tab:
`template, kind, scope, line_type, section_code, from_depth, to_depth,
phase_code, days, item_code, item_name, quantity, currency, amount, remarks`.
Every row can be read on its own — a service keeps its own code and amount, a
consumable keeps its own code, quantity and estimated amount, and a well plan
keeps its section depths and phase days — so the file can be reviewed or costed
outside the app without guessing which column belongs to which kind of line.
Depths are written as typed (`0`, `1200`), never as `0E-10` or `1200.0000000000`.

## Permissions

`template:read` is enough to browse and apply a template, and it is what the
pickers need. `template:create`, `template:update`, `template:delete` and
`template:export` gate authoring, copying, deleting and the CSV export of the
library (including its usage audit). A workspace owner always has all five; any
other role receives them only when an administrator assigns them in
**Administration → Roles**, so an estimator can be allowed to use templates
without being allowed to rewrite them.

## Verification

`make templates-check` renders the library page and the picker in a DOM and
asserts the behaviour described above: an incomplete template is refused before
it reaches the API, the picker lists every line and marks the unavailable ones
before anything is applied, confirming is the only way a template reaches a
record, an empty library points at **Manage templates**, and a shared template
can be copied but not edited or deleted by the person it was shared with.
`backend/tests/test_record_templates.py` covers the same contract server-side,
including that applying a template bumps its use count, writes an `apply` audit
entry, and never creates an AFE by itself.

`make catalogue-check` covers the bulk-revision dialog and the catalogue tables:
every type shows a **Description** column, the dialog names exactly which codes
change before anything is uploaded, it cannot run on a file alone or on a reason
shorter than three characters, and when the server refuses a batch the message
stays on screen saying no price was changed.
