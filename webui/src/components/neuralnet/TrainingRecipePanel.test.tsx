import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { NeuralNetworkState } from '../../types/state'
import { TrainingRecipePanel } from './TrainingRecipePanel'

function network(): NeuralNetworkState['networks'][number] {
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
    training_recipe: {
      optimizer: 'adamw',
      lr_schedule: 'cosine',
      normalization: 'layernorm',
      batch_mode: 'cross_sectional',
      ranking_loss: { objective: 'soft_spearman', temperature: 0.05, mse_anchor_weight: 0.1 },
      swa: { enabled: true, epochs_averaged: 12 },
      early_stop_metric: 'rank_ic_non_overlapping',
      early_stop_head: 'rank_20d',
      early_stop_smoothing_epochs: 3,
    },
  }
}

describe('TrainingRecipePanel (V5.1 Phase 3, items 1/10/11)', () => {
  it('shows a graceful empty state when no network has a recorded recipe', () => {
    render(
      <TrainingRecipePanel
        neuralNetwork={{
          networks: [{ ...network(), training_recipe: null }],
          totals: { total_networks: 1, total_layers: 3, total_nodes: 88, total_edges: 1760, trained_count: 1 },
          excluded: [],
        }}
      />,
    )
    expect(screen.getByText(/No training recipe recorded yet/)).toBeInTheDocument()
  })

  it('renders the optimizer/schedule/batch-mode/SWA fields for a network with a recipe', () => {
    render(
      <TrainingRecipePanel
        neuralNetwork={{
          networks: [network()],
          totals: { total_networks: 1, total_layers: 3, total_nodes: 88, total_edges: 1760, trained_count: 1 },
          excluded: [],
        }}
      />,
    )
    expect(screen.getByText('Sequence Encoder')).toBeInTheDocument()
    expect(screen.getByText('adamw')).toBeInTheDocument()
    expect(screen.getByText('cosine')).toBeInTheDocument()
    expect(screen.getByText('cross_sectional')).toBeInTheDocument()
    expect(screen.getByText('layernorm')).toBeInTheDocument()
    expect(screen.getByText('12 epochs')).toBeInTheDocument()
    expect(screen.getByText('soft_spearman')).toBeInTheDocument()
  })
})
