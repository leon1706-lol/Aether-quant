import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { BenchmarkComparisonReport, EvaluationState } from '../../types/evaluation'
import { BenchmarkPanel } from './BenchmarkPanel'

const REPORT: BenchmarkComparisonReport = {
  baselines: [
    { strategy: 'momentum', net_sharpe: 0.412, total_return_pct: 3.21 },
    { strategy: 'mean_reversion', net_sharpe: -0.108, total_return_pct: -1.4 },
    { strategy: 'random_entry', net_sharpe: 0.052, total_return_pct: 0.31 },
    { strategy: 'sp500', net_sharpe: 0.881, total_return_pct: 12.4, status: 'OK' },
    { strategy: '60_40', net_sharpe: 0.702, total_return_pct: 9.1, status: 'OK' },
  ],
  model_kind: 'sequence',
  head: 'rank_20d',
  split: 'backtest',
}

function evaluationWith(benchmarks: EvaluationState['benchmarks']): EvaluationState {
  return {
    rank_book: { status: 'not_evaluated', hint: '' },
    capacity: { status: 'not_evaluated', hint: '' },
    stress: { status: 'not_evaluated', hint: '' },
    ablation: { status: 'not_evaluated', hint: '' },
    walk_forward: { status: 'not_evaluated', hint: '' },
    book_spread_calibration: { status: 'not_evaluated', hint: '' },
    book_history_reconciliation: { status: 'not_evaluated', hint: '' },
    benchmarks,
  }
}

describe('BenchmarkPanel', () => {
  it('shows the not-evaluated empty state with the exact CLI hint', () => {
    render(<BenchmarkPanel evaluation={undefined} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
    expect(screen.getByText('aq evaluate --benchmarks')).toBeInTheDocument()
  })

  it('renders every baseline row with sharpe and total return', () => {
    render(<BenchmarkPanel evaluation={evaluationWith(REPORT)} />)
    expect(screen.getByTestId('bench-row-sp500')).toBeInTheDocument()
    expect(screen.getByTestId('bench-row-60_40')).toBeInTheDocument()
    expect(screen.getByTestId('bench-row-momentum')).toBeInTheDocument()
    // Signed formatting: positive sharpe gets a plus, negative does not.
    expect(screen.getByText('+0.412')).toBeInTheDocument()
    expect(screen.getByText('-0.108')).toBeInTheDocument()
    expect(screen.getByText('+12.40%')).toBeInTheDocument()
    // Public vs naive note column.
    expect(screen.getAllByText('public benchmark').length).toBe(2)
    expect(screen.getAllByText('naive strategy').length).toBe(3)
  })

  it('renders a skipped baseline as a muted row with its reason', () => {
    const skipped: BenchmarkComparisonReport = {
      baselines: [
        { strategy: 'momentum', net_sharpe: 0.4, total_return_pct: 1.0 },
        { strategy: 'sp500', net_sharpe: null, total_return_pct: null, status: 'SKIPPED: no usable SPY closes in close_pivot' },
      ],
      split: 'backtest',
    }
    render(<BenchmarkPanel evaluation={evaluationWith(skipped)} />)
    expect(screen.getByText(/SKIPPED: no usable SPY closes/)).toBeInTheDocument()
    // Both metric cells (sharpe + total return) render the em-dash placeholder.
    expect(screen.getAllByText('—')).toHaveLength(2)
  })

  it('handles a not_evaluated payload served by the backend identically to undefined', () => {
    render(<BenchmarkPanel evaluation={evaluationWith({ status: 'not_evaluated', hint: 'run it' })} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
  })
})
