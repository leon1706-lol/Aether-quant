// Raw shape returned by monitoring/api_server.py's csv.DictReader-backed
// /api/grafana/* endpoints - every value is still a string, parsed downstream.
export type CsvRow = Record<string, string>

export interface RuntimeMetricsSnapshot {
  project?: string
  phase?: string
  mode?: string
  updated_at?: string
  portfolio_value?: number
  cash?: number
  holdings_value?: number
  invested_positions?: number
  active_signals?: number
  average_confidence?: number
  average_moe_probability?: number
  average_annualized_volatility?: number
  max_leverage_factor?: number
  daily_drawdown?: number
  total_drawdown?: number
  trade_lock_active?: boolean
  dominant_primary_regime?: string
  dominant_risk_regime?: string
  runtime_mode?: string
  allow_live_orders?: boolean
}
