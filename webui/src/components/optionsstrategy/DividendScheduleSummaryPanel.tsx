import type { Signal } from '../../types/state'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

function sortedSignals(signals: Record<string, Signal> | undefined) {
  return Object.entries(signals ?? {})
    .map(([symbol, payload]) => ({ symbol, ...payload }))
    .sort((a, b) => String(a.ticker || a.symbol).localeCompare(String(b.ticker || b.symbol)))
}

export function DividendScheduleSummaryPanel({ signals }: { signals: Record<string, Signal> | undefined }) {
  const rows = sortedSignals(signals).filter((asset) => asset.dividend_schedule)

  return (
    <Panel title="Dividend Schedule">
      {rows.length === 0 ? (
        <div className="p-8 text-center text-white/60">
          No dividend-schedule data cached (assignment-risk detector is off, or no schedule backfilled yet).
        </div>
      ) : (
        <div className="grid gap-2">
          {rows.map((asset) => {
            const schedule = asset.dividend_schedule!
            const estimate = schedule.next_ex_dividend_estimate
            return (
              <div key={asset.symbol} className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-white">{asset.ticker || asset.symbol}</span>
                  <Badge tone={estimate.confidence}>{estimate.confidence}</Badge>
                </div>
                <div className="mt-1.5 text-[0.78rem] text-white/60">
                  next ex-div: {estimate.estimated_next_ex_date ?? '—'}
                  {estimate.estimated_amount != null ? ` · $${estimate.estimated_amount.toFixed(2)}/share` : ''}
                  {estimate.cadence_days != null ? ` · ~${estimate.cadence_days}d cadence` : ''}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}
