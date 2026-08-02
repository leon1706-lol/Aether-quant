import type { MacroSnapshot } from '../../types/state'
import { formatNumber, formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'

// V4.12.2 (development/Problems.md #71) - main.py's bond (yield curve,
// credit spread) and alt-data (VIX-derived) payloads were already computed
// every bar to feed the model's base_features, but never reached state.json
// until this phase's macro-plumbing fix. formatNumber/formatPercent coerce
// undefined to 0 (misleading for a genuinely-missing series), so this panel
// checks null/undefined itself and renders '-' instead of a fake zero.
function StatTile({ label, value, percent = false }: { label: string; value: number | null | undefined; percent?: boolean }) {
  const hasValue = typeof value === 'number' && Number.isFinite(value)
  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5 text-center">
      <div className="text-[0.7rem] uppercase tracking-wide text-white/50">{label}</div>
      <div className="mt-1 text-sm font-semibold text-white">
        {hasValue ? (percent ? formatPercent(value) : formatNumber(value)) : '—'}
      </div>
    </div>
  )
}

export function MacroSnapshotPanel({ macro }: { macro: MacroSnapshot | undefined }) {
  return (
    <Panel title="Macro & Alt-Data Snapshot">
      {!macro ? (
        <div className="p-6 text-center text-sm text-white/60">
          No macro snapshot yet — needs at least one bar processed (see `aq backtest` or the paper/live loop).
        </div>
      ) : (
        <>
          <div className="mb-1 text-xs text-white/50">Bond (real Treasury/credit-spread data)</div>
          <div className="mb-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <StatTile label="Yield Curve Level" value={macro.yield_curve_level} />
            <StatTile label="Yield Curve Slope" value={macro.yield_curve_slope} />
            <StatTile label="Yield Curve Curvature" value={macro.yield_curve_curvature} />
            <StatTile label="Credit Spread" value={macro.credit_spread_level} />
          </div>
          <div className="mb-1 text-xs text-white/50">Alt-data (options-implied vol / financial conditions)</div>
          <div className="mb-3 grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            <StatTile label="Implied Vol Level" value={macro.implied_volatility_level} />
            <StatTile label="Implied Vol Term Structure" value={macro.implied_vol_term_structure} />
            <StatTile label="Financial Conditions Δ" value={macro.financial_conditions_change} />
          </div>
          <div className="mb-1 text-xs text-white/50">
            Sensitivity drivers (V5.1 Phase 2 - raw levels, per-asset betas on the Risk page)
          </div>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            <StatTile label="Real Rate (10Y TIPS)" value={macro.sensitivity_driver_levels?.real_rate} />
            <StatTile label="Dollar Index" value={macro.sensitivity_driver_levels?.dollar} />
            <StatTile label="VIX" value={macro.sensitivity_driver_levels?.vix} />
          </div>
        </>
      )}
    </Panel>
  )
}
