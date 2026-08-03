import type { MetricStabilitySummary, MetricWindowSummary } from '../../types/evaluation'
import { isNotEvaluated, type EvaluationState } from '../../types/evaluation'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V5.1 Phase 4 (item 4) - a tiny dependency-free sparkline: one bar per
// walk-forward window's metric value, height scaled to the window with the
// largest |value| in the series. Zero external charting library, matching
// this webui's existing lightweight-panel convention.
function Sparkline({ values }: { values: number[] }) {
  if (values.length === 0) return null
  const maxAbs = Math.max(...values.map((value) => Math.abs(value)), 1e-9)
  return (
    <div className="flex h-8 items-end gap-0.5">
      {values.map((value, index) => {
        const heightPct = Math.max(8, (Math.abs(value) / maxAbs) * 100)
        const positive = value >= 0
        return (
          <div
            key={index}
            title={`window ${index}: ${value.toFixed(4)}`}
            className={`w-1.5 rounded-t ${positive ? 'bg-emerald-400/70' : 'bg-rose-400/70'}`}
            style={{ height: `${heightPct}%` }}
          />
        )
      })}
    </div>
  )
}

function MetricRow({
  name,
  windowSummary,
  stability,
}: {
  name: string
  windowSummary: MetricWindowSummary | undefined
  stability: MetricStabilitySummary
}) {
  const bootstrap = windowSummary?.cross_window_bootstrap
  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-white">{name}</span>
        <Badge tone={stability.stable ? 'trade' : 'reduce_risk'}>{stability.stable ? 'stable' : 'unstable'}</Badge>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-white/60 sm:grid-cols-4">
        <div>
          mean: <span className="text-white">{stability.mean.toFixed(4)}</span>
        </div>
        {bootstrap && (
          <div>
            95% CI: <span className="text-white">[{bootstrap.lower_bound.toFixed(4)}, {bootstrap.upper_bound.toFixed(4)}]</span>
          </div>
        )}
        <div>
          sign flips: <span className="text-white">{(stability.sign_flip_fraction * 100).toFixed(0)}%</span>
        </div>
        <div>
          windows: <span className="text-white">{stability.num_windows}</span>
        </div>
      </div>
      {windowSummary && windowSummary.per_window_metric_values.length > 0 && (
        <div className="mt-2">
          <Sparkline values={windowSummary.per_window_metric_values} />
        </div>
      )}
      {stability.failures.length > 0 && (
        <div className="mt-1 text-xs text-rose-300">{stability.failures.join(', ')}</div>
      )}
    </div>
  )
}

// V5.1 Phase 4 (item 4) - the multi-regime stability readout: one row per
// walk_forward.tracked_metrics entry, sourced from train.py::_run_walk_forward()'s
// summary_by_metric/stability_by_metric (never computed in the webui
// itself - a pure display layer over ml/versions/walk-forward-*/
// walk_forward_summary.json, same read-only contract as every other
// Evaluation-tab panel).
export function WalkForwardStabilityPanel({ evaluation }: { evaluation: EvaluationState | undefined }) {
  const walkForward = evaluation?.walk_forward

  if (!walkForward || isNotEvaluated(walkForward)) {
    return (
      <Panel title="Walk-Forward Stability">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-6 text-center text-sm text-white/50">
          Not evaluated yet — run{' '}
          <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-orange-300">
            aq train --walk-forward --include-multitask --include-sequence
          </code>
        </div>
      </Panel>
    )
  }

  const stabilityByMetric = walkForward.stability_by_metric ?? {}
  const summaryByMetric = walkForward.summary_by_metric ?? {}
  const metricNames = Object.keys(stabilityByMetric)
  const netPerformanceWindows = walkForward.net_performance_by_window ?? []

  return (
    <Panel
      title="Walk-Forward Stability"
      action={<Badge tone="observe">{walkForward.num_windows} windows</Badge>}
    >
      {metricNames.length === 0 ? (
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-6 text-center text-sm text-white/50">
          No tracked metrics recorded for this run.
        </div>
      ) : (
        <div className="flex flex-col gap-2.5">
          {metricNames.map((name) => (
            <MetricRow key={name} name={name} windowSummary={summaryByMetric[name]} stability={stabilityByMetric[name]} />
          ))}
        </div>
      )}
      {netPerformanceWindows.length > 0 && (
        <div className="mt-3 text-xs text-white/60">
          Net-performance simulated for {netPerformanceWindows.length} of {walkForward.num_windows} window(s) — mean
          net Sharpe:{' '}
          <span className="text-white">
            {(
              netPerformanceWindows.reduce((sum, window) => sum + window.simulation.net_sharpe, 0) /
              netPerformanceWindows.length
            ).toFixed(3)}
          </span>
        </div>
      )}
    </Panel>
  )
}
