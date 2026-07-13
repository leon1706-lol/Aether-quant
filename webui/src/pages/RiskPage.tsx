import type { RuntimeState } from '../types/state'
import { RiskCore } from '../components/risk/RiskCore'
import { AssetSizingTable } from '../components/risk/AssetSizingTable'
import { LiquidityTable } from '../components/risk/LiquidityTable'
import { DerivativesMacroPanel } from '../components/risk/DerivativesMacroPanel'

export function RiskPage({ state }: { state: RuntimeState | undefined }) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.12fr_1.88fr]">
      <RiskCore portfolio={state?.portfolio} risk={state?.risk} monitoring={state?.monitoring} />
      <div className="grid gap-4">
        <AssetSizingTable signals={state?.signals} />
        <LiquidityTable signals={state?.signals} />
        <DerivativesMacroPanel derivatives={state?.derivatives} />
      </div>
    </div>
  )
}
