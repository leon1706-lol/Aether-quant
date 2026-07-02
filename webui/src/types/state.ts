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
}
