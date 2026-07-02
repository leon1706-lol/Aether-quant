import { useState } from 'react'
import type { RuntimeState } from '../../types/state'
import { Panel } from '../layout/Panel'

export function RawStateViewer({ state }: { state: RuntimeState | undefined }) {
  const [open, setOpen] = useState(false)

  return (
    <Panel
      title="Raw State"
      action={
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="rounded-full border border-white/15 px-3 py-1 text-xs text-white/80 hover:text-white"
        >
          {open ? 'Hide' : 'Show'}
        </button>
      }
    >
      {open && (
        <pre className="max-h-[420px] overflow-auto rounded-2xl bg-black/30 p-3.5 text-[0.82rem] text-sky-100">
          {JSON.stringify(state ?? {}, null, 2)}
        </pre>
      )}
    </Panel>
  )
}
