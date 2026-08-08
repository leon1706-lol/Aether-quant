import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AblationReport, EvaluationState } from '../../types/evaluation'
import { AblationPanel } from './AblationPanel'

const REPORT: AblationReport = {
  static_baseline: {
    gross_sharpe: 0.1,
    net_sharpe: 0.1,
    gross_total_return: 0.02,
    net_total_return: 0.02,
    net_max_drawdown: -0.03,
    annualized_turnover: 0,
    cost_drag_annual_bps: 0,
    num_rebalances: 1,
    num_dates_used: 250,
    mean_names_long: 20,
    mean_names_short: 0,
    per_date_net_return: [],
    per_date: [],
    delta_vs_static_baseline: 0,
  },
  no_cost_model: {
    gross_sharpe: 0.9,
    net_sharpe: 0.9,
    gross_total_return: 0.15,
    net_total_return: 0.15,
    net_max_drawdown: -0.05,
    annualized_turnover: 3.2,
    cost_drag_annual_bps: 0,
    num_rebalances: 24,
    num_dates_used: 250,
    mean_names_long: 6,
    mean_names_short: 6,
    per_date_net_return: [],
    per_date: [],
    delta_vs_static_baseline: 0.8,
  },
  no_gating: {
    status: 'not_offline_measurable',
    reason: 'The MoE gating blend drives probability_up/magnitude/volatility - absent from the offline dataset.',
  },
}

function evaluationWith(ablation: EvaluationState['ablation']): EvaluationState {
  return {
    rank_book: { status: 'not_evaluated', hint: '' },
    capacity: { status: 'not_evaluated', hint: '' },
    stress: { status: 'not_evaluated', hint: '' },
    ablation,
    walk_forward: { status: 'not_evaluated', hint: '' },
    book_spread_calibration: { status: 'not_evaluated', hint: '' },
    book_history_reconciliation: { status: 'not_evaluated', hint: '' },
  }
}

describe('AblationPanel', () => {
  it('shows the not-evaluated empty state (with the exact CLI hint) when no ablation run exists', () => {
    render(<AblationPanel evaluation={undefined} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
    expect(screen.getByText('aq evaluate --ablation')).toBeInTheDocument()
  })

  it('also shows the empty state when the section is explicitly not_evaluated', () => {
    render(<AblationPanel evaluation={evaluationWith({ status: 'not_evaluated', hint: 'x' })} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
  })

  it('renders measured variants with their delta', () => {
    render(<AblationPanel evaluation={evaluationWith(REPORT)} />)
    expect(screen.getByText('static_baseline')).toBeInTheDocument()
    expect(screen.getByText('no_cost_model')).toBeInTheDocument()
    expect(screen.getByText('+0.800')).toBeInTheDocument()
  })

  it('renders unmeasurable variants with a visible, muted sentinel row rather than omitting them', () => {
    render(<AblationPanel evaluation={evaluationWith(REPORT)} />)
    expect(screen.getByText('no_gating')).toBeInTheDocument()
    expect(screen.getByText('not offline measurable')).toBeInTheDocument()
    expect(screen.getByText(/MoE gating blend/)).toBeInTheDocument()
  })
})
