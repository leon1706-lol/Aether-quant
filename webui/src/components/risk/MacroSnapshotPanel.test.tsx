import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MacroSnapshotPanel } from './MacroSnapshotPanel'

describe('MacroSnapshotPanel (V4.12.2, Problems.md #71)', () => {
  it('shows a graceful empty state when state.macro is absent (pre-first-bar / old artifact)', () => {
    render(<MacroSnapshotPanel macro={undefined} />)
    expect(screen.getByText(/No macro snapshot yet/)).toBeInTheDocument()
  })

  it('renders bond and alt-data stat tiles from a real snapshot', () => {
    render(
      <MacroSnapshotPanel
        macro={{
          yield_curve_level: 0.015,
          yield_curve_slope: -0.002,
          yield_curve_curvature: 0.0004,
          credit_spread_level: 0.021,
          implied_volatility_level: 0.18,
          implied_vol_term_structure: -0.05,
          financial_conditions_change: 0.12,
          sensitivity_driver_levels: { vix: 18.2, real_rate: 0.014, credit: 0.021, dollar: 104.3 },
        }}
      />,
    )
    expect(screen.getByText('Yield Curve Level')).toBeInTheDocument()
    expect(screen.getByText('Implied Vol Level')).toBeInTheDocument()
    expect(screen.queryByText(/No macro snapshot yet/)).not.toBeInTheDocument()
  })

  it('renders the V5.1 Phase 2 sensitivity-driver level tiles when present', () => {
    render(
      <MacroSnapshotPanel
        macro={{ sensitivity_driver_levels: { vix: 18.2, real_rate: 0.014, credit: 0.021, dollar: 104.3 } }}
      />,
    )
    expect(screen.getByText('Real Rate (10Y TIPS)')).toBeInTheDocument()
    expect(screen.getByText('Dollar Index')).toBeInTheDocument()
  })

  it('renders a dash, not a misleading 0.00, for a null value inside a present snapshot', () => {
    render(<MacroSnapshotPanel macro={{ yield_curve_level: null }} />)
    const tile = screen.getByText('Yield Curve Level').parentElement
    expect(tile?.textContent).toContain('—')
  })
})
