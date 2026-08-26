# CONTINUE HERE — V5.4.7 COMPLETE 2026-08-26 (help refresh + full-system bug hunt)

Nothing pending from this round. Two workstreams shipped:

## 1. `aq` help surfaces refreshed (#125)
- `aq evaluate --all` help text fixed (was missing `--benchmarks` since V5.4.4).
- README train/evaluate CLI blocks completed (5 missing flags documented).
- NEW guard: `tests/test_cli_help_surface.py` - every subcommand `--help`
  exits 0 (CI covered only 2 of ~23 before) + two-directional
  README-CLI-reference <-> build_parser() flag sync.
- ci.yml ruff pinned to 0.16.4 (unbounded range = silent CI drift risk).

## 2. Full-system bug hunt (#120-#124) - areas NOT covered by V5.4.6's live-path audit
- **New shared module** `json_safety.py`: finite-safe serialization, atomic
  JSON/text writes, lenient reads. All producers/writers/readers converted.
- **#120 pipeline wedge:** one NaN event permanently stuck Redis->Postgres
  batches (JSONB rejects NaN; xreadgroup(">") never redelivers). Producers
  sanitize; workers fall back per-row with a poison-vs-outage probe; audit
  twin dead-letters chained successors to protect the hash chain. Torn-file
  API 500s -> atomic writers + lenient readers.
- **#121 gating/analyzer:** missing multitask head deflated magnitude/vol
  blends toward OVERSIZING (weights not renormalized); `_clamp01(NaN)` was
  PERFECT confidence passing the trade gate. Both fixed; layernorm eps floor.
- **#122 retraining gates:** fake-zero defaults deadlocked promotion on a
  fresh deploy and let NaN pass everything; now fail-closed with explicit
  reasons, byte-identical when metrics are healthy.
- **#123 data pipeline:** Yahoo NaN-frame rows written as real bars; backfill
  end-day unreachable forever; FRED cache destroyed by narrow refetch;
  config.json truncation window; liquidity div-zero/negative-spread guards.
- **#124 tooling:** promote() verifies artifact hashes pre-flight; rollback
  fails on no-artifact restores; Telegram watermark freeze; worker startup
  crash-loop.

Verified: python **2929/2929** (+71 tests), ruff clean, badge refreshed,
`pip install -e .` re-run for the new py-module (#115 rule).

## For the next session
- Suggested commit: "V5.4.7 aq help refresh + full-system bug hunt (#120-#125):
  pipeline wedge fix, gating blend renormalization, gate fail-closed semantics,
  data-pipeline corruption fixes, CI help-surface guards; 2929 tests green"
- Docker image rebuild still recommended before next compose use (predates
  V5.4.x code); required before paper/live since workers changed materially.
- No AQ backtest strictly needed for this round (nothing in the Lean decision
  path changed except the already-noted V5.4.6 cost-gate conservatism), but if
  one runs anyway it doubles as regression coverage for #121's blend fix.
- Deliberately NOT done (documented in #121): interpreter-level input
  sanitization (downstream guards own that contract); PEL XAUTOCLAIM reclaim
  (poison path now acks everything; outage path intentionally keeps pending).
