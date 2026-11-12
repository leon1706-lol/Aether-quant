// V6.6.5: shapes of /api/health, /api/auth/whoami, /api/accounts, /api/readiness and the trade-lock POST
// (monitoring/api_server.py, execution/live_readiness.py).

export interface Health {
  status: string
  demo?: boolean
  auth?: 'off' | 'required' | string
}

export interface WhoAmI {
  auth: 'off' | 'required' | string
  user: string | null
  role: 'viewer' | 'operator' | 'admin' | null | string
  accounts: string[]
}

export interface AccountRow {
  id: string
  broker: string
  environment: string
  mode: string
  capital_usd?: number | null
  secrets: string
  secrets_missing: string[]
  state: string
  reconciliation_breach: boolean | null
  description?: string
}

export interface AccountsResponse {
  demo: boolean
  accounts: AccountRow[]
}

export interface ReadinessMetric {
  key: string
  group: string
  label: string
  value: unknown
  threshold: string
  status: 'pass' | 'fail' | 'unknown'
  evidence: string
  measured_at: string | null
}

export interface ReadinessScorecard {
  ready: boolean
  account: string
  generated_at: string
  counts: { pass: number; fail: number; unknown: number }
  metrics: ReadinessMetric[]
  blocking: string[]
}

export interface TradeLockResult {
  account: string
  locked: boolean | null
  written: string
  audit_hash: string
}
