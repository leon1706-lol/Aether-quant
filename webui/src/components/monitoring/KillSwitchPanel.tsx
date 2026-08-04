import type { KillSwitchDecision } from '../../types/state'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V5.1 Phase 6 (production safety) - risk/kill_switch.py::evaluate_kill_switch()'s
// decision, evaluated once per bar by main.py::_refresh_risk_state() and
// mirrored at RuntimeState.kill_switch. severity="none" (config disabled,
// or every threshold within bounds) is this project's steady-state
// default - see that module's own fail-open docstring.
function severityTone(severity: string | undefined): string {
  if (severity === 'critical') return 'reduce_risk'
  if (severity === 'warning') return 'watchlist'
  return 'stable'
}

function formatObservedValue(value: number | boolean | null | undefined): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  return value.toFixed(4)
}

const TRIGGER_LABELS: Record<string, string> = {
  rolling_sharpe_below_floor: 'Rolling Sharpe',
  drawdown_velocity_above_cap: 'Drawdown Velocity',
  live_rank_ic_below_floor: 'Live Rank IC',
  consecutive_losses_above_cap: 'Consecutive Losses',
  slippage_divergence_above_cap: 'Slippage Divergence',
  model_age_above_cap: 'Model Age',
  reconciliation_breach: 'Reconciliation Breach',
}

export function KillSwitchPanel({ decision }: { decision: KillSwitchDecision | undefined }) {
  const triggers = decision?.triggers ?? []
  const observed = decision?.observed ?? {}

  return (
    <Panel
      title="Kill Switch"
      action={<Badge tone={severityTone(decision?.severity)}>{decision?.tripped ? 'TRIPPED' : decision?.severity ?? 'none'}</Badge>}
    >
      {!decision ? (
        <div className="p-6 text-center text-sm text-white/60">No data yet.</div>
      ) : (
        <>
          {decision.tripped && (
            <div className="mb-3 rounded-2xl border border-rose-400/40 bg-rose-400/10 px-4 py-3 text-rose-300">
              <strong>TRADE LOCK ACTIVE</strong>
              <div className="text-xs opacity-80 break-words">{decision.reason}</div>
              <div className="mt-1 text-xs opacity-70">Recommended action: {decision.recommended_action}</div>
            </div>
          )}
          {triggers.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-1.5">
              {triggers.map((trigger) => (
                <span key={trigger} className="rounded-full bg-rose-400/15 px-2.5 py-1 text-[0.74rem] text-rose-300">
                  {TRIGGER_LABELS[trigger] ?? trigger}
                </span>
              ))}
            </div>
          )}
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            {Object.entries(observed)
              .filter(([key]) => key !== 'rolling_sharpe_num_bars')
              .map(([key, value]) => (
                <div key={key} className="rounded-2xl border border-white/5 bg-white/[0.03] px-3 py-2.5 text-center">
                  <div className="text-[0.7rem] uppercase tracking-wide text-white/50">
                    {TRIGGER_LABELS[`${key}_above_cap`] ?? TRIGGER_LABELS[`${key}_below_floor`] ?? key}
                  </div>
                  <div className="mt-1 text-sm font-semibold text-white">{formatObservedValue(value)}</div>
                </div>
              ))}
          </div>
        </>
      )}
    </Panel>
  )
}
