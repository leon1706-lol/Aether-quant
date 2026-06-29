import type { Monitoring, Portfolio, Risk } from '../../types/state'
import { formatCurrency, formatNumber, formatPercent } from '../../lib/format'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'
import { RiskBar } from './RiskBar'

function Metric({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="min-h-[96px] rounded-2xl border border-white/10 bg-white/[0.04] p-3.5">
      <span className="mb-2.5 block text-[0.74rem] uppercase tracking-widest text-slate-400">{label}</span>
      <strong className="block text-[1.72rem] leading-tight">{value}</strong>
      <small className="mt-2 block text-slate-400">{sub}</small>
    </div>
  )
}

export function RiskCore({
  portfolio,
  risk,
  monitoring,
}: {
  portfolio: Portfolio | undefined
  risk: Risk | undefined
  monitoring: Monitoring | undefined
}) {
  return (
    <Panel
      title="Risk Core"
      action={
        <Badge tone={risk?.trade_lock_active ? 'sell' : 'buy'}>
          {risk?.trade_lock_active ? risk?.trade_lock_reason || 'risk lock' : 'risk open'}
        </Badge>
      }
    >
      <div className="grid grid-cols-2 gap-2.5">
        <Metric
          label="Portfolio"
          value={formatCurrency(portfolio?.total_portfolio_value)}
          sub={`cash ${formatCurrency(portfolio?.cash)}`}
        />
        <Metric
          label="Avg Annual Vol"
          value={formatPercent(monitoring?.average_annualized_volatility)}
          sub={`target daily ${formatPercent(risk?.target_daily_volatility)}`}
        />
        <Metric
          label="Max Leverage Factor"
          value={`${formatNumber(monitoring?.max_leverage_factor)}x`}
          sub={`cap ${formatNumber(risk?.max_leverage)}x`}
        />
        <Metric
          label="Active Signals"
          value={String(monitoring?.active_signals ?? 0)}
          sub={`positions ${portfolio?.invested_positions ?? 0}`}
        />
      </div>

      <div className="mt-3 grid gap-2.5">
        <RiskBar label="Daily drawdown" value={risk?.daily_drawdown} cap={risk?.max_daily_drawdown_pct} />
        <RiskBar label="Total drawdown" value={risk?.total_drawdown} cap={risk?.max_total_drawdown_pct} />
        <RiskBar label="Exposure caps" value={risk?.max_position_weight} cap={0.5} />
      </div>
    </Panel>
  )
}
