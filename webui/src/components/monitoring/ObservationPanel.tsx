import type { ObservationSummary } from '../../types/state'
import { Panel } from '../layout/Panel'

function formatNumber(value: number | undefined, digits = 2): string {
  if (value === undefined || Number.isNaN(value)) return '-'
  return value.toFixed(digits)
}

function CountTable({ title, counts }: { title: string; counts: Record<string, number> | undefined }) {
  const entries = Object.entries(counts ?? {})

  return (
    <div className="grid min-w-0 gap-2">
      <strong className="text-xs uppercase tracking-widest text-slate-400">{title}</strong>
      {entries.length > 0 ? (
        <div className="grid gap-1">
          {entries.map(([label, count]) => (
            <div key={label} className="flex items-start justify-between gap-3 border-t border-white/5 py-1 text-sm">
              <span className="min-w-0 break-words text-slate-300">{label}</span>
              <span className="shrink-0 text-slate-400">{count}</span>
            </div>
          ))}
        </div>
      ) : (
        <small className="text-slate-500">No data yet</small>
      )}
    </div>
  )
}

export function ObservationPanel({ observation }: { observation: ObservationSummary | undefined }) {
  const metrics: [string, string][] = [
    ['Observations', String(observation?.count_observations ?? 0)],
    ['Simulated Equity', formatNumber(observation?.simulated_equity)],
    ['Simulated Exposure', formatNumber(observation?.simulated_exposure)],
    ['Simulated Drawdown', formatNumber(observation?.simulated_drawdown)],
    ['Simulated Turnover', formatNumber(observation?.simulated_turnover)],
    ['Simulated Sharpe', formatNumber(observation?.simulated_sharpe)],
    ['Simulated Max Drawdown', formatNumber(observation?.simulated_max_drawdown)],
    ['Win Rate', formatNumber(observation?.simulated_win_loss?.win_rate)],
  ]

  return (
    <Panel title="Observation Mode">
      {observation?.is_observation_mode ? (
        <div className="mb-3 rounded-2xl border border-amber-400/40 bg-amber-400/10 px-4 py-3 text-amber-300">
          <strong>{observation.visually_distinct_banner ?? 'SIMULATED - NOT REAL TRADES'}</strong>
          <div className="text-xs text-amber-200/80">runtime mode: {observation.mode}</div>
        </div>
      ) : (
        <div className="mb-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-slate-400">
          <small>Not currently running in observation mode (runtime mode: {observation?.mode ?? 'unknown'})</small>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2.5">
        {metrics.map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
            <small className="text-slate-400">{label}</small>
            <div className="text-sm text-slate-200">{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
        <CountTable title="Signal Distribution" counts={observation?.signal_distribution} />
        <CountTable title="Rejected By Reason" counts={observation?.rejected_by_reason} />
      </div>
    </Panel>
  )
}
