import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BookNeutralityPanel } from './BookNeutralityPanel'

describe('BookNeutralityPanel (V5.1 Phase 1, Problems.md item 6)', () => {
  it('shows a graceful empty state pre-first-rebalance / when neutrality is disabled', () => {
    render(<BookNeutralityPanel diagnostics={undefined} />)
    expect(screen.getByText(/No neutrality pass run yet/)).toBeInTheDocument()
  })

  it('renders gross/net before-after and per-sector net exposure', () => {
    render(
      <BookNeutralityPanel
        diagnostics={{
          pre_gross: 0.48,
          post_gross: 0.48,
          net_before: 0.0,
          net_after: 0.0,
          per_sector_net: { Tech: 0.0, Fin: 0.0 },
          steps_applied: ['per_name_cap', 'sector_neutral', 'dollar_neutral'],
        }}
      />,
    )
    expect(screen.getByText('3 steps')).toBeInTheDocument()
    expect(screen.getByText(/Tech:/)).toBeInTheDocument()
    expect(screen.getByText(/steps applied:/)).toBeInTheDocument()
  })
})
