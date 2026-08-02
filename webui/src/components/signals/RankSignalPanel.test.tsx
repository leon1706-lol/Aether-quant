import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RankSignalPanel } from './RankSignalPanel'

describe('RankSignalPanel (V5.1 Phase 1, Problems.md #73)', () => {
  it('shows a graceful empty state when state.rank_signal is absent (pre-first-bar)', () => {
    render(<RankSignalPanel rankSignal={undefined} />)
    expect(screen.getByText(/No rank signal policy yet/)).toBeInTheDocument()
  })

  it('renders the resolved head blend and model priority', () => {
    render(
      <RankSignalPanel
        rankSignal={{
          heads: { rank_20d: 1.0, rank_5d: 0.0 },
          model_priority: ['sequence', 'multitask'],
          normalization: 'cross_sectional',
          demoted: [],
          reason: 'no_demotion_needed',
        }}
      />,
    )
    expect(screen.getByText(/rank_20d/)).toBeInTheDocument()
    expect(screen.getByText(/sequence → multitask/)).toBeInTheDocument()
    expect(screen.queryByText('demoted')).not.toBeInTheDocument()
  })

  it('surfaces a demoted-head badge when a head failed the promotion gate', () => {
    render(
      <RankSignalPanel
        rankSignal={{
          heads: { rank_20d: 0.0, rank_5d: 1.0 },
          model_priority: ['sequence', 'multitask'],
          normalization: 'cross_sectional',
          demoted: ['rank_20d'],
          reason: 'demoted:rank_20d',
        }}
      />,
    )
    expect(screen.getByText('demoted')).toBeInTheDocument()
    expect(screen.getByText(/rank_20d \(not promotable\)/)).toBeInTheDocument()
  })
})
