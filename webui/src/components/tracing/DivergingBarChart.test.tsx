import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DivergingBarChart } from './DivergingBarChart'

describe('DivergingBarChart', () => {
  it('shows "No data yet" for an empty items list', () => {
    render(<DivergingBarChart items={[]} />)
    expect(screen.getByText('No data yet')).toBeInTheDocument()
  })

  it('grows a positive value bar rightward from the 50% midpoint', () => {
    // max = 10 (the largest |value| across all items), item value = 5 ->
    // pct = (5/10)*50 = 25.
    render(<DivergingBarChart items={[{ label: 'Positive', value: 5 }, { label: 'Reference', value: -10 }]} />)
    const bar = Array.from(document.querySelectorAll('div')).find(
      (el) => (el as HTMLElement).style.backgroundColor === 'rgb(57, 135, 229)',
    )
    expect(bar).toBeTruthy()
    const style = (bar as HTMLElement).style
    expect(style.left).toBe('50%')
    expect(style.width).toBe('25%')
  })

  it('grows a negative value bar leftward from the 50% midpoint', () => {
    // max = 10, item value = -5 -> pct = 25, left = 50-25 = 25%.
    render(<DivergingBarChart items={[{ label: 'Negative', value: -5 }, { label: 'Reference', value: 10 }]} />)
    const bar = Array.from(document.querySelectorAll('div')).find(
      (el) => (el as HTMLElement).style.backgroundColor === 'rgb(230, 103, 103)',
    )
    expect(bar).toBeTruthy()
    const style = (bar as HTMLElement).style
    expect(style.left).toBe('25%')
    expect(style.width).toBe('25%')
  })

  it('renders every item label and its formatted value', () => {
    render(<DivergingBarChart items={[{ label: 'Alpha', value: 0.5 }]} valueFormat={(v) => `${v}!`} />)
    expect(screen.getByText('Alpha')).toBeInTheDocument()
    expect(screen.getByText('0.5!')).toBeInTheDocument()
  })
})
