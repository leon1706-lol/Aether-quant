import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SensitivityPanel } from './SensitivityPanel'

describe('SensitivityPanel (V5.1 Phase 2, item 8 / F2)', () => {
  it('shows a graceful empty state when no symbol has a sensitivity reading yet', () => {
    render(<SensitivityPanel signals={undefined} />)
    expect(screen.getByText(/No per-symbol sensitivity betas yet/)).toBeInTheDocument()
  })

  it('renders one row per symbol with cross_asset_sensitivity present', () => {
    render(
      <SensitivityPanel
        signals={{
          AAPL: {
            symbol: 'AAPL',
            ticker: 'AAPL',
            cross_asset_sensitivity: {
              sens_vix_beta: -0.42,
              sens_vix_interaction: 0.01,
              sens_real_rate_beta: 0.15,
              sens_real_rate_interaction: -0.002,
              sens_credit_beta: 0.05,
              sens_credit_interaction: 0.0,
              sens_dollar_beta: -0.08,
              sens_dollar_interaction: 0.001,
            },
          },
          MSFT: { symbol: 'MSFT', ticker: 'MSFT' },
        }}
      />,
    )
    expect(screen.getByText('AAPL')).toBeInTheDocument()
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument()
    expect(screen.getByText('-0.420')).toBeInTheDocument()
  })
})
