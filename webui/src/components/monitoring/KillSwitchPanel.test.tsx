import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { KillSwitchPanel } from './KillSwitchPanel'

describe('KillSwitchPanel (V5.1 Phase 6, production safety)', () => {
  it('shows a graceful empty state when no data is available yet', () => {
    render(<KillSwitchPanel decision={undefined} />)
    expect(screen.getByText(/No data yet/)).toBeInTheDocument()
  })

  it('renders the steady-state (never tripped) case without a lock banner', () => {
    render(
      <KillSwitchPanel
        decision={{
          tripped: false,
          severity: 'none',
          triggers: [],
          reason: 'kill_switch_disabled',
          recommended_action: 'none',
          observed: {},
          thresholds: {},
        }}
      />,
    )
    expect(screen.queryByText(/TRADE LOCK ACTIVE/)).not.toBeInTheDocument()
    expect(screen.getByText('none')).toBeInTheDocument()
  })

  it('renders a tripped decision with its lock banner, triggers, and recommended action', () => {
    render(
      <KillSwitchPanel
        decision={{
          tripped: true,
          severity: 'critical',
          triggers: ['rolling_sharpe_below_floor', 'consecutive_losses_above_cap'],
          reason: 'kill_switch_rolling_sharpe_below_floor_and_consecutive_losses_above_cap',
          recommended_action: 'trade_lock',
          observed: { rolling_sharpe: -1.5, consecutive_losses: 14, rolling_sharpe_num_bars: 60 },
          thresholds: { min_rolling_sharpe: -1.0, max_consecutive_losses: 12 },
        }}
      />,
    )
    expect(screen.getByText('TRIPPED')).toBeInTheDocument()
    expect(screen.getByText(/TRADE LOCK ACTIVE/)).toBeInTheDocument()
    // "Rolling Sharpe"/"Consecutive Losses" render twice each - once as a
    // trigger chip, once as the observed-value tile label.
    expect(screen.getAllByText('Rolling Sharpe')).toHaveLength(2)
    expect(screen.getAllByText('Consecutive Losses')).toHaveLength(2)
    expect(screen.getByText('-1.5000')).toBeInTheDocument()
    expect(screen.getByText('14.0000')).toBeInTheDocument()
    // rolling_sharpe_num_bars is filtered out of the observed-values grid
    expect(screen.queryByText(/rolling_sharpe_num_bars/)).not.toBeInTheDocument()
  })
})
