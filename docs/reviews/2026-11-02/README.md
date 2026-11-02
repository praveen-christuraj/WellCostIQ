# CyberSec review downloads — 2026-11-02

- [Download the review package](CyberSec-review.zip?raw=1)
- [Exact file checklist and outstanding evidence](CyberSec-review-files.md)
- [Executed validation and limitations](CyberSec-validation.md)
- [ZIP SHA-256 checksum](CyberSec-review.zip.sha256)

The ZIP is the unchanged dated review snapshot prepared against base commit
`68490f1`, with the security configuration changes included in its file snapshot.
It contains manifests, hashed locks, deployment/security configuration, and the
executed audit/build/test evidence. It contains no real environment files,
private keys, database dumps, installed dependencies or virtual environments.

Later application changes on `main` are preserved separately. The archive's
326-test result describes the snapshot tested when the package was prepared;
it must not be read as a new test run against later application features.
Current configuration files also live in their normal repository locations.

Actual workstation/production inventories, secret-scan triage, provider-role
configuration and the PostgreSQL backup/restore cutover remain as listed in the
checklist. Publishing these files does not perform those operational changes.

## Checks after integration with newer main

Before publishing this change, the 40 authentication/security hardening and
account lifecycle tests passed on the integrated source, and the frontend
production build passed on Node 22.23.4. These checks supplement the dated
archive evidence; they do not replace a full regression run for the newer
application features. The committed GitHub workflow runs the full suite and
container checks after the push.
