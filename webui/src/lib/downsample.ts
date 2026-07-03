// Evenly samples down to at most `target` rows so long-running exports
// (observation mode runs thousands of bars) stay cheap to render as SVG paths.
export function downsample<T>(rows: T[], target = 400): T[] {
  if (rows.length <= target) return rows
  const step = rows.length / target
  const out: T[] = []
  for (let i = 0; i < target; i++) {
    out.push(rows[Math.floor(i * step)])
  }
  const last = rows[rows.length - 1]
  if (out[out.length - 1] !== last) out.push(last)
  return out
}
