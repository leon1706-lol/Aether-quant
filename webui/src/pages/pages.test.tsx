/**
 * V4-W1 / V4-W2 page-composition tests.
 *
 * These assert *where* each panel lives, which is exactly what the two
 * layout tasks changed and exactly what a careless import cleanup would
 * silently undo. They deliberately do not assert on panel internals -
 * those belong to the panel components, which these tasks did not touch.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'
import { Overview } from './Overview'
import { OperationsPage } from './OperationsPage'
import { TracingPage } from './TracingPage'
import { AppShell } from '../components/layout/AppShell'

// Panels are identified by their Panel `title`, the same string a user
// reads on screen.
const OVERVIEW_PANELS = ['Observation Mode', 'Signal Board', 'Positions', 'Strategy and Risk']
const OPERATIONS_PANELS = [
  'Performance Triggers',
  'Retraining Status',
  'Paper Trading Readiness',
  'Multi-Asset-Class Readiness',
  'Audit Log',
  'Monitoring Feeds',
  'Raw State',
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
