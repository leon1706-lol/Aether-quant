import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { LineChart } from './LineChart'

const SERIES_A = { id: 'a', label: 'Series A', color: '#3987e5', values: [1, 2, 3] }
const SERIES_B = { id: 'b', label: 'Series B', color: '#e0575b', values: [4, 5, 6] }

describe('LineChart', () => {
  it('renders an aria-label joining every series label', () => {
    render(<LineChart series={[SERIES_A, SERIES_B]} xLabels={['x1', 'x2', 'x3']} />)
    expect(screen.getByRole('img', { name: 'Series A, Series B' })).toBeInTheDocument()
  })

  it('shows the "No data yet" empty state when every value is non-finite', () => {
    render(
      <LineChart
        series={[{ id: 'a', label: 'Series A', color: '#3987e5', values: [NaN, NaN] }]}
        xLabels={['x1', 'x2']}
      />,
    )
    expect(screen.getByText('No data yet')).toBeInTheDocument()
  })

  it('does not show the empty state when at least one value is finite', () => {
    render(<LineChart series={[SERIES_A]} xLabels={['x1', 'x2', 'x3']} />)
    expect(screen.queryByText('No data yet')).not.toBeInTheDocument()
  })

  it('only renders a legend when there is more than one series', () => {
    const { rerender } = render(<LineChart series={[SERIES_A]} xLabels={['x1', 'x2', 'x3']} />)
    expect(screen.queryByText('Series A')).not.toBeInTheDocument()

    rerender(<LineChart series={[SERIES_A, SERIES_B]} xLabels={['x1', 'x2', 'x3']} />)
    expect(screen.getByText('Series A')).toBeInTheDocument()
    expect(screen.getByText('Series B')).toBeInTheDocument()
  })

  it('shows a tooltip with the formatted value at the hovered index', () => {
    render(
      <LineChart
        series={[SERIES_A]}
        xLabels={['x1', 'x2', 'x3']}
        valueFormat={(v) => `${v.toFixed(1)}!`}
      />,
    )
    const interactionRect = document.querySelector('rect[fill="transparent"]')
    expect(interactionRect).toBeTruthy()

    // jsdom's getBoundingClientRect() is all-zero by default; stub it so
    // handleMove()'s pixel-to-index math resolves to a real, predictable
    // index instead of dividing by a zero-width rect. Spying on
    // Element.prototype (not SVGSVGElement.prototype) since jsdom defines
    // the real implementation there.
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      width: 640,
      height: 220,
      right: 640,
      bottom: 220,
      x: 0,
      y: 0,
      toJSON: () => {},
    } as DOMRect)

    // WIDTH=640, PADDING.left=56, PADDING.right=16 -> innerW=568. Aim for
    // index 2 (the last point, x3): xAt(2) = 56 + (2/2)*568 = 624.
    fireEvent.pointerMove(interactionRect!, { clientX: 624, clientY: 100 })

    expect(screen.getByText('x3')).toBeInTheDocument()
    expect(screen.getByText('3.0!')).toBeInTheDocument()
  })
})
