import type { ReactNode } from 'react'

export function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <article className="rounded-3xl border border-white/10 bg-white/5 p-5 shadow-2xl backdrop-blur-md transition-shadow duration-300 hover:border-orange-400/30 hover:shadow-[0_0_18px_2px_rgba(251,146,60,0.35)]">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-white/60">{title}</h2>
        {action}
      </div>
      {children}
    </article>
  )
}
