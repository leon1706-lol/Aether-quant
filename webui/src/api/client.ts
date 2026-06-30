import type { RuntimeState, Scene, Topology } from '../types/state'

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store' })
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

export const fetchState = () => getJson<RuntimeState>('/api/state')
export const fetchScene = () => getJson<Scene>('/api/scene')
export const fetchTopology = () => getJson<Topology>('/api/topology')
