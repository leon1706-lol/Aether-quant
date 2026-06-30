import { useQuery } from '@tanstack/react-query'
import { fetchScene, fetchState, fetchTopology } from './client'

const REFRESH_MS = 5000

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
