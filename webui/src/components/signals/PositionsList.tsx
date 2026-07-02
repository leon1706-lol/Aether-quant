import type { Position } from '../../types/state'
import { formatCurrency, formatNumber, formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'

export function PositionsList({ positions }: { positions: Position[] | undefined }) {
  return (
    <Panel title="Positions">
      <div className="grid gap-2.5">
        {positions && positions.length > 0 ? (
          positions.map((position) => (
            <div
              key={position.symbol}
              className="flex items-center justify-between gap-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3"
            >
              <div className="grid gap-1">
                <strong>{position.symbol}</strong>
                <small className="text-white/60">
                  qty {formatNumber(position.quantity, 2)} | weight {formatPercent(position.weight)}
                </small>
              </div>
              <small className="text-white/60">pnl {formatCurrency(position.unrealized_profit)}</small>
            </div>
          ))
        ) : (
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
            <div className="grid gap-1">
              <strong>No open positions</strong>
              <small className="text-white/60">Portfolio is flat</small>
            </div>
            <small className="text-white/60">0</small>
          </div>
        )}
      </div>
    </Panel>
  )
}
