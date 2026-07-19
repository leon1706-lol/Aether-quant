import { useQuery } from '@tanstack/react-query'
import {
  fetchAssetPerformance,
  fetchAssetsStatus,
  fetchAuditLog,
  fetchEquityCurves,
  fetchMetricsSnapshot,
  fetchNeuralNetwork,
  fetchObservationEquityCurve,
  fetchScene,
  fetchState,
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
