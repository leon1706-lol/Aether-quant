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

export interface DynamicSizing {
  base_target_weight?: number
  target_weight?: number
  annualized_volatility?: number
  leverage_factor?: number
  volatility_regime?: string
  sizing_reason?: string
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
  rank_ic?: { rank_5d: RankIcSummary | null; rank_20d: RankIcSummary | null } | null
  regression_quality?: { magnitude: string | null; volatility: string | null } | null
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

export interface RetrainingStatus {
  generated_at?: string
  active_model: ActiveModelSummary | null
  latest_candidate: ActiveModelSummary | null
  last_trigger: PerformanceTrigger | null
  latest_retraining_event: RetrainingEventSummary | null
  validation_status?: string
  rollback_available: boolean
  rollback_candidates: { model_version_id: string; created_at: string }[]
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
  observation?: ObservationSummary
  performance_triggers?: PerformanceTriggerReport
  retraining_status?: RetrainingStatus
  paper_readiness?: PaperReadiness
}
