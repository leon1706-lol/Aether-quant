import type { Topology } from '../../types/state'
import { formatNumber } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V2-17.5 - client-side aggregation over topology.nodes so the dashboard
// doesn't need a new backend endpoint just to summarize per-node fields
// main.py/topology.learned_topology already writes into state.json.
function summarize(topology: Topology | undefined) {
  const nodes = topology?.nodes ?? []
  const sourceCounts: Record<string, number> = {}
  let confidenceSum = 0
  let uncertaintySum = 0
  let maxStress = 0
  let disagreementCount = 0

  for (const node of nodes) {
    const source = node.topology_source ?? 'deterministic'
    sourceCounts[source] = (sourceCounts[source] ?? 0) + 1
    confidenceSum += node.topology_confidence ?? 0
    uncertaintySum += node.topology_uncertainty ?? 0
    maxStress = Math.max(maxStress, node.stress_score ?? 0)
    if ((node.topology_disagreement ?? 0) >= 0.5) disagreementCount += 1
  }

  const count = nodes.length || 1
  return {
    sourceCounts,
    avgConfidence: confidenceSum / count,
    avgUncertainty: uncertaintySum / count,
    maxStress,
    disagreementCount,
    nodeCount: nodes.length,
  }
}

export function TopologyLearningPanel({ topology }: { topology: Topology | undefined }) {
  const summary = summarize(topology)
  const topologySource = topology?.topology_source ?? 'fallback'

  const metrics: [string, string][] = [
    ['Avg Confidence', formatNumber(summary.avgConfidence, 2)],
    ['Avg Uncertainty', formatNumber(summary.avgUncertainty, 2)],
    ['Max Stress', formatNumber(summary.maxStress, 2)],
    ['Regime/Cluster Mismatches', String(summary.disagreementCount)],
  ]

  return (
    <Panel
      title="Learned Topology"
      action={<Badge tone={topologySource}>{topologySource}</Badge>}
    >
      <div className="mb-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-white/70">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <small className="text-white/60">
            {topology?.model_loaded ? 'Learned model active' : 'Deterministic fallback (no model loaded)'}
          </small>
          {topology?.model_version_id ? (
            <span className="text-xs text-white/40">v {topology.model_version_id.slice(0, 8)}</span>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        {metrics.map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
            <small className="text-white/60">{label}</small>
            <div className="text-sm text-white">{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {Object.entries(summary.sourceCounts).map(([source, count]) => (
          <span key={source} className="rounded-full bg-white/10 px-2 py-0.5 text-[0.72rem] text-white/80">
            {source}: {count}/{summary.nodeCount || 0}
          </span>
        ))}
      </div>

      {topology?.reasons && topology.reasons.length > 0 ? (
        <div className="mt-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <strong className="text-xs uppercase tracking-widest text-white/60">Reasons</strong>
          <div className="mt-1 grid gap-0.5 text-xs text-white/50">
            {topology.reasons.map((reason) => (
              <span key={reason}>{reason}</span>
            ))}
          </div>
        </div>
      ) : null}
    </Panel>
  )
}
