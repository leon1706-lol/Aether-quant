import type { AssetsStatus, NeuralNetworkState, RuntimeState, Scene, Topology } from '../types/state'
import type { CsvRow, RuntimeMetricsSnapshot } from '../types/tracing'
import type { AuditLogStatus } from '../types/audit'

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
export const fetchNeuralNetwork = () => getJson<NeuralNetworkState>('/api/neural-network')
export const fetchAssetsStatus = () => getJson<AssetsStatus>('/api/assets-status')

// Tracing dashboard (V2-18) - reads the same visualization/grafana/* exports
// that used to be Grafana's only consumer, now rendered natively in the webui.
export const fetchMetricsSnapshot = () => getJson<RuntimeMetricsSnapshot>('/api/grafana/metrics-snapshot')
export const fetchEquityCurves = () => getJson<CsvRow[]>('/api/grafana/equity-curves')
export const fetchAssetPerformance = () => getJson<CsvRow[]>('/api/grafana/asset-performance')
export const fetchObservationEquityCurve = () => getJson<CsvRow[]>('/api/grafana/observation-equity-curve')

// Tamper-evident audit trail (development/Problems.md #42) - order
// placement, credential loads, live-mode transitions.
export const fetchAuditLog = () => getJson<AuditLogStatus>('/api/audit-log')
