export function RiskBar({ label, value, cap }: { label: string; value: number | undefined; cap: number | undefined }) {
  const ratio = Math.min(Math.abs(Number(value || 0)) / Math.max(Number(cap || 1), 0.000001), 1)
  const tone = ratio > 0.85 ? 'bg-rose-400' : ratio > 0.55 ? 'bg-amber-400' : 'bg-emerald-400'

  return (
    <div className="grid grid-cols-[130px_1fr_auto] items-center gap-2.5 text-[0.88rem]">
      <span className="text-white/60">{label}</span>
      <div className="relative h-2.5 overflow-hidden rounded-full bg-white/10">
        <div className={`absolute inset-y-0 left-0 rounded-full ${tone}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      <strong>{`${(Number(value || 0) * 100).toFixed(2)}%`}</strong>
    </div>
  )
}
