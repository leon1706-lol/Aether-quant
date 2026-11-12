import { useState } from 'react'
import type { FormEvent } from 'react'
import type { AccountRow } from '../../types/access'
import { Panel } from '../layout/Panel'

// V6.6.5 (#344, #349, #350): what a first-time or signed-out visitor sees, and the account switch.

export function DemoBanner() {
  return (
    <output className="mt-4 block rounded-2xl border border-sky-400/40 bg-sky-400/10 px-4 py-3 text-sm text-sky-200">
      <strong>Demo data.</strong> The shipped rule on the bundled sample (<code>aq hello</code>). No broker, no model and no live
      orders. Nothing here is a live position.
    </output>
  )
}

export function OnboardingPanel() {
  return (
    <Panel title="No runtime feed yet">
      <p className="text-sm text-white/70">
        The API answered, but nothing has written <code>visualization/state.json</code> yet. Three ways to fill this dashboard:
      </p>
      <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-white/80">
        <li>
          <code>aq hello</code>: download a few years of daily bars, run the shipped rule and print a report (no key, no Docker).
        </li>
        <li>
          <code>aq webui --docker</code>: this dashboard with demo data, in one command.
        </li>
        <li>
          A Lean run (<code>aq backtest</code>) or a paper deployment (<code>aq live up</code>) writes the real feed.
        </li>
      </ol>
      <p className="mt-3 text-xs text-white/50">
        Docs: <a className="underline" href="https://leon1706-lol.github.io/Aether-quant/">leon1706-lol.github.io/Aether-quant</a>
      </p>
    </Panel>
  )
}

export function LoginPanel({ onSubmit, failed }: { onSubmit: (token: string) => void; failed: boolean }) {
  const [token, setToken] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (token.trim()) onSubmit(token.trim())
  }
  return (
    <div className="mx-auto max-w-md">
      <Panel title="Sign in">
        <form onSubmit={submit} className="flex flex-col gap-3">
          <p className="text-sm text-white/70">
            This API needs a token. An admin issues one with <code>aq users add NAME --role viewer</code>.
          </p>
          <label htmlFor="aq-token" className="text-xs uppercase tracking-widest text-white/60">
            Token
          </label>
          <input
            id="aq-token"
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            className="rounded-xl border border-white/15 bg-black/30 px-3 py-2 text-white focus:border-orange-400/60 focus:outline-none"
          />
          {failed ? (
            <p role="alert" className="text-sm text-rose-300">
              That token was not accepted.
            </p>
          ) : null}
          <button type="submit" className="rounded-xl bg-orange-400/20 px-4 py-2 text-sm font-medium text-orange-200 hover:bg-orange-400/30">
            Sign in
          </button>
        </form>
      </Panel>
    </div>
  )
}

export function AccountSelector({ accounts, value, onChange }: { accounts: AccountRow[]; value: string; onChange: (account: string) => void }) {
  if (accounts.length < 2) return null
  return (
    <label className="flex items-center gap-2 text-sm text-white/60">
      <span>account</span>
      <select
        aria-label="Account"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-full border border-white/15 bg-black/40 px-3 py-1.5 text-sm text-white"
      >
        {accounts.map((account) => (
          <option key={account.id} value={account.id}>
            {account.id} ({account.broker})
          </option>
        ))}
      </select>
    </label>
  )
}
