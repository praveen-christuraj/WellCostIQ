# Security risk register

This register records only controls visible in the repository. Provider settings,
named ownership and rehearsals remain pending until evidence is attached. Do not
convert a pending risk into an acceptance by adding a date without an approver.

## R-2026-001 — Administrator MFA/SSO deferred

**Status:** PENDING FORMAL ACCEPTANCE — not accepted yet.

MFA/SSO for administrator accounts is deferred. Compensating controls implemented
in the application/configuration are:

- password maximum age 90 days;
- reuse of the last five passwords blocked using one-way password-history hashes;
- lockout after five failed sign-ins for 15 minutes;
- database-backed per-client login/recovery request budgets;
- session revocation from the Security Centre;
- mandatory password change on newly created accounts in production; and
- application-role UPDATE/DELETE revoked on existing `public.audit_logs` by the
  permission-only migration (verify on the deployed cluster before relying on it).

Residual exposure: a stolen Owner password is sufficient to sign in. Detection
still depends on an external log drain, alert delivery and a named reviewer that
are not yet evidenced. Append-only database grants do not make audit storage
external or tamper-evident. Free-tier cold starts and the absence of a provider
edge limiter increase availability/abuse concerns.

- **Owner:** UNASSIGNED (required before acceptance)
- **Expires:** UNASSIGNED (required; must appear in quarterly review)
- **Accepted by:** UNASSIGNED — name and date required
- **Review evidence required:** native MFA/SSO plan or compensating-control test,
  provider log alert test, deployed audit-grant inventory, and a named reviewer.

## R-2026-002 — Hosted edge and recovery controls require provider evidence

**Status:** OPEN — operator action required.

Render's direct hostname has application Host enforcement, but the Compose nginx
rate limits do not sit in front of it. Provider WAF/rate limiting, always-on
hosting, managed PITR/snapshots and an actual timed restore are not proven by
source code. `/app/backups` on Render is ephemeral.

- **Owner:** UNASSIGNED
- **Target/expiry:** UNASSIGNED
- **Closure evidence:** redacted dashboard captures, edge throttle test, restore
  into a disposable database with elapsed time, and source commit/CI identifiers.

## R-2026-003 — PostgreSQL row-level tenant isolation deferred

**Status:** DEFERRED TO DEDICATED DESIGN/UAT RELEASE.

Tenant filters and RBAC are enforced in the API. PostgreSQL RLS or per-tenant
roles are not implemented. Adding them requires query/session-role design,
migration replay, performance tests and tenant-isolation verification; it must
not be mixed into the permission-only audit patch.

- **Owner:** UNASSIGNED
- **Review:** Next architecture/security design cycle, with a dated decision before
  public SaaS launch.
