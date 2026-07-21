import {
  useAssetPerformance,
  useEquityCurves,
  useMetricsSnapshot,
  useObservationEquityCurve,
} from '../api/hooks'
import { AssetPerformancePanel } from '../components/tracing/AssetPerformancePanel'
import { BacktestEquityPanel } from '../components/tracing/BacktestEquityPanel'
import { MetricsSnapshotPanel } from '../components/tracing/MetricsSnapshotPanel'
import { ObservationEquityPanel } from '../components/tracing/ObservationEquityPanel'

export function TracingPage() {
  const { data: metricsSnapshot } = useMetricsSnapshot()
  const { data: equityCurves } = useEquityCurves()
  const { data: assetPerformance } = useAssetPerformance()
  const { data: observationEquity } = useObservationEquityCurve()

  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1.6fr_1fr]">
      <div className="flex min-w-0 flex-col gap-4">
        <MetricsSnapshotPanel snapshot={metricsSnapshot} />
        <BacktestEquityPanel rows={equityCurves} />
        <ObservationEquityPanel rows={observationEquity} />
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <AssetPerformancePanel rows={assetPerformance} />
      </div>
    </div>
  )
}
