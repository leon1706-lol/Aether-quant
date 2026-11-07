import type { GenerationsState } from '../../types/state'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V6.6.1 - the model generations sharing the book, from `aq cycle status`
// (ml/generations/status.json, GET /api/generations). A fresh checkout has no
// status yet, which is an empty view rather than an error.
export function GenerationsPanel({ status }: { status: GenerationsState | undefined }) {
  const generations = status?.generations ?? []
  const due = status?.due ?? []

  return (
    <Panel
      title="Generations"
      action={
        status?.chain_valid === false ? (
          <Badge tone="reduce_risk">chain broken</Badge>
        ) : (
          <Badge tone={status?.enabled ? 'stable' : 'none'}>{status?.enabled ? 'on' : 'off'}</Badge>
        )
      }
    >
      {generations.length === 0 ? (
        <div className="p-6 text-center text-sm text-white/60">No status yet: run aq cycle status.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-white/80">
            <thead>
              <tr className="text-[0.7rem] uppercase tracking-wide text-white/50">
                <th className="px-2 py-1.5 font-medium">Generation</th>
                <th className="px-2 py-1.5 font-medium">Stage</th>
                <th className="px-2 py-1.5 font-medium">Tier</th>
                <th className="px-2 py-1.5 text-right font-medium">Share</th>
                <th className="px-2 py-1.5 font-medium">State</th>
                <th className="px-2 py-1.5 text-right font-medium">Sessions</th>
              </tr>
            </thead>
            <tbody>
              {generations.map((generation) => (
                <tr key={generation.id} className="border-t border-white/5">
                  <td className="px-2 py-1.5 font-semibold text-white">{generation.id}</td>
                  <td className="px-2 py-1.5">{generation.stage}</td>
                  <td className="px-2 py-1.5">{generation.tier}</td>
                  <td className="px-2 py-1.5 text-right">{(generation.share * 100).toFixed(0)}%</td>
                  <td className="px-2 py-1.5">{generation.state ?? 'no record yet'}</td>
                  <td className="px-2 py-1.5 text-right">{generation.sessions ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {due.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1.5 text-sm text-white/70">
          {due.map((item) => (
            <li key={item.action}>
              <span className="font-semibold text-white">{item.action}</span>: {item.why}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
