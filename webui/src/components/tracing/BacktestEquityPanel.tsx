import { useMemo, useState } from 'react'
import type { CsvRow } from '../../types/tracing'
import { toNumber } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { LineChart } from './LineChart'

const STRATEGY_COLOR = '#3987e5'
const BASELINE_COLOR = '#199e70'

export function BacktestEquityPanel({ rows }: { rows: CsvRow[] | undefined }) {
  const tickers = useMemo(() => {
    const seen = new Set<string>()
    for (const row of rows ?? []) {
      if (row.ticker) seen.add(row.ticker)
    }
    return Array.from(seen).sort()
  }, [rows])

  const [ticker, setTicker] = useState<string | undefined>(undefined)
  const activeTicker = ticker && tickers.includes(ticker) ? ticker : tickers[0]

  const tickerRows = useMemo(
    () => (rows ?? []).filter((row) => row.ticker === activeTicker),
    [rows, activeTicker],
  )

  return (
    <Panel
      title="Backtest Equity Curve"
      action={
        <select
          value={activeTicker ?? ''}
          onChange={(e) => setTicker(e.target.value)}
          className="rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-white/80"
        >
          {tickers.map((t) => (
            <option key={t} value={t} className="bg-[#141414]">
              {t}
            </option>
          ))}
        </select>
      }
    >
      <LineChart
        xLabels={tickerRows.map((r) => r.date ?? '')}
        series={[
          {
            id: 'strategy',
            label: 'Strategy (cumulative)',
            color: STRATEGY_COLOR,
            values: tickerRows.map((r) => toNumber(r.cumulative_strategy)),
          },
          {
            id: 'baseline',
            label: 'Buy & hold (cumulative)',
            color: BASELINE_COLOR,
            values: tickerRows.map((r) => toNumber(r.cumulative_baseline)),
          },
        ]}
        valueFormat={(v) => v.toFixed(2)}
        areaOnSingle={false}
      />

      {tickerRows.length > 0 && (
        <details className="mt-3 text-xs text-white/60">
          <summary className="cursor-pointer select-none text-white/50">Table view ({tickerRows.length} rows)</summary>
          <div className="mt-2 max-h-56 overflow-auto rounded-xl border border-white/5">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-[#141414] text-white/50">
                <tr>
                  <th className="px-2 py-1 font-medium">Date</th>
                  <th className="px-2 py-1 font-medium">Strategy</th>
                  <th className="px-2 py-1 font-medium">Buy &amp; hold</th>
                  <th className="px-2 py-1 font-medium">Drawdown</th>
                </tr>
              </thead>
              <tbody className="tabular-nums text-white/70">
                {tickerRows.map((row, i) => (
                  <tr key={i} className="border-t border-white/5">
                    <td className="px-2 py-1">{row.date}</td>
                    <td className="px-2 py-1">{toNumber(row.cumulative_strategy).toFixed(4)}</td>
                    <td className="px-2 py-1">{toNumber(row.cumulative_baseline).toFixed(4)}</td>
                    <td className="px-2 py-1">{toNumber(row.strategy_drawdown).toFixed(4)}</td>
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
