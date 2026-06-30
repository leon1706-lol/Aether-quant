import type { RuntimeState } from '../types/state'
import { useTopology } from '../api/hooks'
import { TopologyScene3D } from '../components/topology/TopologyScene3D'
import { ClusterList } from '../components/topology/ClusterList'

export function TopologyPage({ state }: { state: RuntimeState | undefined }) {
  const { data: topology } = useTopology()
  const resolvedTopology = topology ?? state?.topology

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.6fr_1fr]">
      <TopologyScene3D topology={resolvedTopology} signals={state?.signals} />
      <ClusterList topology={resolvedTopology} />
    </div>
  )
}
