import type { ScoreCard } from '../../types/state'
import { formatValue } from '../../lib/format'
import { Panel } from '../layout/Panel'

export function Scorecards({ cards }: { cards: ScoreCard[] | undefined }) {
  return (
    <Panel title="Scorecards">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
        {cards && cards.length > 0 ? (
          cards.map((card) => (
            <div key={card.key} className="rounded-2xl border border-white/5 bg-white/[0.03] p-4">
              <span className="mb-2 block text-[0.72rem] uppercase tracking-widest text-white/60">
                {card.label}
              </span>
              <span className="text-2xl font-bold">{formatValue(card.value, card.format)}</span>
            </div>
          ))
        ) : (
          <div className="rounded-2xl border border-white/5 bg-white/[0.03] p-4">
            <span className="mb-2 block text-[0.72rem] uppercase tracking-widest text-white/60">Status</span>
            <span className="text-2xl font-bold">No data</span>
          </div>
        )}
      </div>
    </Panel>
  )
}
