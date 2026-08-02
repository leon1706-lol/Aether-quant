import type { Signal } from '../../types/state'
import { formatNumber } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V5.1 Phase 1 (development/Problems.md, item 3 - the actual root cause of
// the fee drag: $2,769 in fees on $3,159 gross profit in the last
// representative backtest) - execution/cost_model.py::build_net_edge_decision()'s
// per-symbol verdict, surfaced so "is the cost gate actually calibrated and
// doing anything" is answerable without reading Postgres/audit logs.
// passes=true/reason="net_edge_gate_disabled" for every row until
// phase_v2.costs.enabled is on AND edge_bps_per_rank_unit is calibrated
// (`aq evaluate --calibrate-edge`) - this project's default.
function sortedRows(signals: Record<string, Signal> | undefined) {
  return Object.entries(signals ?? {})
    .map(([symbol, payload]) => ({ symbol, ...payload }))
    .filter((row) => row.net_edge != null)
    .sort((a, b) => Math.abs(b.net_edge!.net_edge_bps) - Math.abs(a.net_edge!.net_edge_bps))
}

export function NetEdgePanel({ signals }: { signals: Record<string, Signal> | undefined }) {
  const rows = sortedRows(signals)
  const calibrated = rows.some((row) => row.net_edge!.reason !== 'net_edge_gate_disabled')

  return (
    <Panel
      title="Net Edge vs. Cost"
      action={<Badge tone={calibrated ? 'stable' : 'watchlist'}>{calibrated ? 'calibrated' : 'uncalibrated'}</Badge>}
    >
      {rows.length === 0 ? (
        <div className="p-6 text-center text-sm text-white/60">
          No net-edge decisions yet — needs at least one bar with a rank prediction.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="text-left text-[0.7rem] uppercase tracking-wide text-white/60">
                <th className="border-b border-white/10 px-2.5 py-2">Asset</th>
                <th className="border-b border-white/10 px-2.5 py-2">Edge (bps)</th>
                <th className="border-b border-white/10 px-2.5 py-2">Cost (bps)</th>
                <th className="border-b border-white/10 px-2.5 py-2">Net (bps)</th>
                <th className="border-b border-white/10 px-2.5 py-2">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.symbol}>
                  <td className="border-b border-white/5 px-2.5 py-2 text-[0.85rem] font-semibold">
                    {row.ticker || row.symbol}
                  </td>
                  <td className="border-b border-white/5 px-2.5 py-2 text-[0.85rem]">
                    {formatNumber(row.net_edge!.expected_edge_bps, 1)}
                  </td>
                  <td className="border-b border-white/5 px-2.5 py-2 text-[0.85rem]">
                    {formatNumber(row.net_edge!.expected_cost_bps, 1)}
                  </td>
                  <td className="border-b border-white/5 px-2.5 py-2 text-[0.85rem] font-semibold">
                    {formatNumber(row.net_edge!.net_edge_bps, 1)}
                  </td>
                  <td className="border-b border-white/5 px-2.5 py-2">
                    <Badge tone={row.net_edge!.passes ? 'trade' : 'reduce_risk'}>
                      {row.net_edge!.reason.replaceAll('_', ' ')}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}
