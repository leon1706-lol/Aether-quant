import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AssetsStatus } from '../../types/state'
import { AssetsStatusPanel } from './AssetsStatusPanel'

const guard = { enabled: true, max_loss_fraction_nav: 0.01, lookback_bars: 60, cooldown_bars: 60, runtime: null }

function status(overrides: Partial<NonNullable<AssetsStatus['sleeves']>> = {}): AssetsStatus {
  return {
    ib_status: 'disabled',
    futures_risk_enabled: false,
    options_risk_enabled: false,
    forex_risk_enabled: true,
    futures_contract_specs_loaded: 0,
    futures_contract_specs_tickers: [],
    forex_pair_specs_loaded: 15,
    forex_pair_specs_tickers: [],
    fred_cache_series_count: 19,
    fred_cache_most_recent_date: '2026-09-30',
    configured_futures_assets: 0,
    configured_options_assets: 0,
    configured_forex_assets: 15,
    sleeves: {
      forex_sleeve: { enabled: true, signal: 'carry', gross_budget: 0.1, guard },
      bond_sleeve: { enabled: true, signal: 'ts_momentum', gross_budget: 0.3, guard },
      crypto_graduates: { enabled: true, per_name_cap: 0.01, class_gross_cap: 0.05, guard },
      rl_sizing: { enabled: true, range: [0.9, 1.1], shadow_guard: true },
      venue_listing_guard: true,
      learned_topology: true,
      ...overrides,
    },
  }
}

describe('AssetsStatusPanel sleeves (V5.8.0)', () => {
  it('shows each sleeve with its signal, budget and guard', () => {
    render(<AssetsStatusPanel status={status()} />)
    expect(screen.getByText(/on, carry, gross 10.0%, guard on/)).toBeInTheDocument()
    expect(screen.getByText(/on, ts_momentum, gross 30.0%/)).toBeInTheDocument()
    expect(screen.getByText(/capped 1.0% per name \/ 5.0% class/)).toBeInTheDocument()
    expect(screen.getByText(/on, 0.9 to 1.1, shadow guard/)).toBeInTheDocument()
  })

  it('flags a tripped guard in red text', () => {
    const tripped = { ...guard, runtime: { active: false, reason: 'sleeve_loss_guard_tripped' } }
    render(
      <AssetsStatusPanel
        status={status({ bond_sleeve: { enabled: true, signal: 'ts_momentum', gross_budget: 0.3, guard: tripped } })}
      />,
    )
    expect(screen.getByText(/GUARD TRIPPED \(sleeve_loss_guard_tripped\)/)).toBeInTheDocument()
  })

  it('renders without a sleeves block (an older API)', () => {
    const old = status()
    delete old.sleeves
    render(<AssetsStatusPanel status={old} />)
    expect(screen.queryByText(/Class sleeves and overlays/)).not.toBeInTheDocument()
  })
})
