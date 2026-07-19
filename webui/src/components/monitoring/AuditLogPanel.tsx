import type { AuditLogStatus } from '../../types/audit'
import { Panel } from '../layout/Panel'

const EVENT_TYPE_LABELS: Record<string, string> = {
  order_placement: 'Order',
  credential_load: 'Credential',
  live_mode_transition: 'Mode',
}

export function AuditLogPanel({ status }: { status: AuditLogStatus | undefined }) {
  const events = status?.recent_events ?? []
  const chainValid = status?.chain_valid

  return (
    <Panel title="Audit Log">
      {chainValid === false ? (
        <div className="mb-3 rounded-2xl border border-rose-400/40 bg-rose-400/10 px-4 py-3 text-rose-300">
          <strong>CHAIN BROKEN</strong>
          <div className="text-xs text-rose-200/80">
            at event {status?.chain_broken_at_event_id ?? 'unknown'} — tampering or data loss detected
          </div>
        </div>
      ) : (
        <div className="mb-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-white/60">
          <small>
            {chainValid === true
              ? `Chain intact · ${status?.total_entries ?? 0} entries`
              : 'No audit data yet'}
          </small>
        </div>
      )}

      <div className="grid min-w-0 gap-1.5">
        {events.length === 0 && <small className="text-white/40">No recent events</small>}
        {events.map((event) => (
          <div key={event.event_id} className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-2.5">
            <div className="flex items-center justify-between text-xs text-white/40">
              <span>{EVENT_TYPE_LABELS[event.event_type] ?? event.event_type}</span>
              <span>{event.created_at}</span>
            </div>
            <div className="mt-0.5 break-words text-sm text-white/80">
              {JSON.stringify(event.payload)}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  )
}
