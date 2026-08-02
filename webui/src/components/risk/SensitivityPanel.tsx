import type { Signal } from '../../types/state'
import { formatNumber } from '../../lib/format'
import { Panel } from '../layout/Panel'

// V5.1 Phase 2 (item 8 / F2, development/Problems.md) - the panel that
// makes per-asset macro SENSITIVITY legible. Every macro_*/bond_*/alt_*
// feature elsewhere in the dashboard (MacroSnapshotPanel) is a single
// broadcast value identical for every symbol on a date - invisible to a
// cross-sectional ranker by construction. This table is the opposite: one
// row per symbol, each with its OWN rolling beta against 4 macro drivers
// (features/cross_asset_sensitivity.py, main.py::_cross_asset_sensitivity_for_symbol()) -
// the quantity that actually varies across the book and that the model
// consumes as an input.
function sortedRows(signals: Record<string, Signal> | undefined) {
  return Object.entries(signals ?? {})
    .map(([symbol, payload]) => ({ symbol, ...payload }))
    .filter((row) => row.cross_asset_sensitivity != null)
    .sort(
      (a, b) =>
        Math.abs(b.cross_asset_sensitivity!.sens_vix_beta ?? 0) - Math.abs(a.cross_asset_sensitivity!.sens_vix_beta ?? 0),
    )
}

export function SensitivityPanel({ signals }: { signals: Record<string, Signal> | undefined }) {
  const rows = sortedRows(signals)

  return (
    <Panel title="Cross-Asset Macro Sensitivity">
      {rows.length === 0 ? (
        <div className="p-6 text-center text-sm text-white/60">
          No per-symbol sensitivity betas yet — needs enough bar history for a trailing-window regression (see
          phase1.features.cross_asset_sensitivity.min_observations).
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="text-left text-[0.7rem] uppercase tracking-wide text-white/60">
                <th className="border-b border-white/10 px-2.5 py-2">Asset</th>
                <th className="border-b border-white/10 px-2.5 py-2">VIX β</th>
                <th className="border-b border-white/10 px-2.5 py-2">Real Rate β</th>
                <th className="border-b border-white/10 px-2.5 py-2">Credit β</th>
                <th className="border-b border-white/10 px-2.5 py-2">Dollar β</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const sensitivity = row.cross_asset_sensitivity!
                return (
                  <tr key={row.symbol}>
                    <td className="border-b border-white/5 px-2.5 py-2 text-[0.85rem] font-semibold">
                      {row.ticker || row.symbol}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2 text-[0.85rem]">
                      {formatNumber(sensitivity.sens_vix_beta, 3)}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2 text-[0.85rem]">
                      {formatNumber(sensitivity.sens_real_rate_beta, 3)}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2 text-[0.85rem]">
                      {formatNumber(sensitivity.sens_credit_beta, 3)}
                    </td>
                    <td className="border-b border-white/5 px-2.5 py-2 text-[0.85rem]">
                      {formatNumber(sensitivity.sens_dollar_beta, 3)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}
