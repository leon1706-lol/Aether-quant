import { useMemo } from 'react'
import type { CsvRow } from '../../types/tracing'
import { toNumber } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { DivergingBarChart } from './DivergingBarChart'

export function AssetPerformancePanel({ rows }: { rows: CsvRow[] | undefined }) {
  const items = useMemo(
    () =>
      (rows ?? [])
        .map((row) => ({ label: row.ticker, value: toNumber(row.sharpe) }))
        .filter((item) => Number.isFinite(item.value))
        .sort((a, b) => b.value - a.value),
    [rows],
  )

  return (
    <Panel title="Asset Performance (Sharpe, backtest)">
      <DivergingBarChart items={items} valueFormat={(v) => v.toFixed(2)} />

      {rows && rows.length > 0 && (
        <details className="mt-3 text-xs text-white/60">
          <summary className="cursor-pointer select-none text-white/50">Table view ({rows.length} tickers)</summary>
          <div className="mt-2 max-h-56 overflow-auto rounded-xl border border-white/5">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-[#141414] text-white/50">
                <tr>
                  <th className="px-2 py-1 font-medium">Ticker</th>
                  <th className="px-2 py-1 font-medium">Return</th>
                  <th className="px-2 py-1 font-medium">Excess</th>
                  <th className="px-2 py-1 font-medium">Sharpe</th>
                  <th className="px-2 py-1 font-medium">Max DD</th>
                  <th className="px-2 py-1 font-medium">Exposure</th>
                  <th className="px-2 py-1 font-medium">Trades</th>
                </tr>
              </thead>
              <tbody className="tabular-nums text-white/70">
                {rows.map((row, i) => (
                  <tr key={i} className="border-t border-white/5">
                    <td className="px-2 py-1">{row.ticker}</td>
                    <td className="px-2 py-1">{toNumber(row.strategy_return).toFixed(3)}</td>
                    <td className="px-2 py-1">{toNumber(row.excess_return).toFixed(3)}</td>
                    <td className="px-2 py-1">{toNumber(row.sharpe).toFixed(3)}</td>
                    <td className="px-2 py-1">{toNumber(row.max_drawdown).toFixed(3)}</td>
                    <td className="px-2 py-1">{toNumber(row.exposure_rate).toFixed(3)}</td>
                    <td className="px-2 py-1">{row.trade_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </Panel>
  )
}
