import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { NeuralNetworkModel, NeuralNetworkState, RankingQualitySummary } from '../../types/state'
import { NeuralNetworkStatsPanel } from './NeuralNetworkStatsPanel'

// Sequence rank_5d became the first head in the project's history to reach
// `promotable` in the Phase 4.12 retrain (t=2.3158, zero opposite-sign eras).
const PROMOTABLE_RANK_5D: RankingQualitySummary = {
  quality_status: 'promotable',
  promotion_eligible: true,
  failures: [],
  near_misses: [],
  observed: {
    non_overlapping_t_stat: 2.3158,
    non_overlapping_mean_ic: 0.041,
    bootstrap_ci_lower_bound: 0.0084,
    bootstrap_ci_upper_bound: 0.09,
    num_eras: 10,
    num_opposite_sign_eras: 0,
    num_insufficient_data_eras: 1,
    per_era: [
      { era_index: 0, era_start: '2019-01-01', era_end: '2019-03-31', num_dates: 13, mean_ic: 0.28, t_stat: 3.5 },
      { era_index: 9, era_start: '2021-03-21', era_end: '2021-03-31', num_dates: 1, mean_ic: -0.0007, t_stat: -0.01 },
    ],
  },
}

// Multitask rank_20d remains not_promotable - one genuine (COVID) inversion.
const NOT_PROMOTABLE_RANK_20D: RankingQualitySummary = {
  quality_status: 'not_promotable',
  promotion_eligible: false,
  failures: ['era_sign_instability'],
  near_misses: [],
  observed: {
    non_overlapping_t_stat: 2.8954,
    non_overlapping_mean_ic: 0.05,
    bootstrap_ci_lower_bound: 0.0585,
    bootstrap_ci_upper_bound: 0.12,
    num_eras: 9,
    num_opposite_sign_eras: 1,
    num_insufficient_data_eras: 0,
    per_era: [
      {
        era_index: 4,
        era_start: '2019-12-27',
        era_end: '2020-03-25',
        num_dates: 13,
        mean_ic: -0.1654,
        t_stat: -0.9,
      },
    ],
  },
}

function network(): NeuralNetworkModel {
  return {
    name: 'sequence',
    label: 'Sequence Encoder',
    role: 'sequence',
    status: 'trained',
    node_layers: [55, 32, 1],
    layers: [],
    total_layers: 3,
    total_nodes: 88,
    total_edges: 1760,
    ranking_quality: {
      rank_5d: PROMOTABLE_RANK_5D,
      rank_20d: NOT_PROMOTABLE_RANK_20D,
    },
  }
}

function state(): NeuralNetworkState {
  return {
    networks: [network()],
    totals: { total_networks: 1, total_layers: 3, total_nodes: 88, total_edges: 1760, trained_count: 1 },
    excluded: [],
  }
}

describe('NeuralNetworkStatsPanel ranking-quality gates (V4.12.2, Problems.md #71)', () => {
  it('renders the rank_5d gate independently of rank_20d, not just rank_20d', () => {
    render(<NeuralNetworkStatsPanel neuralNetwork={state()} />)
    expect(screen.getByText(/5d promotion gate:/)).toBeInTheDocument()
    expect(screen.getByText(/20d promotion gate:/)).toBeInTheDocument()
    expect(screen.getByText('promotable')).toBeInTheDocument()
    expect(screen.getByText('not_promotable')).toBeInTheDocument()
  })

  it('renders the per-era detail table with era window/mean IC/t-stat', () => {
    render(<NeuralNetworkStatsPanel neuralNetwork={state()} />)
    expect(screen.getAllByText('per-era detail').length).toBeGreaterThan(0)
    expect(screen.getByText('2019-12-27 → 2020-03-25')).toBeInTheDocument()
    expect(screen.getByText('-0.1654')).toBeInTheDocument()
  })

  it('does not render a ranking-quality section at all when the network has none', () => {
    const bare: NeuralNetworkState = {
      networks: [{ ...network(), ranking_quality: undefined }],
      totals: { total_networks: 1, total_layers: 3, total_nodes: 88, total_edges: 1760, trained_count: 1 },
      excluded: [],
    }
    render(<NeuralNetworkStatsPanel neuralNetwork={bare} />)
    expect(screen.queryByText(/promotion gate:/)).not.toBeInTheDocument()
  })
})

describe('NeuralNetworkStatsPanel residual-rank gates (V5.1 Phase 2, item 5)', () => {
  it('renders the residual rank_20d gate alongside rank_5d/20d', () => {
    const baseNetwork = network()
    const withResidual: NeuralNetworkState = {
      networks: [
        {
          ...baseNetwork,
          ranking_quality: {
            rank_5d: baseNetwork.ranking_quality?.rank_5d ?? null,
            rank_20d: baseNetwork.ranking_quality?.rank_20d ?? null,
            residual_rank_20d: PROMOTABLE_RANK_5D,
          },
        },
      ],
      totals: { total_networks: 1, total_layers: 3, total_nodes: 88, total_edges: 1760, trained_count: 1 },
      excluded: [],
    }
    render(<NeuralNetworkStatsPanel neuralNetwork={withResidual} />)
    expect(screen.getByText(/20d residual promotion gate:/)).toBeInTheDocument()
  })
})
