import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { EvaluationState, WalkForwardSummary } from '../../types/evaluation'
import { WalkForwardStabilityPanel } from './WalkForwardStabilityPanel'

const SUMMARY: WalkForwardSummary = {
  run_id: 'walk-forward-abc123',
  num_windows: 6,
  window_results: [],
  summary: {
    num_windows: 6,
    per_window_metric_values: [0.02, 0.03, 0.01, 0.04, 0.02, 0.03],
    cross_window_bootstrap: {
      lower_bound: 0.01,
      upper_bound: 0.04,
      mean_ic: 0.025,
      confidence: 0.95,
      n_resamples: 2000,
      num_observations: 6,
    },
  },
  summary_by_metric: {
    rank_20d_ic: {
      num_windows: 6,
      per_window_metric_values: [0.02, 0.03, 0.01, 0.04, 0.02, 0.03],
      cross_window_bootstrap: {
        lower_bound: 0.01,
        upper_bound: 0.04,
        mean_ic: 0.025,
        confidence: 0.95,
        n_resamples: 2000,
        num_observations: 6,
      },
    },
  },
  stability_by_metric: {
    rank_20d_ic: {
      num_windows: 6,
      mean: 0.025,
      sign_flip_fraction: 0.0,
      stable: true,
      failures: [],
      bootstrap: { lower_bound: 0.01, upper_bound: 0.04, mean: 0.025 },
    },
    residual_rank_20d_ic: {
      num_windows: 6,
      mean: -0.001,
      sign_flip_fraction: 0.5,
      stable: false,
      failures: ['sign_flip_fraction_above_gate'],
      bootstrap: { lower_bound: -0.02, upper_bound: 0.02, mean: -0.001 },
    },
  },
  net_performance_by_window: [],
}

function evaluationWith(walkForward: EvaluationState['walk_forward']): EvaluationState {
  return {
    rank_book: { status: 'not_evaluated', hint: '' },
    capacity: { status: 'not_evaluated', hint: '' },
    stress: { status: 'not_evaluated', hint: '' },
    ablation: { status: 'not_evaluated', hint: '' },
    walk_forward: walkForward,
    book_spread_calibration: { status: 'not_evaluated', hint: '' },
    book_history_reconciliation: { status: 'not_evaluated', hint: '' },
  }
}

describe('WalkForwardStabilityPanel', () => {
  it('shows the not-evaluated empty state (with the exact CLI hint) when no walk-forward run exists', () => {
    render(<WalkForwardStabilityPanel evaluation={undefined} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
    expect(screen.getByText('aq train --walk-forward --include-multitask --include-sequence')).toBeInTheDocument()
  })

  it('also shows the empty state when the section is explicitly not_evaluated', () => {
    render(<WalkForwardStabilityPanel evaluation={evaluationWith({ status: 'not_evaluated', hint: 'x' })} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
  })

  it('renders one row per tracked metric with stable/unstable badges', () => {
    render(<WalkForwardStabilityPanel evaluation={evaluationWith(SUMMARY)} />)
    expect(screen.getByText('rank_20d_ic')).toBeInTheDocument()
    expect(screen.getByText('residual_rank_20d_ic')).toBeInTheDocument()
    expect(screen.getByText('stable')).toBeInTheDocument()
    expect(screen.getByText('unstable')).toBeInTheDocument()
  })

  it('shows the window count badge', () => {
    render(<WalkForwardStabilityPanel evaluation={evaluationWith(SUMMARY)} />)
    expect(screen.getByText('6 windows')).toBeInTheDocument()
  })
})
