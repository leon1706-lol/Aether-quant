import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { postTradeLock } from '../../api/client'
import type { WhoAmI } from '../../types/access'
import { Panel } from '../layout/Panel'

// V6.6.5 (#350): lock (operator) or unlock (admin) the selected account's trading. The API checks the role again and
// writes a hash-chained action record; the buttons only hide what the server would refuse.

export function TradeLockPanel({
  account,
  locked,
  who,
  demo,
}: {
  account: string
  locked: boolean | undefined
  who: WhoAmI | undefined
  demo: boolean
}) {
  const queryClient = useQueryClient()
  const [message, setMessage] = useState<string | null>(null)
  const role = who?.role ?? null
  const canLock = !demo && (role === 'operator' || role === 'admin')
  const canUnlock = !demo && role === 'admin'

  const send = async (value: boolean | null) => {
    try {
      const result = await postTradeLock(account, value)
      setMessage(`${result.account}: ${value === null ? 'back to the rules' : value ? 'locked' : 'unlocked'} (audit ${result.audit_hash.slice(0, 12)})`)
      await queryClient.invalidateQueries({ queryKey: ['state'] })
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'request failed')
    }
  }

  return (
    <Panel title="Trade Lock">
      <p className="text-sm text-white/70">
        Account <strong>{account}</strong>: {locked === undefined ? 'state unknown' : locked ? 'trading locked' : 'trading allowed'}.
      </p>
      {demo ? (
        <p className="mt-2 text-xs text-white/50">The demo dashboard changes nothing.</p>
      ) : !role ? (
        <p className="mt-2 text-xs text-white/50">Sign in as an operator to lock, or an admin to unlock (<code>aq users add</code>).</p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {canLock ? (
          <button type="button" onClick={() => send(true)} className="rounded-xl bg-rose-400/20 px-4 py-2 text-sm text-rose-200 hover:bg-rose-400/30">
            Lock trading
          </button>
        ) : null}
        {canUnlock ? (
          <>
            <button type="button" onClick={() => send(false)} className="rounded-xl bg-emerald-400/20 px-4 py-2 text-sm text-emerald-200 hover:bg-emerald-400/30">
              Unlock
            </button>
            <button type="button" onClick={() => send(null)} className="rounded-xl bg-white/10 px-4 py-2 text-sm text-white/80 hover:bg-white/15">
              Back to the rules
            </button>
          </>
        ) : null}
      </div>
      {message ? (
        <output className="mt-2 block text-xs text-white/60 break-words">{message}</output>
      ) : null}
    </Panel>
  )
}
