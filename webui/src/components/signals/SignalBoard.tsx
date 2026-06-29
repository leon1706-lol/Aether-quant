import type { Signal } from '../../types/state'
import { formatNumber } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from './Badge'

export function SignalBoard({ signals }: { signals: Record<string, Signal> | undefined }) {
  const entries = Object.entries(signals ?? {})

  return (
    <Panel title="Signal Board">
      <div className="grid gap-2.5">
        {entries.length > 0 ? (
          entries.map(([symbol, payload]) => (
            <div
              key={symbol}
              className="flex items-center justify-between gap-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3"
            >
              <div className="grid gap-1">
                <strong className="text-[0.98rem]">{payload.ticker || symbol}</strong>
                <small className="text-slate-400">
                  {payload.execution_note || payload.reason || 'signal update'} | prob{' '}
                  {formatNumber(payload.probability_up, 3)}
                </small>
              </div>
              <Badge tone={payload.signal}>{payload.signal || 'hold'}</Badge>
            </div>
          ))
        ) : (
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
            <div className="grid gap-1">
              <strong>No signals yet</strong>
              <small className="text-slate-400">Waiting for state.json</small>
            </div>
            <Badge>hold</Badge>
          </div>
        )}
      </div>
    </Panel>
  )
}
