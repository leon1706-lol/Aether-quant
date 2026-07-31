import type { RuntimeState } from '../types/state'
import { useEvaluation } from '../api/hooks'
import { RankBookPerformancePanel } from '../components/evaluation/RankBookPerformancePanel'
import { CapacityStressPanel } from '../components/evaluation/CapacityStressPanel'

// V5.1 Phase 0 - the cost-aware rank-book evaluation dashboard: "is the fee
// drag fixed", breadth/capacity, and cost-stress robustness, all sourced
// from `aq evaluate` (never computed by the webui itself - this is a pure
// display layer over ml/evaluation/*.json, same read-only contract every
// other tab already follows).
export function EvaluationPage(_props: { state: RuntimeState | undefined }) {
  const { data: evaluation } = useEvaluation()

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <RankBookPerformancePanel evaluation={evaluation} />
      <CapacityStressPanel evaluation={evaluation} />
    </div>
  )
}
