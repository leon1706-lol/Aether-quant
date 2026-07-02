import type { AssetHeatmapEntry } from '../../types/state'
import { formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'

export function AssetHeatmap({ items }: { items: AssetHeatmapEntry[] | undefined }) {
  return (
    <Panel title="Asset Heatmap">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
        {items && items.length > 0 ? (
          items.map((item) => {
            const positive = (item.excess_return ?? 0) >= 0
            return (
              <div
                key={item.ticker}
                className={`rounded-2xl border border-white/5 p-4 ${
                  positive
                    ? 'bg-gradient-to-b from-emerald-400/15 to-emerald-400/[0.03]'
                    : 'bg-gradient-to-b from-rose-400/15 to-rose-400/[0.03]'
                }`}
              >
                <h3 className="mb-2 text-lg tracking-wide">{item.ticker}</h3>
                <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[0.83rem] text-white/60">
                  <span>Signal</span>
                  <strong className="text-right text-white">{item.signal_bias ?? 'hold'}</strong>
                  <span>Sharpe</span>
                  <strong className="text-right text-white">{(item.sharpe ?? 0).toFixed(2)}</strong>
                  <span>Exposure</span>
                  <strong className="text-right text-white">{formatPercent(item.exposure_rate)}</strong>
                  <span>Excess Return</span>
                  <strong className="text-right text-white">{formatPercent(item.excess_return)}</strong>
                </div>
              </div>
            )
          })
        ) : (
          <div className="rounded-2xl border border-white/5 p-4">
            <h3 className="mb-2 text-lg">No assets yet</h3>
          </div>
        )}
      </div>
    </Panel>
  )
}
