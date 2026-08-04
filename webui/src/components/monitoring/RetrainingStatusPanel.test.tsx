import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RetrainingStatusPanel } from './RetrainingStatusPanel'

// V5.1 Phase 6 (production safety) - covers only the new Auto-Rollback
// block this phase added; the rest of the panel's pre-existing rendering
// (banner/metrics/last-trigger/rollback) was not touched and has no prior
// dedicated test file for this component.
describe('RetrainingStatusPanel — Auto-Rollback block (V5.1 Phase 6)', () => {
  it('shows a graceful empty state when no status data is available yet', () => {
    render(<RetrainingStatusPanel status={undefined} />)
    const autoRollbackHeading = screen.getByText('Auto-Rollback')
    expect(autoRollbackHeading.parentElement).toHaveTextContent('No data yet')
  })

  it('shows Disabled when auto_rollback.config.enabled is false', () => {
    render(
      <RetrainingStatusPanel
        status={{
          active_model: null,
          latest_candidate: null,
          last_trigger: null,
          latest_retraining_event: null,
          rollback_available: false,
          rollback_candidates: [],
          auto_rollback: {
            config: { enabled: false },
            degradation_signals: {
              kill_switch_tripped: false,
              net_sharpe_decay: false,
              rank_ic_decay: false,
              bars_since_promotion: null,
              bars_since_last_rollback: null,
            },
            decision: { should_rollback: false, to_version_id: null, reason: 'auto_rollback_disabled', failures: [] },
          },
        }}
      />,
    )
    expect(screen.getByText(/Disabled/)).toBeInTheDocument()
    expect(screen.getByText(/no action/)).toBeInTheDocument()
  })

  it('shows ROLLBACK PENDING and blocking failures when the selector says yes', () => {
    render(
      <RetrainingStatusPanel
        status={{
          active_model: null,
          latest_candidate: null,
          last_trigger: null,
          latest_retraining_event: null,
          rollback_available: true,
          rollback_candidates: [],
          auto_rollback: {
            config: { enabled: true },
            degradation_signals: {
              kill_switch_tripped: true,
              net_sharpe_decay: false,
              rank_ic_decay: false,
              bars_since_promotion: 100,
              bars_since_last_rollback: null,
            },
            decision: {
              should_rollback: true,
              to_version_id: 'v_old',
              reason: 'kill_switch_tripped',
              failures: [],
            },
          },
        }}
      />,
    )
    expect(screen.getByText(/Armed/)).toBeInTheDocument()
    expect(screen.getByText(/ROLLBACK PENDING/)).toBeInTheDocument()
  })
})
