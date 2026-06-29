import { Canvas } from '@react-three/fiber'
import { Html, Line, OrbitControls } from '@react-three/drei'
import type { Scene, SceneNode } from '../../types/state'
import { Panel } from '../layout/Panel'

const GOOD = '#4fd4a9'
const WARM = '#f2b96b'

function toVec3(node: SceneNode, dims: { width: number; height: number; depth: number }): [number, number, number] {
  const x = (node.x / dims.width) * 20 - 10
  const y = (node.y / dims.height) * 20 - 10
  const z = (node.z / Math.max(dims.depth, 1)) * 12 - 6
  return [x, y, z]
}

function SceneNodeMesh({ node, position }: { node: SceneNode; position: [number, number, number] }) {
  const radius = 0.35 + Math.max(0, Math.min(1, node.intensity ?? 0.4)) * 0.65
  const color = node.kind === 'portfolio' ? WARM : GOOD

  return (
    <group position={position}>
      <mesh>
        <sphereGeometry args={[radius, 24, 24]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.35}
          opacity={Math.max(0.45, Math.min(1, (node.intensity ?? 0.4) + 0.1))}
          transparent
        />
      </mesh>
      <Html distanceFactor={14} className="pointer-events-none select-none">
        <span className="whitespace-nowrap rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-white">
          {node.label}
        </span>
      </Html>
    </group>
  )
}

function SceneLinks({ scene }: { scene: Scene }) {
  const dims = scene.dimensions ?? { width: 100, height: 100, depth: 1 }
  const nodeById = Object.fromEntries(scene.nodes.map((node) => [node.id, node]))

  return (
    <>
      {scene.links.map((link, index) => {
        const source = nodeById[link.source]
        const target = nodeById[link.target]
        if (!source || !target) return null
        return (
          <Line
            key={`${link.source}-${link.target}-${index}`}
            points={[toVec3(source, dims), toVec3(target, dims)]}
            color="#7bc6ff"
            transparent
            opacity={Math.max(0.15, Math.min(0.9, (link.strength ?? 0.2) * 1.4))}
            lineWidth={1}
          />
        )
      })}
    </>
  )
}

export function Scene3D({ scene }: { scene: Scene | undefined }) {
  const dims = scene?.dimensions ?? { width: 100, height: 100, depth: 1 }

  return (
    <Panel title="Market Scene">
      <div className="relative h-[420px] overflow-hidden rounded-2xl bg-black/20">
        {scene && scene.nodes.length > 0 ? (
          <Canvas camera={{ position: [0, 0, 22], fov: 50 }}>
            <ambientLight intensity={0.6} />
            <pointLight position={[10, 10, 10]} intensity={0.8} />
            <SceneLinks scene={scene} />
            {scene.nodes.map((node) => (
              <SceneNodeMesh key={node.id} node={node} position={toVec3(node, dims)} />
            ))}
            <OrbitControls enableDamping makeDefault />
          </Canvas>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-slate-500">
            Waiting for scene data
          </div>
        )}
        <div className="pointer-events-none absolute bottom-3 left-3 flex flex-col gap-1 text-xs text-slate-400">
          <span>Node size = signal intensity or portfolio importance</span>
          <span>Links = current portfolio/asset relationship</span>
        </div>
      </div>
    </Panel>
  )
}
