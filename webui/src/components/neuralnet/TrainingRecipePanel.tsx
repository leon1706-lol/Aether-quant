import type { NeuralNetworkState } from '../../types/state'
import { Panel } from '../layout/Panel'
import { Badge } from '../signals/Badge'

// V5.1 Phase 3 (items 1, 10, 11) - makes "which model am I actually
// looking at" answerable from the UI, which it currently isn't: the
// optimizer/schedule/batch-mode/ranking-loss/SWA recipe a candidate
// trained with only lived in *_training_metrics.json before this panel,
// invisible without reading the raw file.
function RecipeRow({ network }: { network: NeuralNetworkState['networks'][number] }) {
  const recipe = network.training_recipe
  if (!recipe) return null

  return (
    <div className="rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-white">{network.label}</span>
        <Badge tone={recipe.batch_mode === 'cross_sectional' ? 'stable' : undefined}>
          {recipe.ranking_loss?.objective ?? 'mse'}
        </Badge>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[0.7rem] text-white/60 sm:grid-cols-3">
        <span>
          optimizer: <span className="text-white/80">{recipe.optimizer}</span>
        </span>
        <span>
          lr schedule: <span className="text-white/80">{recipe.lr_schedule}</span>
        </span>
        <span>
          batch mode: <span className="text-white/80">{recipe.batch_mode}</span>
        </span>
        {recipe.normalization ? (
          <span>
            trunk norm: <span className="text-white/80">{recipe.normalization}</span>
          </span>
        ) : null}
        <span>
          SWA: <span className="text-white/80">{recipe.swa.enabled ? `${recipe.swa.epochs_averaged} epochs` : 'off'}</span>
        </span>
        <span>
          early stop: <span className="text-white/80">{recipe.early_stop_metric}</span> (
          <span className="text-white/80">{recipe.early_stop_head}</span>, smoothed{' '}
          <span className="text-white/80">{recipe.early_stop_smoothing_epochs}</span>)
        </span>
      </div>
    </div>
  )
}

export function TrainingRecipePanel({ neuralNetwork }: { neuralNetwork: NeuralNetworkState | undefined }) {
  const networks = (neuralNetwork?.networks ?? []).filter((network) => network.training_recipe != null)

  return (
    <Panel title="Training Recipe">
      {networks.length === 0 ? (
        <div className="p-6 text-center text-sm text-white/60">
          No training recipe recorded yet — needs a multitask/sequence candidate trained since V5.1 Phase 3.
        </div>
      ) : (
        <div className="grid gap-2">
          {networks.map((network) => (
            <RecipeRow key={network.name} network={network} />
          ))}
        </div>
      )}
    </Panel>
  )
}
