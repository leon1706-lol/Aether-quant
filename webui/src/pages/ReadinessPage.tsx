import { useAccounts, useReadiness } from '../api/hooks'
import type { ReadinessMetric } from '../types/access'
import { Panel } from '../components/layout/Panel'

// V6.6.5 (#352): the paper-to-live scorecard `aq live-readiness` writes, and every account's secrets and state.

const STATUS_STYLE: Record<string, string> = {
  pass: 'text-emerald-300',
  fail: 'text-rose-300',
  unknown: 'text-amber-300',
}

function show(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') return Number.isInteger(value) ? value.toString() : value.toPrecision(3)
  return String(value)
}

function MetricRow({ metric }: { metric: ReadinessMetric }) {
  return (
    <tr className="border-t border-white/5">
      <td className="py-2 pr-3 text-xs uppercase tracking-wider text-white/50">{metric.group}</td>
      <td className="py-2 pr-3 text-sm text-white/80">{metric.label}</td>
      <td className="py-2 pr-3 text-sm text-white/70 break-words">{show(metric.value)}</td>
      <td className="py-2 pr-3 text-xs text-white/50">{metric.threshold}</td>
      <td className={`py-2 text-sm font-medium ${STATUS_STYLE[metric.status] ?? ''}`}>{metric.status}</td>
    </tr>
  )
}

export function ReadinessPage() {
  const { data: scorecard } = useReadiness()
  const { data: accounts } = useAccounts()

  return (
    <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[1.6fr_1fr]">
      <Panel title="Paper to Live">
        {scorecard ? (
          <>
            <div
              className={`mb-3 rounded-2xl border px-4 py-3 ${
                scorecard.ready ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300' : 'border-amber-400/40 bg-amber-400/10 text-amber-300'
              }`}
            >
              <strong>{scorecard.ready ? 'READY FOR LIVE CAPITAL' : 'NOT READY FOR LIVE CAPITAL'}</strong>
              <div className="mt-1 text-xs opacity-80">
                account {scorecard.account}, {scorecard.generated_at}: {scorecard.counts.pass} pass, {scorecard.counts.fail} fail,{' '}
                {scorecard.counts.unknown} unknown. Unknown counts as fail.
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left">
                <caption className="sr-only">Readiness checks</caption>
                <thead>
                  <tr className="text-xs uppercase tracking-widest text-white/40">
                    <th scope="col" className="pb-2">Group</th>
                    <th scope="col" className="pb-2">Check</th>
                    <th scope="col" className="pb-2">Measured</th>
                    <th scope="col" className="pb-2">Needs</th>
                    <th scope="col" className="pb-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {scorecard.metrics.map((metric) => (
                    <MetricRow key={metric.key} metric={metric} />
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-white/60">
            <small>Not scored yet: run `aq live-readiness` (it writes visualization/grafana/live_readiness.json).</small>
          </div>
        )}
      </Panel>
      <Panel title="Accounts">
        {accounts?.accounts?.length ? (
          <ul className="grid gap-2.5">
            {accounts.accounts.map((account) => (
              <li key={account.id} className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <strong className="text-sm text-white/90">{account.id}</strong>
                  <span className="text-xs text-white/50">
                    {account.broker} · {account.environment} · {account.mode}
                  </span>
                </div>
                <div className="mt-1 text-xs text-white/60 break-words">
                  secrets {account.secrets}
                  {account.secrets_missing.length ? ` (missing ${account.secrets_missing.join(', ')})` : ''} · state {account.state}
                  {account.reconciliation_breach ? ' · reconciliation breach' : ''}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3 text-white/60">
            <small>No account registry: the default account only (accounts.example.json shows the format).</small>
          </div>
        )}
      </Panel>
    </div>
  )
}
