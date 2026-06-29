import type { RuntimeState } from '../types/state'
import { RiskCore } from '../components/risk/RiskCore'
import { AssetSizingTable } from '../components/risk/AssetSizingTable'

export function RiskPage({ state }: { state: RuntimeState | undefined }) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.12fr_1.88fr]">
      <RiskCore portfolio={state?.portfolio} risk={state?.risk} monitoring={state?.monitoring} />
      <AssetSizingTable signals={state?.signals} />
    </div>
  )
}
