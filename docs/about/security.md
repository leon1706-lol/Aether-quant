# Security

Report a vulnerability through a private GitHub Security Advisory on the repository; see `SECURITY.md`.

What CI checks on every push:

- **CodeQL** (Python, TypeScript and the workflows).
- **bandit**, blocking on high severity.
- **pip-audit** and **npm audit**, both blocking.
- **gitleaks** over the whole history, blocking.
- **trivy** on the source tree and the dashboard image, blocking on critical issues that have a fix.
- **OpenSSF Scorecard**, weekly.

Each release attaches SBOMs (CycloneDX) for the wheel's environment and both images, and build provenance attestations for the wheel, the sdist and the images.

At runtime:

- Secrets resolve from files, Docker secrets or the keyring ([Secrets](../live/secrets.md)).
- The API needs tokens with roles once users exist ([Users](../live/users.md)) and binds to localhost by default.
- Live mode refuses the published Postgres password.
- The audit log is hash-chained, and its verification is proved in Lean 4.
