import type { MonteCarloReport, MonteCarloPercentiles } from '../../types/evaluation'
import { isNotEvaluated, type EvaluationState } from '../../types/evaluation'
import { Panel } from '../layout/Panel'

// V5.3.8 - Monte Carlo simulation testing layer panel: renders the
// ml/evaluation/monte_carlo.json summary served via /api/evaluation -
// headline distribution table + an inline SVG of the average equity curve
// with its p5/p95 band (the README's full all-runs chart stays the
// canonical visual; this panel is the at-a-glance webui mirror).
export function MonteCarloPanel({ evaluation }: { evaluation: EvaluationState | undefined }) {
  const report = evaluation?.monte_carlo

  if (!report || isNotEvaluated(report)) {
    return (
      <Panel title="Monte Carlo Simulation">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-6 text-center text-sm text-white/50">
          Not evaluated yet — run{' '}
          <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-orange-300">
            aq evaluate --rank-book --monte-carlo
          </code>
        </div>
      </Panel>
    )
  }

  const mc = report as MonteCarloReport
  const cfg = mc.config

  function buildPath(values: number[], min: number, max: number, width = 300, height = 90): string {
    if (values.length === 0 || max === min) return ''
    const stepX = width / Math.max(values.length - 1, 1)
    return values
      .map((v, i) => {
        const y = height - ((v - min) / (max - min)) * height
        return `${i === 0 ? 'M' : 'L'}${(i * stepX).toFixed(1)},${y.toFixed(1)}`
      })
      .join(' ')
  }

  // Chart scale: union of avg curve + p5/p95 bands so nothing clips.
  const p95Band = mc.pct_band.p95
  const p5Band = mc.pct_band.p5
  const lo = Math.min(...p5Band, ...mc.avg_curve)
  const hi = Math.max(...p95Band, ...mc.avg_curve)
  const W = 300
  const H = 90
  const areaPath =
    p95Band.length > 0 && p5Band.length > 0
      ? `${buildPath(p95Band, lo, hi, W, H)} L${W},${H} L0,${H} Z`
      : ''

  const pctRow = (label: string, s: MonteCarloPercentiles) => (
    <tr key={label} className="text-white/70">
      <td className="pr-3 text-white/40">{label}</td>
      <td className="pr-3">{s.p5}</td>
      <td className="pr-3 font-semibold text-white">{s.p50}</td>
      <td className="pr-3">{s.p95}</td>
    </tr>
  )

  return (
    <Panel title="Monte Carlo Simulation">
      <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-white/50">
          <span>
            {cfg.n_runs} runs · method={cfg.method} · block={cfg.block_size}d · seed={cfg.seed}
          </span>
          {mc.model_kind ? <span>{mc.model_kind}/{mc.head}</span> : null}
        </div>

        <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 h-24 w-full" preserveAspectRatio="none" data-testid="mc-svg">
          {areaPath ? <path d={areaPath} fill="rgba(111,159,196,0.18)" /> : null}
          <path d={buildPath(mc.avg_curve, lo, hi, W, H)} fill="none" stroke="#ef4444" strokeWidth="1.6" />
        </svg>

        <table className="mt-2 w-full border-collapse text-xs">
          <thead>
            <tr className="text-left text-white/40">
              <th className="pr-3 font-normal">metric</th>
              <th className="pr-3 font-normal">p5</th>
              <th className="pr-3 font-normal">p50</th>
              <th className="pr-3 font-normal">p95</th>
            </tr>
          </thead>
          <tbody>
            {pctRow('final return %', mc.final_return_pct)}
            {pctRow('sharpe', mc.sharpe)}
            {pctRow('max drawdown %', mc.max_drawdown)}
          </tbody>
        </table>

        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-white/60">
          <span>P(negative return): <span className="font-semibold text-white">{mc.prob_negative_return}</span></span>
          <span>best: <span className="text-emerald-300">{mc.best_run_total_return}%</span></span>
          <span>worst: <span className="text-red-300">{mc.worst_run_total_return}%</span></span>
        </div>
      </div>
    </Panel>
  )
}
