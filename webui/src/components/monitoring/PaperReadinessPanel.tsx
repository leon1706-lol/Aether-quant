import type { PaperReadiness } from '../../types/state'
import { Panel } from '../layout/Panel'

function formatValue(value: number | string): string {
  if (typeof value === 'number') return Number.isInteger(value) ? value.toString() : value.toFixed(3)
  return value
}

function formatCheckName(name: string): string {
  return name.replace(/_/g, ' ')
}

export function PaperReadinessPanel({ status }: { status: PaperReadiness | undefined }) {
  const banner = status
    ? status.ready
      ? { border: 'border-emerald-400/40', bg: 'bg-emerald-400/10', text: 'text-emerald-300', label: 'READY FOR PAPER TRADING' }
      : { border: 'border-amber-400/40', bg: 'bg-amber-400/10', text: 'text-amber-300', label: 'NOT READY FOR PAPER TRADING' }
    : undefined

  return (
    <Panel title="Paper Trading Readiness">
      {banner ? (
        <div className={`mb-3 rounded-2xl border ${banner.border} ${banner.bg} px-4 py-3 ${banner.text}`}>
          <strong>{banner.label}</strong>
          {status?.blocking_reasons?.length ? (
            <div className="mt-1 text-xs opacity-80 break-words">{status.blocking_reasons.join(', ')}</div>
          ) : null}
        </div>
      ) : (
        <div className="mb-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-white/60">
          <small>No paper-readiness report yet — run `aq paper-readiness`</small>
        </div>
      )}

      <div className="grid min-w-0 gap-2.5">
        {status &&
          Object.entries(status.checks).map(([name, check]) => (
            <div
              key={name}
              className="flex min-w-0 items-center justify-between rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3"
            >
              <span className="text-sm capitalize text-white/80 break-words">{formatCheckName(name)}</span>
              <span className={`text-xs ${check.pass ? 'text-emerald-300' : 'text-rose-300'}`}>
                {formatValue(check.value)} / {formatValue(check.threshold)}
              </span>
            </div>
          ))}

        <div className="flex min-w-0 items-center justify-between rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <span className="text-sm text-white/80">Broker Config</span>
          <span className={`text-xs break-words ${status?.broker_config_present ? 'text-emerald-300' : 'text-rose-300'}`}>
            {status?.broker_config_reason ?? 'no data yet'}
          </span>
        </div>
      </div>
    </Panel>
  )
}
