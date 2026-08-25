import type { BenchmarkBaseline, BenchmarkComparisonReport } from '../../types/evaluation'
import { isNotEvaluated, type EvaluationState } from '../../types/evaluation'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V5.4.4 - Benchmark Comparison panel: renders ml/evaluation/
// benchmark_comparison.json (aq evaluate --benchmarks) served via
// /api/evaluation - the rank book's edge stated against naive strategy
// baselines (momentum/mean-reversion/random-entry) and public benchmarks
// (SPY buy-and-hold, daily-rebalanced 60/40 SPY-TLT), all on the same
// dataset window. Pure display layer - same read-only contract as every
// other panel on this page.

function strategyLabel(strategy: string): string {
  const labels: Record<string, string> = {
    momentum: 'Momentum top-N/L-N',
    mean_reversion: 'Mean reversion',
    random_entry: 'Random entry',
    sp500: 'S&P 500 (SPY buy & hold)',
    '60_40': '60/40 SPY-TLT (daily rebal.)',
  }
  return labels[strategy] ?? strategy
}

function BaselineRow({ baseline }: { baseline: BenchmarkBaseline }) {
  const skipped = baseline.status !== undefined && baseline.status !== 'OK'
  const isPublic = baseline.strategy === 'sp500' || baseline.strategy === '60_40'
  return (
    <tr className={`border-t border-white/5 ${skipped ? 'opacity-50' : ''}`} data-testid={`bench-row-${baseline.strategy}`}>
      <td className="py-1.5 pr-3">
        <span className={isPublic ? 'text-white' : 'text-white/80'}>{strategyLabel(baseline.strategy)}</span>
      </td>
      <td className="py-1.5 pr-3 text-right">
        {baseline.net_sharpe === null ? (
          <span className="text-white/40">—</span>
        ) : (
          <span className={baseline.net_sharpe >= 0 ? 'text-emerald-300' : 'text-rose-300'}>
            {baseline.net_sharpe >= 0 ? '+' : ''}
            {baseline.net_sharpe.toFixed(3)}
          </span>
        )}
      </td>
      <td className="py-1.5 pr-3 text-right">
        {baseline.total_return_pct === null ? (
          <span className="text-white/40">—</span>
        ) : (
          <span className={baseline.total_return_pct >= 0 ? 'text-emerald-300' : 'text-rose-300'}>
            {baseline.total_return_pct >= 0 ? '+' : ''}
            {baseline.total_return_pct.toFixed(2)}%
          </span>
        )}
      </td>
      <td className="py-1.5 text-xs text-white/40">
        {skipped ? baseline.status : isPublic ? 'public benchmark' : 'naive strategy'}
      </td>
    </tr>
  )
}

export function BenchmarkPanel({ evaluation }: { evaluation: EvaluationState | undefined }) {
  const report = evaluation?.benchmarks

  if (!report || isNotEvaluated(report)) {
    return (
      <Panel title="Benchmark Comparison">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-6 text-center text-sm text-white/50">
          Not evaluated yet — run{' '}
          <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-orange-300">aq evaluate --benchmarks</code>
        </div>
      </Panel>
    )
  }

  const benchmarks = report as BenchmarkComparisonReport
  return (
    <Panel
      title="Benchmark Comparison"
      action={<Badge tone="observe">net Sharpe vs baselines{benchmarks.split ? ` · ${benchmarks.split}` : ''}</Badge>}
    >
      <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="text-left text-white/40">
              <th className="py-1 pr-3 font-normal">strategy</th>
              <th className="py-1 pr-3 text-right font-normal">net sharpe</th>
              <th className="py-1 pr-3 text-right font-normal">total return</th>
              <th className="py-1 font-normal">note</th>
            </tr>
          </thead>
          <tbody>
            {benchmarks.baselines.map((baseline) => (
              <BaselineRow key={baseline.strategy} baseline={baseline} />
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
