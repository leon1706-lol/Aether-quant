import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { EvaluationState, RankBookSimulationResult } from '../../types/evaluation'
import { RankBookPerformancePanel } from './RankBookPerformancePanel'

const RESULT: RankBookSimulationResult = {
  gross_sharpe: 1.2,
  net_sharpe: 0.4,
  gross_total_return: 0.18,
  net_total_return: 0.05,
  net_max_drawdown: -0.09,
  annualized_turnover: 8.5,
  cost_drag_annual_bps: 620.0,
  num_rebalances: 24,
  num_dates_used: 250,
  mean_names_long: 6.0,
  mean_names_short: 6.0,
  per_date_net_return: [],
  per_date: [],
}

function evaluationWith(rankBook: EvaluationState['rank_book']): EvaluationState {
  return {
    rank_book: rankBook,
    capacity: { status: 'not_evaluated', hint: '' },
    stress: { status: 'not_evaluated', hint: '' },
    ablation: { status: 'not_evaluated', hint: '' },
    walk_forward: { status: 'not_evaluated', hint: '' },
    book_spread_calibration: { status: 'not_evaluated', hint: '' },
    book_history_reconciliation: { status: 'not_evaluated', hint: '' },
  }
}

describe('RankBookPerformancePanel', () => {
  it('shows the not-evaluated empty state (with the exact CLI hint) when aq evaluate has never run', () => {
    render(<RankBookPerformancePanel evaluation={undefined} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
    expect(screen.getByText('aq evaluate --rank-book')).toBeInTheDocument()
  })

  it('also shows the empty state when the section is explicitly not_evaluated', () => {
    render(<RankBookPerformancePanel evaluation={evaluationWith({ status: 'not_evaluated', hint: 'x' })} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
  })

  it('renders every stat tile from a real simulation result', () => {
    render(<RankBookPerformancePanel evaluation={evaluationWith(RESULT)} />)
    expect(screen.getByText('1.200')).toBeInTheDocument() // gross sharpe
    expect(screen.getByText('0.400')).toBeInTheDocument() // net sharpe
    expect(screen.getByText('620.0 bps/yr')).toBeInTheDocument()
    expect(screen.getByText('8.50x')).toBeInTheDocument()
    expect(screen.getByText('24')).toBeInTheDocument()
  })

  it('flags cost drag when net Sharpe has collapsed to less than half of gross', () => {
    const { container } = render(<RankBookPerformancePanel evaluation={evaluationWith(RESULT)} />)
    // net_sharpe (0.4) < gross_sharpe (1.2) * 0.5 (0.6) -> severe drag tone.
    expect(container.querySelector('.text-rose-300')).not.toBeNull()
  })
})
