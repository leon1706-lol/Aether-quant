import type { NeuralNetworkState, RankingQualitySummary } from '../../types/state'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V4.12.2 (development/Problems.md #71) - the promotion-gate verdict was
// only ever rendered for rank_20d, even though rank_5d/sector_neutral_rank_20d
// are computed and typed identically. Sequence's rank_5d became the first
// head in the project's history to reach `promotable` this phase - it was
// invisible in the webui before this fix. Also renders the per-era
// diagnostic (observed.per_era) that assess_ranking_quality_from_predictions()
// already computes - previously only inspectable by reading the raw JSON.
function RankingQualityGate({ label, summary }: { label: string; summary: RankingQualitySummary | null | undefined }) {
  if (!summary) return null
  const { observed } = summary
  return (
    <span className="col-span-2 flex flex-col gap-1">
      <span className="flex flex-wrap items-center gap-1.5">
        {label} promotion gate: <Badge tone={summary.quality_status}>{summary.quality_status}</Badge>
        <span className="text-white/80">
          CI [{observed.bootstrap_ci_lower_bound.toFixed(3)}, {observed.bootstrap_ci_upper_bound.toFixed(3)}], t=
          {observed.non_overlapping_t_stat.toFixed(2)}, {observed.num_eras} eras (
          {observed.num_opposite_sign_eras} opposite-sign
          {observed.num_insufficient_data_eras ? `, ${observed.num_insufficient_data_eras} insufficient-data` : ''})
        </span>
      </span>
      {observed.per_era.length > 0 ? (
        <details className="text-[0.68rem] text-white/50">
          <summary className="cursor-pointer select-none text-white/40">per-era detail</summary>
          <table className="mt-1 w-full border-collapse">
            <thead>
              <tr className="text-left text-white/40">
                <th className="pr-2 font-normal">Era</th>
                <th className="pr-2 font-normal">Window</th>
                <th className="pr-2 font-normal">n</th>
                <th className="pr-2 font-normal">mean IC</th>
                <th className="pr-2 font-normal">t</th>
              </tr>
            </thead>
            <tbody>
              {observed.per_era.map((era) => {
                // per_era doesn't carry its own insufficient-data flag from the
                // backend - this mirrors phase1.target.ranking.promotion_gate's
                // DEFAULT era_min_observations (3, config.json), a visual-only
                // heuristic that can drift if that config is changed.
                const insufficient = era.num_dates < 3
                const opposesAggregate =
                  !insufficient &&
                  ((observed.non_overlapping_mean_ic > 0 && era.mean_ic < 0) ||
                    (observed.non_overlapping_mean_ic < 0 && era.mean_ic > 0))
                const tone = insufficient ? 'text-white/30' : opposesAggregate ? 'text-rose-300' : 'text-emerald-300/80'
                return (
                  <tr key={era.era_index} className={tone}>
                    <td className="pr-2">{era.era_index}</td>
                    <td className="pr-2">
                      {era.era_start} → {era.era_end}
                    </td>
                    <td className="pr-2">{era.num_dates}</td>
                    <td className="pr-2">{era.mean_ic.toFixed(4)}</td>
                    <td className="pr-2">{era.t_stat.toFixed(2)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </details>
      ) : null}
    </span>
  )
}

function NetworkRow({ network }: { network: NeuralNetworkState['networks'][number] }) {
  const tone = network.role === 'baseline' ? 'baseline' : network.quality_status ?? undefined

  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-white">{network.label}</span>
        <Badge tone={tone}>{network.role === 'baseline' ? 'baseline' : network.quality_status ?? 'unknown'}</Badge>
      </div>
      {network.status === 'trained' ? (
        <div className="mt-2 grid grid-cols-3 gap-2 text-center">
          <div>
            <small className="text-white/50">Layers</small>
            <div className="text-sm text-white">{network.total_layers}</div>
          </div>
          <div>
            <small className="text-white/50">Nodes</small>
            <div className="text-sm text-white">{network.total_nodes}</div>
          </div>
          <div>
            <small className="text-white/50">Edges</small>
            <div className="text-sm text-white">{network.total_edges.toLocaleString()}</div>
          </div>
        </div>
      ) : (
        <div className="mt-2 text-xs text-white/40">Not trained yet</div>
      )}
      {network.horizon_mcc || network.rank_ic || network.ranking_quality || network.regression_quality ? (
        <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 border-t border-white/5 pt-2 text-[0.7rem] text-white/60">
          {network.horizon_mcc ? (
            <>
              <span>
                5d MCC: <span className="text-white/80">{network.horizon_mcc.direction_5d?.toFixed(3) ?? '—'}</span>
              </span>
              <span>
                20d MCC: <span className="text-white/80">{network.horizon_mcc.direction_20d?.toFixed(3) ?? '—'}</span>
              </span>
            </>
          ) : null}
          {network.rank_ic ? (
            <>
              <span>
                5d rank-IC:{' '}
                <span className="text-white/80">
                  {network.rank_ic.rank_5d
                    ? `${network.rank_ic.rank_5d.mean_ic.toFixed(3)} (t=${network.rank_ic.rank_5d.t_stat.toFixed(2)})`
                    : '—'}
                </span>
              </span>
              <span>
                20d rank-IC:{' '}
                <span className="text-white/80">
                  {network.rank_ic.rank_20d
                    ? `${network.rank_ic.rank_20d.mean_ic.toFixed(3)} (t=${network.rank_ic.rank_20d.t_stat.toFixed(2)})`
                    : '—'}
                </span>
              </span>
              {network.rank_ic.sector_neutral_rank_20d !== undefined ? (
                <span>
                  20d sector-neutral rank-IC:{' '}
                  <span className="text-white/80">
                    {network.rank_ic.sector_neutral_rank_20d
                      ? `${network.rank_ic.sector_neutral_rank_20d.mean_ic.toFixed(3)} (t=${network.rank_ic.sector_neutral_rank_20d.t_stat.toFixed(2)})`
                      : '—'}
                  </span>
                </span>
              ) : null}
            </>
          ) : null}
          <RankingQualityGate label="5d" summary={network.ranking_quality?.rank_5d} />
          <RankingQualityGate label="20d" summary={network.ranking_quality?.rank_20d} />
          <RankingQualityGate label="20d sector-neutral" summary={network.ranking_quality?.sector_neutral_rank_20d} />
          {network.regression_quality ? (
            <span className="col-span-2">
              Regression quality: mag={network.regression_quality.magnitude ?? '—'}, vol=
              {network.regression_quality.volatility ?? '—'}
            </span>
          ) : null}
        </div>
      ) : null}
      <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-[0.7rem] text-white/40">
        <span>{network.node_layers.length > 0 ? network.node_layers.join(' → ') : '—'}</span>
        <span>{network.last_modified ? new Date(network.last_modified).toLocaleString() : 'no file yet'}</span>
      </div>
    </div>
  )
}

export function NeuralNetworkStatsPanel({ neuralNetwork }: { neuralNetwork: NeuralNetworkState | undefined }) {
  const totals = neuralNetwork?.totals
  const networks = neuralNetwork?.networks ?? []

  return (
    <Panel title="Network Stats">
      <div className="mb-3 grid grid-cols-2 gap-2.5">
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <small className="text-white/60">Networks Trained</small>
          <div className="text-sm text-white">
            {totals?.trained_count ?? 0} / {totals?.total_networks ?? 0}
          </div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <small className="text-white/60">Total Layers</small>
          <div className="text-sm text-white">{totals?.total_layers ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <small className="text-white/60">Total Nodes</small>
          <div className="text-sm text-white">{totals?.total_nodes ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <small className="text-white/60">Total Edges</small>
          <div className="text-sm text-white">{(totals?.total_edges ?? 0).toLocaleString()}</div>
        </div>
      </div>

      <div className="grid gap-2">
        {networks.map((network) => (
          <NetworkRow key={network.name} network={network} />
        ))}
      </div>

      {neuralNetwork?.excluded && neuralNetwork.excluded.length > 0 ? (
        <div className="mt-3 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
          <strong className="text-xs uppercase tracking-widest text-white/60">Not shown here</strong>
          <div className="mt-1 grid gap-1 text-xs text-white/50">
            {neuralNetwork.excluded.map((entry) => (
              <span key={entry.name}>
                <span className="text-white/70">{entry.name}</span> — {entry.reason}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </Panel>
  )
}
