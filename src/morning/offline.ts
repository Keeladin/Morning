import type {
  AttendanceEntry, CardObservation, ConstructionWorkItem, OtherActivity, ReportingModel,
  ShiftKind, ShiftReport, StopFixRecord, SupervisorContext,
} from './types'

const ROOT = 'morning.offline.v1'
const LAST_PRINCIPAL = `${ROOT}.last-principal`
const SESSION = `${ROOT}.session`

export type OfflineDraft = { report: ShiftReport; pending: boolean }

function localId(prefix: string): string {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}_${Math.random().toString(16).slice(2)}`
  return `offline_${prefix}_${suffix}`
}

function readJson<T>(key: string): T | null {
  try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) as T : null } catch { return null }
}
function writeJson(key: string, value: unknown): void {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* storage unavailable/full */ }
}

export function setOfflinePrincipal(principalId: string | null): void {
  try {
    if (principalId) localStorage.setItem(LAST_PRINCIPAL, principalId)
    else localStorage.removeItem(LAST_PRINCIPAL)
  } catch { /* ignore */ }
}
export function getOfflinePrincipal(): string | null {
  try { return localStorage.getItem(LAST_PRINCIPAL) } catch { return null }
}
export function cacheOfflineSession(value: unknown): void { writeJson(SESSION, value) }
export function getOfflineSession<T>(): T | null { return readJson<T>(SESSION) }
export function clearOfflineSession(): void { try { localStorage.removeItem(SESSION) } catch { /* ignore */ } }

function scopedKey(name: string): string | null {
  const principal = getOfflinePrincipal()
  return principal ? `${ROOT}.${principal}.${name}` : null
}
export function cacheOfflineData(name: string, value: unknown): void {
  const key = scopedKey(name); if (key) writeJson(key, value)
}
export function getOfflineData<T>(name: string): T | null {
  const key = scopedKey(name); return key ? readJson<T>(key) : null
}

export function loadOfflineDraft(model: ReportingModel): OfflineDraft | null {
  return getOfflineData<OfflineDraft>(`draft.${model}`)
}
export function saveOfflineDraft(report: ShiftReport, pending: boolean): ShiftReport {
  cacheOfflineData(`draft.${report.reporting_model}`, { report, pending } satisfies OfflineDraft)
  return report
}
export function clearOfflineDraft(model: ReportingModel): void {
  const key = scopedKey(`draft.${model}`); if (key) try { localStorage.removeItem(key) } catch { /* ignore */ }
}
export function offlineDraftById(reportId: string): OfflineDraft | null {
  for (const model of ['tmm', 'construction'] as ReportingModel[]) {
    const draft = loadOfflineDraft(model)
    if (draft?.report.id === reportId) return draft
  }
  return null
}
export function pendingOfflineDrafts(): OfflineDraft[] {
  return (['tmm', 'construction'] as ReportingModel[])
    .map(loadOfflineDraft).filter((item): item is OfflineDraft => Boolean(item?.pending))
}
export function isOfflineReportPending(reportId: string): boolean { return Boolean(offlineDraftById(reportId)?.pending) }

function emptyReport(
  supervisor: SupervisorContext, shiftDate: string, shiftKind: ShiftKind, reportingModel: ReportingModel, crewIds: string[],
): ShiftReport {
  const now = new Date().toISOString()
  return {
    id: localId('report'), shift_date: shiftDate, shift_kind: shiftKind, shift_id: `${shiftDate}:${shiftKind}`,
    supervisor_principal_id: supervisor.principal_id, crew_id: crewIds[0] || supervisor.crew_id, crew_ids: crewIds, reporting_model: reportingModel,
    status: 'draft', attendance: [], stop_fix: [], cards: [], machine_events: [], construction_work: [], other_activities: [], brothers_keeper: null,
    created_at: now, updated_at: now, submitted_at: null, safety_reviewed_empty: false,
    machine_activity_reviewed_empty: false, other_activities_reviewed_empty: false,
    construction_work_reviewed_empty: false, construction_outstanding_reviewed_empty: false,
  }
}

export function createOfflineReport(body: Record<string, unknown>): ShiftReport {
  const supervisor = getOfflineData<SupervisorContext>('me')
  if (!supervisor) throw new Error('No cached supervisor profile is available. Connect once before starting a report offline.')
  const shiftDate = String(body.shift_date || '')
  const shiftKind = String(body.shift_kind || '') as ShiftKind
  const reportingModel = String(body.reporting_model || 'tmm') as ReportingModel
  const crewIds = Array.isArray(body.crew_ids) ? body.crew_ids.map(String).filter(Boolean) : []
  if (reportingModel === 'tmm' && !crewIds.length) throw new Error('Select at least one crew before starting the report.')
  if (reportingModel === 'construction' && !supervisor.crew_id) throw new Error('No cached Construction crew is available.')
  const selectedCrewIds = reportingModel === 'construction' ? [supervisor.crew_id!] : crewIds
  if (!/^\d{4}-\d{2}-\d{2}$/.test(shiftDate) || !['morning', 'afternoon', 'night'].includes(shiftKind)) {
    throw new Error('No cached shift is available. Connect once before starting a report offline.')
  }
  return saveOfflineDraft(emptyReport(supervisor, shiftDate, shiftKind, reportingModel, selectedCrewIds), true)
}

function touch(report: ShiftReport): ShiftReport { return { ...report, updated_at: new Date().toISOString() } }
function jsonBody(body: BodyInit | null | undefined): Record<string, any> {
  if (!body || typeof body !== 'string') return {}
  try { return JSON.parse(body) as Record<string, any> } catch { return {} }
}

export function applyOfflineReportMutation(path: string, init: RequestInit, pending = true): ShiftReport {
  const method = (init.method || 'GET').toUpperCase()
  const payload = jsonBody(init.body)
  if (path === '/api/morning/draft' && method === 'POST') {
    const report = createOfflineReport(payload)
    return pending ? report : saveOfflineDraft(report, false)
  }

  const match = path.match(/^\/api\/morning\/reports\/([^/]+)(\/.*)?$/)
  if (!match) throw new Error('This action requires a connection.')
  const state = offlineDraftById(decodeURIComponent(match[1]))
  if (!state) throw new Error('No local copy of this report is available.')
  let report = state.report
  const suffix = match[2] || ''

  if (suffix === '/attendance' && method === 'POST') {
    report = { ...report, attendance: (payload.entries || []) as AttendanceEntry[] }
  } else if (suffix === '/brothers-keeper' && method === 'PUT') {
    const contribution = String(payload.contribution || '').trim()
    if (!contribution) throw new Error('Brothers Keeper contribution is required.')
    report = { ...report, brothers_keeper: contribution }
  } else if (suffix === '/stop-fix' && method === 'POST') {
    const item: StopFixRecord = {
      id: localId('stopfix'), number: String(payload.number || ''), issued_at: new Date().toISOString(),
      area_of_concern: String(payload.area_of_concern || ''), location: String(payload.location || ''),
      reason: String(payload.reason || ''), instruction: String(payload.instruction || ''), status: 'open', rectified_at: null,
    }
    report = { ...report, stop_fix: [...report.stop_fix, item], safety_reviewed_empty: false }
  } else if (/^\/stop-fix\/[^/]+$/.test(suffix) && method === 'PATCH') {
    const id = suffix.split('/').at(-1)!
    report = { ...report, stop_fix: report.stop_fix.map(item => item.id === id ? {
      ...item, ...payload, rectified_at: payload.status === 'rectified' ? new Date().toISOString() : payload.status === 'open' ? null : item.rectified_at,
    } : item) }
  } else if (/^\/stop-fix\/[^/]+$/.test(suffix) && method === 'DELETE') {
    const id = suffix.split('/').at(-1)!; report = { ...report, stop_fix: report.stop_fix.filter(item => item.id !== id) }
  } else if (suffix === '/cards' && method === 'POST') {
    const item: CardObservation = { id: localId('card'), card_type: payload.card_type, reason: String(payload.reason || '') }
    report = { ...report, cards: [...report.cards, item], safety_reviewed_empty: false }
  } else if (/^\/cards\/[^/]+$/.test(suffix) && method === 'DELETE') {
    const id = suffix.split('/').at(-1)!; report = { ...report, cards: report.cards.filter(item => item.id !== id) }
  } else if (suffix === '/machine-events' && method === 'POST') {
    report = { ...report, machine_events: [...report.machine_events, {
      id: localId('event'), machine_id: String(payload.machine_id || ''), start_time: String(payload.start_hhmm || ''),
      end_time: String(payload.end_hhmm || ''), issue: String(payload.issue || ''), person_id: payload.person_id || null,
    }], machine_activity_reviewed_empty: false }
  } else if (/^\/machine-events\/[^/]+$/.test(suffix) && method === 'PATCH') {
    const id = suffix.split('/').at(-1)!
    report = { ...report, machine_events: report.machine_events.map(item => item.id === id ? {
      ...item, ...(payload.machine_id !== undefined ? { machine_id: payload.machine_id } : {}),
      ...(payload.start_hhmm !== undefined ? { start_time: payload.start_hhmm } : {}),
      ...(payload.end_hhmm !== undefined ? { end_time: payload.end_hhmm } : {}),
      ...(payload.issue !== undefined ? { issue: payload.issue } : {}),
      ...(payload.person_id !== undefined ? { person_id: payload.person_id || null } : {}),
    } : item) }
  } else if (/^\/machine-events\/[^/]+$/.test(suffix) && method === 'DELETE') {
    const id = suffix.split('/').at(-1)!; report = { ...report, machine_events: report.machine_events.filter(item => item.id !== id) }
  } else if (suffix === '/construction-work' && method === 'POST') {
    const item: ConstructionWorkItem = {
      id: localId('construction'), kind: payload.kind, level: String(payload.level || '').replace(/\s/g, '').toUpperCase(),
      location: String(payload.location || ''), task: String(payload.task || ''), status: payload.status,
      progress_percent: payload.progress_percent ?? null, update_text: String(payload.update_text || ''),
      constraint_text: payload.constraint_text || null, next_action: payload.next_action || null,
    }
    report = { ...report, construction_work: [...report.construction_work, item],
      ...(item.kind === 'core' ? { construction_work_reviewed_empty: false } : { construction_outstanding_reviewed_empty: false }) }
  } else if (/^\/construction-work\/[^/]+$/.test(suffix) && method === 'PATCH') {
    const id = suffix.split('/').at(-1)!
    report = { ...report, construction_work: report.construction_work.map(item => item.id === id ? { ...item, ...payload } : item) }
  } else if (/^\/construction-work\/[^/]+$/.test(suffix) && method === 'DELETE') {
    const id = suffix.split('/').at(-1)!; report = { ...report, construction_work: report.construction_work.filter(item => item.id !== id) }
  } else if (suffix === '/other-activities' && method === 'POST') {
    const item: OtherActivity = { id: localId('activity'), category: payload.category || null, description: String(payload.description || '') }
    report = { ...report, other_activities: [...report.other_activities, item], other_activities_reviewed_empty: false }
  } else if (/^\/other-activities\/[^/]+$/.test(suffix) && method === 'DELETE') {
    const id = suffix.split('/').at(-1)!; report = { ...report, other_activities: report.other_activities.filter(item => item.id !== id) }
  } else if (suffix === '/section-resolution' && method === 'PATCH') {
    const field = ({ safety: 'safety_reviewed_empty', machine_activity: 'machine_activity_reviewed_empty',
      other_activities: 'other_activities_reviewed_empty', construction_work: 'construction_work_reviewed_empty',
      construction_outstanding: 'construction_outstanding_reviewed_empty' } as const)[payload.section as string]
    if (!field) throw new Error('Unknown report section.')
    report = { ...report, [field]: Boolean(payload.reviewed) }
  } else if (suffix === '/submit' && method === 'POST') {
    report = pending
      ? { ...report, offline_submit_pending: true }
      : { ...report, status: 'submitted', submitted_at: new Date().toISOString(), offline_submit_pending: undefined }
  } else if (suffix === '/abandon' && method === 'POST') {
    report = { ...report, status: 'abandoned' }
  } else {
    throw new Error('This action requires a connection.')
  }
  return saveOfflineDraft(touch(report), pending)
}

export function demoWhatsappText(report: ShiftReport): string {
  const people = getOfflineData<{ people: { id: string; name: string }[] }>('tmm-personnel')?.people || []
  const machines = getOfflineData<{ machines: { id: string; machine_id: string }[] }>('machines')?.machines || []
  const personName = (id: string | null) => people.find(item => item.id === id)?.name || id || 'Unassigned'
  const machineName = (id: string) => machines.find(item => item.id === id)?.machine_id || id
  const lines = [`*DEMO — ${report.shift_kind.toUpperCase()} SHIFT — ${report.shift_date}*`, `Attendance: ${report.attendance.filter(item => item.present).length} present / ${report.attendance.filter(item => !item.present).length} absent`]
  if (report.brothers_keeper) lines.push(`Brothers Keeper: ${report.brothers_keeper}`)
  if (report.machine_events.length) {
    lines.push('', '*Machine Activity*')
    for (const item of report.machine_events) lines.push(`${machineName(item.machine_id)} · ${item.start_time}–${item.end_time} · ${item.issue} · ${personName(item.person_id)}`)
  }
  if (report.other_activities.length) {
    lines.push('', '*Other Activities*')
    for (const item of report.other_activities) lines.push(`• ${item.description}`)
  }
  lines.push('', '_Demo Mode — this report was not saved to Morning._')
  return lines.join('\n')
}
