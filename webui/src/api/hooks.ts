import { useQuery } from '@tanstack/react-query'
import {
  fetchAssetPerformance,
  fetchAssetsStatus,
  fetchAuditLog,
  fetchEquityCurves,
  fetchEvaluation,
  fetchMetricsSnapshot,
  fetchNeuralNetwork,
  fetchObservationEquityCurve,
  fetchScene,
  fetchState,
  fetchStrategyCatalog,
  fetchTopology,
} from './client'

const REFRESH_MS = 5000
const TRACING_REFRESH_MS = 15000

export function useRuntimeState() {
  return useQuery({
    queryKey: ['state'],
    queryFn: fetchState,
    refetchInterval: REFRESH_MS,
  })
}

export function useScene() {
  return useQuery({
    queryKey: ['scene'],
    queryFn: fetchScene,
    refetchInterval: REFRESH_MS,
  })
}

export function useTopology() {
  return useQuery({
    queryKey: ['topology'],
    queryFn: fetchTopology,
    refetchInterval: REFRESH_MS,
  })
}

export function useNeuralNetwork() {
  return useQuery({
    queryKey: ['neural-network'],
    queryFn: fetchNeuralNetwork,
    refetchInterval: REFRESH_MS,
  })
}

export function useAssetsStatus() {
  return useQuery({
    queryKey: ['assets-status'],
    queryFn: fetchAssetsStatus,
    refetchInterval: TRACING_REFRESH_MS,
  })
}

// V5.1 Phase 0 - refreshed no faster than TRACING_REFRESH_MS: unlike
// state/scene/topology/neural-network (which change every bar), evaluation
// reports only change when someone runs `aq evaluate` - a 5s poll would
// just be wasted requests against an unchanged file.
export function useEvaluation() {
  return useQuery({
    queryKey: ['evaluation'],
    queryFn: fetchEvaluation,
    refetchInterval: TRACING_REFRESH_MS,
  })
}

// Phase 4.8 - the 43-strategy registry is a static, in-memory Python dict
// that never changes at runtime (no config/state dependency at all,
// unlike every other hook here) - staleTime: Infinity means React Query
// treats the first successful fetch as always-fresh and never refetches
// on its own; refetchInterval is omitted entirely for the same reason.
export function useStrategyCatalog() {
  return useQuery({
    queryKey: ['strategy-catalog'],
    queryFn: fetchStrategyCatalog,
    staleTime: Infinity,
  })
}

export function useMetricsSnapshot() {
  return useQuery({
    queryKey: ['tracing', 'metrics-snapshot'],
    queryFn: fetchMetricsSnapshot,
    refetchInterval: TRACING_REFRESH_MS,
  })
}

export function useEquityCurves() {
  return useQuery({
    queryKey: ['tracing', 'equity-curves'],
    queryFn: fetchEquityCurves,
    refetchInterval: TRACING_REFRESH_MS,
  })
}

export function useAuditLog() {
  return useQuery({
    queryKey: ['audit-log'],
    queryFn: fetchAuditLog,
    refetchInterval: TRACING_REFRESH_MS,
  })
}

export function useAssetPerformance() {
  return useQuery({
    queryKey: ['tracing', 'asset-performance'],
    queryFn: fetchAssetPerformance,
    refetchInterval: TRACING_REFRESH_MS,
  })
}

export function useObservationEquityCurve() {
  return useQuery({
    queryKey: ['tracing', 'observation-equity-curve'],
    queryFn: fetchObservationEquityCurve,
    refetchInterval: TRACING_REFRESH_MS,
  })
}
