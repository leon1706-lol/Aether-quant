export interface Portfolio {
  cash: number
  total_portfolio_value: number
  invested_positions?: number
}

export interface Position {
  symbol: string
  quantity: number
  weight?: number
  unrealized_profit?: number
}

// risk/asset_class_router.py::route_position_sizing()'s "extra" payload -
// {} for equity/crypto/bond, {contract_count} for future, {lot_count} for
// forex (V4.6), {options_decision} for option (only once a position was
// actually sized). Present under dynamic_sizing.asset_class_routing_extra.
export interface FuturesRoutingExtra {
  contract_count: number
}

// Mirrors risk/forex_risk.py::ForexSizingDecision - the Forex sibling of
// FuturesRoutingExtra above.
export interface ForexRoutingExtra {
  lot_count: number
}

// data/reference/forex_pair_specs.json's per-pair shape - resolved by
// main.py's self.forex_pair_specs.get(ticker) and threaded through
// risk/asset_class_router.py::route_position_sizing()'s forex branch
// (Phase 4.8) purely for webui display, no sizing-math change.
export interface ForexPairSpec {
  description?: string
  pip_size: number
  lot_size: number
  leverage_max: number
  margin_pct: number
}

// Mirrors portfolio/options_strategy.py::OptionsPositionDecision.to_dict() -
// contract_symbol is already stringified there (never a raw Lean Symbol) so
// it round-trips through JSON safely.
export interface OptionsDecision {
  contracts: number
  right: 'call' | 'put' | string
  strike: number
  expiry: string
  target_delta: number
  actual_delta: number
  vega_budget_used: number
  sizing_reason: string
  contract_symbol: string | null
}

// One leg of a multi-leg options position - mirrors
// portfolio/options_strategy.py::OptionsSpreadLeg.to_dict() (reused
// identically by OptionsMultiLegPositionDecision and
// portfolio/options_margin_sizing.py::MarginSizingDecision).
export interface OptionsSpreadLeg {
  strike: number
  right: 'call' | 'put' | string
  side: 'long' | 'short' | string
  contract_symbol: string | null
}

// Mirrors OptionsSpreadPositionDecision.to_dict() (legacy 2-leg vertical,
// `expiry` singular) AND OptionsMultiLegPositionDecision.to_dict() (V4.5,
// any leg count, `expiries` a tuple - 2 entries only for the calendar
// family) - both share every other field, distinguished here by which of
// `expiry`/`expiries` is present.
export interface OptionsMultiLegDecision {
  strategy_name: string
  legs: OptionsSpreadLeg[]
  expiry?: string
  expiries?: string[]
  contracts: number
  net_debit_or_credit: number
  net_delta: number
  net_vega: number
  sizing_reason: string
}

// Mirrors portfolio/options_margin_sizing.py::MarginSizingDecision.to_dict()
// - the margin-tier sibling of OptionsMultiLegDecision (naked/uncovered-
// leg/bounded-backspread strategies a vega budget can't safely size).
export interface OptionsMarginDecision {
  strategy_name: string
  legs: OptionsSpreadLeg[]
  expiries: string[]
  contracts: number
  margin_required: number
  margin_utilization: number
  sizing_reason: string
}

export interface AssetClassRoutingExtra {
  contract_count?: number
  lot_count?: number
  // Phase 4.8 - present alongside lot_count for forex only; {} when the
  // ticker has no entry in data/reference/forex_pair_specs.json.
  pair_spec?: ForexPairSpec | Record<string, never>
  options_decision?: OptionsDecision | OptionsMultiLegDecision | OptionsMarginDecision
}

// Mirrors risk/position_sizing.py::PositionSizingDecision field-for-field -
// every multiplier that actually composes sized_weight (V4.12.2 closes the
// gap where these were computed/persisted but never typed/rendered here).
export interface DynamicSizing {
  base_target_weight?: number
  target_weight?: number
  rolling_volatility?: number
  annualized_volatility?: number
  leverage_factor?: number
  volatility_regime?: string
  volatility_source?: string
  sizing_reason?: string
  volatility_multiplier?: number
  confidence_multiplier?: number
  // Topology-informed sizing (V2-17.5+) - 1.0/"topology_sizing_disabled_or_absent"
  // when phase_v2.dynamic_risk.topology_sizing_enabled is off (this project's
  // default), a real multiplier + reason otherwise.
  topology_multiplier?: number
  topology_sizing_reason?: string
  // Rank-informed sizing (V4.11) - same disabled-vs-active convention as topology above.
  rank_multiplier?: number
  rank_sizing_reason?: string
  // RL sizing overlay (Phase 4.12, development/Problems.md #71) - 1.0/
  // "rl_sizing_disabled_or_absent" by default (phase_v2.dynamic_risk.rl_sizing_enabled
  // is off), a learned multiplier + reason once enabled and a trained model is loaded.
  rl_multiplier?: number
  rl_sizing_reason?: string
  // Cost-aware sizing (V5.1 Phase 1, development/Problems.md, item 3) - same
  // disabled-vs-active convention as rank/topology/rl above: 1.0/
  // "cost_sizing_disabled_or_absent" while phase_v2.costs.cost_sizing_enabled
  // is off (this project's default), a real shrink-only multiplier once
  // enabled and calibrated - see risk/position_sizing.py::cost_sizing_multiplier().
  cost_multiplier?: number
  cost_sizing_reason?: string
  // Present for future/option assets only - see AssetClassRoutingExtra above.
  asset_class_routing_extra?: AssetClassRoutingExtra
}

// V5.1 Phase 1 (development/Problems.md, item 3) - execution/cost_model.py::
// NetEdgeDecision.to_dict(). passes=true/reason="net_edge_gate_disabled"
// whenever phase_v2.costs.enabled is off or edge_bps_per_rank_unit is
// uncalibrated (0.0) - this project's default until `aq evaluate
// --calibrate-edge` sets a real value.
export interface NetEdge {
  expected_edge_bps: number
  expected_cost_bps: number
  net_edge_bps: number
  passes: boolean
  reason: string
}

// V5.1 Phase 1 (development/Problems.md #73) - portfolio/rank_signal.py::
// resolve_rank_signal_policy()'s return shape, resolved once per run and
// mirrored at RuntimeState.rank_signal.
export interface RankSignalPolicy {
  heads: Record<string, number>
  model_priority: string[]
  normalization: string
  demoted: string[]
  reason: string
}

// V5.1 Phase 1 (development/Problems.md, item 6) - portfolio/book_neutrality.py::
// apply_book_neutrality()'s diagnostics from the book's last rebalance bar -
// {} pre-first-rebalance or whenever phase_v2.portfolio_book.neutrality.enabled
// is off (this project's default until Lean Backtest 1 validates it).
export interface BookNeutralityDiagnostics {
  pre_gross?: number
  post_gross?: number
  net_before?: number
  net_after?: number
  per_sector_net?: Record<string, number>
  steps_applied?: string[]
}

// V5.1 Phase 6 (production safety) - risk/kill_switch.py::KillSwitchDecision.
// to_dict(), evaluated once per bar in main.py::_refresh_risk_state() and
// mirrored at RuntimeState.kill_switch. severity="none"/tripped=false is
// the steady-state default (config-gated fail-open, see that module's own
// docstring).
export interface KillSwitchDecision {
  tripped: boolean
  severity: 'none' | 'warning' | 'critical' | string
  triggers: string[]
  reason: string
  recommended_action: string
  observed: Record<string, number | boolean | null>
  thresholds: Record<string, number>
}

// V5.1 Phase 6 (production safety) - execution/reconciliation.py::
// ReconciliationReport.to_dict(), evaluated once per bar in main.py::
// _refresh_risk_state(). {status: "not_applicable", reason: "..."} is the
// steady-state default whenever the portfolio-book-with-neutrality path
// or phase_v2.reconciliation.enabled isn't active - see
// main.py::_evaluate_reconciliation()'s own docstring.
export interface ReconciliationDrift {
  symbol: string
  expected_weight: number
  actual_weight: number
  delta_weight: number
  delta_usd: number
}

export interface ReconciliationReport {
  status?: 'not_applicable' | 'not_evaluated' | string
  reason?: string
  matched?: string[]
  drifted?: ReconciliationDrift[]
  orphan_broker?: ReconciliationDrift[]
  missing_broker?: ReconciliationDrift[]
  max_abs_weight_drift?: number
  breach?: boolean
}

export interface MarketAnalysis {
  action?: 'observe' | 'simulate' | 'trade' | 'reduce_risk' | 'retrain_candidate' | string
  signal?: string
  target_weight?: number
  confidence?: number
  probability_up?: number
  trading_eligible?: boolean
  topology_considered?: boolean
  reasons?: string[]
  // V5.1 Phase 1 - null/undefined whenever the net-edge gate is disabled/
  // uncalibrated this bar - see NetEdge's own docstring.
  net_edge?: NetEdge | null
}

export interface TopologyContext {
  state?: string
  cluster_id?: string
  market_distance?: number
  correlation_strength?: number
  volatility_pressure?: number
  topology_risk?: 'isolated' | 'normal' | 'elevated' | string
  regime_label?: string
  // V2-17.5 - learned topology overlay, present once topology.learned_topology
  // has scored this asset (see topology_source for whether it actually did).
  topology_source?: 'deterministic' | 'learned' | 'hybrid' | 'fallback' | string
  cluster_probs?: Record<string, number>
  topology_confidence?: number
  topology_uncertainty?: number
  stress_score?: number
  neighbor_shift_score?: number
  topology_disagreement?: number
  learned_neighbors?: string[]
  cluster_dominant_regime_label?: string
}

export interface LiquidityInfo {
  daily_dollar_volume?: number
  order_value?: number
  participation_rate?: number
  estimated_slippage?: number
  spread_proxy?: number
  estimated_round_trip_cost?: number
  liquidity_risk?: 'normal' | 'thin' | 'high_impact' | 'blocked' | string
  recommended_action?: 'allow' | 'reduce_size' | 'simulate_instead' | 'block' | string
  adjusted_target_weight?: number
  reasons?: string[]
}

// features/bond_features.py's analytic duration/convexity/DV01 - mirrors
// main.py::_bond_analytics_for_symbol()'s return shape exactly. null (not
// 0.0) for a non-bond symbol or missing inputs, same None-vs-neutral-
// default distinction that module's own docstring documents.
export interface BondAnalytics {
  analytic_modified_duration: number | null
  analytic_convexity: number | null
  bond_dv01: number | null
}

// portfolio/options_assignment_risk.py's per-leg score/flag, populated by
// main.py::_apply_option_assignment_risk_sweep() - keyed by leg contract
// symbol (string). Only ever populated for a short-call leg of a held
// multi-leg strategy when phase_v2.options_risk.assignment_risk_detector
// is enabled (default off) - {} / absent otherwise, not every held
// position gets an entry.
export interface AssignmentRiskLeg {
  score: number
  flag: boolean
}

// features/cross_asset_sensitivity.py's CROSS_ASSET_SENSITIVITY_FEATURE_NAMES -
// mirrors main.py::_cross_asset_sensitivity_for_symbol()'s return shape
// exactly. Neutral 0.0 (not null) per key, matching that function's own
// "never raises, 0.0 for too-little-history" contract.
export interface CrossAssetSensitivity {
  sens_vix_beta?: number
  sens_vix_interaction?: number
  sens_real_rate_beta?: number
  sens_real_rate_interaction?: number
  sens_credit_beta?: number
  sens_credit_interaction?: number
  sens_dollar_beta?: number
  sens_dollar_interaction?: number
}

export interface DividendEstimate {
  estimated_next_ex_date: string | null
  estimated_amount: number | null
  cadence_days: number | null
  confidence: 'low' | 'medium' | 'none' | string
  method: string
}

// data_pipeline/dividend_backfill.py::dividend_schedule_payload() - loaded
// once at main.py init into self._dividend_schedule_by_ticker, only when
// the same assignment_risk_detector flag above is enabled.
export interface DividendSchedule {
  ticker: string
  fetched_at: string
  history: { ex_date: string; amount: number }[]
  next_ex_dividend_estimate: DividendEstimate
}

// Lean's Slice.Splits, same-bar only (fires once, on the split event bar) -
// mirrors main.py's corporate_action_payload shape.
export interface CorporateActionEvent {
  split_factor: number
  reference_price: number
}

export interface Signal {
  ticker?: string
  symbol?: string
  security_type?: string
  trading_eligible?: boolean
  signal?: 'buy' | 'sell' | 'hold' | string
  probability_up?: number
  confidence?: number
  target_weight?: number
  execution_note?: string
  reason?: string
  dynamic_sizing?: DynamicSizing
  market_analysis?: MarketAnalysis
  topology?: TopologyContext
  liquidity?: LiquidityInfo
  // V5.1 Phase 1 (development/Problems.md #73) - the PRE-normalization
  // blended score and which model(s)/head(s) contributed it, alongside
  // predicted_rank_20d (the cross-sectional-normalized value) - see
  // portfolio/rank_signal.py.
  raw_rank_score?: number | null
  rank_source?: string
  // Also embedded in market_analysis.net_edge - surfaced top-level too for
  // the same reason liquidity is (a dedicated panel shouldn't need to
  // reach through market_analysis for it).
  net_edge?: NetEdge | null
  // Phase 3 of the 5/10 -> 9/10 roadmap (portfolio/book_construction.py):
  // the Stage-2 long/short book's role for this symbol, when
  // phase_v2.portfolio_book.enabled - null/absent for non-book-controlled
  // symbols or when the book overlay is off.
  portfolio_book_role?: 'long' | 'short' | 'flat' | string | null
  // Phase 4.8 - V4.7 features that were computed but never actually
  // reached state.json before this. Every field below is null/undefined
  // for the common case (equity/crypto symbols, or the relevant
  // detector/model being off/unloaded, which is this codebase's default) -
  // any consumer must render a graceful empty state, never assume presence.
  bond_analytics?: BondAnalytics | null
  // V5.1 Phase 2 (item 8 / F2) - per-symbol macro sensitivity betas.
  cross_asset_sensitivity?: CrossAssetSensitivity | null
  assignment_risk?: Record<string, AssignmentRiskLeg> | null
  dividend_schedule?: DividendSchedule | null
  strategy_selector_scores?: Record<string, number> | null
  corporate_action?: CorporateActionEvent | null
}

export interface Risk {
  trade_lock_active?: boolean
  trade_lock_reason?: string
  daily_drawdown?: number
  total_drawdown?: number
  max_daily_drawdown_pct?: number
  max_total_drawdown_pct?: number
  max_position_weight?: number
  target_daily_volatility?: number
  max_leverage?: number
  min_confidence_to_trade?: number
}

export interface Monitoring {
  mode?: string
  feeds?: Record<string, string>
  average_annualized_volatility?: number
  max_leverage_factor?: number
  active_signals?: number
  runtime_mode?: string
  allow_live_orders?: boolean
  observation_active?: boolean
}

export interface ScoreCard {
  key: string
  label: string
  value: number
  format: 'currency' | 'percent' | 'number' | string
}

export interface AssetHeatmapEntry {
  ticker: string
  strategy_return?: number
  excess_return?: number
  sharpe?: number
  max_drawdown?: number
  exposure_rate?: number
  trade_count?: number
  signal_bias?: string
}

export interface StrategyMetrics {
  total_return?: number
  annualized_return?: number
  annualized_volatility?: number
  sharpe?: number
  max_drawdown?: number
  hit_rate?: number
  average_daily_return?: number
}

export interface StrategySnapshot {
  rows?: number
  buy_threshold?: number
  sell_threshold?: number
  exposure_rate?: number
  trade_count?: number
  turnover?: number
  strategy?: StrategyMetrics
  buy_and_hold?: StrategyMetrics
  excess_return_vs_buy_and_hold?: number
}

export interface DashboardBlock {
  scorecards?: ScoreCard[]
  asset_heatmap?: AssetHeatmapEntry[]
  strategy_snapshot?: StrategySnapshot
  visualization_stage?: string
  runtime_mode?: string
  simulated_mode?: boolean
}

export interface SceneNode {
  id: string
  label: string
  kind: 'portfolio' | 'asset' | string
  x: number
  y: number
  z: number
  intensity: number
  value: number
  detail?: string
}

export interface SceneLink {
  source: string
  target: string
  strength: number
}

export interface Scene {
  layout?: string
  nodes: SceneNode[]
  links: SceneLink[]
  dimensions?: { width: number; height: number; depth: number }
}

export interface TopologyNode {
  symbol: string
  cluster_id: string
  x: number
  y: number
  z: number
  market_distance: number
  correlation_strength: number
  volatility_pressure: number
  topology_risk: 'isolated' | 'normal' | 'elevated' | string
  regime_label: string
  // V2-17.5 - see TopologyContext for field meanings; same shape, this is
  // the node as it appears in topology.nodes rather than a per-signal copy.
  topology_source?: 'deterministic' | 'learned' | 'hybrid' | 'fallback' | string
  cluster_probs?: Record<string, number>
  topology_confidence?: number
  topology_uncertainty?: number
  stress_score?: number
  neighbor_shift_score?: number
  topology_disagreement?: number
  learned_neighbors?: string[]
  cluster_dominant_regime_label?: string
}

export interface TopologyLink {
  source: string
  target: string
  correlation: number
  distance: number
}

export interface TopologyCluster {
  cluster_id: string
  members: string[]
  average_correlation: number
  dominant_regime_label: string
}

export interface Topology {
  state?: string
  nodes: TopologyNode[]
  links: TopologyLink[]
  clusters: TopologyCluster[]
  dimensions?: { width: number; height: number; depth: number }
  reasons?: string[]
  // V2-17.5 - bar-level learned-topology summary. topology_source reflects
  // the mix across all nodes: "learned" only if every node was learned,
  // "fallback" if the model is missing or every node fell back, "hybrid"
  // otherwise.
  topology_source?: 'deterministic' | 'learned' | 'hybrid' | 'fallback' | string
  model_loaded?: boolean
  model_version_id?: string | null
  learned_neighbors_by_symbol?: Record<string, string[]>
}

export interface NeuralNetworkLayer {
  index: number
  type: string
  in_features?: number | null
  out_features?: number | null
  weight_abs_mean?: number | null
  weight_abs_max?: number | null
  // Which multitask/sequence head this layer belongs to (e.g. "direction",
  // "magnitude", "volatility"), or null/absent for a trunk layer (or for
  // any layer of a flat, non-branching network like baseline/expert/gating).
  head?: string | null
}

export interface RankIcSummary {
  mean_ic: number
  std_ic: number
  t_stat: number
  num_dates: number
}

// Phase 2 of the 5/10 -> 9/10 roadmap: the code-enforced promotion-gate
// verdict (train.py::assess_ranking_quality()) - distinct from
// NeuralNetworkModel.quality_status (the older direction-model gate).
// Per-era diagnostic (development/Problems.md #71) - one entry per
// non-overlapping era from train.py::assess_ranking_quality_from_predictions(),
// so a promotion-gate failure is traceable to which era and when, not just
// a count.
export interface RankingQualityEraDiagnostic {
  era_index: number
  era_start: string
  era_end: string
  num_dates: number
  mean_ic: number
  t_stat: number
}

export interface RankingQualitySummary {
  quality_status: 'promotable' | 'watchlist' | 'not_promotable' | string
  promotion_eligible: boolean
  failures: string[]
  near_misses: string[]
  observed: {
    non_overlapping_t_stat: number
    non_overlapping_mean_ic: number
    bootstrap_ci_lower_bound: number
    bootstrap_ci_upper_bound: number
    num_eras: number
    num_opposite_sign_eras: number
    num_insufficient_data_eras: number
    per_era: RankingQualityEraDiagnostic[]
  }
}

// V5.1 Phase 4 (items 7, 12): train.py::assess_net_performance_quality()'s
// verdict - mirrors RankingQualitySummary's shape (quality_status/
// promotion_eligible/failures/near_misses/observed), but over net
// Sharpe/turnover/capacity/double-cost-stress instead of rank-IC.
export interface NetPerformanceSummary {
  quality_status: 'promotable' | 'watchlist' | 'not_promotable' | string
  promotion_eligible: boolean
  failures: string[]
  near_misses: string[]
  observed: {
    net_sharpe: number
    annualized_turnover: number
    capacity_usd: number
    double_cost_net_sharpe: number | null
  }
}

export interface NeuralNetworkModel {
  name: string
  label: string
  role: 'baseline' | 'expert' | 'gating' | 'multitask' | 'expert_multitask' | 'sequence' | string
  status: 'trained' | 'not_trained' | string
  quality_status?: 'stable' | 'watchlist' | 'disabled_for_gating' | 'learned' | string | null
  node_layers: number[]
  layers: NeuralNetworkLayer[]
  total_layers: number
  total_nodes: number
  total_edges: number
  last_modified?: string | null
  // Present (non-empty) only for multitask/sequence networks: each output
  // head's own node_layers, branching off node_layers' final width. Empty
  // object for flat networks (baseline/expert/gating).
  heads?: Record<string, number[]>
  // Multi-horizon/ranking evaluation (Phase 3/4/6) - only populated for
  // baseline_multitask/sequence (the two networks with horizon_5d/20d and
  // rank_5d/20d heads; experts/expert_multitask stay 1d-direction-only by
  // design). null when the network has no such heads, or hasn't been
  // retrained since these metrics existed.
  horizon_mcc?: { direction_5d: number | null; direction_20d: number | null } | null
  // sector_neutral_rank_20d (Phase 5 of the 5/10 -> 9/10 roadmap): same
  // RankIcSummary shape as rank_5d/20d, sector-demeaned instead of
  // universe-wide - see build_cross_sectional_rank_targets()'s docstring.
  // residual_rank_5d/20d (V5.1 Phase 2, item 5): combined market+sector+
  // size-residualized rank targets - see train.py::build_residual_rank_targets()'s
  // docstring. beta_neutral_rank_20d ships enabled:false by default (see
  // config.json's horizon_heads) so is deliberately not surfaced here yet.
  rank_ic?: {
    rank_5d: RankIcSummary | null
    rank_20d: RankIcSummary | null
    sector_neutral_rank_20d?: RankIcSummary | null
    residual_rank_5d?: RankIcSummary | null
    residual_rank_20d?: RankIcSummary | null
  } | null
  // Per-head promotion-gate verdict, same head keys as rank_ic above -
  // null when the backtest run didn't compute a ranking_promotion_config
  // (e.g. an older artifact predating Phase 2).
  ranking_quality?: {
    rank_5d: RankingQualitySummary | null
    rank_20d: RankingQualitySummary | null
    sector_neutral_rank_20d?: RankingQualitySummary | null
    residual_rank_5d?: RankingQualitySummary | null
    residual_rank_20d?: RankingQualitySummary | null
  } | null
  // V5.1 Phase 4 (items 7, 12) - only the ONE head
  // phase1.target.ranking.net_performance.head is configured for (default
  // rank_20d) has a non-null entry; every other head key stays null.
  net_performance?: {
    rank_5d: NetPerformanceSummary | null
    rank_20d: NetPerformanceSummary | null
    sector_neutral_rank_20d?: NetPerformanceSummary | null
    residual_rank_5d?: NetPerformanceSummary | null
    residual_rank_20d?: NetPerformanceSummary | null
  } | null
  regression_quality?: { magnitude: string | null; volatility: string | null } | null
  // V5.1 Phase 3 (items 1, 10, 11) - the actual optimizer/schedule/batch-
  // mode/ranking-loss/SWA recipe this candidate trained with. null for
  // baseline/expert/gating or an older pre-Phase-3 artifact.
  training_recipe?: TrainingRecipe | null
}

// train_multitask.py/train_sequence.py's "training_recipe" metrics field -
// see compute_combined_multitask_loss()'s docstring in train.py for the
// underlying ranking_loss/date_group_ids contract this describes.
export interface TrainingRecipe {
  optimizer: 'adam' | 'adamw' | string
  lr_schedule: 'none' | 'cosine' | string
  normalization?: 'none' | 'layernorm' | string
  batch_mode: 'random' | 'cross_sectional' | string
  ranking_loss: {
    objective: 'mse' | 'soft_spearman' | 'listnet' | string
    temperature?: number
    listnet_temperature?: number
    mse_anchor_weight?: number
  } | null
  swa: { enabled: boolean; epochs_averaged: number }
  early_stop_metric: string
  early_stop_head: string
  early_stop_smoothing_epochs: number
}

export interface NeuralNetworkExcluded {
  name: string
  reason: string
}

export interface NeuralNetworkState {
  generated_at?: string
  networks: NeuralNetworkModel[]
  totals: {
    total_networks: number
    total_layers: number
    total_nodes: number
    total_edges: number
    trained_count: number
  }
  excluded: NeuralNetworkExcluded[]
}

export interface ObservationSummary {
  mode?: string
  allow_live_orders?: boolean
  is_observation_mode?: boolean
  visually_distinct_banner?: string
  count_observations?: number
  signal_distribution?: Record<string, number>
  action_distribution?: Record<string, number>
  rejected_by_reason?: Record<string, number>
  simulated_win_loss?: { wins: number; losses: number; win_rate: number }
  simulated_sharpe?: number
  simulated_max_drawdown?: number
  simulated_equity?: number
  simulated_cash?: number
  simulated_drawdown?: number
  simulated_exposure?: number
  simulated_turnover?: number
}

export interface PerformanceTrigger {
  trigger_id: string
  created_at: string
  trigger_type: string
  severity: 'info' | 'warning' | 'critical' | string
  mode?: string
  scope: string
  metric_value?: number
  threshold?: number
  message: string
  recommended_action: string
  retrain_candidate: boolean
}

export interface PerformanceTriggerReport {
  generated_at?: string
  source_event_count?: number
  enabled?: boolean
  source?: string
  triggers: PerformanceTrigger[]
  summary?: {
    active_trigger_count: number
    severity_distribution?: Record<string, number>
    retrain_candidate: boolean
    latest_trigger: PerformanceTrigger | null
    trigger_type_counts?: Record<string, number>
  }
}

export interface ActiveModelSummary {
  model_version_id: string
  status?: string
  created_at: string
  metrics?: Record<string, unknown>
  aether_vault_commit?: string | null
}

export interface RetrainingEventSummary {
  retraining_id: string
  source_trigger_id?: string | null
  candidate_version_id?: string | null
  created_at: string
  status: string
  reason: string
}

// V5.1 Phase 6 (production safety) - retraining/auto_rollback.py::
// select_rollback_target()'s return shape, wrapped by retraining/
// status_export.py::build_status_view()'s read-only diagnostic snapshot.
// kill_switch_tripped/net_sharpe_decay/rank_ic_decay are always false in
// THIS snapshot (this exporter has no live-signal input wired in - the
// real enforcement path is retraining/worker.py::RetrainingWorker.
// check_auto_rollback(), which runs with real live signals but writes no
// webui-visible artifact of its own beyond this same retraining_status.json
// on its next status() call).
export interface AutoRollbackDecision {
  should_rollback: boolean
  to_version_id: string | null
  reason: string
  failures: string[]
}

export interface AutoRollback {
  config: Record<string, unknown>
  degradation_signals: {
    kill_switch_tripped: boolean
    net_sharpe_decay: boolean
    rank_ic_decay: boolean
    bars_since_promotion: number | null
    bars_since_last_rollback: number | null
  }
  decision: AutoRollbackDecision
}

export interface RetrainingStatus {
  generated_at?: string
  active_model: ActiveModelSummary | null
  latest_candidate: ActiveModelSummary | null
  last_trigger: PerformanceTrigger | null
  latest_retraining_event: RetrainingEventSummary | null
  validation_status?: string
  rollback_available: boolean
  rollback_candidates: { model_version_id: string; created_at: string }[]
  auto_rollback?: AutoRollback
}

export interface PaperReadinessCheck {
  pass: boolean
  value: number | string
  threshold: number | string
}

export interface PaperReadiness {
  generated_at?: string
  ready: boolean
  checks: Record<string, PaperReadinessCheck>
  blocking_reasons: string[]
  broker_config_present: boolean
  broker_config_reason: string
}

// monitoring/assets_status.py::build_assets_status() - IB/futures/options/
// FRED readiness, computed live on every /api/assets-status request (not
// embedded in RuntimeState/state.json, unlike paper_readiness/
// retraining_status - see fetchAssetsStatus() in api/client.ts).
export interface AssetsStatus {
  ib_status: 'disabled' | 'enabled_but_lean_credentials_missing' | 'ready' | string
  futures_risk_enabled: boolean
  options_risk_enabled: boolean
  forex_risk_enabled: boolean
  futures_contract_specs_loaded: number
  futures_contract_specs_tickers: string[]
  forex_pair_specs_loaded: number
  forex_pair_specs_tickers: string[]
  fred_cache_series_count: number
  fred_cache_most_recent_date: string | null
  configured_futures_assets: number
  configured_options_assets: number
  configured_forex_assets: number
}

// monitoring/strategy_catalog.py::build_strategy_catalog() -
// portfolio/options_strategy.py::MULTI_LEG_STRATEGY_REGISTRY's 43 entries,
// static (never changes at runtime), served by its own /api/strategies
// endpoint rather than embedded in RuntimeState/state.json - see that
// endpoint's own docstring for why.
export interface StrategyCatalogEntry {
  name: string
  leg_count: number
  risk_tier: string
  shape_family: string
  has_expiry_pair: boolean
}

export interface StrategyCatalog {
  strategies: StrategyCatalogEntry[]
  total_count: number
}

// One options-chain row - mirrors main.py::_build_options_chains_payload()'s
// row shape after _options_chains_payload_for_state()'s JSON-safe
// stringify-symbol pass (never the raw Lean Symbol object).
export interface OptionsChainRow {
  symbol: string
  strike: number
  right: 'call' | 'put' | string
  expiry: string
  bid: number
  ask: number
  volume: number
  open_interest: number
  delta: number
  gamma: number
  theta: number
  vega: number
  rho: number
  iv: number
}

export interface FuturesChainEntry {
  front_month_price: number | null
  next_month_price: number | null
}

// main.py::_write_state()'s "derivatives" block - the SAME per-bar payloads
// route_position_sizing()/_build_model_input() already consume for sizing
// and features, now also surfaced for the webui (previously computed but
// never exposed anywhere outside the runtime).
export interface DerivativesState {
  macro?: {
    futures_term_structure_slope?: number
    options_put_call_ratio?: number
    options_implied_vol_skew?: number
  }
  options_chains?: Record<string, OptionsChainRow[]>
  futures_chains?: Record<string, FuturesChainEntry>
}

// main.py::_write_state()'s "macro" block (V4.12.2, development/Problems.md
// #71) - self.latest_bond_payload (_build_bond_payload(), real Treasury/
// credit-spread observations) merged with self.latest_alt_data_payload
// (_build_alt_data_payload(), VIX/VXV/NFCI-derived) - both already fed every
// symbol's model input every bar, previously never reached state.json.
export interface MacroSnapshot {
  yield_curve_level?: number | null
  yield_curve_slope?: number | null
  yield_curve_curvature?: number | null
  credit_spread_level?: number | null
  treasury_10yr_level?: number | null
  treasury_3mo_level?: number | null
  treasury_2yr_level?: number | null
  treasury_5yr_level?: number | null
  implied_volatility_level?: number | null
  implied_vol_term_structure?: number | null
  financial_conditions_change?: number | null
  // V5.1 Phase 2 (item 8 / F2) - raw as-of levels for the 4 cross-asset
  // sensitivity drivers (features/cross_asset_sensitivity.py); "credit" is
  // omitted here since bond_credit_spread_level above already covers it.
  // Informational only - the model reads per-symbol sensitivity BETAS, not
  // these broadcast levels. Keyed by driver (vix/real_rate/credit/dollar),
  // any of which may be null pre-first-bar or if FRED backfill is missing.
  sensitivity_driver_levels?: {
    vix?: number | null
    real_rate?: number | null
    credit?: number | null
    dollar?: number | null
  }
}

export interface RuntimeState {
  project?: string
  mode?: string
  updated_at?: string
  insight?: string
  portfolio: Portfolio
  positions: Position[]
  signals: Record<string, Signal>
  risk?: Risk
  dashboard?: DashboardBlock
  monitoring?: Monitoring
  scene?: Scene
  topology?: Topology
  derivatives?: DerivativesState
  macro?: MacroSnapshot
  observation?: ObservationSummary
  performance_triggers?: PerformanceTriggerReport
  retraining_status?: RetrainingStatus
  paper_readiness?: PaperReadiness
  // V5.1 Phase 1 (development/Problems.md #73 / item 6) - resolved once
  // per run (rank_signal) / refreshed on the book's last rebalance bar
  // (book_neutrality, {} pre-first-rebalance or when disabled).
  rank_signal?: RankSignalPolicy
  book_neutrality?: BookNeutralityDiagnostics
  // V5.1 Phase 6 (production safety) - evaluated once per bar in main.py::
  // _refresh_risk_state(), see KillSwitchDecision/ReconciliationReport's
  // own docstrings above for each field's steady-state default.
  kill_switch?: KillSwitchDecision
  reconciliation?: ReconciliationReport
}
