import { Canvas } from '@react-three/fiber'
import { Html, Line, OrbitControls } from '@react-three/drei'
import type { Signal, Topology, TopologyNode } from '../../types/state'
import { Panel } from '../layout/Panel'

const ACTION_COLORS: Record<string, string> = {
  trade: '#34d399',
  reduce_risk: '#fb7185',
  retrain_candidate: '#fbbf24',
  simulate: '#38bdf8',
  observe: '#cbd5e1',
}

function toVec3(node: TopologyNode, dims: { width: number; height: number; depth: number }): [number, number, number] {
  const x = (node.x / dims.width) * 20 - 10
  const y = (node.y / dims.height) * 20 - 10
  const z = (node.z / Math.max(dims.depth, 1)) * 12 - 6
  return [x, y, z]
}

function TopologyNodeMesh({
  node,
  position,
  action,
}: {
  node: TopologyNode
  position: [number, number, number]
  action: string | undefined
}) {
  const radius = 0.3 + Math.max(0, Math.min(1, node.volatility_pressure ?? 0.3)) * 0.5
  const color = (action && ACTION_COLORS[action]) || '#7bc6ff'
  // V2-17.5 - dim/fade nodes still running on the deterministic fallback so
  // learned-vs-fallback coverage is visible at a glance without breaking
  // the existing action-based coloring.
  const isFallback = node.topology_source === 'fallback'
  const opacity = isFallback ? 0.55 : 0.92
  const confidence = node.topology_confidence

  return (
    <group position={position}>
      <mesh>
        <sphereGeometry args={[radius, 24, 24]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.35} opacity={opacity} transparent />
      </mesh>
      <Html distanceFactor={14} className="pointer-events-none select-none">
        <span className="whitespace-nowrap rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-white">
          {node.symbol} · {node.cluster_id}
          {node.topology_source ? ` · ${node.topology_source}` : ''}
          {confidence !== undefined ? ` (${Math.round(confidence * 100)}%)` : ''}
        </span>
      </Html>
    </group>
  )
}

function TopologyLinks({ topology }: { topology: Topology }) {
  const dims = topology.dimensions ?? { width: 100, height: 100, depth: 1 }
  const nodeBySymbol = Object.fromEntries(topology.nodes.map((node) => [node.symbol, node]))

  return (
    <>
      {topology.links.map((link, index) => {
        const source = nodeBySymbol[link.source]
        const target = nodeBySymbol[link.target]
        if (!source || !target) return null
        return (
          <Line
            key={`${link.source}-${link.target}-${index}`}
            points={[toVec3(source, dims), toVec3(target, dims)]}
            color="#7bc6ff"
            transparent
            opacity={Math.max(0.15, Math.min(0.9, link.correlation))}
            lineWidth={1}
          />
        )
      })}
    </>
  )
}

export function TopologyScene3D({
  topology,
  signals,
}: {
  topology: Topology | undefined
  signals: Record<string, Signal> | undefined
}) {
  const dims = topology?.dimensions ?? { width: 100, height: 100, depth: 1 }
  const actionBySymbol = Object.fromEntries(
    Object.values(signals ?? {}).map((signal) => [signal.ticker ?? '', signal.market_analysis?.action]),
  )

  return (
    <Panel title="Market Topology">
      <div className="relative h-[460px] overflow-hidden rounded-2xl bg-black/20">
        {topology && topology.nodes.length > 0 ? (
          <Canvas camera={{ position: [0, 0, 22], fov: 50 }}>
            <ambientLight intensity={0.6} />
            <pointLight position={[10, 10, 10]} intensity={0.8} />
            <TopologyLinks topology={topology} />
            {topology.nodes.map((node) => (
              <TopologyNodeMesh
                key={node.symbol}
                node={node}
                position={toVec3(node, dims)}
                action={actionBySymbol[node.symbol]}
              />
            ))}
            <OrbitControls enableDamping makeDefault />
          </Canvas>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-white/40">
            {topology?.state === 'insufficient_data'
              ? 'Insufficient correlated history yet — waiting for more bars.'
              : 'Waiting for topology data'}
          </div>
        )}
        <div className="pointer-events-none absolute bottom-3 left-3 flex flex-col gap-1 text-xs text-white/60">
          <span>Node color = trade / reduce_risk / retrain_candidate / simulate / observe</span>
          <span>Links = pairwise return correlation above the display threshold</span>
        </div>
      </div>
    </Panel>
  )
}
