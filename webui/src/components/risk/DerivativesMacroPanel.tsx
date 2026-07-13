import { useMemo, useState } from 'react'
import type { DerivativesState } from '../../types/state'
import { formatNumber, formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { LineChart } from '../tracing/LineChart'

const CALL_COLOR = '#3987e5'
const PUT_COLOR = '#e0575b'

// IV smile/skew: implied vol as a function of strike, for the nearest
// expiry in the underlying's current chain - a single bar's snapshot (this
// project has no completed backtest yet to log a per-strike history
// across bars), not a time series. LineChart's x-axis is ordinal (evenly
// spaced by index, not by actual strike gap) - an accepted simplification
// already used for date-indexed charts elsewhere in this app.
export function DerivativesMacroPanel({ derivatives }: { derivatives: DerivativesState | undefined }) {
  const optionsChains = derivatives?.options_chains ?? {}
  const underlyings = useMemo(() => Object.keys(optionsChains).sort(), [optionsChains])
  const [underlying, setUnderlying] = useState<string | undefined>(undefined)
  const activeUnderlying = underlying && underlyings.includes(underlying) ? underlying : underlyings[0]

  const rows = optionsChains[activeUnderlying ?? ''] ?? []
  const nearestExpiry = useMemo(() => rows.map((r) => r.expiry).sort()[0], [rows])
  const expiryRows = rows.filter((r) => r.expiry === nearestExpiry)
  const strikes = Array.from(new Set(expiryRows.map((r) => r.strike))).sort((a, b) => a - b)

  const ivAt = (right: string, strike: number) => {
    const row = expiryRows.find((r) => r.right === right && r.strike === strike)
    return row ? row.iv : NaN
  }

  const macro = derivatives?.macro

  return (
    <Panel
      title="Options IV Skew / Futures Term Structure"
      action={
        underlyings.length > 0 ? (
          <select
            value={activeUnderlying ?? ''}
            onChange={(e) => setUnderlying(e.target.value)}
            className="rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs text-white/80"
          >
            {underlyings.map((u) => (
              <option key={u} value={u} className="bg-[#141414]">
                {u}
              </option>
            ))}
          </select>
        ) : undefined
      }
    >
      {strikes.length > 0 ? (
        <>
          <div className="mb-1 text-xs text-white/50">
            {activeUnderlying} · nearest expiry {nearestExpiry}
          </div>
          <LineChart
            xLabels={strikes.map((s) => formatNumber(s))}
            series={[
              { id: 'call', label: 'Call IV', color: CALL_COLOR, values: strikes.map((s) => ivAt('call', s)) },
              { id: 'put', label: 'Put IV', color: PUT_COLOR, values: strikes.map((s) => ivAt('put', s)) },
            ]}
            valueFormat={(v) => formatPercent(v)}
            areaOnSingle={false}
          />
        </>
      ) : (
        <div className="p-6 text-center text-sm text-white/60">
          No options chain data yet — needs IB connected and an option asset configured (see `aq assets status`).
        </div>
      )}

      <div className="mt-3 grid grid-cols-3 gap-2.5 text-center">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5">
          <div className="text-[0.7rem] uppercase tracking-wide text-white/50">Term Structure Slope</div>
          <div className="mt-1 text-sm font-semibold text-white">
            {macro ? formatNumber(macro.futures_term_structure_slope ?? 0) : '—'}
          </div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5">
          <div className="text-[0.7rem] uppercase tracking-wide text-white/50">Put/Call Ratio</div>
          <div className="mt-1 text-sm font-semibold text-white">
            {macro ? formatNumber(macro.options_put_call_ratio ?? 0) : '—'}
          </div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5">
          <div className="text-[0.7rem] uppercase tracking-wide text-white/50">IV Skew</div>
          <div className="mt-1 text-sm font-semibold text-white">
            {macro ? formatNumber(macro.options_implied_vol_skew ?? 0) : '—'}
          </div>
        </div>
      </div>
    </Panel>
  )
}
