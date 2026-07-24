import type { StrategyCatalog } from '../../types/state'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

const RISK_TIER_TONES: Record<string, string> = {
  vega_budget: 'buy',
  margin_naked: 'sell',
  margin_uncovered_leg: 'hold',
  margin_bounded_backspread: 'hold',
  covered_protective: 'learned',
  unreachable_arbitrage: 'fallback',
}

function StrategyCard({ entry }: { entry: StrategyCatalog['strategies'][number] }) {
  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-white">{entry.name}</span>
        <Badge tone={RISK_TIER_TONES[entry.risk_tier]}>{entry.risk_tier}</Badge>
      </div>
      <div className="mt-1 text-[0.74rem] text-white/50">
        {entry.leg_count} legs · {entry.shape_family}
        {entry.has_expiry_pair ? ' · calendar (2 expiries)' : ''}
      </div>
    </div>
  )
}

// Purely static data (portfolio/options_strategy.py::MULTI_LEG_STRATEGY_REGISTRY
// never changes at runtime) - renders immediately once /api/strategies
// responds, independent of whether any backtest has ever run.
export function StrategyCatalogBrowser({ catalog }: { catalog: StrategyCatalog | undefined }) {
  const strategies = catalog?.strategies ?? []

  return (
    <Panel title="Strategy Catalog" action={<Badge>{catalog?.total_count ?? 0} strategies</Badge>}>
      {strategies.length === 0 ? (
        <div className="p-8 text-center text-white/60">Loading strategy catalog…</div>
      ) : (
        <div className="grid max-h-[420px] gap-2 overflow-y-auto">
          {strategies.map((entry) => (
            <StrategyCard key={entry.name} entry={entry} />
          ))}
        </div>
      )}
    </Panel>
  )
}
