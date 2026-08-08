import type { BookSpreadCalibrationReport } from '../../types/evaluation'
import { isNotEvaluated, type EvaluationState } from '../../types/evaluation'
import { Panel } from '../layout/Panel'

// V5.2.3 - closes a pre-existing gap: aq evaluate --calibrate-book-spread
// (V5.1) has always written ml/evaluation/book_spread_calibration.json but
// was never surfaced in the webui until this panel. Pure display layer
// over that report, same read-only contract every other evaluation panel
// already follows.
export function BookSpreadCalibrationPanel({ evaluation }: { evaluation: EvaluationState | undefined }) {
  const report = evaluation?.book_spread_calibration

  if (!report || isNotEvaluated(report)) {
    return (
      <Panel title="Book Spread Calibration">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-6 text-center text-sm text-white/50">
          Not evaluated yet — run{' '}
          <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-orange-300">
            aq evaluate --calibrate-book-spread
          </code>
        </div>
      </Panel>
    )
  }

  const calibration = report as BookSpreadCalibrationReport
  const distribution = calibration.spread_distribution

  return (
    <Panel title="Book Spread Calibration">
      <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm text-white">
            calibrated_min_rank_confidence_spread: {calibration.calibrated_min_rank_confidence_spread.toFixed(4)}
          </span>
          <span className="text-xs text-white/50">p{(calibration.percentile * 100).toFixed(0)}</span>
        </div>
        <div className="mt-1.5 text-xs text-white/50">
          {calibration.num_dates_used} dates used, {calibration.num_dates_skipped_thin_universe} skipped (thin universe)
        </div>
        <table className="mt-2 w-full border-collapse text-xs">
          <thead>
            <tr className="text-left text-white/40">
              <th className="pr-3 font-normal">min</th>
              <th className="pr-3 font-normal">p10</th>
              <th className="pr-3 font-normal">p25</th>
              <th className="pr-3 font-normal">median</th>
              <th className="pr-3 font-normal">p75</th>
              <th className="pr-3 font-normal">max</th>
            </tr>
          </thead>
          <tbody>
            <tr className="text-white/70">
              <td className="pr-3">{distribution.min ?? '—'}</td>
              <td className="pr-3">{distribution.p10 ?? '—'}</td>
              <td className="pr-3">{distribution.p25 ?? '—'}</td>
              <td className="pr-3">{distribution.median ?? '—'}</td>
              <td className="pr-3">{distribution.p75 ?? '—'}</td>
              <td className="pr-3">{distribution.max ?? '—'}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
