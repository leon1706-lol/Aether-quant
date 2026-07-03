import { useMemo, useRef, useState } from 'react'

export interface LineSeries {
  id: string
  label: string
  color: string
  values: number[]
}

const WIDTH = 640
const PADDING = { top: 12, right: 16, bottom: 24, left: 56 }

function niceTicks(min: number, max: number, count: number): number[] {
  if (min === max) return [min]
  const step = (max - min) / count
  return Array.from({ length: count + 1 }, (_, i) => min + step * i)
}

export function LineChart({
  series,
  xLabels,
  height = 220,
  valueFormat = (v: number) => v.toFixed(2),
  areaOnSingle = true,
}: {
  series: LineSeries[]
  xLabels: string[]
  height?: number
  valueFormat?: (v: number) => string
  areaOnSingle?: boolean
}) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  const innerW = WIDTH - PADDING.left - PADDING.right
  const innerH = height - PADDING.top - PADDING.bottom
  const n = xLabels.length

  const { min, max } = useMemo(() => {
    let lo = Infinity
    let hi = -Infinity
    for (const s of series) {
      for (const v of s.values) {
        if (Number.isFinite(v)) {
          if (v < lo) lo = v
          if (v > hi) hi = v
        }
      }
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { min: 0, max: 1 }
    if (lo === hi) {
      lo -= 1
      hi += 1
    }
    const pad = (hi - lo) * 0.08
    return { min: lo - pad, max: hi + pad }
  }, [series])

  const xAt = (i: number) => (n <= 1 ? PADDING.left : PADDING.left + (i / (n - 1)) * innerW)
  const yAt = (v: number) => PADDING.top + innerH - ((v - min) / (max - min)) * innerH

  const paths = useMemo(
    () =>
      series.map((s) => {
        let d = ''
        s.values.forEach((v, i) => {
          if (!Number.isFinite(v)) return
          d += `${d ? 'L' : 'M'}${xAt(i).toFixed(2)},${yAt(v).toFixed(2)} `
        })
        return { ...s, d }
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [series, min, max, n],
  )

  const gridValues = niceTicks(min, max, 4)

  function handleMove(e: React.PointerEvent<SVGRectElement>) {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect || n === 0) return
    const px = ((e.clientX - rect.left) / rect.width) * WIDTH
    const ratio = (px - PADDING.left) / innerW
    const idx = Math.round(ratio * (n - 1))
    setHoverIdx(Math.min(n - 1, Math.max(0, idx)))
  }

  const hasData = series.some((s) => s.values.some((v) => Number.isFinite(v)))

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${height}`}
        className="w-full"
        style={{ height }}
        role="img"
        aria-label={series.map((s) => s.label).join(', ')}
      >
        {gridValues.map((v) => (
          <g key={v}>
            <line
              x1={PADDING.left}
              x2={WIDTH - PADDING.right}
              y1={yAt(v)}
              y2={yAt(v)}
              stroke="rgba(255,255,255,0.08)"
              strokeWidth={1}
            />
            <text x={PADDING.left - 8} y={yAt(v)} textAnchor="end" dominantBaseline="middle" fill="rgba(255,255,255,0.4)" fontSize={10}>
              {valueFormat(v)}
            </text>
          </g>
        ))}

        {paths.length === 1 && areaOnSingle && paths[0].d && (
          <path
            d={`${paths[0].d} L${xAt(n - 1).toFixed(2)},${yAt(min).toFixed(2)} L${xAt(0).toFixed(2)},${yAt(min).toFixed(2)} Z`}
            fill={paths[0].color}
            opacity={0.1}
            stroke="none"
          />
        )}

        {paths.map((s) => (
          <path key={s.id} d={s.d} fill="none" stroke={s.color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        ))}

        {hoverIdx !== null && (
          <line
            x1={xAt(hoverIdx)}
            x2={xAt(hoverIdx)}
            y1={PADDING.top}
            y2={height - PADDING.bottom}
            stroke="rgba(255,255,255,0.25)"
            strokeWidth={1}
          />
        )}

        {hoverIdx !== null &&
          series.map((s) => {
            const v = s.values[hoverIdx]
            if (!Number.isFinite(v)) return null
            return (
              <circle key={s.id} cx={xAt(hoverIdx)} cy={yAt(v)} r={4} fill={s.color} stroke="#0d0d0d" strokeWidth={2} />
            )
          })}

        <rect
          x={PADDING.left}
          y={PADDING.top}
          width={Math.max(innerW, 0)}
          height={Math.max(innerH, 0)}
          fill="transparent"
          onPointerMove={handleMove}
          onPointerLeave={() => setHoverIdx(null)}
        />
      </svg>

      {!hasData && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-white/40">No data yet</div>
      )}

      {hoverIdx !== null && hasData && (
        <div
          className="pointer-events-none absolute top-2 z-10 max-w-[220px] rounded-xl border border-white/10 bg-[#141414]/95 px-3 py-2 text-xs shadow-xl"
          style={{ left: `${(xAt(hoverIdx) / WIDTH) * 100}%`, transform: 'translateX(-50%)' }}
        >
          <div className="mb-1 truncate text-white/50">{xLabels[hoverIdx]}</div>
          <div className="grid gap-1">
            {series.map((s) => (
              <div key={s.id} className="flex items-center gap-2">
                <span className="inline-block h-0.5 w-3 shrink-0" style={{ backgroundColor: s.color }} />
                <span className="font-semibold text-white">
                  {Number.isFinite(s.values[hoverIdx]) ? valueFormat(s.values[hoverIdx]) : '-'}
                </span>
                <span className="truncate text-white/50">{s.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {series.length > 1 && (
        <div className="mt-2 flex flex-wrap gap-3">
          {series.map((s) => (
            <div key={s.id} className="flex items-center gap-1.5 text-xs text-white/60">
              <span className="inline-block h-0.5 w-3" style={{ backgroundColor: s.color }} />
              {s.label}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
