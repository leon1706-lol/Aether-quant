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
}
