export function formatCurrency(value: number | undefined): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(Number(value || 0))
}

export function formatPercent(value: number | undefined, digits = 2): string {
  return `${(Number(value || 0) * 100).toFixed(digits)}%`
}

export function formatNumber(value: number | undefined, digits = 2): string {
  return Number(value || 0).toFixed(digits)
}

export function formatValue(value: number | undefined, format: string): string {
  if (format === 'currency') return formatCurrency(value)
  if (format === 'percent') return formatPercent(value)
  return formatNumber(value, 3)
}
