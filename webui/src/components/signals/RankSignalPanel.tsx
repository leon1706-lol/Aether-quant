import type { RankSignalPolicy } from '../../types/state'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V5.1 Phase 1 (development/Problems.md #73) - portfolio/rank_signal.py::
// resolve_rank_signal_policy()'s resolved blend, so "which head(s)/model(s)
// are actually driving the book this run" is answerable from the
// dashboard instead of only from a Debug() log line.
export function RankSignalPanel({ rankSignal }: { rankSignal: RankSignalPolicy | undefined }) {
  if (!rankSignal) {
    return (
      <Panel title="Rank Signal">
        <div className="p-6 text-center text-sm text-white/60">
          No rank signal policy yet — needs at least one bar processed.
        </div>
      </Panel>
    )
  }

  const heads = Object.entries(rankSignal.heads ?? {}).filter(([, weight]) => weight > 0)

  return (
    <Panel
      title="Rank Signal"
      action={<Badge tone={rankSignal.normalization === 'cross_sectional' ? 'stable' : 'watchlist'}>{rankSignal.normalization}</Badge>}
    >
      <div className="mb-2 flex flex-wrap gap-2">
        {heads.length === 0 ? (
          <span className="text-sm text-white/60">no active heads (policy left unchanged - see reason below)</span>
        ) : (
          heads.map(([head, weight]) => (
            <span key={head} className="rounded-full bg-sky-400/15 px-2.5 py-1 text-[0.78rem] text-sky-300">
              {head} × {weight.toFixed(2)}
            </span>
          ))
        )}
      </div>
      <div className="mb-2 text-[0.78rem] text-white/50">
        model priority: {(rankSignal.model_priority ?? []).join(' → ') || '—'}
      </div>
      {rankSignal.demoted && rankSignal.demoted.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Badge tone="not_promotable">demoted</Badge>
          <span className="text-[0.78rem] text-white/60">{rankSignal.demoted.join(', ')} (not promotable)</span>
        </div>
      )}
      <div className="text-[0.74rem] text-white/40">{rankSignal.reason}</div>
    </Panel>
  )
}
