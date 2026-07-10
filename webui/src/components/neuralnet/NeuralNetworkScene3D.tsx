import { Canvas } from '@react-three/fiber'
import { Html, Line, OrbitControls } from '@react-three/drei'
import type { NeuralNetworkModel, NeuralNetworkState } from '../../types/state'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

const NETWORK_GAP = 9
const LAYER_GAP = 3.2
const NODE_GAP = 0.55
const MAX_NODES_PER_LAYER = 12
const HIDDEN_NODE_RADIUS = 0.18
const OUTPUT_NODE_RADIUS = 0.32
const OUTPUT_NODE_COLOR = '#fef3c7'

// Baseline centered, experts arranged around it, gating at the far end
// (it consumes every other network's output), then the multitask family
// (baseline + each expert's magnitude/volatility head) and finally the
// Phase 2 sequence encoder - so the biggest/most important network still
// reads as the visual anchor, with the newer additions trailing it in the
// order they were introduced.
const NETWORK_ORDER = [
  'bullish',
  'bearish',
  'baseline',
  'sideways',
  'volatility',
  'gating',
  'baseline_multitask',
  'bullish_multitask',
  'bearish_multitask',
  'sideways_multitask',
  'volatility_multitask',
  'sequence',
]

// Multitask/sequence exports use a branching {"trunk", "heads"} shape
// instead of one flat layer list - heads are rendered as separate labeled
// mini-network columns (see headColumnsFor()) rather than a single merged
// diagram, so this fixes the display order of the 3 heads regardless of
// the backend dict's iteration order.
const HEAD_DISPLAY_ORDER = ['direction', 'magnitude', 'volatility']

type Vec3 = [number, number, number]

function networkColor(network: NeuralNetworkModel): string {
  if (network.role === 'baseline') return '#38bdf8'
  if (network.role === 'gating') return '#a78bfa'
  if (network.role === 'multitask' || network.role === 'expert_multitask') return '#2dd4bf'
  if (network.role === 'sequence') return '#818cf8'
  switch (network.quality_status) {
    case 'stable':
      return '#34d399'
    case 'watchlist':
      return '#fbbf24'
    case 'disabled_for_gating':
      return '#fb7185'
    default:
      return '#cbd5e1'
  }
}

// Expands one multitask/sequence network into one synthetic diagram column
// per head - each column is `network.node_layers` (the shared trunk) with
// that head's own tail appended, so the trunk is genuinely rendered once
// per head via the exact same NetworkDiagram/layerNodePositions primitives
// the flat baseline/expert/gating networks already use, no new 3D layout
// code required. A network with no `heads` (flat networks, or a
// not-yet-trained multitask/sequence network - heads is always {} on the
// not_trained path) renders as a single column, unchanged from before.
function headColumnsFor(network: NeuralNetworkModel): NeuralNetworkModel[] {
  const heads = network.heads
  if (!heads || Object.keys(heads).length === 0) {
    return [network]
  }
  const orderedHeadNames = [
    ...HEAD_DISPLAY_ORDER.filter((name) => heads[name]),
    ...Object.keys(heads).filter((name) => !HEAD_DISPLAY_ORDER.includes(name)),
  ]
  return orderedHeadNames.map((headName) => ({
    ...network,
    name: `${network.name}::${headName}`,
    label: `${network.label} · ${headName}`,
    node_layers: [...network.node_layers, ...heads[headName].slice(1)],
  }))
}

function sampledIndexCount(width: number): number {
  return Math.min(width, MAX_NODES_PER_LAYER)
}

function layerNodePositions(network: NeuralNetworkModel, columnX: number): Vec3[][] {
  const layerCount = network.node_layers.length
  return network.node_layers.map((width, layerIndex) => {
    const z = (layerIndex - (layerCount - 1) / 2) * LAYER_GAP
    const shown = sampledIndexCount(width)
    return Array.from({ length: shown }, (_, shownIndex) => {
      const y = (shownIndex - (shown - 1) / 2) * NODE_GAP
      return [columnX, y, z] as Vec3
    })
  })
}

function edgesBetweenLayers(a: Vec3[], b: Vec3[]): [Vec3, Vec3][] {
  const edges: [Vec3, Vec3][] = []
  const na = a.length
  const nb = b.length
  for (let i = 0; i < na; i += 1) {
    for (let j = 0; j < nb; j += 1) {
      const ratioA = na > 1 ? i / (na - 1) : 0.5
      const ratioB = nb > 1 ? j / (nb - 1) : 0.5
      if (na <= 3 || nb <= 3 || Math.abs(ratioA - ratioB) < 0.3) {
        edges.push([a[i], b[j]])
      }
    }
  }
  return edges
}

function NetworkDiagram({ network, columnX }: { network: NeuralNetworkModel; columnX: number }) {
  if (network.status !== 'trained' || network.node_layers.length === 0) {
    return (
      <group position={[columnX, 0, 0]}>
        <Html distanceFactor={16} className="pointer-events-none select-none">
          <span className="whitespace-nowrap rounded bg-black/60 px-2 py-1 text-[10px] font-semibold text-white/50">
            {network.label} · not trained
          </span>
        </Html>
      </group>
    )
  }

  const color = networkColor(network)
  const layers = layerNodePositions(network, columnX)
  const topLayerY = (sampledIndexCount(network.node_layers[0]) - 1) / 2 + 1.1

  return (
    <group>
      {layers.slice(0, -1).map((layer, index) =>
        edgesBetweenLayers(layer, layers[index + 1]).map(([start, end], edgeIndex) => (
          <Line
            key={`${network.name}-edge-${index}-${edgeIndex}`}
            points={[start, end]}
            color={color}
            transparent
            opacity={0.18}
            lineWidth={1}
          />
        )),
      )}
      {layers.map((layer, layerIndex) => {
        const isOutputLayer = layerIndex === layers.length - 1
        return layer.map((position, nodeIndex) => (
          <mesh key={`${network.name}-node-${layerIndex}-${nodeIndex}`} position={position}>
            <sphereGeometry args={[isOutputLayer ? OUTPUT_NODE_RADIUS : HIDDEN_NODE_RADIUS, 16, 16]} />
            <meshStandardMaterial
              color={isOutputLayer ? OUTPUT_NODE_COLOR : color}
              emissive={isOutputLayer ? OUTPUT_NODE_COLOR : color}
              emissiveIntensity={isOutputLayer ? 0.9 : 0.4}
            />
          </mesh>
        ))
      })}
      <Html position={[columnX, topLayerY, layers.length ? layers[0][0][2] - LAYER_GAP * 0.6 : 0]} distanceFactor={16} className="pointer-events-none select-none">
        <div className="flex flex-col items-center gap-1 whitespace-nowrap">
          <span className="rounded bg-black/70 px-2 py-0.5 text-[11px] font-semibold text-white">{network.label}</span>
          {network.quality_status ? (
            <span className="scale-90">
              <Badge tone={network.quality_status}>{network.quality_status}</Badge>
            </span>
          ) : (
            <span className="scale-90">
              <Badge tone="baseline">baseline</Badge>
            </span>
          )}
        </div>
      </Html>
      <Html
        position={layers[layers.length - 1][0]}
        distanceFactor={16}
        className="pointer-events-none select-none"
      >
        <span className="translate-y-4 whitespace-nowrap rounded bg-black/70 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-200">
          output
        </span>
      </Html>
    </group>
  )
}

export function NeuralNetworkScene3D({ neuralNetwork }: { neuralNetwork: NeuralNetworkState | undefined }) {
  const networks = neuralNetwork?.networks ?? []
  const orderedNetworks = NETWORK_ORDER.map((name) => networks.find((network) => network.name === name)).filter(
    (network): network is NeuralNetworkModel => Boolean(network),
  )
  const diagramColumns = orderedNetworks.flatMap(headColumnsFor)
  const slotCount = diagramColumns.length || 1

  return (
    <Panel title="Neural Networks">
      <div className="relative h-[460px] overflow-hidden rounded-2xl bg-black/20">
        {diagramColumns.length > 0 ? (
          <Canvas camera={{ position: [2, 5, 26], fov: 50 }}>
            <ambientLight intensity={0.6} />
            <pointLight position={[10, 10, 10]} intensity={0.8} />
            {diagramColumns.map((network, slotIndex) => (
              <NetworkDiagram
                key={network.name}
                network={network}
                columnX={(slotIndex - (slotCount - 1) / 2) * NETWORK_GAP}
              />
            ))}
            <OrbitControls enableDamping makeDefault />
          </Canvas>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-white/40">
            Waiting for neural network data
          </div>
        )}
        <div className="pointer-events-none absolute bottom-3 left-3 flex flex-col gap-1 text-xs text-white/60">
          <span>Baseline (sky) centered · experts colored by quality status · gating (violet) blends them all</span>
          <span>Multitask family (teal) and the Phase 2 sequence encoder (indigo) each render one column per
            output head — direction / magnitude / volatility — sharing the same trunk shape</span>
          <span>Every column funnels down to one glowing amber output node — the final decision for that head</span>
          <span>Wide layers are sampled to a legible node count — exact totals are in the stats panel</span>
        </div>
      </div>
    </Panel>
  )
}
