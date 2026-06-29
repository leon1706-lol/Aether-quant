const TONES: Record<string, string> = {
  buy: 'bg-emerald-400/15 text-emerald-300',
  low_volatility: 'bg-emerald-400/15 text-emerald-300',
  sell: 'bg-rose-400/15 text-rose-300',
  high_volatility: 'bg-rose-400/15 text-rose-300',
  hold: 'bg-amber-400/15 text-amber-300',
  normal_volatility: 'bg-amber-400/15 text-amber-300',
}

export function Badge({ tone, children }: { tone?: string; children: React.ReactNode }) {
  const className = (tone && TONES[tone]) || 'bg-white/10 text-slate-300'
  return (
    <span className={`rounded-full px-2.5 py-1 text-[0.72rem] font-medium uppercase tracking-wide ${className}`}>
      {children}
    </span>
  )
}
