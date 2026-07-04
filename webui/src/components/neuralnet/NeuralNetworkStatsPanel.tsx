import type { NeuralNetworkState } from '../../types/state'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

function NetworkRow({ network }: { network: NeuralNetworkState['networks'][number] }) {
  const tone = network.role === 'baseline' ? 'baseline' : network.quality_status ?? undefined

  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-white">{network.label}</span>
        <Badge tone={tone}>{network.role === 'baseline' ? 'baseline' : network.quality_status ?? 'unknown'}</Badge>
      </div>
      {network.status === 'trained' ? (
        <div className="mt-2 grid grid-cols-3 gap-2 text-center">
          <div>
            <small className="text-white/50">Layers</small>
            <div className="text-sm text-white">{network.total_layers}</div>
          </div>
          <div>
            <small className="text-white/50">Nodes</small>
            <div className="text-sm text-white">{network.total_nodes}</div>
          </div>
          <div>
            <small className="text-white/50">Edges</small>
            <div className="text-sm text-white">{network.total_edges.toLocaleString()}</div>
          </div>
        </div>
      ) : (
        <div className="mt-2 text-xs text-white/40">Not trained yet</div>
      )}
      <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[0.7rem] text-white/40">
        <span>{network.node_layers.length > 0 ? network.node_layers.join(' → ') : '—'}</span>
        <span>{network.last_modified ? new Date(network.last_modified).toLocaleString() : 'no file yet'}</span>
      </div>
    </div>
  )
}

export function NeuralNetworkStatsPanel({ neuralNetwork }: { neuralNetwork: NeuralNetworkState | undefined }) {
  const totals = neuralNetwork?.totals
  const networks = neuralNetwork?.networks ?? []

  return (
    <Panel title="Network Stats">
      <div className="mb-3 grid grid-cols-2 gap-2.5">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <small className="text-white/60">Networks Trained</small>
          <div className="text-sm text-white">
            {totals?.trained_count ?? 0} / {totals?.total_networks ?? 0}
          </div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <small className="text-white/60">Total Layers</small>
          <div className="text-sm text-white">{totals?.total_layers ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <small className="text-white/60">Total Nodes</small>
          <div className="text-sm text-white">{totals?.total_nodes ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <small className="text-white/60">Total Edges</small>
          <div className="text-sm text-white">{(totals?.total_edges ?? 0).toLocaleString()}</div>
        </div>
      </div>

      <div className="grid gap-2">
        {networks.map((network) => (
          <NetworkRow key={network.name} network={network} />
        ))}
      </div>

      {neuralNetwork?.excluded && neuralNetwork.excluded.length > 0 ? (
        <div className="mt-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <strong className="text-xs uppercase tracking-widest text-white/60">Not shown here</strong>
          <div className="mt-1 grid gap-1 text-xs text-white/50">
            {neuralNetwork.excluded.map((entry) => (
              <span key={entry.name}>
                <span className="text-white/70">{entry.name}</span> — {entry.reason}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </Panel>
  )
}
