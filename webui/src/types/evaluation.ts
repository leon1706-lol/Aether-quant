// V5.1 Phase 0 - types for /api/evaluation, mirroring
// evaluation/rank_book_simulator.py::RankBookSimulationResult and
// monitoring/evaluation_state.py::build_evaluation_state()'s per-section
// {status: "not_evaluated", hint} degrade contract exactly.

export interface NotEvaluated {
  status: 'not_evaluated'
  hint: string
}

export interface RankBookSimulationResult {
  gross_sharpe: number
  net_sharpe: number
  gross_total_return: number
  net_total_return: number
  net_max_drawdown: number
  annualized_turnover: number
  cost_drag_annual_bps: number
  num_rebalances: number
  num_dates_used: number
  mean_names_long: number
  mean_names_short: number
  per_date_net_return: number[]
  per_date: string[]
}

export interface CapacityTopNRow {
  top_n: number
  net_sharpe: number
}

export interface CapacityReport {
  capacity_usd: number
  binding_ticker: string | null
  per_top_n: CapacityTopNRow[]
}

export interface CostStressEntry extends RankBookSimulationResult {
  cost_multiplier: number
}

export interface CostStressReport {
  entries: CostStressEntry[]
}

// V5.1 Phase 4 - mirrors train.py::summarize_walk_forward_run()'s /
// bootstrap_ic_confidence_interval()'s exact return shape.
export interface CrossWindowBootstrap {
  lower_bound: number
  upper_bound: number
  mean_ic: number
  confidence: number
  n_resamples: number
  num_observations: number
}

export interface MetricWindowSummary {
  num_windows: number
  per_window_metric_values: number[]
  cross_window_bootstrap: CrossWindowBootstrap
}

// Mirrors evaluation/rank_book_simulator.py::summarize_metric_stability()'s
// return shape - note its own internal bootstrap uses {lower_bound,
// upper_bound, mean} (no _ic suffix, no confidence/n_resamples/
// num_observations - a torch-free duplicate with a narrower shape, see
// that function's own docstring for why it is deliberately NOT the same
// train.py helper CrossWindowBootstrap above wraps).
export interface MetricStabilitySummary {
  num_windows: number
  mean: number
  sign_flip_fraction: number
  stable: boolean
  failures: string[]
  bootstrap: { lower_bound: number; upper_bound: number; mean: number }
}

export interface WalkForwardNetPerformanceWindow {
  window_index: number
  head: string
  model_kind: 'sequence' | 'multitask'
  simulation: RankBookSimulationResult
  capacity: CapacityReport
  stress: CostStressEntry[]
}

export interface WalkForwardWindowResult {
  window: Record<string, unknown>
  version_id: string
  backtest_mcc: number
}

export interface WalkForwardSummary {
  run_id: string | null
  num_windows: number
  window_results: WalkForwardWindowResult[]
  summary: MetricWindowSummary
  summary_by_metric: Record<string, MetricWindowSummary>
  stability_by_metric: Record<string, MetricStabilitySummary>
  net_performance_by_window: WalkForwardNetPerformanceWindow[]
}

// V5.1 Phase 5 (item 9) - mirrors evaluation/ablation.py::run_ablation()'s
// return shape exactly: either a real RankBookSimulationResult-shaped
// entry (plus delta_vs_static_baseline) or the honesty-contract sentinel
// for anything not offline-measurable (runtime-only mechanisms) or an
// unrecognized variant name.
export interface AblationMeasuredEntry extends RankBookSimulationResult {
  delta_vs_static_baseline: number
}

export interface AblationSentinelEntry {
  status: 'not_offline_measurable' | 'unknown_variant' | 'insufficient_windows' | 'walk_forward_derived'
  reason?: string
}

export type AblationVariantEntry = AblationMeasuredEntry | AblationSentinelEntry

export function isAblationSentinel(entry: AblationVariantEntry): entry is AblationSentinelEntry {
  return 'status' in entry
}

export type AblationReport = Record<string, AblationVariantEntry>

// V5.2.3 - mirrors evaluation/rank_signal_calibration.py::calibrate_book_confidence_spread()'s
// return shape (V5.1 report, only wired into /api/evaluation in V5.2.3
// alongside the book-history reconciliation report below - a pre-existing
// gap closed while touching this same file).
export interface SpreadDistribution {
  min: number | null
  p10: number | null
  p25: number | null
  median: number | null
  p75: number | null
  max: number | null
}

export interface BookSpreadCalibrationReport {
  calibrated_min_rank_confidence_spread: number
  percentile: number
  num_dates_used: number
  num_dates_skipped_thin_universe: number
  spread_distribution: SpreadDistribution
}

// V5.2.2/V5.2.3 (development/Problems.md #91) - mirrors
// evaluation/rank_signal_calibration.py::reconcile_book_history_date()'s
// (or replay_book_history_reconciliation()'s) per-date return shape.
export interface BookHistoryRoleSymbols {
  long: string[]
  short: string[]
}

export interface BookHistorySymbolDelta {
  raw_score_delta: number | null
  weight_delta: number | null
}

export interface BookHistoryPerDateResult {
  date: string
  logged_symbols: BookHistoryRoleSymbols
  offline_symbols: BookHistoryRoleSymbols
  symbols_matched: string[]
  symbols_only_logged: string[]
  symbols_only_offline: string[]
  role_mismatches: string[]
  overlap_fraction: number | null
  per_symbol_deltas: Record<string, BookHistorySymbolDelta>
}

// Mirrors summarize_book_history_reconciliation()'s return shape.
export interface BookHistoryReconciliationSummary {
  num_dates: number
  num_dates_exact_match: number
  mean_overlap_fraction: number | null
  mean_raw_score_delta_abs: number | null
  mean_weight_delta_abs: number | null
  num_dates_with_weight_logged: number
  num_symbols_only_logged_total: number
  num_symbols_only_offline_total: number
}

// V5.2.3 - mirrors summarize_universe_snapshot_by_security_type()'s return
// shape. num_dates_with_universe_data === 0 means the log was written
// without phase_v2.diagnostics.book_history.include_full_universe - NOT
// that every security type had zero observations.
export interface UniverseSecurityTypeStats {
  num_symbol_dates: number
  mean_raw_rank_score: number | null
  feature_ready_rate: number | null
  trading_eligible_rate: number | null
}

export interface UniverseSnapshotSummary {
  num_dates_with_universe_data: number
  by_security_type: Record<string, UniverseSecurityTypeStats>
}

// Top-level persisted/served payload from `aq evaluate --reconcile-book-history`.
export interface BookHistoryReconciliationReport {
  mode: 'independent' | 'replay_hysteresis'
  per_date: BookHistoryPerDateResult[]
  summary: BookHistoryReconciliationSummary
  universe_summary: UniverseSnapshotSummary
}

export interface EvaluationState {
  rank_book: RankBookSimulationResult | NotEvaluated
  capacity: CapacityReport | NotEvaluated
  stress: CostStressReport | NotEvaluated
  ablation: AblationReport | NotEvaluated
  walk_forward: WalkForwardSummary | NotEvaluated
  book_spread_calibration: BookSpreadCalibrationReport | NotEvaluated
  book_history_reconciliation: BookHistoryReconciliationReport | NotEvaluated
}

export function isNotEvaluated(value: unknown): value is NotEvaluated {
  return typeof value === 'object' && value !== null && (value as { status?: string }).status === 'not_evaluated'
}
