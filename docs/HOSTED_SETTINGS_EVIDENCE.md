# Hosted settings evidence capture

No live hosted dashboard was accessed from the repository workspace. The captures
below are **pending**, not asserted values. Store redacted plain-text output under
`evidence/` outside the delivered source bundle when that directory is used for
local review; never include environment values, session cookies, tokens,
connection URLs, password fingerprints or unredacted screenshots with secrets.

Each capture must include UTC timestamp, source commit, CI run URL/ID, operator,
tool/source (dashboard page), and an explicit comparison with the committed file.

## `evidence/vercel-dashboard-settings.txt`

Capture from **Settings → General**:

- Root Directory (expected `frontend`)
- Build Command (`npm run build`)
- Install Command (`npm ci`)
- Node.js version (`22.x`; deployed patch consistent with the project engine)
- Production branch and Auto-Deploy behavior
- Deployment Protection for preview deployments
- Actual production domains (safe to record; no DNS credentials)

Compare with `frontend/vercel.json`, including the exact Render rewrite hostname,
one-year HSTS and the CSP ending in `upgrade-insecure-requests`.

## `evidence/render-dashboard-settings.txt`

Capture from **Build & Deploy** and **Environment**:

- Runtime Docker, Root Directory `backend`, Dockerfile Path `./Dockerfile`
- Auto-Deploy **off**; record the manually deployed commit and passing CI run
- Health Check `/api/health`
- Plan/region and whether the instance sleeps
- Environment **key names only**, with values redacted and secret flags visible:
  `DATABASE_URL`, `MIGRATION_DATABASE_URL`, `SECRET_KEY`, `ALLOWED_HOSTS`,
  `SECURE_COOKIES`, `CORS_ORIGINS`, token/password policy keys and bootstrap keys
- Confirm `BOOTSTRAP_ADMIN_ON_STARTUP=false` and `SEED_ADMIN_PASSWORD` absent
  after first successful setup
- Deployed image identifier/digest if the provider supplies one; otherwise say
  explicitly that image-by-digest provenance is not available

Compare with `render.yaml`. Do not paste environment export output.

## `evidence/supabase-settings.txt`

Capture without credentials:

- Connection pool mode (expected Session pooler for this application)
- Port/host type and dedicated role names only, not complete URLs
- Whether both runtime and migration URLs carry `sslmode=require` (yes/no)
- PITR/snapshot enabled state and retention
- Network restrictions and database version/extensions
- Latest restore rehearsal date/result and elapsed time

## GitHub branch/release evidence

Record that the Security workflow is a required status check on the protected
production branch, review is required, and direct pushes cannot bypass it. Render
manual deploy must reference a passing run. This setting cannot be established by
`render.yaml` alone.
