import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import type { RuntimeState } from '../../types/state'

const REFRESH_LABEL = 'refresh: 5s'

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
}: {
  state: RuntimeState | undefined
  isError: boolean
  children: ReactNode
}) {
  return (
    <div className="min-h-screen text-white">
      <div className="mx-auto w-[min(1480px,calc(100%-28px))] py-6">
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-white/10 pb-5">
          <div>
            <h1 className="text-3xl font-semibold tracking-wide sm:text-4xl">Aether Quant</h1>
            <p className="mt-2 max-w-xl text-sm text-white/60">
              Unified runtime console for portfolio state, risk and the market scene.
            </p>
            <nav className="mt-4 flex gap-2">
              <NavLink
                to="/"
                className={({ isActive }) =>
                  `rounded-full px-4 py-1.5 text-sm font-medium transition ${
                    isActive ? 'bg-orange-400/15 text-orange-300' : 'text-white/60 hover:text-white'
                  }`
                }
              >
                Overview
              </NavLink>
              <NavLink
                to="/risk"
                className={({ isActive }) =>
                  `rounded-full px-4 py-1.5 text-sm font-medium transition ${
                    isActive ? 'bg-orange-400/15 text-orange-300' : 'text-white/60 hover:text-white'
                  }`
                }
              >
                Risk
              </NavLink>
              <NavLink
                to="/topology"
                className={({ isActive }) =>
                  `rounded-full px-4 py-1.5 text-sm font-medium transition ${
                    isActive ? 'bg-orange-400/15 text-orange-300' : 'text-white/60 hover:text-white'
                  }`
                }
              >
                Topology
              </NavLink>
            </nav>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <StatusChip strong>mode: {isError ? 'feed unavailable' : state?.mode ?? 'loading'}</StatusChip>
            <StatusChip>updated: {state?.updated_at ?? 'waiting'}</StatusChip>
            <StatusChip>{REFRESH_LABEL}</StatusChip>
          </div>
        </header>
        <main className="mt-6">{children}</main>
      </div>
    </div>
  )
}
