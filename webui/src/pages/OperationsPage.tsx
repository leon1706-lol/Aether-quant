import type { RuntimeState } from '../types/state'
import { useAssetsStatus, useAuditLog } from '../api/hooks'
import { MonitoringFeeds } from '../components/monitoring/MonitoringFeeds'
import { PerformanceTriggersPanel } from '../components/monitoring/PerformanceTriggersPanel'
import { RetrainingStatusPanel } from '../components/monitoring/RetrainingStatusPanel'
import { PaperReadinessPanel } from '../components/monitoring/PaperReadinessPanel'
import { AssetsStatusPanel } from '../components/monitoring/AssetsStatusPanel'
import { AuditLogPanel } from '../components/monitoring/AuditLogPanel'
import { RawStateViewer } from '../components/monitoring/RawStateViewer'

export function OperationsPage({ state }: { state: RuntimeState | undefined }) {
  const { data: assetsStatus } = useAssetsStatus()
  const { data: auditLog } = useAuditLog()

  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
      <div className="flex min-w-0 flex-col gap-4">
        <PerformanceTriggersPanel report={state?.performance_triggers} />
        <RetrainingStatusPanel status={state?.retraining_status} />
        <PaperReadinessPanel status={state?.paper_readiness} />
        <AssetsStatusPanel status={assetsStatus} />
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <AuditLogPanel status={auditLog} />
        <MonitoringFeeds monitoring={state?.monitoring} />
        <RawStateViewer state={state} />
      </div>
    </div>
  )
}
