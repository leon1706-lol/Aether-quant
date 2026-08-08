import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { BookSpreadCalibrationReport, EvaluationState } from '../../types/evaluation'
import { BookSpreadCalibrationPanel } from './BookSpreadCalibrationPanel'

const REPORT: BookSpreadCalibrationReport = {
  calibrated_min_rank_confidence_spread: 0.5014,
  percentile: 0.1,
  num_dates_used: 200,
  num_dates_skipped_thin_universe: 3,
  spread_distribution: { min: 0.1, p10: 0.55, p25: 0.6, median: 0.7, p75: 0.8, max: 0.95 },
}

function evaluationWith(bookSpreadCalibration: EvaluationState['book_spread_calibration']): EvaluationState {
  return {
    rank_book: { status: 'not_evaluated', hint: '' },
    capacity: { status: 'not_evaluated', hint: '' },
    stress: { status: 'not_evaluated', hint: '' },
    ablation: { status: 'not_evaluated', hint: '' },
    walk_forward: { status: 'not_evaluated', hint: '' },
    book_spread_calibration: bookSpreadCalibration,
    book_history_reconciliation: { status: 'not_evaluated', hint: '' },
  }
}

describe('BookSpreadCalibrationPanel', () => {
  it('shows the not-evaluated empty state (with the exact CLI hint) when no calibration run exists', () => {
    render(<BookSpreadCalibrationPanel evaluation={undefined} />)
    expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument()
    expect(screen.getByText('aq evaluate --calibrate-book-spread')).toBeInTheDocument()
  })

  it('renders the calibrated spread and its distribution', () => {
    render(<BookSpreadCalibrationPanel evaluation={evaluationWith(REPORT)} />)
    expect(screen.getByText(/calibrated_min_rank_confidence_spread: 0\.5014/)).toBeInTheDocument()
    expect(screen.getByText(/200 dates used/)).toBeInTheDocument()
    expect(screen.getByText('0.55')).toBeInTheDocument()
  })
})
