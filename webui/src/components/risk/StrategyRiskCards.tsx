import type { Risk, StrategySnapshot } from '../../types/state'
import { formatNumber, formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'

function MiniCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.03] p-3.5">
      <div className="mb-2 text-[0.72rem] uppercase tracking-widest text-white/60">{label}</div>
      <div>{value}</div>
    </div>
  )
}

export function StrategyRiskCards({
  strategy,
  risk,
}: {
  strategy: StrategySnapshot | undefined
  risk: Risk | undefined
}) {
  return (
    <Panel title="Strategy and Risk">
      <div className="grid grid-cols-2 gap-3">
        {strategy?.strategy && (
          <>
            <MiniCard label="Backtest Return" value={formatPercent(strategy.strategy.total_return)} />
            <MiniCard label="Backtest Sharpe" value={formatNumber(strategy.strategy.sharpe, 3)} />
          </>
        )}
        <MiniCard label="Trade Lock" value={risk?.trade_lock_active ? 'Active' : 'Open'} />
        <MiniCard label="Min Confidence" value={formatPercent(risk?.min_confidence_to_trade)} />
      </div>
    </Panel>
  )
}
