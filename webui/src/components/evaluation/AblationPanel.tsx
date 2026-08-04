import type { AblationMeasuredEntry, AblationVariantEntry } from '../../types/evaluation'
import { isAblationSentinel, isNotEvaluated, type EvaluationState } from '../../types/evaluation'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V5.1 Phase 5 (item 9) - Delta net Sharpe vs the static (equal-weight,
// buy-and-hold) baseline, as a diverging bar. Deliberately gives the
// not-offline-measurable variants (gating, topology sizing, the net-edge
// gate, ...) their own visibly muted row rather than omitting them -
// evaluation/ablation.py's own "honesty contract enforced in code, not
// just docs" guardrail extends to the webui: their ABSENCE of a number
// must be visible, not silently dropped from the list.
function DivergingBar({ delta, maxAbs }: { delta: number; maxAbs: number }) {
  const widthPct = maxAbs > 0 ? Math.min(100, (Math.abs(delta) / maxAbs) * 100) : 0
  const positive = delta >= 0
  return (
    <div className="relative flex h-4 w-full items-center">
      <div className="absolute left-1/2 h-full w-px bg-white/15" />
      <div
        className={`absolute h-3 rounded-sm ${positive ? 'bg-emerald-400/70' : 'bg-rose-400/70'}`}
        style={
          positive
            ? { left: '50%', width: `${widthPct / 2}%` }
            : { right: '50%', width: `${widthPct / 2}%` }
        }
      />
    </div>
  )
}

function VariantRow({ name, entry, maxAbsDelta }: { name: string; entry: AblationVariantEntry; maxAbsDelta: number }) {
  if (isAblationSentinel(entry)) {
    return (
      <div className="rounded-2xl border border-white/5 bg-white/[0.02] px-4 py-2.5 opacity-50">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm text-white/60">{name}</span>
          <Badge tone="observe">{entry.status.replace(/_/g, ' ')}</Badge>
        </div>
        {entry.reason && <div className="mt-1 text-xs text-white/40">{entry.reason}</div>}
      </div>
    )
  }

  const measured = entry as AblationMeasuredEntry
  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-white">{name}</span>
        <span
          className={`text-sm ${measured.delta_vs_static_baseline >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}
        >
          {measured.delta_vs_static_baseline >= 0 ? '+' : ''}
          {measured.delta_vs_static_baseline.toFixed(3)}
        </span>
      </div>
      <div className="mt-1.5">
        <DivergingBar delta={measured.delta_vs_static_baseline} maxAbs={maxAbsDelta} />
      </div>
      <div className="mt-1 text-xs text-white/50">
        net_sharpe={measured.net_sharpe.toFixed(3)}, turnover={measured.annualized_turnover.toFixed(2)}x
      </div>
    </div>
  )
}

export function AblationPanel({ evaluation }: { evaluation: EvaluationState | undefined }) {
  const ablation = evaluation?.ablation

  if (!ablation || isNotEvaluated(ablation)) {
    return (
      <Panel title="Ablation">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-6 text-center text-sm text-white/50">
          Not evaluated yet — run{' '}
          <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-orange-300">
            aq evaluate --ablation
          </code>
        </div>
      </Panel>
    )
  }

  const entries = Object.entries(ablation)
  const measuredDeltas = entries
    .filter(([, entry]) => !isAblationSentinel(entry))
    .map(([, entry]) => Math.abs((entry as AblationMeasuredEntry).delta_vs_static_baseline))
  const maxAbsDelta = measuredDeltas.length > 0 ? Math.max(...measuredDeltas, 1e-9) : 1e-9

  return (
    <Panel title="Ablation" action={<Badge tone="observe">Δ net Sharpe vs static baseline</Badge>}>
      {entries.length === 0 ? (
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-6 text-center text-sm text-white/50">
          No variants recorded in the last ablation run.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {entries.map(([name, entry]) => (
            <VariantRow key={name} name={name} entry={entry} maxAbsDelta={maxAbsDelta} />
          ))}
        </div>
      )}
    </Panel>
  )
}
