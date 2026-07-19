// Shape of visualization/grafana/audit_log.json, written by
// audit/postgres_worker.py (development/Problems.md #42) and served as-is
// by monitoring/api_server.py's GET /api/audit-log.
export interface AuditLogEvent {
  event_id: string
  created_at: string
  event_type: 'order_placement' | 'credential_load' | 'live_mode_transition'
  actor: string
  prev_hash: string
  hash: string
  payload: Record<string, unknown>
}

export interface AuditLogStatus {
  generated_at?: string
  total_entries?: number
  chain_valid?: boolean
  chain_broken_at_event_id?: string | null
  recent_events?: AuditLogEvent[]
}
