# Bandit baseline review — 2026-11-06

CI runs `bandit -r backend/app -l`. Exactly the 20 findings below carry a scoped
`# nosec Bxxx` comment on the reviewed line, with a short justification; there is
no file-wide or global suppression and no `continue-on-error`. Any new or unmarked
finding fails the job. CI separately runs `--ignore-nosec` and uploads the complete
report so these 20 remain visible for review.

Keep each suppression scoped to its exact reviewed line and update this document
with every intentional change. Prefer fixing real findings over adding `nosec`.

## B608 — seven user-facing validation messages, not SQL

Bandit's heuristic interprets strings beginning with “Select” as SQL. Each of
these f-strings is returned in an HTTP/domain validation error and none is passed
to SQLAlchemy `execute`, `text`, a driver cursor or any other query interface.
Values remain ordinary application error text.

| Location | Reviewed purpose |
|---|---|
| `app/api/rig_well.py:401` | Ask the user to select active Master Data. |
| `app/services/afe.py:560` | Missing AFE service validation. |
| `app/services/afe.py:666` | Missing AFE drill-bit validation. |
| `app/services/afe.py:732` | Missing AFE tangible validation. |
| `app/services/catalogue.py:304` | Missing catalogue parent validation. |
| `app/services/catalogue.py:529` | Missing catalogue option validation. |
| `app/services/daily_cost.py:334` | Missing scoped Daily Cost reference validation. |

There is no SQL construction or injection sink at these locations.

## B105 — protocol labels, public errors and a rejected development placeholder

| Location | Why it is not a credential |
|---|---|
| `app/api/auth.py:157,209` | OAuth `token_type: bearer` protocol label; no token value. |
| `app/api/deps.py:24` | Public “Invalid or expired access token” error text. |
| `app/core/config.py:29` | Deliberate development-only placeholder. Production rejects it and non-SQLite non-development configurations require a unique 32+ character key. |
| `app/core/security.py:28` | JWT `type=access` claim discriminator, not a secret. |

## B101 — internal invariants/type narrowing

- `app/schemas/afe.py:28–30` verifies at import that Python constants and their
  `Literal` type definitions remain aligned. These are developer invariants, not
  validation or authorization of attacker-controlled input.
- `app/services/daily_cost.py:1735` is a type-narrowing invariant after the line
  kind has already been selected; persistence rules do not rely on `assert`.
- `app/services/daily_cost.py:3899` proves the date has been populated in the
  branch that needs an end date; it is not an authorization boundary.

Production does not use `python -O`; regardless, no permission or tenant check is
implemented by these assertions.

## B110/B112 — deliberate compatibility/reflection fallbacks

- `app/services/daily_cost.py:3287` falls back to the standard amendment window
  when optional legacy amendment metadata cannot be read.
- `app/services/daily_cost.py:3313` preserves compatibility with a database that
  predates the optional amendment-history table. Actual business commits and
  database errors are not silently discarded by this fallback.
- `app/services/dependencies.py:88` ignores an unrelated unresolved optional
  foreign key during metadata reflection. It does not skip a resolved dependency
  or change tenant authorization; the database remains the final FK guard.

These sites should be narrowed to concrete driver/ORM exceptions in future
maintenance where feasible, rather than broadening the baseline.
