import type { Signal } from '../../types/state'
import { formatNumber } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

function sortedSignals(signals: Record<string, Signal> | undefined) {
  return Object.entries(signals ?? {})
    .map(([symbol, payload]) => ({ symbol, ...payload }))
    .sort((a, b) => String(a.ticker || a.symbol).localeCompare(String(b.ticker || b.symbol)))
}

// Reuses AssetSizingTable.tsx's exact structural-dispatch idiom
// ('legs' in decision) to find only multi-leg option positions - never a
// single-leg OptionsDecision, which has no `legs` field at all.
function MultiLegRow({ asset }: { asset: Signal & { symbol: string } }) {
  const decision = asset.dynamic_sizing?.asset_class_routing_extra?.options_decision
  if (!decision || !('legs' in decision)) return null

  const expiry = 'expiry' in decision && decision.expiry ? decision.expiry : decision.expiries?.join(' / ')
  const assignmentRisk = asset.assignment_risk ?? {}

  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-white">
          {asset.ticker || asset.symbol} — {decision.strategy_name}
        </span>
        <span className="text-[0.74rem] text-white/50">exp {expiry}</span>
      </div>
      <div className="mt-2 grid gap-1.5">
        {decision.legs.map((leg, index) => {
          const risk = leg.contract_symbol ? assignmentRisk[leg.contract_symbol] : undefined
          return (
            <div key={`${leg.contract_symbol ?? index}`} className="flex items-center justify-between gap-2 text-[0.78rem]">
              <span className="text-white/70">
                {leg.side} {leg.right} {formatNumber(leg.strike)}
              </span>
              {risk ? (
                <span className="flex items-center gap-1.5">
                  <span className="text-white/50">assignment risk {formatNumber(risk.score)}</span>
                  <Badge tone={risk.flag ? 'sell' : 'hold'}>{risk.flag ? 'flagged' : 'ok'}</Badge>
                </span>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function HeldMultiLegPositionsPanel({ signals }: { signals: Record<string, Signal> | undefined }) {
  const rows = sortedSignals(signals).filter((asset) => {
    const decision = asset.dynamic_sizing?.asset_class_routing_extra?.options_decision
    return decision && 'legs' in decision
  })

  return (
    <Panel title="Held Multi-Leg Positions" action={<Badge>{rows.length} positions</Badge>}>
      {rows.length === 0 ? (
        <div className="p-8 text-center text-white/60">No held multi-leg option positions this bar.</div>
      ) : (
        <div className="grid gap-2">
          {rows.map((asset) => (
            <MultiLegRow key={asset.symbol} asset={asset} />
          ))}
        </div>
      )}
    </Panel>
  )
}
