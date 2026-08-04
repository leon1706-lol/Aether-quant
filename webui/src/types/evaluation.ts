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

export interface EvaluationState {
  rank_book: RankBookSimulationResult | NotEvaluated
  capacity: CapacityReport | NotEvaluated
  stress: CostStressReport | NotEvaluated
  ablation: AblationReport | NotEvaluated
  walk_forward: WalkForwardSummary | NotEvaluated
}

export function isNotEvaluated(value: unknown): value is NotEvaluated {
  return typeof value === 'object' && value !== null && (value as { status?: string }).status === 'not_evaluated'
}
