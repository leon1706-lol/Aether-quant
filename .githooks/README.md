# .githooks

Opt-in git hooks: `git config core.hooksPath .githooks`.

- **`pre-commit`:** runs `aq secrets-check` and blocks a commit with a populated secret in `lean.json` or a tracked `.env`. See [`SECURITY.md`](../SECURITY.md).
