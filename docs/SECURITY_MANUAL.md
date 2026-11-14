# WellCostIQ Security Manual

This guide explains the controls built into WellCostIQ and the deployment work that remains the responsibility of the customer’s IT team. It is written in two levels: the first section is for ordinary users and workspace administrators; the second is for IT, security and deployment personnel.

## Part 1 — Everyday security for non-IT users

### Signing in safely

- Sign in only through your organisation’s approved WellCostIQ address. Never follow an unexpected reset link or disclose a password in chat or email.
- The workspace ID and work email identify your account. A wrong workspace, unknown email and wrong password all produce the same public error so an outsider cannot discover registered accounts.
- Five failed password attempts temporarily lock the account for 15 minutes. An authorised administrator can unlock it from the Security Centre after verifying the person.
- Sessions use a short-lived access token and a rotating, browser-only refresh cookie. Signing out invalidates the current refresh session. A password change or password reset invalidates every session for that user.

### Password rules

Passwords must be 12–128 characters and use at least three of these four groups: lowercase letters, uppercase letters, numbers and symbols. The password must not contain the user’s email address and common default passwords — including keyboard and number sequences — are rejected. The last five passwords an account has used cannot be chosen again. Use a company-approved password manager and a unique password.

### Password expiry and mandatory changes

- A password is valid for **90 days** by default for every account, including Owner. The Security Centre shows the expiry date, marks accounts whose password has expired, and lists those expiring within 14 days.
- When the period ends you can still sign in once, but the workspace is replaced by the password screen until a compliant replacement is saved. Nothing else is reachable meanwhile, and you receive a notification.
- New accounts created by an administrator must choose their own password at first sign-in; the administrator’s initial value is never a long-term credential.
- An administrator can force a change at any time. A forced change ends every session immediately and keeps the password screen in place until the new password is saved.
- Saving a new password signs out every other device. If you did not make the change, contact IT immediately.

### When an administrator controls your password

The Security Centre can act **without a request from you**, because a lost laptop, a suspected leak or a leaver cannot wait for a support ticket. Three things can happen, and each one tells you what occurred:

- **A one-time reset code is issued.** You receive a notification. Redeeming the code sets a new password and signs out every session.
- **A new password is required.** You receive a notification and every session ends. After signing in, the only screen available is the password screen; the workspace reopens as soon as a compliant password is saved.
- **Sessions are revoked or the account is locked.** Revocation signs you out everywhere but keeps the password. A lock blocks sign-in completely until an authorised administrator releases it.

If you receive any of these notices and did not expect it, contact your workspace administrator or IT security immediately — the audit trail records who acted, when and why.

### Forgotten password process

1. On the sign-in page choose **Forgot password?**.
2. Enter the workspace ID, work email and an optional reason. The confirmation is deliberately generic.
3. A user with **Review password reset requests** sees a high-priority task and notification.
4. The administrator verifies the requester outside WellCostIQ, approves or rejects the request, and if approved receives a single-use code. The plain code is shown only once; WellCostIQ stores only its SHA-256 hash.
5. The administrator gives the code to the verified user through the organisation’s approved secure channel—not an open group, ticket comment or unverified caller.
6. The user opens **I already have an approved reset code** on the sign-in page, supplies the code and a new password. Codes expire after 30 minutes by default and cannot be reused.

7. If the code is lost or expires before it is used, the administrator opens the same request under **Reset requests** and chooses **Issue new code**. The earlier code stops working at once; only one code per account is ever live.

The request appears in two places: the **Security Centre** queue (needs *Review password reset requests*) and the **Task Manager** (also needs *View tasks*). The notification opens the Security Centre. A request for an **owner** account can only be approved, rejected or re-issued by an owner. The workspace ID, e-mail and code may be pasted with surrounding blanks or a line break.

Never approve your own unexpected request without verifying why it was raised. Repeated or suspicious requests should be escalated to IT/security.

### Notifications and tasks

- The bell shows personal notifications. Notifications are stored as one typed row per recipient; recipients cannot see another user’s inbox.
- The **Notification centre** adds filters (read state, severity, type, text, date range), 20/50/100 paging, mark read/unread, dismissal and CSV/Excel/PDF export of the view you are looking at.
- Announcements are addressed to every active user, to chosen roles, or to chosen people. Each broadcast keeps one typed header row, so an authorised sender can see how many recipients read it and can **recall** it — recalling withdraws only the copies nobody has opened.
- The Task Manager shows only tasks the user created, is assigned, is permitted to act on, or—if authorised—all workspace tasks.
- The task queue supports status, priority, type, assignee and due-date filters (including overdue and due-today), 20/50/100 paging, bulk claim/complete/reopen/cancel/reassign, a per-task history with comments, and CSV/Excel/PDF export.
- Existing AFE transitions remain the source of truth. Submitting an AFE creates a review task; completing review creates an approval task. Acting on the task does not bypass the AFE permission or status checks.
- Announcements sent by authorised users appear in the addressed inboxes. Do not place passwords, reset codes, personal data or secrets in announcements or task descriptions.

### Roles and audit trail

Access is tenant-scoped and permission-based. Give users the smallest role they need. Owner access is powerful and should be limited. Sign-in, failed sign-in, password recovery decisions, user administration, notification sending, task changes and business changes are recorded in the read-only audit trail with actor, time and request details.

Report a lost device, suspicious notification, unexpected password reset, or unexplained audit entry immediately. IT should deactivate the user or force a password reset and review the audit trail.

### Error messages

When an action fails, the application shows one pop-up with the server’s readable explanation: a missing permission, a record that changed, a validation problem or a missing endpoint. A “Not found” answer always names what was missing and what to do next; if it names an API route, the browser tab and the deployed API are different versions and a reload after deployment resolves it. Messages that carry no information are replaced with a plain sentence rather than passed through.

Three rules keep the messages usable:

1. **A permission answer names the capability**, for example *“Permission denied. This action needs security:read.”* The user can then ask an administrator for exactly that capability instead of guessing.
2. **A rejected form is translated into plain language.** The API describes validation failures in developer terms (*“String should match pattern '^(low|normal|high|critical)$'”*); the browser rewrites them as *“Priority must be one of: low, normal, high, critical.”* No technical field path or regex is ever shown.
3. **An address the application does not serve is a page, not a silent redirect.** Reloading a bookmark that no longer exists shows the requested address, the reason it usually fails (an older page bundle than the deployed build) and buttons back to the dashboard. An unmatched API route is logged on the server with method, path and API version so the operator can see which call a browser is making.

## Part 2 — IT and deployment security

### Security architecture

- **Tenant isolation:** application queries and mutable records are scoped by `organization_id`; RBAC checks run server-side.
- **Authentication:** Argon2 password hashing through `pwdlib`; signed HS256 access JWTs default to 15 minutes; refresh tokens are opaque random values stored only as SHA-256 hashes and rotated on use.
- **Revocation:** user `token_version` invalidates outstanding access tokens after a credential reset; all stored refresh sessions are deleted.
- **Recovery:** enumeration-safe request response, per-IP request throttling, administrator permission gate, short-lived one-time code, hash-only persistence and complete audit history.
- **Owner protection:** every account action (reset code, forced change, session revocation, lock, unlock, and the bulk forms) refuses an Owner target unless the actor is an Owner. Separation of duties therefore survives delegation: a security administrator cannot take over the workspace's highest-privileged account.
- **Administrator password control:** one-time codes without a user request, forced password change (`users.must_change_password`), session revocation (`token_version` plus refresh-session deletion), and account lock. Each action writes a typed request/notification row and an audit entry with the administrator’s reason.
- **Password history:** `password_history` stores one-way hashes of the previous five passwords per account, so reuse is refused on every path (sign-in change, reset code, administrator action). No plaintext password is ever stored or logged.
- **Password lifetime:** `PASSWORD_MAX_AGE_DAYS` (default 90) applies to every account with no Owner exemption. `users.password_expires_at` is written on each change and derived from `password_changed_at`/`created_at` for accounts that predate the control, so a dormant account cannot keep an old password indefinitely. An expired password authenticates once and is then contained exactly like a forced change; the account holder is notified once and the Security Centre lists expiry state.
- **Containment:** while `must_change_password` is set or the password has expired, only `GET /auth/me`, `POST /auth/change-password`, `POST /auth/logout`, `POST /auth/logout-all` and `POST /auth/refresh` are reachable; every other endpoint answers 403 with an instruction to set a new password.
- **Replay detection:** a rotated refresh token is tombstoned. Presenting one again revokes every session for that account, bumps `token_version` and writes a `refresh_reuse` audit entry.
- **Client identity and throttling:** audit addresses and per-client budgets come from `core/request_security.py`, which believes `X-Forwarded-For` only when the connecting peer is listed in `TRUSTED_PROXY_IPS`. Login (30/15 min), forgot-password (5/15 min), reset-code verification (10/15 min) and password change (10/15 min) are budgeted per client; account lockout remains 5 failures / 15 minutes.
- **Log hygiene:** a redaction filter masks passwords, tokens, cookies and secret keys; SQLAlchemy engine logging is pinned to WARNING; free-text audit fields are stripped of control characters and length-capped.
- **Uploaded documents:** the stored and served MIME type is derived from file signatures, never from the client; only verified PDF/JPEG/PNG/GIF render inline; downloads carry `Content-Security-Policy: default-src 'none'; sandbox` and `nosniff`.
- **Exports and imports:** server-generated report CSVs, the database browser and the browser’s own CSV/XLSX exports neutralise spreadsheet formulas while keeping numbers numeric. Imports accept `.xlsx`/`.csv` only, within 10 MiB / 10,000 rows / 200 columns, after a ZIP preflight (2,000 entries, 50 MiB expansion, no ZIP64/encryption).
- **Archives:** credential and access-control tables (`users`, `password_history`, `password_reset_*`, `refresh_sessions`, `roles`, `permissions` and their links) are excluded from archives and preserved across a restore. Archives are business-data recovery, never a credential copy.
- **Browser controls:** HttpOnly/SameSite refresh cookie, optional Secure flag, strict CORS allow-list, clickjacking/content-sniffing/referrer/permissions/CSP response headers, and HSTS when secure cookies are enabled.
- **Persistence:** security workflow, notifications and task history use ordinary typed relational columns. Reset secrets and raw refresh tokens are never stored. There are no JSON/JSONB business payload columns.
- **Data browser:** authentication secrets and other protected fields remain excluded from the application database browser.

### New permission keys

| Permission | Purpose |
|---|---|
| `security:read` | View the account register, the recovery queue and the security summary |
| `security:password-reset` | Open the Security Centre, approve/reject requests, issue one-time reset codes on demand, force a password change and revoke sessions (the account register itself still needs `security:read`) |
| `security:unlock` | Lock or unlock an account |
| `notifications:manage` | Send workspace-wide announcements |
| `tasks:read` | Read permitted workflow tasks |
| `tasks:create` | Create manual tasks |
| `tasks:manage` | Manage all workspace tasks |

The migration grants these permissions to existing Owner roles. For separation of duties, create a dedicated security-administrator role and avoid routine use of Owner accounts.

### Production deployment checklist

1. Set a unique, randomly generated `SECRET_KEY` of at least 32 bytes. Never reuse development or test values. Store it in the platform secret manager, not source control.
2. Use PostgreSQL with a dedicated least-privilege database role. Restrict database network access to the API service and authorised backup/operations systems.
3. Run `cd backend && alembic upgrade head` before starting the updated application. Back up the database first and confirm the migration reaches revision **`f2a6c8d41e07`** (permission-only audit grants; parent `f1d7a4c95b23`). It leaves `public.audit_logs` and every user, password, audit and business row in place. Render's pinned Docker entrypoint performs this automatically.
4. Terminate TLS at the approved reverse proxy/load balancer, redirect HTTP to HTTPS, set `SECURE_COOKIES=true`, and ensure proxy forwarding headers are overwritten—not appended from untrusted clients. Set `TRUSTED_PROXY_IPS` to that proxy’s private address/CIDR only (the bundled compose file uses `172.28.0.0/16`); leave it empty when the API is directly reachable and never use `*`. Configure exact `NGINX_SERVER_NAMES` for Compose and `ALLOWED_HOSTS` for Render; hosted PostgreSQL URLs must carry `sslmode=require`, `verify-ca` or `verify-full`.
5. Set `CORS_ORIGINS` to exact approved HTTPS frontend origins. Do not use `*` with credentialed requests.
6. Keep the API and database on private networks where possible. Allow public ingress only to the reverse proxy; restrict administrative consoles by VPN or identity-aware access.
7. Configure central log collection and alert on repeated `login_failed`, password reset requests, account unlocks, role/permission changes, owner changes and unusual export volume. Application logs must not collect passwords, reset codes, JWTs or cookies.
8. Back up the database encrypted in transit and at rest. Test restoration regularly. Define retention for business, notification, task and audit data according to company policy and law.
9. Apply operating-system, container, Python and Node security updates through a tested release pipeline. Scan dependencies and container images before deployment.
10. Test light/dark UI, login, lockout, forgot/reset, session revocation, RBAC denial, AFE task generation, notifications, audit visibility, backup and restore in UAT.

### Reverse proxy requirements

Preserve the original client address only from trusted proxies. Strip inbound `X-Forwarded-For` at the public boundary and set it from the connection address. Limit request/body sizes and apply edge rate limits to `/api/v1/auth/login`, `/api/v1/auth/forgot-password`, `/api/v1/auth/reset-password` and refresh endpoints. Use a web application firewall where required by policy.

### Operational procedures

- **Joiner:** create the account with minimum roles and transmit the initial password separately. Require immediate password change under organisational policy.
- **Mover:** review and remove obsolete roles before adding new ones.
- **Leaver:** deactivate the user immediately; this blocks token use. Review assigned open tasks and transfer them.
- **Suspected compromise:** deactivate the account, revoke every session, force a password change (or issue a one-time code), preserve logs, inspect audit and session activity, rotate affected infrastructure secrets, and follow the organisation’s incident-response plan.
- **Administrator-initiated reset:** issue the code from Security centre → Accounts, record the reason, deliver it through an approved channel, and confirm the account holder completes the change. A forced change is preferable when the old password may be known to somebody else.
- **Reset-code handling:** verify identity, approve just before use, disclose once through an approved channel, and never record the plain code in a ticket or audit note. Reject stale or suspicious requests.
- **Periodic review:** quarterly (or more often) review Owner accounts, privileged permission assignments, inactive users, open reset requests, open/overdue tasks, CORS origins, TLS posture, backups and audit alerts.

### Validation after deployment

Use a non-production workspace to confirm that an unknown account and a known account receive the same forgot-password response; the sixth request within 15 minutes is throttled; an unapproved, expired or reused code fails; a valid reset signs out every session; an administrator-issued code works without a prior request; a forced change closes the workspace until the new password is saved; a reused password is refused; an account whose `password_expires_at` has passed is confined to the password screen until it is changed; replaying a rotated refresh token ends every session and writes `refresh_reuse`; locking blocks sign-in and unlocking restores it; recalling an announcement removes unread copies only; users cannot see cross-tenant records; non-authorised users receive HTTP 403; and AFE review/approval tasks do not bypass existing transitions.

### Proxy, TLS and Host ownership contract

| Control | Owner component | Required configuration / verification |
|---|---|---|
| Public TLS certificate and HTTP→HTTPS redirect | Customer's fronting TLS proxy or Vercel/Render edge | Only the public proxy terminates TLS. Record certificate/renewal ownership in the responsibility matrix below. |
| HSTS | nginx on Compose; Vercel/API middleware on hosted paths | `max-age=31536000; includeSubDomains`; do not add `preload` until every subdomain is HTTPS-only. |
| Forwarded scheme/client | Fronting proxy → nginx → API | Proxy overwrites `X-Forwarded-Proto`, `X-Forwarded-For` and `X-Real-IP`; never append an untrusted client chain. |
| nginx real IP | `edge_net` only | nginx trusts `172.29.0.0/16`. This is safe only while `WEB_BIND_ADDRESS=127.0.0.1`; if nginx is directly exposed, remove `set_real_ip_from` rather than trusting LAN clients. |
| API proxy trust | `TRUSTED_PROXY_IPS` | Compose uses `172.28.0.0/16`. Render leaves it blank unless Render supplies a verified static proxy range. |
| Host allowlist | nginx and API | Compose builds exact space-separated `NGINX_SERVER_NAMES` and retains `localhost 127.0.0.1` for probes. Render sets its actual `ALLOWED_HOSTS`. Unknown hosts must fail; do not use `*`. |
| Browser/API verbs | nginx/API | Assets and SPA accept GET/HEAD; API accepts only implemented verbs. Same-origin OPTIONS is denied at nginx until a real cross-origin caller requires it. |

The API adds its own CSP, nosniff, frame-deny and referrer policy so direct hosted
responses and error pages do not depend on an edge rule. Health checks return only
liveness and API version; they never disclose whether an owner exists.

### Backup, restore and retention targets

The repository's in-app archives are operational workspace recovery tools, not a
substitute for provider database snapshots. Render's `/app/backups` filesystem is
ephemeral and must not be treated as a backup. Until the business approves tighter
objectives, the proposed targets for approval are **RPO 24 hours** and **RTO 4
hours**; they are targets, not evidence that a provider is configured.

1. The database owner must enable Supabase PITR or automated encrypted snapshots
   with retention that meets the approved RPO. Store one independent copy outside
   the service instance and restrict restore credentials.
2. Restore the latest copy into a disposable database, run Alembic and application
   smoke tests, and record start/end UTC, source snapshot, operator, result and
   commit. Never rehearse by replacing UAT or production data.
3. The data controller must approve commercial-data and client-PII retention and
   tenant-deletion handling. Until that decision is recorded, do not invent a
   purge interval or claim compliance.
4. Save restore evidence with the collection metadata required by the evidence
   procedure. A screenshot of enabled backups is not a restore rehearsal.

### Monitoring, alerting and ownership

Ship Render and nginx/application logs to the organisation's approved central log
drain; Compose's 10 MB × 3 rotation is only local disk protection. Alert on
repeated `login_failed`, recovery/request throttles, lockout storms, new-location
Owner sign-in, role/permission/Owner changes, bulk deletes, unusual export/backup
volume, migration failures and audit-write failures. Logs must never contain
passwords, reset codes, cookies, tokens or database URLs.

| Responsibility | Primary / deputy (organisation must name both) | Cadence |
|---|---|---|
| Infrastructure, TLS, proxy, image deploys | **UNASSIGNED — production release blocker** | Deploy review; quarterly configuration comparison |
| Application and API security | **UNASSIGNED — production release blocker** | Weekly alerts; each release |
| Database roles, PITR and restore | **UNASSIGNED — production release blocker** | Daily backup check; quarterly restore |
| Audit/log review and incident coordination | **UNASSIGNED — production release blocker** | Daily triage; quarterly access review |

Replace every UNASSIGNED entry with a person and deputy before production. A
synthetic lockout storm must produce a notification to that named reviewer; the
repository cannot prove that external notification path.

### Incident response — first actions

1. **Contain:** deactivate the affected account or isolate the affected service;
   revoke sessions/force a password change where appropriate. Do not delete the
   account, audit rows, database or logs to make the symptom disappear.
2. **Preserve and assess:** snapshot/ship logs and audit history, record UTC and
   affected tenants, and open the incident with the named owner and deputy.
3. **Eradicate/recover:** rotate only confirmed affected credentials using the
   procedure below, deploy a reviewed fix, restore into a clean environment when
   required, and validate access/tenant boundaries before reopening service.

The incident owner must assess contractual and legal client-notification duties
with the data controller/legal contact. Record who decided, when, and what was
communicated. Do not include secret values in the incident record.

### Credential rotation procedure (rehearse in a disposable environment)

- **`SECRET_KEY`:** generate `openssl rand -hex 32`, deploy the new value through
  the secret manager, and restart the API. This invalidates every access/refresh
  token and forces all users to sign in again; schedule and communicate that
  effect. It does not change passwords or business rows.
- **`wellcosting_app` password:** during a maintenance window, change the role
  password as DBA, update only `DATABASE_URL`, then rolling-restart the API.
  Verify existing sign-in and audit writes. Do not drop/recreate the role.
- **`wellcosting_migrator` password:** change the role password, update only
  `MIGRATION_DATABASE_URL`, then deploy within the migration window. Verify the
  migration credential is unset before Uvicorn starts. Do not run migrations as
  the restricted application role.
- **PostgreSQL administrator password:** DBA-only operation; update
  `POSTGRES_PASSWORD` only for fresh-cluster initialization. On an existing
  cluster, rotate the role using provider tooling and preserve the same data
  volume. Never re-run initialization scripts against UAT.
- **Supabase pooler credential:** regenerate/copy it in Supabase's approved
  connection settings, identify every Render service/operator store holding it,
  update both role-specific URLs independently and verify TLS. Never paste it in
  tickets, evidence or source control.

Only the named database/infrastructure owners may perform these rotations; a
second approver is required for production except during the incident owner's
declared emergency containment. Record rehearsal date, operator, elapsed time and
rollback outcome. No rehearsal is claimed by this document.

### Non-destructive file-secret migration (Compose maintenance window)

The current Compose file remains environment-compatible for UAT. Moving to file
secrets must not rotate credentials or initialise a new database:

1. Snapshot the database and record current secret fingerprints privately. Create
   `.secrets/` outside Git with mode 0700 and each file mode 0600, containing the
   **same existing values** (no trailing newline unless the reader trims it).
2. Deploy application/entrypoint support that reads `POSTGRES_PASSWORD_FILE`,
   `DB_APP_PASSWORD_FILE`, `DB_MIGRATION_PASSWORD_FILE`, `SECRET_KEY_FILE` and a
   seed-password file. Do not remove the old environment values first.
3. Start against the existing `postgres18_data` volume and verify the original
   users, password login, roles, audit and business data. Inspect metadata/logs
   without printing secrets. Only then remove superseded environment values.
4. Set `BOOTSTRAP_ADMIN_ON_STARTUP=false` after first-run setup and delete the
   seed password from the dashboard. Entrypoint exports reduce Compose metadata
   exposure but do not remove `/proc` environment exposure; native application
   file readers are required to close that residual risk.

### Existing-cluster audit and role runbook

The new Alembic revision revokes UPDATE/DELETE on `public.audit_logs` from
`wellcosting_app` while preserving SELECT/INSERT and all rows. The migration role
must own that table. Verify with `scripts/postgres-inventory.sql`; do not move or
copy the table in this release. Runtime SQLAlchemy connections set 120 s statement,
60 s idle-in-transaction and 10 s lock timeouts without requiring ALTER ROLE.
Fresh clusters also receive application CONNECTION LIMIT 20. Existing clusters
need a DBA to review worker/pool counts before applying that limit manually; a
21st connection can otherwise interrupt UAT. One Uvicorn worker with the current
pool fits the default budget.

### Current boundaries and recommended next phase

WellCostIQ currently provides password authentication and tenant-aware RBAC; it does not yet claim MFA, SAML/OIDC single sign-on, SCIM provisioning, breached-password intelligence, tamper-evident external audit storage or whole-platform SIEM integration. Organisations requiring those controls should place identity-aware access at the edge now and plan native MFA/SSO as a separately tested security release. Do not describe those controls as implemented until UAT and security review are complete.
