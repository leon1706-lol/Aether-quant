import type { RuntimeState } from '../types/state'
import { useEvaluation } from '../api/hooks'
import { RankBookPerformancePanel } from '../components/evaluation/RankBookPerformancePanel'
import { CapacityStressPanel } from '../components/evaluation/CapacityStressPanel'
import { WalkForwardStabilityPanel } from '../components/evaluation/WalkForwardStabilityPanel'
import { AblationPanel } from '../components/evaluation/AblationPanel'
import { BookSpreadCalibrationPanel } from '../components/evaluation/BookSpreadCalibrationPanel'
import { BookHistoryReconciliationPanel } from '../components/evaluation/BookHistoryReconciliationPanel'

// V5.1 Phase 0 - the cost-aware rank-book evaluation dashboard: "is the fee
// drag fixed", breadth/capacity, and cost-stress robustness, all sourced
// from `aq evaluate` (never computed by the webui itself - this is a pure
// display layer over ml/evaluation/*.json, same read-only contract every
// other tab already follows). V5.2.3 (development/Problems.md #91) added
// the book-history reconciliation panel (plus the book-spread calibration
// panel, a V5.1 report that was never wired in until now) - both close
// the same "aq evaluate report has zero frontend exposure" gap this page
// exists to avoid.
export function EvaluationPage(_props: { state: RuntimeState | undefined }) {
  const { data: evaluation } = useEvaluation()

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <RankBookPerformancePanel evaluation={evaluation} />
      <CapacityStressPanel evaluation={evaluation} />
      <WalkForwardStabilityPanel evaluation={evaluation} />
      <AblationPanel evaluation={evaluation} />
      <BookSpreadCalibrationPanel evaluation={evaluation} />
      <BookHistoryReconciliationPanel evaluation={evaluation} />
    </div>
  )
}
