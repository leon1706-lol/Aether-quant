import type { AssetsStatus, GenerationsState, NeuralNetworkState, RuntimeState, Scene, StrategyCatalog, Topology } from '../types/state'
import type { CsvRow, RuntimeMetricsSnapshot } from '../types/tracing'
import type { AuditLogStatus } from '../types/audit'
import type { EvaluationState } from '../types/evaluation'
import type { AccountsResponse, Health, ReadinessScorecard, TradeLockResult, WhoAmI } from '../types/access'
import { authHeaders } from './session'

// V6.6.5: the status travels with the error so the shell can tell "sign in" (401) from "not written yet" (404).
export class HttpError extends Error {
  readonly status: number

  constructor(path: string, status: number) {
    super(`${path} -> HTTP ${status}`)
    this.status = status
  }
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', headers: authHeaders() })
  if (!response.ok) {
    throw new HttpError(path, response.status)
  }
  return (await response.json()) as T
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new HttpError(path, response.status)
  }
  return (await response.json()) as T
}

const withAccount = (path: string, account: string) => (account && account !== 'default' ? `${path}?account=${encodeURIComponent(account)}` : path)

export const fetchState = (account = 'default') => getJson<RuntimeState>(withAccount('/api/state', account))
export const fetchScene = () => getJson<Scene>('/api/scene')
export const fetchTopology = () => getJson<Topology>('/api/topology')
export const fetchNeuralNetwork = () => getJson<NeuralNetworkState>('/api/neural-network')
// V5.1 Phase 0 - cost-aware rank-book simulation/capacity/stress reports.
export const fetchEvaluation = () => getJson<EvaluationState>('/api/evaluation')
export const fetchAssetsStatus = () => getJson<AssetsStatus>('/api/assets-status')
// V6.6.1 - `aq cycle status`'s view of the model generations.
export const fetchGenerations = () => getJson<GenerationsState>('/api/generations')
// Phase 4.8 - the 43-strategy registry, static (never changes at runtime).
export const fetchStrategyCatalog = () => getJson<StrategyCatalog>('/api/strategies')

// Tracing dashboard (V2-18) - reads the same visualization/grafana/* exports
// that used to be Grafana's only consumer, now rendered natively in the webui.
export const fetchMetricsSnapshot = () => getJson<RuntimeMetricsSnapshot>('/api/grafana/metrics-snapshot')
export const fetchEquityCurves = () => getJson<CsvRow[]>('/api/grafana/equity-curves')
export const fetchAssetPerformance = () => getJson<CsvRow[]>('/api/grafana/asset-performance')
export const fetchObservationEquityCurve = () => getJson<CsvRow[]>('/api/grafana/observation-equity-curve')

// Tamper-evident audit trail (development/Problems.md #42) - order
// placement, credential loads, live-mode transitions.
export const fetchAuditLog = () => getJson<AuditLogStatus>('/api/audit-log')

// V6.6.5: demo/auth flags, the signed-in user, the accounts, the paper-to-live scorecard, and the one write.
export const fetchHealth = () => getJson<Health>('/api/health')
export const fetchWhoAmI = () => getJson<WhoAmI>('/api/auth/whoami')
export const fetchAccounts = () => getJson<AccountsResponse>('/api/accounts')
export const fetchReadiness = () => getJson<ReadinessScorecard>('/api/readiness')
export const postTradeLock = (account: string, locked: boolean | null) =>
  postJson<TradeLockResult>(`/api/accounts/${encodeURIComponent(account)}/trade-lock`, { locked })
