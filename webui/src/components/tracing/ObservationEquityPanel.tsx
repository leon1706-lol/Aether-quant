import { useMemo } from 'react'
import type { CsvRow } from '../../types/tracing'
import { toNumber } from '../../lib/format'
import { downsample } from '../../lib/downsample'
import { Panel } from '../layout/Panel'
import { LineChart } from './LineChart'

const EQUITY_COLOR = '#3987e5'
const CASH_COLOR = '#199e70'
const DRAWDOWN_COLOR = '#e66767'

export function ObservationEquityPanel({ rows }: { rows: CsvRow[] | undefined }) {
  const sampled = useMemo(() => downsample(rows ?? [], 400), [rows])

  const xLabels = sampled.map((r) => `bar ${r.bar_index}`)

  return (
    <Panel title="Observation Mode Equity Curve">
      <LineChart
        xLabels={xLabels}
        series={[
          { id: 'equity', label: 'Simulated equity', color: EQUITY_COLOR, values: sampled.map((r) => toNumber(r.equity)) },
          { id: 'cash', label: 'Simulated cash', color: CASH_COLOR, values: sampled.map((r) => toNumber(r.cash)) },
        ]}
        valueFormat={(v) => `$${(v / 1000).toFixed(0)}k`}
        areaOnSingle={false}
      />

      <div className="mt-3">
        <strong className="text-xs uppercase tracking-widest text-white/60">Drawdown</strong>
        <LineChart
          height={120}
          xLabels={xLabels}
          series={[{ id: 'drawdown', label: 'Simulated drawdown', color: DRAWDOWN_COLOR, values: sampled.map((r) => toNumber(r.drawdown)) }]}
          valueFormat={(v) => `${(v * 100).toFixed(1)}%`}
        />
      </div>

      {sampled.length > 0 && (
        <details className="mt-3 text-xs text-white/60">
          <summary className="cursor-pointer select-none text-white/50">
            Table view (last {Math.min(50, sampled.length)} of {rows?.length ?? 0} bars)
          </summary>
          <div className="mt-2 max-h-56 overflow-auto rounded-xl border border-white/5">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-[#141414] text-white/50">
                <tr>
                  <th className="px-2 py-1 font-medium">Bar</th>
                  <th className="px-2 py-1 font-medium">Equity</th>
                  <th className="px-2 py-1 font-medium">Cash</th>
                  <th className="px-2 py-1 font-medium">Exposure</th>
                  <th className="px-2 py-1 font-medium">Drawdown</th>
                </tr>
              </thead>
              <tbody className="tabular-nums text-white/70">
                {sampled.slice(-50).map((row, i) => (
                  <tr key={i} className="border-t border-white/5">
                    <td className="px-2 py-1">{row.bar_index}</td>
                    <td className="px-2 py-1">{toNumber(row.equity).toFixed(2)}</td>
                    <td className="px-2 py-1">{toNumber(row.cash).toFixed(2)}</td>
                    <td className="px-2 py-1">{toNumber(row.exposure).toFixed(4)}</td>
                    <td className="px-2 py-1">{toNumber(row.drawdown).toFixed(4)}</td>
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
