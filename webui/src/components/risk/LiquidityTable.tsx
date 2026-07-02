import type { Signal } from '../../types/state'
import { formatNumber, formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

const LIQUIDITY_TONES: Record<string, string> = {
  normal: 'trade',
  thin: 'retrain_candidate',
  high_impact: 'hold',
  blocked: 'reduce_risk',
}

const LIQUIDITY_LABELS: Record<string, string> = {
  normal: 'normal',
  thin: 'thin',
  high_impact: 'high impact',
  blocked: 'blocked',
}

const ACTION_TONES: Record<string, string> = {
  allow: 'trade',
  reduce_size: 'retrain_candidate',
  simulate_instead: 'simulate',
  block: 'reduce_risk',
}

function formatDdv(value: number | undefined): string {
  if (value === undefined || value === null) return '—'
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(1)}B`
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`
  return `$${value.toFixed(0)}`
}

function sortedRows(signals: Record<string, Signal> | undefined) {
  return Object.entries(signals ?? {})
    .map(([symbol, s]) => ({ symbol, ticker: s.ticker ?? symbol, liquidity: s.liquidity, security_type: s.security_type }))
    .filter((r) => r.liquidity !== undefined)
    .sort((a, b) => a.ticker.localeCompare(b.ticker))
}

export function LiquidityTable({ signals }: { signals: Record<string, Signal> | undefined }) {
  const rows = sortedRows(signals)

  return (
    <Panel title="Liquidity &amp; Execution Impact" action={<Badge>{rows.length} assets</Badge>}>
      {rows.length === 0 ? (
        <div className="p-8 text-center text-white/60">
          No liquidity data yet. Run a Lean backtest or observation loop to populate state.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="text-left text-[0.7rem] uppercase tracking-wide text-white/60">
                <th className="border-b border-white/10 px-2.5 py-2.5">Asset</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Daily $ Vol</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Order Value</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Participation</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Est. Slippage</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Spread Proxy</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Round-Trip</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Risk</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const liq = row.liquidity!
                const risk = liq.liquidity_risk ?? 'normal'
                const action = liq.recommended_action ?? 'allow'
                return (
                  <tr key={row.symbol}>
                    <td className="border-b border-white/5 px-2.5 py-2.5">
                      <div className="font-extrabold tracking-wide text-[0.88rem]">{row.ticker}</div>
                      <div className="text-[0.72rem] text-white/60">{row.security_type ?? 'asset'}</div>
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5 text-[0.85rem]">
                      {formatDdv(liq.daily_dollar_volume)}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5 text-[0.85rem]">
                      {liq.order_value !== undefined ? `$${formatNumber(liq.order_value, 0)}` : '—'}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5 text-[0.85rem]">
                      {liq.participation_rate !== undefined
                        ? formatPercent(liq.participation_rate, 3)
                        : '—'}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5 text-[0.85rem]">
                      {liq.estimated_slippage !== undefined
                        ? formatPercent(liq.estimated_slippage, 3)
                        : '—'}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5 text-[0.85rem]">
                      {liq.spread_proxy !== undefined ? formatPercent(liq.spread_proxy, 2) : '—'}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5 text-[0.85rem]">
                      {liq.estimated_round_trip_cost !== undefined
                        ? formatPercent(liq.estimated_round_trip_cost, 3)
                        : '—'}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5">
                      <Badge tone={LIQUIDITY_TONES[risk]}>
                        {LIQUIDITY_LABELS[risk] ?? risk}
                      </Badge>
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5">
                      <Badge tone={ACTION_TONES[action]}>{action.replace(/_/g, ' ')}</Badge>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-[0.7rem] text-white/40">
        DDV = close × volume proxy · Spread = static 5 bps equity / 20 bps crypto · Slippage = participation × daily vol × 0.1
      </p>
    </Panel>
  )
}
