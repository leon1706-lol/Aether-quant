import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { DynamicSizing, Signal } from '../../types/state'
import { AssetSizingTable } from './AssetSizingTable'

function signal(overrides: Partial<DynamicSizing>): Record<string, Signal> {
  return {
    AAPL: {
      ticker: 'AAPL',
      signal: 'buy',
      confidence: 0.6,
      target_weight: 0.05,
      dynamic_sizing: {
        base_target_weight: 0.05,
        target_weight: 0.05,
        annualized_volatility: 0.2,
        leverage_factor: 1,
        volatility_regime: 'normal_volatility',
        sizing_reason: 'sized',
        ...overrides,
      },
    },
  }
}

describe('AssetSizingTable multiplier breakdown (V4.12.2, Problems.md #71)', () => {
  it('shows the empty state with no signals', () => {
    render(<AssetSizingTable signals={undefined} />)
    expect(screen.getByText(/No runtime signals yet/)).toBeInTheDocument()
  })

  it('renders every multiplier chip at its neutral value muted, not highlighted', () => {
    render(<AssetSizingTable signals={signal({})} />)
    expect(screen.getByText('rl ×1.00')).toBeInTheDocument()
    expect(screen.getByText('rank ×1.00')).toBeInTheDocument()
    expect(screen.getByText('topo ×1.00')).toBeInTheDocument()
    expect(screen.getByText('conf ×1.00')).toBeInTheDocument()
    expect(screen.getByText('rl ×1.00').className).not.toContain('text-sky-300')
  })

  it('highlights an active RL sizing multiplier and surfaces its reason as a tooltip', () => {
    render(
      <AssetSizingTable
        signals={signal({ rl_multiplier: 0.75, rl_sizing_reason: 'rl_sizing_shrink_low_confidence' })}
      />,
    )
    const chip = screen.getByText('rl ×0.75')
    expect(chip).toBeInTheDocument()
    expect(chip.className).toContain('text-sky-300')
    expect(chip.getAttribute('title')).toBe('rl_sizing_shrink_low_confidence')
  })
})
