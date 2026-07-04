import type { RuntimeState } from '../types/state'
import { Scorecards } from '../components/scorecards/Scorecards'
import { Scene3D } from '../components/scene3d/Scene3D'
import { AssetHeatmap } from '../components/heatmap/AssetHeatmap'
import { SignalBoard } from '../components/signals/SignalBoard'
import { PositionsList } from '../components/signals/PositionsList'
import { StrategyRiskCards } from '../components/risk/StrategyRiskCards'
import { MonitoringFeeds } from '../components/monitoring/MonitoringFeeds'
import { ObservationPanel } from '../components/monitoring/ObservationPanel'
import { PerformanceTriggersPanel } from '../components/monitoring/PerformanceTriggersPanel'
import { RetrainingStatusPanel } from '../components/monitoring/RetrainingStatusPanel'
import { RawStateViewer } from '../components/monitoring/RawStateViewer'

export function Overview({ state }: { state: RuntimeState | undefined }) {
  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1.4fr_1fr]">
      <div className="flex min-w-0 flex-col gap-4">
        <Scorecards cards={state?.dashboard?.scorecards} />
        <Scene3D scene={state?.scene} />
        <AssetHeatmap items={state?.dashboard?.asset_heatmap} />
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <PerformanceTriggersPanel report={state?.performance_triggers} />
        <RetrainingStatusPanel status={state?.retraining_status} />
        <ObservationPanel observation={state?.observation} />
        <SignalBoard signals={state?.signals} />
        <PositionsList positions={state?.positions} />
        <StrategyRiskCards strategy={state?.dashboard?.strategy_snapshot} risk={state?.risk} />
        <MonitoringFeeds monitoring={state?.monitoring} />
        <RawStateViewer state={state} />
      </div>
    </div>
  )
}
