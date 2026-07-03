const TONES: Record<string, string> = {
  buy: 'bg-emerald-400/15 text-emerald-300',
  low_volatility: 'bg-emerald-400/15 text-emerald-300',
  trade: 'bg-emerald-400/15 text-emerald-300',
  sell: 'bg-rose-400/15 text-rose-300',
  high_volatility: 'bg-rose-400/15 text-rose-300',
  reduce_risk: 'bg-rose-400/15 text-rose-300',
  hold: 'bg-amber-400/15 text-amber-300',
  normal_volatility: 'bg-amber-400/15 text-amber-300',
  retrain_candidate: 'bg-amber-400/15 text-amber-300',
  simulate: 'bg-sky-400/15 text-sky-300',
  observe: 'bg-white/10 text-white/80',
  learned: 'bg-emerald-400/15 text-emerald-300',
  hybrid: 'bg-amber-400/15 text-amber-300',
  fallback: 'bg-white/10 text-white/80',
  deterministic: 'bg-sky-400/15 text-sky-300',
}

export function Badge({ tone, children }: { tone?: string; children: React.ReactNode }) {
  const className = (tone && TONES[tone]) || 'bg-white/10 text-white/80'
  return (
    <span className={`rounded-full px-2.5 py-1 text-[0.72rem] font-medium uppercase tracking-wide ${className}`}>
      {children}
    </span>
  )
}
