import type { CapacityReport, CostStressReport } from '../../types/evaluation'
import { isNotEvaluated, type EvaluationState } from '../../types/evaluation'
import { Panel } from '../layout/Panel'

function EmptyState({ hintCommand }: { hintCommand: string }) {
  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-6 text-center text-sm text-white/50">
      Not evaluated yet — run{' '}
      <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-orange-300">{hintCommand}</code>
    </div>
  )
}

function formatUsd(value: number): string {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`
  return `$${value.toFixed(0)}`
}

// V5.1 Phase 0 - the breadth check (is the edge concentrated in a handful
// of names, or genuinely spread across the cross-section?) plus the
// capacity/cost-stress robustness numbers item 12 of the V5.1 roadmap asks
// for, all sourced from one `aq evaluate --capacity --stress` run.
export function CapacityStressPanel({ evaluation }: { evaluation: EvaluationState | undefined }) {
  const capacity = evaluation?.capacity
  const stress = evaluation?.stress

  return (
    <Panel title="Capacity & Cost Stress">
      <div className="grid gap-3">
        <div>
          <h3 className="mb-1.5 text-[0.7rem] uppercase tracking-widest text-white/40">Breadth &amp; Capacity</h3>
          {!capacity || isNotEvaluated(capacity) ? (
            <EmptyState hintCommand="aq evaluate --capacity" />
          ) : (
            (() => {
              const report = capacity as CapacityReport
              return (
                <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-white">Capacity: {formatUsd(report.capacity_usd)}</span>
                    <span className="text-xs text-white/50">binding: {report.binding_ticker ?? '—'}</span>
                  </div>
                  <table className="mt-2 w-full border-collapse text-xs">
                    <thead>
                      <tr className="text-left text-white/40">
                        <th className="pr-3 font-normal">top_n</th>
                        <th className="pr-3 font-normal">net Sharpe</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.per_top_n.map((row) => (
                        <tr key={row.top_n} className="text-white/70">
                          <td className="pr-3">{row.top_n}</td>
                          <td className="pr-3">{row.net_sharpe.toFixed(3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            })()
          )}
        </div>

        <div>
          <h3 className="mb-1.5 text-[0.7rem] uppercase tracking-widest text-white/40">Cost Stress</h3>
          {!stress || isNotEvaluated(stress) ? (
            <EmptyState hintCommand="aq evaluate --stress" />
          ) : (
            (() => {
              const report = stress as CostStressReport
              return (
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="text-left text-white/40">
                      <th className="pr-3 font-normal">multiplier</th>
                      <th className="pr-3 font-normal">net Sharpe</th>
                      <th className="pr-3 font-normal">net return</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.entries.map((entry) => (
                      <tr key={entry.cost_multiplier} className={entry.net_sharpe > 0 ? 'text-emerald-300/80' : 'text-rose-300/80'}>
                        <td className="pr-3">{entry.cost_multiplier}x</td>
                        <td className="pr-3">{entry.net_sharpe.toFixed(3)}</td>
                        <td className="pr-3">{(entry.net_total_return * 100).toFixed(2)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            })()
          )}
        </div>
      </div>
    </Panel>
  )
}
