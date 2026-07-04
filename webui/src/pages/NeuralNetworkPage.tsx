import type { RuntimeState } from '../types/state'
import { useNeuralNetwork } from '../api/hooks'
import { NeuralNetworkScene3D } from '../components/neuralnet/NeuralNetworkScene3D'
import { NeuralNetworkStatsPanel } from '../components/neuralnet/NeuralNetworkStatsPanel'

export function NeuralNetworkPage(_props: { state: RuntimeState | undefined }) {
  const { data: neuralNetwork } = useNeuralNetwork()

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.6fr_1fr]">
      <NeuralNetworkScene3D neuralNetwork={neuralNetwork} />
      <NeuralNetworkStatsPanel neuralNetwork={neuralNetwork} />
    </div>
  )
}
