import { describe, expect, it } from 'vitest'
import { formatCurrency, formatNumber, formatPercent, formatValue, toNumber } from './format'

describe('formatCurrency', () => {
  it('defaults undefined to $0', () => {
    expect(formatCurrency(undefined)).toBe('$0')
  })

  it('formats a positive value, rounded to 0 decimals', () => {
    expect(formatCurrency(1234.56)).toBe('$1,235')
  })

  it('formats a negative value', () => {
    expect(formatCurrency(-1234.56)).toBe('-$1,235')
  })

  it('formats a large value with thousands separators', () => {
    expect(formatCurrency(1500000)).toBe('$1,500,000')
  })
})

describe('formatPercent', () => {
  it('multiplies by 100 and appends a % sign, 2 digits by default', () => {
    expect(formatPercent(0.1234)).toBe('12.34%')
  })

  it('respects a custom digits param', () => {
    expect(formatPercent(0.1234, 1)).toBe('12.3%')
  })

  it('defaults undefined to 0.00%', () => {
    expect(formatPercent(undefined)).toBe('0.00%')
  })
})

describe('formatNumber', () => {
  it('defaults undefined to 0.00', () => {
    expect(formatNumber(undefined)).toBe('0.00')
  })

  it('respects a custom digits param', () => {
    expect(formatNumber(3.14159, 4)).toBe('3.1416')
  })
})

describe('formatValue', () => {
  it('dispatches to formatCurrency for "currency"', () => {
    expect(formatValue(1234.56, 'currency')).toBe('$1,235')
  })

  it('dispatches to formatPercent for "percent"', () => {
    expect(formatValue(0.1234, 'percent')).toBe('12.34%')
  })

  it('falls through to formatNumber with 3 digits for any other format string', () => {
    // Non-obvious from the signature alone: the fallback uses 3 digits,
    // not formatNumber's own 2-digit default.
    expect(formatValue(3.14159, 'raw')).toBe('3.142')
  })
})

describe('toNumber', () => {
  it('returns NaN for undefined', () => {
    expect(toNumber(undefined)).toBeNaN()
  })

  it('returns NaN for an empty string', () => {
    expect(toNumber('')).toBeNaN()
  })

  it('parses a valid numeric string', () => {
    expect(toNumber('3.5')).toBe(3.5)
  })
})
