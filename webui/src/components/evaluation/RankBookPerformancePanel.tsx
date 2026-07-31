import type { RankBookSimulationResult } from '../../types/evaluation'
import { isNotEvaluated, type EvaluationState } from '../../types/evaluation'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

function StatTile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
      <small className="text-white/60">{label}</small>
      <div className={`text-sm ${tone ?? 'text-white'}`}>{value}</div>
    </div>
  )
}

// V5.1 Phase 0 - the headline "is the fee drag fixed" tile: net Sharpe next
// to gross Sharpe makes the cost drag visually obvious without doing the
// subtraction yourself, the same reason the V4.12.3 backtest table shows
// both strategy and buy-and-hold side by side.
export function RankBookPerformancePanel({ evaluation }: { evaluation: EvaluationState | undefined }) {
  const rankBook = evaluation?.rank_book

  if (!rankBook || isNotEvaluated(rankBook)) {
    return (
      <Panel title="Rank Book Performance">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-6 text-center text-sm text-white/50">
          Not evaluated yet — run{' '}
          <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-orange-300">
            aq evaluate --rank-book
          </code>
        </div>
      </Panel>
    )
  }

  const result = rankBook as RankBookSimulationResult
  const costDragSevere = result.net_sharpe < result.gross_sharpe * 0.5

  return (
    <Panel
      title="Rank Book Performance"
      action={<Badge tone={result.net_sharpe > 0 ? 'trade' : 'reduce_risk'}>net {result.net_sharpe > 0 ? 'positive' : 'negative'}</Badge>}
    >
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
        <StatTile label="Gross Sharpe" value={result.gross_sharpe.toFixed(3)} />
        <StatTile
          label="Net Sharpe"
          value={result.net_sharpe.toFixed(3)}
          tone={result.net_sharpe > 0 ? 'text-emerald-300' : 'text-rose-300'}
        />
        <StatTile
          label="Cost Drag"
          value={`${result.cost_drag_annual_bps.toFixed(1)} bps/yr`}
          tone={costDragSevere ? 'text-rose-300' : undefined}
        />
        <StatTile label="Gross Total Return" value={`${(result.gross_total_return * 100).toFixed(2)}%`} />
        <StatTile label="Net Total Return" value={`${(result.net_total_return * 100).toFixed(2)}%`} />
        <StatTile label="Net Max Drawdown" value={`${(result.net_max_drawdown * 100).toFixed(2)}%`} />
        <StatTile label="Annualized Turnover" value={`${result.annualized_turnover.toFixed(2)}x`} />
        <StatTile label="Rebalances" value={String(result.num_rebalances)} />
        <StatTile label="Dates Used" value={String(result.num_dates_used)} />
        <StatTile label="Mean Names Long" value={result.mean_names_long.toFixed(1)} />
        <StatTile label="Mean Names Short" value={result.mean_names_short.toFixed(1)} />
      </div>
    </Panel>
  )
}
