import type { AssetsStatus } from '../../types/state'
import { Panel } from '../layout/Panel'

const IB_STATUS_LABEL: Record<string, string> = {
  disabled: 'DISABLED',
  enabled_but_lean_credentials_missing: 'CREDENTIALS MISSING',
  ready: 'READY',
}

function ibBannerTone(status: string | undefined) {
  if (status === 'ready') return { border: 'border-emerald-400/40', bg: 'bg-emerald-400/10', text: 'text-emerald-300' }
  if (status === 'enabled_but_lean_credentials_missing') return { border: 'border-amber-400/40', bg: 'bg-amber-400/10', text: 'text-amber-300' }
  return { border: 'border-white/10', bg: 'bg-white/[0.03]', text: 'text-white/60' }
}

function Row({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex min-w-0 items-center justify-between rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
      <span className="text-sm text-white/80">{label}</span>
      <span className={`text-xs break-words ${tone ?? 'text-white/60'}`}>{value}</span>
    </div>
  )
}

export function AssetsStatusPanel({ status }: { status: AssetsStatus | undefined }) {
  const banner = ibBannerTone(status?.ib_status)

  return (
    <Panel title="Multi-Asset-Class Readiness">
      <div className={`mb-3 rounded-2xl border ${banner.border} ${banner.bg} px-4 py-3 ${banner.text}`}>
        <strong>IB: {status ? (IB_STATUS_LABEL[status.ib_status] ?? status.ib_status) : 'loading…'}</strong>
        {!status && <div className="mt-1 text-xs opacity-80">No report yet — run `aq assets status`</div>}
      </div>

      <div className="grid min-w-0 gap-2.5">
        <Row
          label="Futures trading"
          value={status ? (status.futures_risk_enabled ? 'enabled' : 'disabled') : '—'}
          tone={status?.futures_risk_enabled ? 'text-emerald-300' : 'text-white/60'}
        />
        <Row
          label="Options trading"
          value={status ? (status.options_risk_enabled ? 'enabled' : 'disabled') : '—'}
          tone={status?.options_risk_enabled ? 'text-emerald-300' : 'text-white/60'}
        />
        <Row
          label="Futures contract specs"
          value={status ? `${status.futures_contract_specs_loaded} loaded` : '—'}
        />
        <Row
          label="FRED yield-curve cache"
          value={
            status
              ? `${status.fred_cache_series_count} series, most recent ${status.fred_cache_most_recent_date ?? 'never populated'}`
              : '—'
          }
        />
        <Row
          label="Configured futures assets"
          value={status ? String(status.configured_futures_assets) : '—'}
        />
        <Row
          label="Configured options assets"
          value={status ? String(status.configured_options_assets) : '—'}
        />
      </div>
    </Panel>
  )
}
