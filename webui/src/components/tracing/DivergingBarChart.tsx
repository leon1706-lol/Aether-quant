// Diverging blue/red categorical pair from the dataviz skill's validated
// dark-mode palette - blue = positive, red = negative, gray = zero midpoint.
const POSITIVE = '#3987e5'
const NEGATIVE = '#e66767'

export interface DivergingBarItem {
  label: string
  value: number
}

export function DivergingBarChart({
  items,
  valueFormat = (v: number) => v.toFixed(3),
}: {
  items: DivergingBarItem[]
  valueFormat?: (v: number) => string
}) {
  const max = Math.max(1e-9, ...items.map((i) => Math.abs(i.value)))

  if (items.length === 0) {
    return <div className="text-sm text-white/40">No data yet</div>
  }

  return (
    <div className="grid gap-2">
      {items.map((item) => {
        const positive = item.value >= 0
        const pct = (Math.abs(item.value) / max) * 50
        return (
          <div key={item.label} className="grid grid-cols-[64px_1fr_76px] items-center gap-2">
            <span className="truncate text-xs text-white/70">{item.label}</span>
            <div className="relative h-3 rounded-full bg-white/5">
              <div className="absolute left-1/2 top-0 h-3 w-px -translate-x-1/2 bg-white/20" aria-hidden />
              <div
                className="absolute top-0 h-3 rounded-full"
                style={{
                  backgroundColor: positive ? POSITIVE : NEGATIVE,
                  left: positive ? '50%' : `${50 - pct}%`,
                  width: `${pct}%`,
                }}
              />
            </div>
            <span className="text-right text-xs font-semibold tabular-nums text-white">{valueFormat(item.value)}</span>
          </div>
        )
      })}
    </div>
  )
}
