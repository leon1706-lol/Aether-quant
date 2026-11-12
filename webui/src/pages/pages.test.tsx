/**
 * V4-W1 / V4-W2 page-composition tests.
 *
 * These assert *where* each panel lives, which is exactly what the two
 * layout tasks changed and exactly what a careless import cleanup would
 * silently undo. They deliberately do not assert on panel internals -
 * those belong to the panel components, which these tasks did not touch.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Overview } from './Overview'
import { OperationsPage } from './OperationsPage'
import { OptionsStrategyPage } from './OptionsStrategyPage'
import { EvaluationPage } from './EvaluationPage'
import { RiskPage } from './RiskPage'
import { TracingPage } from './TracingPage'
import { ReadinessPage } from './ReadinessPage'
import { AppShell } from '../components/layout/AppShell'

// Panels are identified by their Panel `title`, the same string a user
// reads on screen.
const OVERVIEW_PANELS = ['Observation Mode', 'Rank Signal', 'Signal Board', 'Positions', 'Strategy and Risk']
const OPERATIONS_PANELS = [
  // V5.1 Phase 6 (production safety)
  'Kill Switch',
  'Reconciliation',
  // V6.6.5
  'Trade Lock',
  // V6.6.1
  'Generations',
  'Performance Triggers',
  'Retraining Status',
  'Paper Trading Readiness',
  'Multi-Asset-Class Readiness',
  'Audit Log',
  'Monitoring Feeds',
  'Raw State',
]
// Phase 4.8 - every panel the Options & Strategy page renders.
const OPTIONS_STRATEGY_PANELS = [
  'Held Multi-Leg Positions',
  'Dividend Schedule',
  'Strategy Selector Scores',
  'Corporate Actions',
  'Strategy Catalog',
  'Forex Pair Detail',
]

function renderWithProviders(ui: ReactElement, { route = '/' }: { route?: string } = {}) {
  // retry:false so the 404s a fresh checkout returns (audit-log, etc.)
  // fail fast instead of holding the test open.
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

function panelTitles(): string[] {
  return screen.queryAllByRole('heading').map((heading) => heading.textContent?.trim() ?? '')
}

describe('V4-W1: Overview / Operations split', () => {
  it('Overview keeps the trading-side panels', () => {
    renderWithProviders(<Overview state={undefined} />)
    const titles = panelTitles()
    for (const panel of OVERVIEW_PANELS) {
      expect(titles).toContain(panel)
    }
  })

  it('Overview no longer renders any of the panels that moved to Operations', () => {
    renderWithProviders(<Overview state={undefined} />)
    const titles = panelTitles()
    for (const panel of OPERATIONS_PANELS) {
      expect(titles).not.toContain(panel)
    }
  })

  it('Operations renders every panel that moved off Overview', () => {
    renderWithProviders(<OperationsPage state={undefined} />)
    const titles = panelTitles()
    for (const panel of OPERATIONS_PANELS) {
      expect(titles).toContain(panel)
    }
  })

  it('Operations does not duplicate the panels Overview kept', () => {
    renderWithProviders(<OperationsPage state={undefined} />)
    const titles = panelTitles()
    for (const panel of OVERVIEW_PANELS) {
      expect(titles).not.toContain(panel)
    }
  })

  it('AppShell exposes an Operations nav link pointing at /operations', () => {
    renderWithProviders(
      <AppShell state={undefined} isError={false}>
        <div />
      </AppShell>,
    )
    const link = screen.getByRole('link', { name: 'Operations' })
    expect(link).toHaveAttribute('href', '/operations')
  })

  it('marks only the active route pill as active', () => {
    // `end` on the "/" NavLink is what stops Overview from staying
    // highlighted on every sub-route.
    renderWithProviders(
      <AppShell state={undefined} isError={false}>
        <div />
      </AppShell>,
      { route: '/operations' },
    )
    expect(screen.getByRole('link', { name: 'Operations' }).className).toContain('text-orange-300')
    expect(screen.getByRole('link', { name: 'Overview' }).className).not.toContain('text-orange-300')
  })
})

describe('Phase 4.8: Options & Strategy page', () => {
  it('renders every panel even with no state at all (fresh-clone/no-backtest-ever-run case)', () => {
    renderWithProviders(<OptionsStrategyPage state={undefined} />)
    const titles = panelTitles()
    for (const panel of OPTIONS_STRATEGY_PANELS) {
      expect(titles).toContain(panel)
    }
  })

  it('shows the dormant strategy-selector empty state, never a blank table, when no model is loaded', () => {
    renderWithProviders(<OptionsStrategyPage state={undefined} />)
    expect(
      screen.getByText('No trained strategy-selector model loaded — falls back to static risk-tier ordering.'),
    ).toBeInTheDocument()
  })

  it('AppShell exposes an Options & Strategy nav link pointing at /options-strategy', () => {
    renderWithProviders(
      <AppShell state={undefined} isError={false}>
        <div />
      </AppShell>,
    )
    const link = screen.getByRole('link', { name: 'Options & Strategy' })
    expect(link).toHaveAttribute('href', '/options-strategy')
  })
})

describe('V5.1 Phase 0: Evaluation page', () => {
  it('renders both evaluation panels even with no data at all (aq evaluate never run)', () => {
    renderWithProviders(<EvaluationPage state={undefined} />)
    const titles = panelTitles()
    expect(titles).toContain('Rank Book Performance')
    expect(titles).toContain('Capacity & Cost Stress')
  })

  it('shows the not-evaluated empty state, never a blank/crashed panel, when no report exists', () => {
    renderWithProviders(<EvaluationPage state={undefined} />)
    expect(screen.getAllByText(/Not evaluated yet/).length).toBeGreaterThan(0)
  })

  it('AppShell exposes an Evaluation nav link pointing at /evaluation', () => {
    renderWithProviders(
      <AppShell state={undefined} isError={false}>
        <div />
      </AppShell>,
    )
    const link = screen.getByRole('link', { name: 'Evaluation' })
    expect(link).toHaveAttribute('href', '/evaluation')
  })
})

describe('V5.1 Phase 1: Rank Signal / Net Edge / Book Neutrality panels', () => {
  it('Overview renders the Rank Signal panel', () => {
    renderWithProviders(<Overview state={undefined} />)
    expect(panelTitles()).toContain('Rank Signal')
  })

  it('RiskPage renders the Net Edge and Book Neutrality panels', () => {
    renderWithProviders(<RiskPage state={undefined} />)
    const titles = panelTitles()
    expect(titles).toContain('Net Edge vs. Cost')
    expect(titles).toContain('Book Neutrality')
  })
})

describe('V5.1 Phase 2: Cross-Asset Sensitivity panel', () => {
  it('RiskPage renders the Cross-Asset Macro Sensitivity panel', () => {
    renderWithProviders(<RiskPage state={undefined} />)
    expect(panelTitles()).toContain('Cross-Asset Macro Sensitivity')
  })
})

describe('V4-W2: Tracing column layout', () => {
  it('puts asset performance alone in the right column and the charts in the left', () => {
    const { container } = renderWithProviders(<TracingPage />)
    const columns = container.firstElementChild?.children
    expect(columns).toHaveLength(2)

    const [left, right] = Array.from(columns ?? [])
    const titlesIn = (element: Element) =>
      Array.from(element.querySelectorAll('h2')).map((heading) => heading.textContent?.trim() ?? '')

    expect(titlesIn(left)).toEqual([
      'Runtime Metrics Snapshot',
      'Backtest Equity Curve',
      'Observation Mode Equity Curve',
    ])
    expect(titlesIn(right)).toEqual(['Asset Performance (Sharpe, backtest)'])
  })
})

function stubApi(routes: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input).split('?')[0]
      if (path in routes) {
        return new Response(JSON.stringify(routes[path]), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response('{"detail":"not found"}', { status: path === '/api/auth/whoami' ? 401 : 404 })
    }),
  )
}

describe('V6.6.5: demo, sign-in, accounts and readiness', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.sessionStorage.clear()
  })

  it('AppShell exposes a Readiness nav link pointing at /readiness', () => {
    renderWithProviders(
      <AppShell state={undefined} isError={false}>
        <div />
      </AppShell>,
    )
    expect(screen.getByRole('link', { name: 'Readiness' })).toHaveAttribute('href', '/readiness')
  })

  it('labels demo data on every page', async () => {
    stubApi({ '/api/health': { status: 'ok', demo: true, auth: 'off' } })
    renderWithProviders(
      <AppShell state={undefined} isError={false}>
        <div />
      </AppShell>,
    )
    expect(await screen.findByText('Demo data.')).toBeInTheDocument()
  })

  it('shows onboarding instead of a bare error when the feed is missing', async () => {
    stubApi({ '/api/health': { status: 'ok', demo: false, auth: 'off' } })
    renderWithProviders(
      <AppShell state={undefined} isError>
        <div />
      </AppShell>,
    )
    expect(await screen.findByText('No runtime feed yet')).toBeInTheDocument()
    expect(screen.getByText(/aq hello/)).toBeInTheDocument()
  })

  it('asks for a token when the API requires one, and hides the pages', async () => {
    stubApi({ '/api/health': { status: 'ok', demo: false, auth: 'required' } })
    renderWithProviders(
      <AppShell state={undefined} isError={false}>
        <div>secret page</div>
      </AppShell>,
    )
    expect(await screen.findByLabelText('Token')).toBeInTheDocument()
    expect(screen.queryByText('secret page')).not.toBeInTheDocument()
  })

  it('offers an account selector when there is more than one account', async () => {
    stubApi({
      '/api/health': { status: 'ok', demo: false, auth: 'off' },
      '/api/accounts': { demo: false, accounts: [
        { id: 'default', broker: 'paper', environment: 'live-paper', mode: '(config)', secrets: '0/0', secrets_missing: [], state: '-', reconciliation_breach: null },
        { id: 'paper-b', broker: 'paper', environment: 'live-paper', mode: 'observation', secrets: '0/0', secrets_missing: [], state: '-', reconciliation_breach: null },
      ] },
    })
    const onChange = vi.fn()
    renderWithProviders(
      <AppShell state={undefined} isError={false} account="default" onAccountChange={onChange}>
        <div />
      </AppShell>,
    )
    expect(await screen.findByLabelText('Account')).toBeInTheDocument()
  })

  it('Readiness renders its panels with no scorecard yet, and the scorecard when there is one', async () => {
    renderWithProviders(<ReadinessPage />)
    expect(panelTitles()).toEqual(expect.arrayContaining(['Paper to Live', 'Accounts']))
    expect(screen.getByText(/Not scored yet/)).toBeInTheDocument()
    vi.unstubAllGlobals()
    stubApi({
      '/api/readiness': { ready: false, account: 'default', generated_at: '2026-11-08T00:00:00Z', counts: { pass: 1, fail: 0, unknown: 1 }, blocking: ['x'],
        metrics: [
          { key: 'kill_switch_enabled', group: 'safety', label: 'Kill switch enabled', value: true, threshold: 'true', status: 'pass', evidence: '', measured_at: null },
          { key: 'paper_bands', group: 'paper', label: 'Every paper metric inside its reference band', value: null, threshold: 'all inside', status: 'unknown', evidence: '', measured_at: null },
        ] },
    })
    renderWithProviders(<ReadinessPage />)
    await waitFor(() => expect(screen.getByText('NOT READY FOR LIVE CAPITAL')).toBeInTheDocument())
    expect(screen.getByText('Kill switch enabled')).toBeInTheDocument()
  })

  it('Trade Lock shows no buttons without a signed-in operator', () => {
    renderWithProviders(<OperationsPage state={undefined} />)
    expect(screen.queryByRole('button', { name: 'Lock trading' })).not.toBeInTheDocument()
  })
})
