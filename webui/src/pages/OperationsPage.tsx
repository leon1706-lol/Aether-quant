import type { RuntimeState } from '../types/state'
import { useAssetsStatus, useAuditLog, useGenerations, useHealth, useWhoAmI } from '../api/hooks'
import { TradeLockPanel } from '../components/monitoring/TradeLockPanel'
import { GenerationsPanel } from '../components/monitoring/GenerationsPanel'
import { MonitoringFeeds } from '../components/monitoring/MonitoringFeeds'
import { PerformanceTriggersPanel } from '../components/monitoring/PerformanceTriggersPanel'
import { RetrainingStatusPanel } from '../components/monitoring/RetrainingStatusPanel'
import { PaperReadinessPanel } from '../components/monitoring/PaperReadinessPanel'
import { AssetsStatusPanel } from '../components/monitoring/AssetsStatusPanel'
import { AuditLogPanel } from '../components/monitoring/AuditLogPanel'
import { RawStateViewer } from '../components/monitoring/RawStateViewer'
import { KillSwitchPanel } from '../components/monitoring/KillSwitchPanel'
import { ReconciliationPanel } from '../components/monitoring/ReconciliationPanel'

export function OperationsPage({ state, account = 'default' }: { state: RuntimeState | undefined; account?: string }) {
  const { data: assetsStatus } = useAssetsStatus()
  const { data: auditLog } = useAuditLog()
  const { data: generations } = useGenerations()
  const { data: health } = useHealth()
  const { data: who } = useWhoAmI(health?.auth === 'required')

  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
      <div className="flex min-w-0 flex-col gap-4">
        {/* V5.1 Phase 6 (production safety) - the two highest-stakes
            operational panels lead the page, ahead of the pre-existing
            monitoring feeds below. */}
        <KillSwitchPanel decision={state?.kill_switch} />
        <ReconciliationPanel report={state?.reconciliation} />
        <TradeLockPanel account={account} locked={state?.risk?.trade_lock_active} who={who} demo={Boolean(health?.demo)} />
        <GenerationsPanel status={generations} />
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
