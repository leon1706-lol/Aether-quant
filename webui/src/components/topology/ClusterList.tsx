import type { Topology } from '../../types/state'
import { formatNumber } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

export function ClusterList({ topology }: { topology: Topology | undefined }) {
  const clusters = topology?.clusters ?? []

  return (
    <Panel title="Clusters" action={<Badge>{clusters.length} clusters</Badge>}>
      <div className="grid gap-2.5">
        {clusters.length > 0 ? (
          clusters.map((cluster) => (
            <div
              key={cluster.cluster_id}
              className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3"
            >
              <div className="mb-2 flex items-center justify-between gap-3">
                <strong className="text-[0.95rem]">{cluster.cluster_id}</strong>
                <Badge>{cluster.dominant_regime_label}</Badge>
              </div>
              <div className="mb-2 flex flex-wrap gap-1.5">
                {cluster.members.map((member) => (
                  <span
                    key={member}
                    className="rounded-full bg-white/10 px-2 py-0.5 text-[0.72rem] text-white/80"
                  >
                    {member}
                  </span>
                ))}
              </div>
              <small className="text-white/60">
                avg correlation {formatNumber(cluster.average_correlation, 2)}
              </small>
            </div>
          ))
        ) : (
          <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-center text-white/60">
            No clusters yet — waiting for topology data.
          </div>
        )}
      </div>
    </Panel>
  )
}
