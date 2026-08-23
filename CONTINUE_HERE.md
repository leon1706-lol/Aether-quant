# CONTINUE HERE — V5.3.9 session break 2026-08-23 (evening)

## Done so far this round
- requirements-dev.txt: +pytest-cov, +ruff
- pyproject.toml: [tool.ruff] (line-length 240, E/F, per-file ignores for main.py star-imports / __init__ re-exports / scripts/profile_inference E501) + [tool.coverage.run/report] source+omit config
- ruff check: **ALL CLEAN** (604 findings triaged → 23 auto-fixed, 16 hand-fixed incl. dead-store `rank_signal_config` removals ×3 in aq_cli.py, loop-var shadow renames in test_aq_cli, underscore-unused locals in trainers)
- **Coverage measured locally: TOTAL 82%** → calibrated CI gate = `--cov-fail-under=80`
- `.github/workflows/ci.yml` REWRITTEN with 5 jobs:
  python-tests (matrix ubuntu+windows, pytest --cov --cov-fail-under=80, coverage.xml artifact on ubuntu) ·
  python-lint (ruff + py_compile) · webui-tests (+`npx vitest run --pool=threads` before build) ·
  cli-smoke (pip install -e .; aq --help/evaluate --help/config get phase1.universe.name/secrets-check) ·
  workflows-lint (actionlint)
- `.github/workflows/release.yml`: added NON-BLOCKING `tag-tests` job (visibility only, deliberately NOT in needs chains — user decision)
- tests/test_ci_workflows.py: **7 meta-tests ALL GREEN** pinning triggers/matrix/cov-gate/vitest-in-CI/ruff/py_compile/release-non-blocking/three-publish-targets/README-MC-docs

## Remaining queue tomorrow (in order)
1. **tests/test_monte_carlo.py +3 edge cases**: all-positive series ⇒ P(neg)==0 exactly; block_size ≥ n clamps safely (no crash); n_plot_points > n handled.
2. **tests/test_generate_evaluation_report.py +1**: Monte Carlo markers render the not-run-yet fallback when ml/evaluation/monte_carlo.json is absent (call update_readme_evaluation_sections on a README fixture containing the markers).
3. **Full pytest suite** run (`python -m pytest -q -m "not lean_backtest"`) — expect ~2747+ green.
4. **Docs**: Problems.md #109 (CI hardening round), Changelog V5.3.9 entry, README "Development & CI" paragraph, CONTRIBUTING CI-expectations note, architecture.md CI touch, evaluation/README nothing new needed.
5. **Vault**: generate_code_graph + regenerate_vault --append-handoff.
6. **Final report in chat** + suggested commit message (user commits manually).

## Notes
- ruff auto-fix removed some imports across repo — full suite was NOT yet re-run after that; do it at step 3 and fix anything that surfaces.
- ci.yml windows leg uses pip cache via setup-python `cache: "pip"`.
- actionlint job downloads latest binary each run (no pin) — acceptable, flagged in #109 if it ever breaks.
