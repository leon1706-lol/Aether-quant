# CONTINUE HERE — V5.4.4 COMPLETE 2026-08-25 (morning)

Nothing pending from this round. V5.4.4 shipped in full:

1. Public benchmarks (`evaluation/public_benchmarks.py`) + strategy
   baselines surfaced END-TO-END: `aq evaluate --benchmarks` (in `--all`)
   -> ml/evaluation/benchmark_comparison.json -> README "Benchmark
   Comparison" auto-section (AQ:BENCHMARK markers) -> webui BenchmarkPanel
   via /api/evaluation's `benchmarks` key.
2. HRP live book sizing (`phase_v2.portfolio_book.allocation_method`,
   default "rank" byte-identical) + single-sided full-gross fix.
3. CI python-lint fix (V5.4.3's two ruff findings).
4. Monte Carlo README chart + test-badge clobberer bugs (Problems.md #114)
   - guard in update_readme_evaluation_sections, mocked badge writer.
5. Packaging gap fixed (Problems.md #115): installed `aq` console script
   now works for evaluate/audit (evaluation/portfolio/features/audit/
   inference/analyzer added to packages; generate_evaluation_report to
   py-modules). RE-RAN `pip install -e .` already.
6. mean_reversion_baseline un-placeholdered (real next-day accrual).

Verified: python **2834/2834** (aq test), vitest **103/103**, ruff clean,
real benchmarks run live in README (multitask rank book 1.681 vs SP500
1.214 / 60-40 1.624 / momentum 0.476 / MR -0.119 / random -0.217,
backtest split, 820 dates x 93 tickers). Docs: Changelog V5.4.4,
Problems.md #114+#115, architecture.md, evaluation/README.md,
portfolio/README.md, root README (section + TOC + CLI row), vault graph +
HANDOFF all updated.

## If continuing in a future session
- Suggested commit message is in the chat handoff (user commits manually).
- Optional follow-ups discussed but NOT scheduled: flip
  `allocation_method` to `"hrp"` + run an AQ backtest for Lean-side
  validation; rebuild engine docker image before next compose use; no
  codespace/model training needed this round.
