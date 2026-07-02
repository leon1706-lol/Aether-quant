import type { RetrainingStatus } from '../../types/state'
import { Panel } from '../layout/Panel'

function formatNumber(value: number | undefined, digits = 2): string {
  if (value === undefined || Number.isNaN(value)) return '-'
  return value.toFixed(digits)
}

function shortHash(hash: string | null | undefined): string {
  if (!hash) return '-'
  return hash.slice(0, 8)
}

const STATUS_BANNER: Record<string, { border: string; bg: string; text: string; label: string }> = {
  promoted: { border: 'border-emerald-400/40', bg: 'bg-emerald-400/10', text: 'text-emerald-300', label: 'MODEL PROMOTED' },
  validated: { border: 'border-amber-400/40', bg: 'bg-amber-400/10', text: 'text-amber-300', label: 'CANDIDATE VALIDATED — AWAITING PROMOTION' },
  running: { border: 'border-sky-400/40', bg: 'bg-sky-400/10', text: 'text-sky-300', label: 'RETRAINING IN PROGRESS' },
  planned: { border: 'border-sky-400/40', bg: 'bg-sky-400/10', text: 'text-sky-300', label: 'RETRAINING PLANNED' },
  rejected: { border: 'border-rose-400/40', bg: 'bg-rose-400/10', text: 'text-rose-300', label: 'CANDIDATE REJECTED' },
  failed: { border: 'border-rose-400/40', bg: 'bg-rose-400/10', text: 'text-rose-300', label: 'RETRAINING FAILED' },
}

export function RetrainingStatusPanel({ status }: { status: RetrainingStatus | undefined }) {
  const event = status?.latest_retraining_event
  const banner = event ? STATUS_BANNER[event.status] : undefined

  const metrics: [string, string][] = [
    ['Active Version', shortHash(status?.active_model?.model_version_id)],
    ['Latest Candidate', shortHash(status?.latest_candidate?.model_version_id)],
    ['Validation Status', status?.validation_status ?? 'none'],
    ['Vault Commit', shortHash(status?.active_model?.aether_vault_commit)],
  ]

  return (
    <Panel title="Retraining Status">
      {banner ? (
        <div className={`mb-3 rounded-2xl border ${banner.border} ${banner.bg} px-4 py-3 ${banner.text}`}>
          <strong>{banner.label}</strong>
          {event?.reason && <div className="text-xs opacity-80">{event.reason}</div>}
        </div>
      ) : (
        <div className="mb-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-white/60">
          <small>No retraining activity yet</small>
        </div>
      )}

      <div className="grid grid-cols-2 gap-2.5">
        {metrics.map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
            <small className="text-white/60">{label}</small>
            <div className="text-sm text-white break-words">{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-3 grid min-w-0 gap-1 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
        <strong className="text-xs uppercase tracking-widest text-white/60">Last Retrain Trigger</strong>
        {status?.last_trigger ? (
          <div className="grid gap-1 text-sm text-white/80">
            <span className="break-words">{status.last_trigger.message}</span>
            <span className="text-xs text-white/40">
              {status.last_trigger.trigger_type} · {status.last_trigger.severity} ·{' '}
              {formatNumber(status.last_trigger.metric_value, 3)} vs threshold{' '}
              {formatNumber(status.last_trigger.threshold, 3)}
            </span>
          </div>
        ) : (
          <small className="text-white/40">No data yet</small>
        )}
      </div>

      <div className="mt-3 grid min-w-0 gap-1 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
        <strong className="text-xs uppercase tracking-widest text-white/60">Rollback</strong>
        {status?.rollback_available ? (
          <span className="text-sm text-white/80">
            {status.rollback_candidates.length} restorable version(s) available
          </span>
        ) : (
          <small className="text-white/40">No rollback candidates yet</small>
        )}
      </div>
    </Panel>
  )
}
