import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { NetEdgePanel } from './NetEdgePanel'

describe('NetEdgePanel (V5.1 Phase 1, Problems.md item 3)', () => {
  it('shows a graceful empty state when no symbol has a net_edge decision yet', () => {
    render(<NetEdgePanel signals={undefined} />)
    expect(screen.getByText(/No net-edge decisions yet/)).toBeInTheDocument()
  })

  it('reports "uncalibrated" while every row is gate-disabled (this project default)', () => {
    render(
      <NetEdgePanel
        signals={{
          AAPL: {
            symbol: 'AAPL',
            ticker: 'AAPL',
            net_edge: {
              expected_edge_bps: 0,
              expected_cost_bps: 0,
              net_edge_bps: 0,
              passes: true,
              reason: 'net_edge_gate_disabled',
            },
          },
        }}
      />,
    )
    expect(screen.getByText('uncalibrated')).toBeInTheDocument()
    expect(screen.getByText('AAPL')).toBeInTheDocument()
  })

  it('reports "calibrated" and renders the verdict once a real net-edge decision is present', () => {
    render(
      <NetEdgePanel
        signals={{
          MSFT: {
            symbol: 'MSFT',
            ticker: 'MSFT',
            net_edge: {
              expected_edge_bps: 22.5,
              expected_cost_bps: 6.0,
              net_edge_bps: 16.5,
              passes: true,
              reason: 'net_edge_clears_cost',
            },
          },
        }}
      />,
    )
    expect(screen.getByText('calibrated')).toBeInTheDocument()
    expect(screen.getByText('net edge clears cost')).toBeInTheDocument()
  })
})
