import type { DynamicSizing, Signal } from '../../types/state'
import { formatNumber, formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

function sortedSignals(signals: Record<string, Signal> | undefined) {
  return Object.entries(signals ?? {})
    .map(([symbol, payload]) => ({ symbol, ...payload }))
    .sort((a, b) => String(a.ticker || a.symbol).localeCompare(String(b.ticker || b.symbol)))
}

// asset_class_routing_extra is only present for future/option assets
// (risk/asset_class_router.py::route_position_sizing()) - equity/crypto/
// bond sizing has nothing to show here.
function AssetClassDetail({ sizing }: { sizing: DynamicSizing }) {
  const extra = sizing.asset_class_routing_extra
  if (!extra) return null

  if (extra.options_decision) {
    const d = extra.options_decision
    return (
      <div className="mt-1 text-[0.74rem] text-white/50">
        {d.contracts}x {d.right} {formatNumber(d.strike)} exp {d.expiry} · Δ {formatNumber(d.actual_delta)} · vega
        budget {formatPercent(d.vega_budget_used)}
      </div>
    )
  }
  if (typeof extra.contract_count === 'number') {
    return <div className="mt-1 text-[0.74rem] text-white/50">{extra.contract_count} futures contracts</div>
  }
  return null
}

function VolatilityBar({ annualVol }: { annualVol: number }) {
  const width = Math.min(annualVol / 0.8, 1) * 100
  const tone = annualVol > 0.45 ? 'bg-rose-400' : annualVol > 0.25 ? 'bg-amber-400' : 'bg-emerald-400'
  return (
    <div className="grid min-w-[150px] gap-1.5">
      <div className="flex justify-between text-[0.76rem] text-white/60">
        <span>annual vol</span>
        <strong className="text-white">{formatPercent(annualVol)}</strong>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-white/10">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  )
}

function PositionSizeBar({ base, target }: { base: number; target: number }) {
  const width = Math.min(Math.abs(target) / 0.25, 1) * 100
  return (
    <div className="grid min-w-[150px] gap-1.5">
      <div className="flex justify-between text-[0.76rem] text-white/60">
        <span>base {formatPercent(base)}</span>
        <strong className="text-white">{formatPercent(target)}</strong>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-white/10">
        <div className="h-full rounded-full bg-sky-400" style={{ width: `${width}%` }} />
      </div>
    </div>
  )
}

export function AssetSizingTable({ signals }: { signals: Record<string, Signal> | undefined }) {
  const rows = sortedSignals(signals)

  return (
    <Panel title="Asset Volatility And Sizing" action={<Badge>{rows.length} assets</Badge>}>
      {rows.length === 0 ? (
        <div className="p-8 text-center text-white/60">
          No runtime signals yet. Run a Lean backtest or observation loop to populate state.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="text-left text-[0.7rem] uppercase tracking-wide text-white/60">
                <th className="border-b border-white/10 px-2.5 py-2.5">Asset</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Signal</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Book Role</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Regime</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Volatility</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Position Size</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Leverage</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Confidence</th>
                <th className="border-b border-white/10 px-2.5 py-2.5">Reason</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((asset) => {
                const sizing = asset.dynamic_sizing ?? {}
                const base = Number(asset.target_weight ?? sizing.base_target_weight ?? 0)
                const target = Number(asset.target_weight ?? sizing.target_weight ?? 0)
                const annualVol = Number(sizing.annualized_volatility ?? 0)
                const leverage = Number(sizing.leverage_factor ?? 0)
                const confidence = Number(asset.confidence ?? 0)
                const regime = sizing.volatility_regime || 'unknown'
                const signal = asset.signal || 'hold'

                return (
                  <tr key={asset.symbol}>
                    <td className="border-b border-white/5 px-2.5 py-2.5 text-[0.88rem]">
                      <div className="font-extrabold tracking-wide">{asset.ticker || asset.symbol}</div>
                      <div className="text-[0.78rem] text-white/60">
                        {asset.security_type || 'asset'} / {asset.trading_eligible ? 'tradable' : 'observe'}
                      </div>
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5">
                      <Badge tone={signal}>{signal}</Badge>
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5">
                      {asset.portfolio_book_role ? (
                        <Badge tone={asset.portfolio_book_role}>{asset.portfolio_book_role}</Badge>
                      ) : (
                        <span className="text-[0.78rem] text-white/40">—</span>
                      )}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5">
                      <Badge tone={regime}>{regime}</Badge>
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5">
                      <VolatilityBar annualVol={annualVol} />
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5">
                      <PositionSizeBar base={base} target={target} />
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5 text-[0.88rem]">
                      {formatNumber(leverage)}x
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5 text-[0.88rem]">
                      {formatPercent(confidence)}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2.5 text-[0.78rem] text-white/60">
                      {sizing.sizing_reason || asset.execution_note || asset.reason || 'waiting'}
                      <AssetClassDetail sizing={sizing} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}
