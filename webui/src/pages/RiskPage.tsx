import type { RuntimeState } from '../types/state'
import { RiskCore } from '../components/risk/RiskCore'
import { AssetSizingTable } from '../components/risk/AssetSizingTable'
import { LiquidityTable } from '../components/risk/LiquidityTable'
import { NetEdgePanel } from '../components/risk/NetEdgePanel'
import { DerivativesMacroPanel } from '../components/risk/DerivativesMacroPanel'
import { MacroSnapshotPanel } from '../components/risk/MacroSnapshotPanel'
import { BookNeutralityPanel } from '../components/portfolio/BookNeutralityPanel'

export function RiskPage({ state }: { state: RuntimeState | undefined }) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.12fr_1.88fr]">
      <RiskCore portfolio={state?.portfolio} risk={state?.risk} monitoring={state?.monitoring} />
      <div className="grid gap-4">
        <AssetSizingTable signals={state?.signals} />
        <LiquidityTable signals={state?.signals} />
        <NetEdgePanel signals={state?.signals} />
        <BookNeutralityPanel diagnostics={state?.book_neutrality} />
        <DerivativesMacroPanel derivatives={state?.derivatives} />
        <MacroSnapshotPanel macro={state?.macro} />
      </div>
    </div>
  )
}
