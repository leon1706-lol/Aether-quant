import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ReconciliationPanel } from './ReconciliationPanel'

describe('ReconciliationPanel (V5.1 Phase 6, production safety)', () => {
  it('shows a graceful empty state when no data is available yet', () => {
    render(<ReconciliationPanel report={undefined} />)
    expect(screen.getByText(/No data yet/)).toBeInTheDocument()
  })

  it('shows the not_applicable sentinel rather than a misleading all-orphan report', () => {
    render(
      <ReconciliationPanel
        report={{ status: 'not_applicable', reason: 'portfolio_book_neutrality_or_reconciliation_disabled' }}
      />,
    )
    expect(screen.getByText('not applicable')).toBeInTheDocument()
    expect(screen.getByText(/portfolio_book_neutrality_or_reconciliation_disabled/)).toBeInTheDocument()
  })

  it('renders a fully-matched report as ok, with zero counts elsewhere', () => {
    render(
      <ReconciliationPanel
        report={{
          matched: ['AAPL', 'MSFT'],
          drifted: [],
          orphan_broker: [],
          missing_broker: [],
          max_abs_weight_drift: 0.002,
          breach: false,
        }}
      />,
    )
    expect(screen.getByText('ok')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  it('renders a breach with per-symbol drift rows', () => {
    render(
      <ReconciliationPanel
        report={{
          matched: [],
          drifted: [{ symbol: 'AAPL', expected_weight: 0.1, actual_weight: 0.16, delta_weight: 0.06, delta_usd: 6000 }],
          orphan_broker: [{ symbol: 'TSLA', expected_weight: 0.0, actual_weight: 0.05, delta_weight: 0.05, delta_usd: 5000 }],
          missing_broker: [],
          max_abs_weight_drift: 0.06,
          breach: true,
        }}
      />,
    )
    expect(screen.getByText('BREACH')).toBeInTheDocument()
    expect(screen.getByText('AAPL')).toBeInTheDocument()
    expect(screen.getByText('TSLA')).toBeInTheDocument()
  })
})
