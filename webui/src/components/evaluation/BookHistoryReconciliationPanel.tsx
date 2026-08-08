import type { BookHistoryReconciliationReport } from '../../types/evaluation'
import { isNotEvaluated, type EvaluationState } from '../../types/evaluation'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

function formatPercent(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`
}

function formatNumber(value: number | null, digits = 4): string {
  return value === null ? '—' : value.toFixed(digits)
}

const INDEPENDENT_CAVEAT =
  'Reconciled independently per date (no hysteresis replayed) - a mismatch can mean either a real ' +
  "divergence OR the live book correctly holding an incumbent that day's natural ranking alone " +
  "wouldn't pick. Re-run with --replay-hysteresis for the hysteresis-aware alternative."

const REPLAY_CAVEAT =
  "Hysteresis replayed (--replay-hysteresis) - offline's own held allocations are carried forward " +
  "date-by-date, the same way the live book does. The first reconciled date still starts from a cold " +
  '(empty) held-allocations state, so early dates may show a colder-start mismatch than mid-series ones.'

// V5.2.2/V5.2.3 (development/Problems.md #91) - the book-history
// reconciliation dashboard: how far did a real Lean backtest's actual
// selections diverge from a fresh offline re-derivation of the same raw
// scores, and (once a backtest has been run with
// phase_v2.diagnostics.book_history.include_full_universe=true) which
// security types never even got a usable feature/score in the live book
// at all versus which simply scored unremarkably. Pure display layer over
// aq evaluate --reconcile-book-history's persisted report.
export function BookHistoryReconciliationPanel({ evaluation }: { evaluation: EvaluationState | undefined }) {
  const report = evaluation?.book_history_reconciliation

  if (!report || isNotEvaluated(report)) {
    return (
      <Panel title="Book History Reconciliation">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-6 text-center text-sm text-white/50">
          Not evaluated yet — run{' '}
          <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-orange-300">
            aq evaluate --reconcile-book-history
          </code>
        </div>
      </Panel>
    )
  }

  const reconciliation = report as BookHistoryReconciliationReport
  const { summary, universe_summary: universeSummary, mode } = reconciliation

  return (
    <Panel
      title="Book History Reconciliation"
      action={<Badge tone="observe">{mode === 'replay_hysteresis' ? 'hysteresis replay' : 'independent'}</Badge>}
    >
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5">
          <div className="text-[0.65rem] uppercase tracking-widest text-white/40">Mean Overlap</div>
          <div className="mt-1 text-lg text-white">{formatPercent(summary.mean_overlap_fraction)}</div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5">
          <div className="text-[0.65rem] uppercase tracking-widest text-white/40">Exact Match Dates</div>
          <div className="mt-1 text-lg text-white">
            {summary.num_dates_exact_match}/{summary.num_dates}
          </div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5">
          <div className="text-[0.65rem] uppercase tracking-widest text-white/40">Only-One-Side Symbols</div>
          <div className="mt-1 text-lg text-white">
            {summary.num_symbols_only_logged_total}/{summary.num_symbols_only_offline_total}
          </div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5">
          <div className="text-[0.65rem] uppercase tracking-widest text-white/40">Mean Raw Score Δ</div>
          <div className="mt-1 text-lg text-white">{formatNumber(summary.mean_raw_score_delta_abs)}</div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5">
          <div className="text-[0.65rem] uppercase tracking-widest text-white/40">Mean Weight Δ</div>
          <div className="mt-1 text-lg text-white">{formatNumber(summary.mean_weight_delta_abs)}</div>
          <div className="mt-0.5 text-[0.65rem] text-white/40">
            {summary.num_dates_with_weight_logged}/{summary.num_dates} dates had a logged weight
          </div>
        </div>
      </div>

      <p className="mt-3 text-xs text-white/50">{mode === 'replay_hysteresis' ? REPLAY_CAVEAT : INDEPENDENT_CAVEAT}</p>

      <div className="mt-3">
        <h3 className="mb-1.5 text-[0.7rem] uppercase tracking-widest text-white/40">
          Universe Snapshot (by security type)
        </h3>
        {universeSummary.num_dates_with_universe_data === 0 ? (
          <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-4 text-center text-xs text-white/50">
            Not available for this log — re-run with{' '}
            <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-orange-300">
              phase_v2.diagnostics.book_history.include_full_universe=true
            </code>{' '}
            to see per-security-type score/readiness breakdowns for symbols that were never selected.
          </div>
        ) : (
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="text-left text-white/40">
                <th className="pr-3 font-normal">security_type</th>
                <th className="pr-3 font-normal">mean raw score</th>
                <th className="pr-3 font-normal">feature ready</th>
                <th className="pr-3 font-normal">trading eligible</th>
                <th className="pr-3 font-normal">n</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(universeSummary.by_security_type)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([securityType, stats]) => (
                  <tr key={securityType} className="text-white/70">
                    <td className="pr-3">{securityType}</td>
                    <td className="pr-3">{formatNumber(stats.mean_raw_rank_score)}</td>
                    <td className="pr-3">{formatPercent(stats.feature_ready_rate)}</td>
                    <td className="pr-3">{formatPercent(stats.trading_eligible_rate)}</td>
                    <td className="pr-3">{stats.num_symbol_dates}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  )
}
