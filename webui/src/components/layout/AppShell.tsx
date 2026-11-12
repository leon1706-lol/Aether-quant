import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { NavLink } from 'react-router-dom'
import type { RuntimeState } from '../../types/state'
import { useAccounts, useHealth, useWhoAmI } from '../../api/hooks'
import { HttpError } from '../../api/client'
import { getToken, setToken } from '../../api/session'
import { AccountSelector, DemoBanner, LoginPanel, OnboardingPanel } from '../access/AccessPanels'

const REFRESH_LABEL = 'refresh: 5s'

const NAV_ITEMS: { to: string; label: string }[] = [
  { to: '/', label: 'Overview' },
  { to: '/operations', label: 'Operations' },
  { to: '/risk', label: 'Risk' },
  { to: '/options-strategy', label: 'Options & Strategy' },
  { to: '/topology', label: 'Topology' },
  { to: '/neural-network', label: 'Neural Network' },
  { to: '/evaluation', label: 'Evaluation' },
  { to: '/readiness', label: 'Readiness' },
  { to: '/tracing', label: 'Tracing' },
]

function StatusChip({ children, strong = false }: { children: ReactNode; strong?: boolean }) {
  return (
    <span
      className={`whitespace-nowrap rounded-full border px-3 py-1.5 text-sm ${
        strong
          ? 'border-orange-400/40 bg-orange-400/10 text-orange-300'
          : 'border-white/15 bg-white/5 text-white/60'
      }`}
    >
      {children}
    </span>
  )
}

export function AppShell({
  state,
  isError,
  children,
  account = 'default',
  onAccountChange,
}: {
  state: RuntimeState | undefined
  isError: boolean
  children: ReactNode
  account?: string
  onAccountChange?: (account: string) => void
}) {
  const queryClient = useQueryClient()
  const { data: health } = useHealth()
  const authRequired = health?.auth === 'required'
  const whoami = useWhoAmI(authRequired)
  const { data: accounts } = useAccounts()
  const signedOut = authRequired && (!getToken() || (whoami.error instanceof HttpError && whoami.error.status === 401))
  const user = whoami.data?.user ?? null

  const signIn = (token: string) => {
    setToken(token)
    void queryClient.invalidateQueries()
  }
  const signOut = () => {
    setToken(null)
    void queryClient.invalidateQueries()
  }

  return (
    <div className="min-h-screen text-white">
      <div className="mx-auto w-[min(1480px,calc(100%-28px))] overflow-x-hidden py-6">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-white/10 pb-5">
          <div>
            <h1 className="text-3xl font-semibold tracking-wide sm:text-4xl">Aether Quant</h1>
            <p className="mt-2 max-w-xl text-sm text-white/60">
              Unified runtime console for portfolio state, risk and the market scene.
            </p>
            <nav aria-label="Pages" className="mt-4 flex flex-wrap gap-2">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) =>
                    `rounded-full px-4 py-1.5 text-sm font-medium transition ${
                      isActive ? 'bg-orange-400/15 text-orange-300' : 'text-white/60 hover:text-white'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {onAccountChange && accounts?.accounts ? <AccountSelector accounts={accounts.accounts} value={account} onChange={onAccountChange} /> : null}
            <StatusChip strong>mode: {isError ? 'feed unavailable' : state?.mode ?? 'loading'}</StatusChip>
            <StatusChip>updated: {state?.updated_at ?? 'waiting'}</StatusChip>
            <StatusChip>{REFRESH_LABEL}</StatusChip>
            {user ? (
              <>
                <StatusChip>
                  {user} ({whoami.data?.role})
                </StatusChip>
                <button type="button" onClick={signOut} className="rounded-full border border-white/15 px-3 py-1.5 text-sm text-white/60 hover:text-white">
                  Sign out
                </button>
              </>
            ) : null}
          </div>
        </header>
        {health?.demo ? <DemoBanner /> : null}
        <main className="mt-6">
          {signedOut ? (
            <LoginPanel onSubmit={signIn} failed={Boolean(getToken())} />
          ) : (
            <>
              {isError && !health?.demo ? (
                <div className="mb-4">
                  <OnboardingPanel />
                </div>
              ) : null}
              {children}
            </>
          )}
        </main>
      </div>
    </div>
  )
}
