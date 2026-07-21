/**
 * V4-W3: the topology scene reads the backend's declared `dimensions.depth`
 * to tell the two embedding modes apart. depth === 1 means 2D mode (z is
 * the volatility encoding); depth === 100 means the backend embedded a
 * real third correlation-distance axis.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Topology } from '../../types/state'
import { TopologyScene3D } from './TopologyScene3D'

function topologyWithDepth(depth: number): Topology {
  return {
    state: 'ready',
    nodes: [
      {
        symbol: 'AAA',
        cluster_id: 'cluster_0',
        x: 50,
        y: 50,
        z: depth > 1 ? 50 : 0.5,
        market_distance: 0.2,
        correlation_strength: 0.8,
        volatility_pressure: 0.3,
        topology_risk: 'normal',
        regime_label: 'bullish',
      },
    ],
    links: [],
    clusters: [],
    dimensions: { width: 100, height: 100, depth },
    reasons: [],
  } as unknown as Topology
}

describe('TopologyScene3D embedding-mode legend', () => {
  it('describes z as volatility pressure in 2D mode', () => {
    render(<TopologyScene3D topology={topologyWithDepth(1)} signals={undefined} />)
    expect(screen.getByText(/z = volatility pressure/)).toBeInTheDocument()
  })

  it('describes all three axes as distance-preserving in 3D mode', () => {
    render(<TopologyScene3D topology={topologyWithDepth(100)} signals={undefined} />)
    expect(screen.getByText(/all three axes are distance-preserving/)).toBeInTheDocument()
  })

  it('always credits node size to volatility, which carries it in both modes', () => {
    render(<TopologyScene3D topology={topologyWithDepth(100)} signals={undefined} />)
    expect(screen.getByText(/Node size = volatility pressure/)).toBeInTheDocument()
  })
})
