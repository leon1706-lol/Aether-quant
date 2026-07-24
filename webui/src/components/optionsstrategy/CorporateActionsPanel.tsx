import type { Signal } from '../../types/state'
import { formatNumber } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

function sortedSignals(signals: Record<string, Signal> | undefined) {
  return Object.entries(signals ?? {})
    .map(([symbol, payload]) => ({ symbol, ...payload }))
    .sort((a, b) => String(a.ticker || a.symbol).localeCompare(String(b.ticker || b.symbol)))
}

// Same-bar only (Lean's Slice.Splits fires once, on the split event bar) -
// this is a live/current-bar glance, not a durable audit trail (that's
// experience_events/_session_events, fed independently). Showing nothing
// outside of an actual split bar is expected, not a bug.
export function CorporateActionsPanel({ signals }: { signals: Record<string, Signal> | undefined }) {
  const rows = sortedSignals(signals).filter((asset) => asset.corporate_action)

  return (
    <Panel title="Corporate Actions" action={<Badge>{rows.length} this bar</Badge>}>
      {rows.length === 0 ? (
        <div className="p-8 text-center text-white/60">
          No corporate-action (split) events this bar. Live glance only - see the experience-event audit trail for history.
        </div>
      ) : (
        <div className="grid gap-2">
          {rows.map((asset) => {
            const action = asset.corporate_action!
            return (
              <div key={asset.symbol} className="flex items-center justify-between gap-2 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-[0.82rem]">
                <span className="font-medium text-white">{asset.ticker || asset.symbol}</span>
                <span className="text-white/60">
                  split factor {formatNumber(action.split_factor, 4)} · ref price {formatNumber(action.reference_price)}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}
