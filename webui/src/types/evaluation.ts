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

// Phase 4/5 shapes - loosely typed until those phases land; the webui only
// ever reads a handful of top-level fields from these before then.
export type WalkForwardSummary = Record<string, unknown>
export type AblationReport = Record<string, unknown>

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
