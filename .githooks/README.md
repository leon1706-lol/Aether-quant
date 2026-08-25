# .githooks

Optional git hooks, opt-in per clone (never auto-installed on a fresh
checkout):

```powershell
git config core.hooksPath .githooks
```

Currently one hook: `pre-commit`, which invokes `aq secrets-check`
(`execution/secret_scan.py`) and blocks the commit if a populated secret
field is about to land in the tracked `lean.json` or a real `.env` file is
tracked by git. This is what actually stops a secret from being committed —
see [`SECURITY.md`](../SECURITY.md) for the reporting policy.
