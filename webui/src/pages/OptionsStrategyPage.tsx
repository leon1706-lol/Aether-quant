import type { RuntimeState } from '../types/state'
import { useStrategyCatalog } from '../api/hooks'
import { CorporateActionsPanel } from '../components/optionsstrategy/CorporateActionsPanel'
import { DividendScheduleSummaryPanel } from '../components/optionsstrategy/DividendScheduleSummaryPanel'
import { ForexPairDetailPanel } from '../components/optionsstrategy/ForexPairDetailPanel'
import { HeldMultiLegPositionsPanel } from '../components/optionsstrategy/HeldMultiLegPositionsPanel'
import { StrategyCatalogBrowser } from '../components/optionsstrategy/StrategyCatalogBrowser'
import { StrategySelectorScoresPanel } from '../components/optionsstrategy/StrategySelectorScoresPanel'

export function OptionsStrategyPage({ state }: { state: RuntimeState | undefined }) {
  const { data: catalog } = useStrategyCatalog()

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
      <div className="grid gap-4">
        <HeldMultiLegPositionsPanel signals={state?.signals} />
        <DividendScheduleSummaryPanel signals={state?.signals} />
        <StrategySelectorScoresPanel signals={state?.signals} />
        <CorporateActionsPanel signals={state?.signals} />
      </div>
      <div className="grid gap-4">
        <StrategyCatalogBrowser catalog={catalog} />
        <ForexPairDetailPanel signals={state?.signals} />
      </div>
    </div>
  )
}
