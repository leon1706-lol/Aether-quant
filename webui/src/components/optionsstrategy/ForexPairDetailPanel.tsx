import type { Signal } from '../../types/state'
import { formatNumber, formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

function sortedSignals(signals: Record<string, Signal> | undefined) {
  return Object.entries(signals ?? {})
    .map(([symbol, payload]) => ({ symbol, ...payload }))
    .sort((a, b) => String(a.ticker || a.symbol).localeCompare(String(b.ticker || b.symbol)))
}

// Replaces the plain "{lot_count} forex lots" string AssetSizingTable.tsx
// still shows in the Risk page - richer per-pair detail here instead.
export function ForexPairDetailPanel({ signals }: { signals: Record<string, Signal> | undefined }) {
  const rows = sortedSignals(signals).filter((asset) => {
    const extra = asset.dynamic_sizing?.asset_class_routing_extra
    return extra && typeof extra.lot_count === 'number'
  })

  return (
    <Panel title="Forex Pair Detail" action={<Badge>{rows.length} pairs</Badge>}>
      {rows.length === 0 ? (
        <div className="p-8 text-center text-white/60">No forex positions this bar.</div>
      ) : (
        <div className="grid gap-2">
          {rows.map((asset) => {
            const extra = asset.dynamic_sizing?.asset_class_routing_extra
            const spec = extra?.pair_spec
            const hasSpec = spec && 'pip_size' in spec
            return (
              <div key={asset.symbol} className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-medium text-white">{asset.ticker || asset.symbol}</span>
                  <span className="text-[0.78rem] text-white/60">{extra?.lot_count} lots</span>
                </div>
                {hasSpec ? (
                  <div className="mt-1.5 text-[0.74rem] text-white/50">
                    pip {formatNumber(spec.pip_size, 5)} · lot size {spec.lot_size.toLocaleString()} · max leverage{' '}
                    {spec.leverage_max}x · margin {formatPercent(spec.margin_pct)}
                  </div>
                ) : (
                  <div className="mt-1.5 text-[0.74rem] text-white/40">No pair spec loaded for this ticker.</div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}
