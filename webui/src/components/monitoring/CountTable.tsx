export function CountTable({ title, counts }: { title: string; counts: Record<string, number> | undefined }) {
  const entries = Object.entries(counts ?? {})

  return (
    <div className="grid min-w-0 gap-2">
      <strong className="text-xs uppercase tracking-widest text-white/60">{title}</strong>
      {entries.length > 0 ? (
        <div className="grid gap-1">
          {entries.map(([label, count]) => (
            <div key={label} className="flex items-start justify-between gap-3 border-t border-white/5 py-1 text-sm">
              <span className="min-w-0 break-words text-white/80">{label}</span>
              <span className="shrink-0 text-white/60">{count}</span>
            </div>
          ))}
        </div>
      ) : (
        <small className="text-white/40">No data yet</small>
      )}
    </div>
  )
}
