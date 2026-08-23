import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { MonteCarloReport, MonteCarloPercentiles, EvaluationState } from '../../types/evaluation'
import { MonteCarloPanel } from './MonteCarloPanel'

const P = (base: number): MonteCarloPercentiles => {
  // Round to dodge float artifacts (9.38 - 2 === 7.380000000000001).
  const r = (v: number) => Number(v.toFixed(6))
  return {
    p5: r(base - 2),
    p25: r(base - 1),
    p50: r(base),
    p75: r(base + 1),
    p95: r(base + 2),
  }
}

const REPORT: MonteCarloReport = {
  status: 'OK',
  config: { n_runs: 1000, block_size: 20, seed: 42, method: 'block', trading_days_per_year: 252 },
  avg_curve: [1.0, 1.02, 1.05, 1.03],
  pct_band: {
    p5: [1.0, 0.98, 0.99, 0.97],
    p25: [1.0, 1.0, 1.01, 1.0],
    p75: [1.0, 1.04, 1.08, 1.06],
    p95: [1.0, 1.06, 1.12, 1.09],
  },
  final_return_pct: P(9.38),
  sharpe: P(1.4),
  max_drawdown: P(5.5),
  prob_negative_return: 0.095,
  best_run_total_return: 31.2,
  worst_run_total_return: -6.4,
}

function evaluationWith(monteCarlo: EvaluationState['monte_carlo']): EvaluationState {
  return {
    rank_book: { status: 'not_evaluated', hint: '' },
    capacity: { status: 'not_evaluated', hint: '' },
    stress: { status: 'not_evaluated', hint: '' },
    ablation: { status: 'not_evaluated', hint: '' },
    walk_forward: { status: 'not_evaluated', hint: '' },
    book_spread_calibration: { status: 'not_evaluated', hint: '' },
    book_history_reconciliation: { status: 'not_evaluated', hint: '' },
    monte_carlo: monteCarlo,
  }
}

describe('MonteCarloPanel', () => {
  it('shows the not-evaluated empty state with the exact CLI hint', () => {
    render(<MonteCarloPanel evaluation={undefined} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
    expect(screen.getByText('aq evaluate --rank-book --monte-carlo')).toBeInTheDocument()
  })

  it('renders config echo and headline distributions from the report', () => {
    render(<MonteCarloPanel evaluation={evaluationWith(REPORT)} />)
    expect(screen.getByText(/1000 runs · method=block · block=20d · seed=42/)).toBeInTheDocument()
    // final-return row values
    expect(screen.getByText('7.38')).toBeInTheDocument() // p5 = 9.38-2
    expect(screen.getByText('9.38')).toBeInTheDocument() // p50
    expect(screen.getByText('11.38')).toBeInTheDocument() // p95
    expect(screen.getByText(/P\(negative return\):/)).toBeInTheDocument()
  })

  it('renders the svg chart with average line and band area', () => {
    const { container } = render(<MonteCarloPanel evaluation={evaluationWith(REPORT)} />)
    const svg = container.querySelector('[data-testid="mc-svg"]')
    expect(svg).toBeTruthy()
    const paths = svg!.querySelectorAll('path')
    // area band path + red average path minimum
    expect(paths.length).toBeGreaterThanOrEqual(2)
    const avgPath = Array.from(paths).find((p) => p.getAttribute('stroke') === '#ef4444')
    expect(avgPath).toBeTruthy()
  })

  it('handles a not_evaluated payload served by the backend identically to undefined', () => {
    render(<MonteCarloPanel evaluation={evaluationWith({ status: 'not_evaluated', hint: 'run it' })} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
  })
})
