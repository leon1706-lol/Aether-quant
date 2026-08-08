import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { BookHistoryReconciliationReport, EvaluationState } from '../../types/evaluation'
import { BookHistoryReconciliationPanel } from './BookHistoryReconciliationPanel'

const BASE_SUMMARY = {
  num_dates: 112,
  num_dates_exact_match: 0,
  mean_overlap_fraction: 0.346,
  mean_raw_score_delta_abs: 0.037,
  mean_weight_delta_abs: 0.135,
  num_dates_with_weight_logged: 112,
  num_symbols_only_logged_total: 671,
  num_symbols_only_offline_total: 671,
}

function reportWith(overrides: Partial<BookHistoryReconciliationReport>): BookHistoryReconciliationReport {
  return {
    mode: 'independent',
    per_date: [],
    summary: BASE_SUMMARY,
    universe_summary: { num_dates_with_universe_data: 0, by_security_type: {} },
    ...overrides,
  }
}

function evaluationWith(bookHistoryReconciliation: EvaluationState['book_history_reconciliation']): EvaluationState {
  return {
    rank_book: { status: 'not_evaluated', hint: '' },
    capacity: { status: 'not_evaluated', hint: '' },
    stress: { status: 'not_evaluated', hint: '' },
    ablation: { status: 'not_evaluated', hint: '' },
    walk_forward: { status: 'not_evaluated', hint: '' },
    book_spread_calibration: { status: 'not_evaluated', hint: '' },
    book_history_reconciliation: bookHistoryReconciliation,
  }
}

describe('BookHistoryReconciliationPanel', () => {
  it('shows the not-evaluated empty state (with the exact CLI hint) when no reconciliation run exists', () => {
    render(<BookHistoryReconciliationPanel evaluation={undefined} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
    expect(screen.getByText('aq evaluate --reconcile-book-history')).toBeInTheDocument()
  })

  it('renders the summary stat tiles and the independent-mode caveat', () => {
    render(<BookHistoryReconciliationPanel evaluation={evaluationWith(reportWith({}))} />)
    expect(screen.getByText('34.6%')).toBeInTheDocument()
    expect(screen.getByText('0/112')).toBeInTheDocument()
    expect(screen.getByText(/no hysteresis replayed/)).toBeInTheDocument()
  })

  it('shows the replay-hysteresis caveat instead when mode is replay_hysteresis', () => {
    render(<BookHistoryReconciliationPanel evaluation={evaluationWith(reportWith({ mode: 'replay_hysteresis' }))} />)
    expect(screen.getByText(/Hysteresis replayed/)).toBeInTheDocument()
    expect(screen.getByText('hysteresis replay')).toBeInTheDocument()
  })

  it('shows the missing-universe-data hint when the log has no full-universe snapshot', () => {
    render(<BookHistoryReconciliationPanel evaluation={evaluationWith(reportWith({}))} />)
    expect(screen.getByText(/include_full_universe=true/)).toBeInTheDocument()
  })

  it('renders the per-security-type breakdown table when universe data is present', () => {
    const report = reportWith({
      universe_summary: {
        num_dates_with_universe_data: 107,
        by_security_type: {
          equity: { num_symbol_dates: 8000, mean_raw_rank_score: 0.5, feature_ready_rate: 0.99, trading_eligible_rate: 1.0 },
          crypto: { num_symbol_dates: 200, mean_raw_rank_score: 0.9, feature_ready_rate: 1.0, trading_eligible_rate: 1.0 },
        },
      },
    })
    render(<BookHistoryReconciliationPanel evaluation={evaluationWith(report)} />)
    expect(screen.getByText('equity')).toBeInTheDocument()
    expect(screen.getByText('crypto')).toBeInTheDocument()
    expect(screen.queryByText(/include_full_universe=true/)).not.toBeInTheDocument()
  })
})
