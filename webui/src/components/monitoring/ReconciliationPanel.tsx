import type { ReconciliationReport } from '../../types/state'
import { formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V5.1 Phase 6 (production safety) - execution/reconciliation.py::
// reconcile_positions()'s report, evaluated once per bar by main.py::
// _evaluate_reconciliation() and mirrored at RuntimeState.reconciliation.
// {status: "not_applicable"} is this project's steady-state default until
// the portfolio-book-with-neutrality path and phase_v2.reconciliation.enabled
// are both on - see that method's own docstring for why it's scoped that way.
export function ReconciliationPanel({ report }: { report: ReconciliationReport | undefined }) {
  const isMeasured = report?.status === undefined

  return (
    <Panel
      title="Reconciliation"
      action={
        isMeasured ? (
          <Badge tone={report?.breach ? 'reduce_risk' : 'stable'}>{report?.breach ? 'BREACH' : 'ok'}</Badge>
        ) : (
          <Badge tone="none">not applicable</Badge>
        )
      }
    >
      {!report ? (
        <div className="p-6 text-center text-sm text-white/60">No data yet.</div>
      ) : !isMeasured ? (
        <div className="p-6 text-center text-sm text-white/60">
          {report.reason ?? 'Not applicable this bar.'}
        </div>
      ) : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5 text-center">
              <div className="text-[0.7rem] uppercase tracking-wide text-white/50">Matched</div>
              <div className="mt-1 text-sm font-semibold text-white">{report.matched?.length ?? 0}</div>
            </div>
            <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5 text-center">
              <div className="text-[0.7rem] uppercase tracking-wide text-white/50">Drifted</div>
              <div className="mt-1 text-sm font-semibold text-white">{report.drifted?.length ?? 0}</div>
            </div>
            <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5 text-center">
              <div className="text-[0.7rem] uppercase tracking-wide text-white/50">Orphan (Broker)</div>
              <div className="mt-1 text-sm font-semibold text-white">{report.orphan_broker?.length ?? 0}</div>
            </div>
            <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5 text-center">
              <div className="text-[0.7rem] uppercase tracking-wide text-white/50">Missing (Broker)</div>
              <div className="mt-1 text-sm font-semibold text-white">{report.missing_broker?.length ?? 0}</div>
            </div>
          </div>
          <div className="mb-2 text-xs text-white/50">
            Max abs weight drift: <span className="text-white/80">{formatPercent(report.max_abs_weight_drift)}</span>
          </div>
          {[...(report.drifted ?? []), ...(report.orphan_broker ?? []), ...(report.missing_broker ?? [])].length > 0 && (
            <div className="grid gap-1">
              {[...(report.drifted ?? []), ...(report.orphan_broker ?? []), ...(report.missing_broker ?? [])].map((row) => (
                <div
                  key={row.symbol}
                  className="flex items-center justify-between rounded-xl border border-white/5 bg-white/[0.03] px-3 py-1.5 text-xs"
                >
                  <span className="text-white/80">{row.symbol}</span>
                  <span className="text-white/50">
                    expected {formatPercent(row.expected_weight)} · actual {formatPercent(row.actual_weight)} · Δ{' '}
                    {formatPercent(row.delta_weight)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Panel>
  )
}
