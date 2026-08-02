import type { BookNeutralityDiagnostics } from '../../types/state'
import { formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V5.1 Phase 1 (development/Problems.md, item 6) - portfolio/book_neutrality.py::
// apply_book_neutrality()'s diagnostics from the book's last rebalance bar.
// {} pre-first-rebalance or whenever phase_v2.portfolio_book.neutrality.enabled
// is off (config default: on - see config.json).
export function BookNeutralityPanel({ diagnostics }: { diagnostics: BookNeutralityDiagnostics | undefined }) {
  const steps = diagnostics?.steps_applied ?? []
  const perSector = Object.entries(diagnostics?.per_sector_net ?? {})

  return (
    <Panel title="Book Neutrality" action={<Badge tone={steps.length > 0 ? 'stable' : 'watchlist'}>{steps.length} steps</Badge>}>
      {steps.length === 0 ? (
        <div className="p-6 text-center text-sm text-white/60">
          No neutrality pass run yet — needs the portfolio book active with at least one rebalance bar.
        </div>
      ) : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5 text-center">
              <div className="text-[0.7rem] uppercase tracking-wide text-white/50">Gross (pre)</div>
              <div className="mt-1 text-sm font-semibold text-white">{formatPercent(diagnostics?.pre_gross)}</div>
            </div>
            <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5 text-center">
              <div className="text-[0.7rem] uppercase tracking-wide text-white/50">Gross (post)</div>
              <div className="mt-1 text-sm font-semibold text-white">{formatPercent(diagnostics?.post_gross)}</div>
            </div>
            <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5 text-center">
              <div className="text-[0.7rem] uppercase tracking-wide text-white/50">Net (pre)</div>
              <div className="mt-1 text-sm font-semibold text-white">{formatPercent(diagnostics?.net_before)}</div>
            </div>
            <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5 text-center">
              <div className="text-[0.7rem] uppercase tracking-wide text-white/50">Net (post)</div>
              <div className="mt-1 text-sm font-semibold text-white">{formatPercent(diagnostics?.net_after)}</div>
            </div>
          </div>
          {perSector.length > 0 && (
            <div className="mb-2">
              <div className="mb-1 text-xs text-white/50">Per-sector net exposure</div>
              <div className="flex flex-wrap gap-1.5">
                {perSector.map(([sector, net]) => (
                  <span key={sector} className="rounded-full bg-white/[0.06] px-2.5 py-1 text-[0.74rem] text-white/70">
                    {sector}: {formatPercent(net)}
                  </span>
                ))}
              </div>
            </div>
          )}
          <div className="text-[0.74rem] text-white/40">steps applied: {steps.join(', ')}</div>
        </>
      )}
    </Panel>
  )
}
