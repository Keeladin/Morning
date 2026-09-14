import {
  addOfflineMachineState, applyOfflineReportMutation, cacheOfflineData, cacheOfflineSession, clearOfflineDraft, clearOfflineSession,
  getOfflineData, getOfflineSession, isOfflineReportPending, loadOfflineDraft, offlineDraftById, pendingOfflineDrafts,
  saveOfflineDraft, setOfflinePrincipal, demoWhatsappText,
} from './offline'
import type { ReportingModel, ShiftReport } from './types'

let csrfToken: string | null = null
let syncTimer: number | null = null
let demoMode = false

export function setMorningDemoMode(value: boolean) { demoMode = value }
export function setMorningCsrfToken(token: string | null) { csrfToken = token }
export { isOfflineReportPending }

export class MorningApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, message: string, body: unknown) { super(message); this.status = status; this.body = body }
}

async function responseBody(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return null
  try { return JSON.parse(text) } catch { return text }
}
function apiError(response: Response, body: unknown): MorningApiError {
  const message = typeof body === 'object' && body && 'error' in body && typeof (body as { error: unknown }).error === 'string'
    ? (body as { error: string }).error : `HTTP ${response.status}`
  return new MorningApiError(response.status, message, body)
}
function reportingModel(path: string): ReportingModel {
  return new URL(path, window.location.origin).searchParams.get('reporting_model') === 'construction' ? 'construction' : 'tmm'
}
function looksLikeReport(body: unknown): body is ShiftReport {
  return Boolean(body && typeof body === 'object' && 'shift_date' in body && 'reporting_model' in body && 'attendance' in body)
}

function cachedGet<T>(path: string): T | null {
  if (path === '/api/morning/auth/session') {
    const session = getOfflineSession<T>()
    const principal = (session as { principal?: { principal_id?: string; demo_mode?: boolean }; csrf_token?: string } | null)?.principal
    if (principal?.principal_id) { demoMode = Boolean(principal.demo_mode); setOfflinePrincipal(principal.principal_id) }
    const token = (session as { csrf_token?: string } | null)?.csrf_token
    if (token) csrfToken = token
    return session
  }
  if (path === '/api/morning/shift') return getOfflineData<T>('shift')
  if (path === '/api/morning/me') return getOfflineData<T>('me')
  if (path === '/api/morning/machines') return getOfflineData<T>('machines')
  if (path === '/api/morning/personnel') return getOfflineData<T>('tmm-personnel')
  if (path === '/api/morning/crews') return getOfflineData<T>('tmm-crews')
  if (path === '/api/morning/construction/config') return getOfflineData<T>('construction-config')
  if (path === '/api/morning/roster' || path.startsWith('/api/morning/roster?') || path.includes('/participants')) return getOfflineData<T>('roster')
  if (path.startsWith('/api/morning/draft?')) return { report: loadOfflineDraft(reportingModel(path))?.report || null } as T
  const stateMatch = path.match(/^\/api\/morning\/reports\/([^/]+)\/machine-states$/)
  if (stateMatch) return { states: offlineDraftById(stateMatch[1])?.report.machine_states || [] } as T
  const reportMatch = path.match(/^\/api\/morning\/reports\/([^/]+)$/)
  if (reportMatch) return offlineDraftById(reportMatch[1])?.report as T || null
  return null
}

function cacheSuccess(path: string, body: unknown): unknown {
  if (path === '/api/morning/auth/session' || path === '/api/morning/auth/login') {
    const principal = (body as { principal?: { principal_id?: string }; authenticated?: boolean; csrf_token?: string } | null)?.principal
    if (principal?.principal_id) {
      demoMode = Boolean((principal as { demo_mode?: boolean }).demo_mode)
      setOfflinePrincipal(principal.principal_id)
      const token = (body as { csrf_token?: string }).csrf_token; if (token) csrfToken = token
      cacheOfflineSession(path === '/api/morning/auth/login' ? { authenticated: true, principal, csrf_token: token } : body)
    } else if (path === '/api/morning/auth/session' && (body as { authenticated?: boolean } | null)?.authenticated === false) {
      demoMode = false; clearOfflineSession(); setOfflinePrincipal(null)
    }
    return body
  }
  if (path === '/api/morning/auth/logout') { demoMode = false; clearOfflineSession(); setOfflinePrincipal(null); return body }
  if (path === '/api/morning/shift') cacheOfflineData('shift', body)
  else if (path === '/api/morning/me') cacheOfflineData('me', body)
  else if (path === '/api/morning/machines') cacheOfflineData('machines', body)
  else if (path === '/api/morning/personnel') cacheOfflineData('tmm-personnel', body)
  else if (path === '/api/morning/crews') cacheOfflineData('tmm-crews', body)
  else if (path === '/api/morning/construction/config') cacheOfflineData('construction-config', body)
  else if (path === '/api/morning/roster' || path.startsWith('/api/morning/roster?') || path.includes('/participants')) cacheOfflineData('roster', body)
  else if (path.startsWith('/api/morning/draft?')) {
    const model = reportingModel(path)
    const local = loadOfflineDraft(model)
    if (local?.pending) { scheduleOfflineSync(); return { report: local.report } }
    const report = (body as { report?: ShiftReport | null } | null)?.report
    if (report) saveOfflineDraft(report, false, true); else clearOfflineDraft(model)
  } else if (looksLikeReport(body)) saveOfflineDraft(body, false)
  return body
}

async function sendSnapshot(report: ShiftReport): Promise<ShiftReport> {
  const headers = new Headers({ 'Content-Type': 'application/json' })
  if (csrfToken) headers.set('X-CSRF-Token', csrfToken)
  const response = await fetch('/api/morning/offline-sync', {
    method: 'POST', headers, credentials: 'include',
    body: JSON.stringify({ report, submit: Boolean(report.offline_submit_pending) }),
  })
  const body = await responseBody(response)
  if (!response.ok) throw apiError(response, body)
  if (!looksLikeReport(body)) throw new Error('Morning returned an invalid synchronization response.')
  const synced = { ...body, machine_states: report.machine_states || [], offline_submit_pending: undefined }
  saveOfflineDraft(synced, false)
  window.dispatchEvent(new CustomEvent('morning:report-synced', { detail: { report: synced } }))
  return synced
}

async function refreshSessionForSync(): Promise<boolean> {
  try {
    const response = await fetch('/api/morning/auth/session', { credentials: 'include' })
    if (!response.ok) return false
    const body = await responseBody(response) as { authenticated?: boolean; principal?: { principal_id?: string }; csrf_token?: string }
    if (!body?.authenticated || !body.principal?.principal_id) return false
    setOfflinePrincipal(body.principal.principal_id); cacheOfflineSession(body)
    if (body.csrf_token) csrfToken = body.csrf_token
    return true
  } catch { return false }
}

export async function syncOfflineReports(): Promise<void> {
  if (!navigator.onLine || !pendingOfflineDrafts().length) return
  if (!await refreshSessionForSync()) return
  for (const draft of pendingOfflineDrafts()) {
    try { await sendSnapshot(draft.report) } catch (error) {
      const message = error instanceof Error ? error.message : 'Local report is still waiting to synchronize.'
      window.dispatchEvent(new CustomEvent('morning:sync-failed', { detail: { message } }))
    }
  }
}
export function scheduleOfflineSync(): void {
  if (!navigator.onLine || syncTimer !== null) return
  syncTimer = window.setTimeout(() => { syncTimer = null; void syncOfflineReports() }, 1200)
}

function queueBackgroundSnapshot(report: ShiftReport): void {
  // The generated service worker applies Workbox Background Sync to this endpoint.
  // Calling it while offline places the latest complete snapshot in that durable queue.
  void sendSnapshot(report).catch(() => undefined)
}

export async function morningApi<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {})
  if (!headers.has('Content-Type') && init.body) headers.set('Content-Type', 'application/json')
  const method = (init.method || 'GET').toUpperCase()
  if (method !== 'GET' && method !== 'HEAD' && csrfToken) headers.set('X-CSRF-Token', csrfToken)
  const statePost = path.match(/^\/api\/morning\/reports\/([^/]+)\/machine-states$/)
  const offlineState = () => {
    const payload = init.body && typeof init.body === 'string' ? JSON.parse(init.body) as Record<string, unknown> : {}
    const declaration = addOfflineMachineState(statePost![1], payload, !demoMode)
    const draft = offlineDraftById(statePost![1])
    if (!demoMode && draft) queueBackgroundSnapshot(draft.report)
    return declaration as T
  }

  if (statePost && method === 'POST' && (demoMode || !navigator.onLine)) return offlineState()

  if (demoMode && (path === '/api/morning/draft' || path.startsWith('/api/morning/draft?') || path.startsWith('/api/morning/reports/'))) {
    if (method === 'GET' || method === 'HEAD') {
      if (/^\/api\/morning\/reports\/[^/]+\/whatsapp$/.test(path)) {
        const reportId = path.split('/')[4]
        const local = cachedGet<ShiftReport>(`/api/morning/reports/${reportId}`)
        if (!local) throw new Error('No demo report is available.')
        return { text: demoWhatsappText(local) } as T
      }
      const cached = cachedGet<T>(path); if (cached !== null) return cached
    } else {
      return applyOfflineReportMutation(path, init, false) as T
    }
  }

  if (!navigator.onLine) {
    if (method === 'GET' || method === 'HEAD') {
      const cached = cachedGet<T>(path); if (cached !== null) return cached
    } else if (path === '/api/morning/draft' || path.startsWith('/api/morning/reports/')) {
      const local = applyOfflineReportMutation(path, init)
      queueBackgroundSnapshot(local)
      return local as T
    }
  }

  let response: Response
  try { response = await fetch(path, { ...init, headers, credentials: 'include' }) }
  catch (networkError) {
    if (method === 'GET' || method === 'HEAD') {
      const cached = cachedGet<T>(path); if (cached !== null) return cached
    } else if (statePost && method === 'POST') {
      return offlineState()
    } else if (path === '/api/morning/draft' || path.startsWith('/api/morning/reports/')) {
      const local = applyOfflineReportMutation(path, init)
      queueBackgroundSnapshot(local)
      return local as T
    }
    throw networkError
  }

  const body = await responseBody(response)
  if (!response.ok) throw apiError(response, body)
  const result = cacheSuccess(path, body)
  if (looksLikeReport(result) && isOfflineReportPending(result.id)) scheduleOfflineSync()
  return result as T
}
