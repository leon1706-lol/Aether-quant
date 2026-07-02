import type { PerformanceTriggerReport } from '../../types/state'
import { Panel } from '../layout/Panel'
import { CountTable } from './CountTable'

function formatNumber(value: number | undefined, digits = 2): string {
  if (value === undefined || Number.isNaN(value)) return '-'
  return value.toFixed(digits)
}

export function PerformanceTriggersPanel({ report }: { report: PerformanceTriggerReport | undefined }) {
  const summary = report?.summary
  const latest = summary?.latest_trigger

  const metrics: [string, string][] = [
    ['Active Triggers', String(summary?.active_trigger_count ?? 0)],
    ['Info', String(summary?.severity_distribution?.info ?? 0)],
    ['Warning', String(summary?.severity_distribution?.warning ?? 0)],
    ['Critical', String(summary?.severity_distribution?.critical ?? 0)],
  ]

  return (
    <Panel title="Performance Triggers">
      {summary?.retrain_candidate ? (
        <div className="mb-3 rounded-2xl border border-rose-400/40 bg-rose-400/10 px-4 py-3 text-rose-300">
          <strong>RETRAIN CANDIDATE DETECTED</strong>
          {latest && <div className="text-xs text-rose-200/80">{latest.message}</div>}
        </div>
      ) : (
        <div className="mb-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-white/60">
          <small>No retrain signal</small>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2.5">
        {metrics.map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
            <small className="text-white/60">{label}</small>
            <div className="text-sm text-white">{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-3 grid min-w-0 gap-1 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
        <strong className="text-xs uppercase tracking-widest text-white/60">Latest Trigger</strong>
        {latest ? (
          <div className="grid gap-1 text-sm text-white/80">
            <span className="break-words">{latest.message}</span>
            <span className="text-xs text-white/40">
              {latest.trigger_type} · {latest.scope} · {formatNumber(latest.metric_value, 3)} vs threshold{' '}
              {formatNumber(latest.threshold, 3)} · {latest.recommended_action}
            </span>
          </div>
        ) : (
          <small className="text-white/40">No data yet</small>
        )}
      </div>

      <div className="mt-3 min-w-0">
        <CountTable title="Trigger Type Counts" counts={summary?.trigger_type_counts} />
      </div>
    </Panel>
  )
}
