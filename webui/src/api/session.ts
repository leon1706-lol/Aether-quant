// V6.6.5 (#349, #350): the bearer token and the selected account, per browser tab. sessionStorage can be missing or
// throw (private windows, blocked storage), so every access is guarded and the app works without it.

const TOKEN_KEY = 'aq.token'
const ACCOUNT_KEY = 'aq.account'

function read(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null || value === '') window.sessionStorage.removeItem(key)
    else window.sessionStorage.setItem(key, value)
  } catch {
    // storage blocked: the value lives only until the next reload
  }
}

export const getToken = (): string | null => read(TOKEN_KEY)
export const setToken = (token: string | null): void => write(TOKEN_KEY, token)
export const getAccount = (): string => read(ACCOUNT_KEY) ?? 'default'
export const setAccount = (account: string): void => write(ACCOUNT_KEY, account === 'default' ? null : account)

export function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}
