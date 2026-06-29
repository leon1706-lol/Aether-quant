import type { Monitoring } from '../../types/state'
import { Panel } from '../layout/Panel'

export function MonitoringFeeds({ monitoring }: { monitoring: Monitoring | undefined }) {
  const feeds = Object.entries(monitoring?.feeds ?? {})

  return (
    <Panel title="Monitoring Feeds">
      <div className="grid gap-2.5">
        {feeds.length > 0 ? (
          feeds.map(([key, value]) => (
            <div
              key={key}
              className="flex items-center justify-between gap-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3"
            >
              <div className="grid gap-1">
                <strong>{key}</strong>
                <small className="text-slate-400">{value}</small>
              </div>
              <small className="text-slate-400">{monitoring?.mode ?? 'idle'}</small>
            </div>
          ))
        ) : (
          <div className="flex items-center justify-between gap-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
            <div className="grid gap-1">
              <strong>No feeds yet</strong>
              <small className="text-slate-400">Monitoring export waiting</small>
            </div>
            <small className="text-slate-400">-</small>
          </div>
        )}
      </div>
    </Panel>
  )
}
