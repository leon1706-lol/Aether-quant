import type { RuntimeMetricsSnapshot } from '../../types/tracing'
import { formatCurrency, formatNumber, formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'

export function MetricsSnapshotPanel({ snapshot }: { snapshot: RuntimeMetricsSnapshot | undefined }) {
  const metrics: [string, string][] = [
    ['Portfolio Value', formatCurrency(snapshot?.portfolio_value)],
    ['Cash', formatCurrency(snapshot?.cash)],
    ['Active Signals', String(snapshot?.active_signals ?? 0)],
    ['Avg Confidence', formatPercent(snapshot?.average_confidence)],
    ['Avg MoE Probability', formatPercent(snapshot?.average_moe_probability)],
    ['Avg Annualized Vol', formatPercent(snapshot?.average_annualized_volatility)],
    ['Max Leverage Factor', formatNumber(snapshot?.max_leverage_factor)],
    ['Daily Drawdown', formatPercent(snapshot?.daily_drawdown)],
    ['Total Drawdown', formatPercent(snapshot?.total_drawdown)],
  ]

  return (
    <Panel title="Runtime Metrics Snapshot">
      {snapshot?.trade_lock_active && (
        <div className="mb-3 rounded-2xl border border-rose-400/40 bg-rose-400/10 px-4 py-3 text-rose-300">
          <strong>TRADE LOCK ACTIVE</strong>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
        {metrics.map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
            <small className="text-white/60">{label}</small>
            <div className="text-sm text-white">{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-3 grid min-w-0 gap-1 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-sm text-white/80">
        <span>
          Regime: <strong className="text-white">{snapshot?.dominant_primary_regime ?? '-'}</strong> ·{' '}
          {snapshot?.dominant_risk_regime ?? '-'}
        </span>
        <span className="text-xs text-white/40">
          runtime mode: {snapshot?.runtime_mode ?? '-'} · updated {snapshot?.updated_at ?? '-'}
        </span>
      </div>
    </Panel>
  )
}
