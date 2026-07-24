import type { Signal } from '../../types/state'
import { formatNumber } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

function sortedSignals(signals: Record<string, Signal> | undefined) {
  return Object.entries(signals ?? {})
    .map(([symbol, payload]) => ({ symbol, ...payload }))
    .sort((a, b) => String(a.ticker || a.symbol).localeCompare(String(b.ticker || b.symbol)))
}

// train_strategy_selector.py has no data source at all until real option
// positions actually trade (its own module docstring) - realistically
// permanent in this environment, so this empty state is the expected,
// common case, not a loading/error state.
export function StrategySelectorScoresPanel({ signals }: { signals: Record<string, Signal> | undefined }) {
  const rows = sortedSignals(signals).filter(
    (asset) => asset.strategy_selector_scores && Object.keys(asset.strategy_selector_scores).length > 0,
  )

  return (
    <Panel title="Strategy Selector Scores">
      {rows.length === 0 ? (
        <div className="p-8 text-center text-white/60">
          No trained strategy-selector model loaded — falls back to static risk-tier ordering.
        </div>
      ) : (
        <div className="grid gap-2">
          {rows.map((asset) => (
            <div key={asset.symbol} className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
              <div className="text-sm font-medium text-white">{asset.ticker || asset.symbol}</div>
              <div className="mt-1.5 grid gap-1 text-[0.78rem] text-white/60">
                {Object.entries(asset.strategy_selector_scores ?? {})
                  .sort((a, b) => b[1] - a[1])
                  .map(([name, score]) => (
                    <div key={name} className="flex items-center justify-between gap-2">
                      <span className="text-white/70">{name}</span>
                      <Badge>{formatNumber(score, 3)}</Badge>
                    </div>
                  ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
