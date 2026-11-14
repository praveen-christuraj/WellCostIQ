# The in-application guide

The guide answers two different questions with two different mechanisms, and says
which one produced the answer:

| Question | Source | Example |
| --- | --- | --- |
| How does this application work? | **Memory** — 22 shipped entries, quoted verbatim | "How are actual days calculated?" |
| What does *my* workspace say? | The same services the pages use, under the caller's permissions | "AFE balance on WELL-01" |

There is **no model call anywhere**. The same question always produces the same,
checkable answer, and an administrator can read exactly what the guide is allowed
to say. A question it cannot match is reported as unknown with the list of topics
it does know — it never guesses.

## Where to find it

- **Help & Guide → Ask the guide** (`/assistant`, capability `assistant:read`),
  with the ask box, the answer, outstanding data checks, the caller's own recent
  questions and the full memory.
- **Any page** — the floating button at the bottom right, or `Alt+G`. The drawer
  opens the same service and passes the current route, so that page's memory entry
  ranks first.

## What an answer contains

Every answer is four things, so a figure can always be traced:

- the sentence (memory text, or one computed statement);
- `facts[]` — labelled values, each with a hint, the page that proves it and the
  capability that guards it;
- `steps[]` — the order of work, when the answer is procedural;
- `sources[]` — the pages to open next, plus `follow_ups[]` questions.

`confidence` is `high` for a memory entry matched on its curated keywords, `medium`
for a best match, and `low` when nothing matched. `intent` names what kind of
question it was: `knowledge`, `data_health`, `actual_days`, `cost_position`,
`forecast`, `out_of_scope`, `npt_upa`, `status` or `permission`.

## Permissions

The guide never shows a figure the caller may not read. A caller without a
capability gets `intent: "permission"` and a sentence naming the exact key —
for example `daily-cost:read` — instead of a number or an approximation, and the
data-quality checks only cover the modules that caller can read.

| Capability | What it allows |
| --- | --- |
| `assistant:read` | Ask the guide, read its memory and your own transcript |
| `assistant:manage` | Add, edit and remove **workspace** memory entries (audited) |

## The memory

`SYSTEM_MEMORY` in `backend/app/services/assistant.py` is seeded once per
workspace into `assistant_memory` and is never overwritten by a later release that
changes an entry (a shipped entry is immutable through the API: `PATCH` and
`DELETE` return **409**). It covers four kinds of knowledge:

- **workflow** (`workflow-*`) — the order that makes a well costable, and the
  month-end routine;
- **calculation** (`calc-*`) — actual days, NPT/UPA days, the responsible party,
  the AFE balance, the forecast, out-of-scope cost and LIH treatment;
- **data entry** (`entry-*`) — what a daily sheet, sub-activity, well progress and
  AFE estimate need before they save, and what the entry checks on a daily sheet
  point out (`entry-checks`);
- **navigation and policy** (`nav-*`, `policy-*`) — where each job lives, who may
  do what, deletion rules, unsaved-changes protection, currency and depth rules.

A workspace adds its own entry for a local rule — an approval threshold, a
cost-code convention, a required sign-off. It is matched, quoted and cited exactly
like a shipped entry, it can carry its own required capability, and it is never
visible to another workspace.

## Endpoints

| Method | Path | Capability |
| --- | --- | --- |
| GET | `/api/v1/assistant/overview` | `assistant:read` |
| POST | `/api/v1/assistant/ask` | `assistant:read` |
| GET | `/api/v1/assistant/history` | `assistant:read` (own questions only) |
| GET | `/api/v1/assistant/memory` | `assistant:read` |
| POST | `/api/v1/assistant/memory` | `assistant:manage` |
| PATCH | `/api/v1/assistant/memory/{id}` | `assistant:manage` |
| DELETE | `/api/v1/assistant/memory/{id}` | `assistant:manage` |

`POST /ask` takes `{question, route?}`; `route` is the page the user was on and only
affects ranking. Every memory write is audited with action `create`, `update` or
`delete` on entity `assistant_memory`.

## Rules for contributors

1. **Never add a model call.** If the guide cannot answer, it must say so.
2. **New knowledge goes in `SYSTEM_MEMORY`, not in prose in a handler.** Give it
   `keywords` people actually type, a `route`, and the `permission` a reader needs.
3. **Never compute a figure twice.** Answer from the service the page uses, so the
   guide and the page can never disagree.
4. **Score on keywords and titles, never on the body.** Scoring prose made "who won
   the world cup?" match every entry containing "the".
5. **A refusal is a refusal.** `intent: "permission"` must name the capability and
   carry no figure.

## Verification

- `backend/tests/test_assistant.py` — seeding idempotency, memory-backed answers and
  their routes, the unknown-question fallback, permission gating (including 403 on
  memory creation by a viewer), workspace memory creation and tenant isolation,
  shipped-memory 409, and the per-user transcript.
- `make assistant-check` — 23 jsdom assertions on the answer card: sentence shown
  verbatim, figures with their guarding capability, steps, proving pages, follow-up
  buttons, refusals styled as refusals, unknown answers labelled, no markup
  injection, quick prompts.
- `cd backend && ../.venv/bin/python -m pytest -q`, `cd frontend && npm run build`.
