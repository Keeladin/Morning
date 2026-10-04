import { afterEach, describe, expect, it, vi } from 'vitest'
import { morningApi, syncOfflineReports, submitWithReceipt, resumeOfflineSync } from '../../src/morning/api'
import { cacheOfflineData, loadOfflineDraft, offlineDraftById, pendingOfflineDrafts, saveOfflineDraft, setOfflinePrincipal } from '../../src/morning/offline'
import type { MachineStateDeclaration, ShiftReport, SupervisorContext } from '../../src/morning/types'

afterEach(() => {
  localStorage.clear()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function makeOffline() {
  vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false)
  vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline') }))
}

describe('offline shift capture', () => {
  it('creates and persists a complete local TMM draft without network', async () => {
    makeOffline()
    setOfflinePrincipal('principal-lyle')
    cacheOfflineData('me', {
      principal_id: 'principal-lyle', display_name: 'Lyle', role: 'supervisor', crew_id: 'crew-1', crew_name: 'Crew 1',
    } satisfies SupervisorContext)
    const started = await morningApi<ShiftReport>('/api/morning/draft', {
      method: 'POST',
      body: JSON.stringify({ shift_date: '2026-09-02', shift_kind: 'morning', reporting_model: 'tmm', crew_ids: ['crew-1'] }),
    })
    expect(started.id).toMatch(/^offline_report_/)

    const attendance = await morningApi<ShiftReport>(`/api/morning/reports/${started.id}/attendance`, {
      method: 'POST', body: JSON.stringify({ entries: [{ person_id: 'person-1', present: true }] }),
    })
    expect(attendance.attendance).toEqual([{ person_id: 'person-1', present: true }])

    const brothers = await morningApi<ShiftReport>(`/api/morning/reports/${started.id}/brothers-keeper`, {
      method: 'PUT', body: JSON.stringify({ contribution: 'Improve lighting at the workshop entrance.' }),
    })
    expect(brothers.brothers_keeper).toBe('Improve lighting at the workshop entrance.')

    const event = await morningApi<ShiftReport>(`/api/morning/reports/${started.id}/machine-events`, {
      method: 'POST', body: JSON.stringify({
        machine_id: 'machine-1', person_id: 'person-1', start_hhmm: '08:10', end_hhmm: '08:35', issue: 'Hose repair',
      }),
    })
    expect(event.machine_events[0].start_time).toBe('08:10')
    const state = await morningApi<MachineStateDeclaration>(`/api/morning/reports/${started.id}/machine-states`, {
      method: 'POST', body: JSON.stringify({ machine_id: 'machine-1', declared_hhmm: '08:35', state: 'not_tested' }),
    })
    expect(state.state).toBe('not_tested')
    expect(state.declared_at).toBe('08:35')
    await morningApi<ShiftReport>(`/api/morning/reports/${started.id}/section-resolution`, {
      method: 'PATCH', body: JSON.stringify({ section: 'safety', reviewed: true }),
    })
    await morningApi<ShiftReport>(`/api/morning/reports/${started.id}/section-resolution`, {
      method: 'PATCH', body: JSON.stringify({ section: 'other_activities', reviewed: true }),
    })
    const queued = await morningApi<ShiftReport>(`/api/morning/reports/${started.id}/submit`, { method: 'POST', body: '{}' })
    expect(queued.offline_submit_pending).toBe(true)

    const restored = await morningApi<{ report: ShiftReport | null }>('/api/morning/draft?reporting_model=tmm')
    expect(restored.report?.id).toBe(started.id)
    expect(restored.report?.machine_events).toHaveLength(1)
    expect(restored.report?.machine_states).toHaveLength(1)
    expect(restored.report?.offline_submit_pending).toBe(true)
  })

  it('keeps multiple unsynced reports instead of overwriting by reporting model', async () => {
    makeOffline()
    setOfflinePrincipal('principal-lyle')
    cacheOfflineData('me', {
      principal_id: 'principal-lyle', display_name: 'Lyle', role: 'supervisor', crew_id: 'crew-1', crew_name: 'Crew 1',
    } satisfies SupervisorContext)
    const first = await morningApi<ShiftReport>('/api/morning/draft', {
      method: 'POST',
      body: JSON.stringify({ shift_date: '2026-09-02', shift_kind: 'morning', reporting_model: 'tmm', crew_ids: ['crew-1'] }),
    })
    const second = await morningApi<ShiftReport>('/api/morning/draft', {
      method: 'POST',
      body: JSON.stringify({ shift_date: '2026-09-02', shift_kind: 'afternoon', reporting_model: 'tmm', crew_ids: ['crew-1'] }),
    })
    expect(second.id).not.toBe(first.id)
    expect(new Set(pendingOfflineDrafts().map(item => item.report.id))).toEqual(new Set([first.id, second.id]))
    const current = await morningApi<{ report: ShiftReport | null }>('/api/morning/draft?reporting_model=tmm')
    expect(current.report?.id).toBe(second.id)
  })


  it('keeps an online-started report current when the connection drops before submit', async () => {
    let online = true
    vi.spyOn(window.navigator, 'onLine', 'get').mockImplementation(() => online)
    setOfflinePrincipal('principal-lyle')
    const serverDraft: ShiftReport = {
      id: 'report-server-1', shift_date: '2026-09-21', shift_kind: 'morning', shift_id: '2026-09-21:morning',
      supervisor_principal_id: 'principal-lyle', crew_id: 'crew-1', crew_ids: ['crew-1'], reporting_model: 'tmm',
      status: 'draft', attendance: [{ person_id: 'person-1', present: true }], stop_fix: [], cards: [], machine_events: [],
      machine_states: [], construction_work: [], other_activities: [], brothers_keeper: 'Keep access routes clear.',
      created_at: '2026-09-21T04:00:00Z', updated_at: '2026-09-21T04:30:00Z', submitted_at: null,
      safety_reviewed_empty: true, machine_activity_reviewed_empty: true, other_activities_reviewed_empty: true,
      construction_work_reviewed_empty: false, construction_outstanding_reviewed_empty: false,
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = typeof input === 'string' ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname
      if (path === '/api/morning/draft') {
        return new Response(JSON.stringify(serverDraft), { status: 201, headers: { 'Content-Type': 'application/json' } })
      }
      throw new TypeError('offline')
    }))

    const started = await morningApi<ShiftReport>('/api/morning/draft', {
      method: 'POST',
      body: JSON.stringify({ shift_date: serverDraft.shift_date, shift_kind: serverDraft.shift_kind, reporting_model: 'tmm', crew_ids: ['crew-1'] }),
    })
    expect(started.id).toBe(serverDraft.id)

    online = false
    const queued = await morningApi<ShiftReport>(`/api/morning/reports/${started.id}/submit`, { method: 'POST', body: '{}' })
    expect(queued.offline_submit_pending).toBe(true)

    const restored = await morningApi<{ report: ShiftReport | null }>('/api/morning/draft?reporting_model=tmm')
    expect(restored.report?.id).toBe(serverDraft.id)
    expect(restored.report?.attendance).toEqual(serverDraft.attendance)
    expect(restored.report?.offline_submit_pending).toBe(true)
  })

  it('recovers an orphaned active draft created by an older build', async () => {
    makeOffline()
    setOfflinePrincipal('principal-lyle')
    const orphan: ShiftReport = {
      id: 'report-orphaned', shift_date: '2026-09-21', shift_kind: 'night', shift_id: '2026-09-21:night',
      supervisor_principal_id: 'principal-lyle', crew_id: 'crew-1', crew_ids: ['crew-1'], reporting_model: 'tmm',
      status: 'draft', attendance: [{ person_id: 'person-1', present: true }], stop_fix: [], cards: [], machine_events: [],
      machine_states: [], construction_work: [], other_activities: [], brothers_keeper: 'Check stored energy before work.',
      created_at: '2026-09-20T20:00:00Z', updated_at: '2026-09-20T21:45:00Z', submitted_at: null,
      safety_reviewed_empty: true, machine_activity_reviewed_empty: true, other_activities_reviewed_empty: true,
      construction_work_reviewed_empty: false, construction_outstanding_reviewed_empty: false,
      offline_submit_pending: true,
    }
    localStorage.setItem(
      'morning.offline.v1.principal-lyle.draft.id.report-orphaned',
      JSON.stringify({ report: orphan, pending: true }),
    )

    const restored = await morningApi<{ report: ShiftReport | null }>('/api/morning/draft?reporting_model=tmm')
    expect(restored.report?.id).toBe(orphan.id)
    expect(restored.report?.offline_submit_pending).toBe(true)
    expect(localStorage.getItem('morning.offline.v1.principal-lyle.draft.current.tmm')).toContain(orphan.id)
  })


  it('replaces an offline temporary report id after the server has already submitted the shift', async () => {
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(true)
    setOfflinePrincipal('principal-jurie')
    const local: ShiftReport = {
      id: 'offline_report_stale', shift_date: '2026-10-01', shift_kind: 'night', shift_id: '2026-10-01:night',
      supervisor_principal_id: 'principal-jurie', crew_id: 'crew-1', crew_ids: ['crew-1'], reporting_model: 'tmm',
      status: 'draft', attendance: [{ person_id: 'person-1', present: true }], stop_fix: [], cards: [], machine_events: [],
      machine_states: [], construction_work: [], other_activities: [], brothers_keeper: 'Local copy',
      created_at: '2026-10-01T02:00:00Z', updated_at: '2026-10-01T03:30:00Z', submitted_at: null,
      safety_reviewed_empty: true, machine_activity_reviewed_empty: true, other_activities_reviewed_empty: true,
      construction_work_reviewed_empty: false, construction_outstanding_reviewed_empty: false, offline_submit_pending: true,
    }
    const submitted: ShiftReport = {
      ...local, id: 'shiftreport_server', status: 'submitted', brothers_keeper: 'Server copy',
      updated_at: '2026-10-01T03:01:16Z', submitted_at: '2026-10-01T03:01:16Z', offline_submit_pending: undefined,
    }
    saveOfflineDraft(local, true, true)
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = typeof input === 'string' ? input : input instanceof URL ? input.pathname : new URL(input.url).pathname
      if (path === '/api/morning/auth/session') {
        return new Response(JSON.stringify({
          authenticated: true, principal: { principal_id: 'principal-jurie' }, csrf_token: 'csrf',
        }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      if (path === '/api/morning/offline-sync') {
        return new Response(JSON.stringify(submitted), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      throw new Error('unexpected request: ' + path)
    }))

    await syncOfflineReports()

    expect(offlineDraftById(local.id)).toBeNull()
    expect(pendingOfflineDrafts()).toHaveLength(0)
    expect(loadOfflineDraft('tmm')).toBeNull()
  })

})


function receiptDraft(id: string): ShiftReport {
  return {
    id, shift_date: '2026-10-02', shift_kind: 'morning', shift_id: '2026-10-02:morning',
    supervisor_principal_id: 'receipt-owner', crew_id: 'crew-1', crew_ids: ['crew-1'], reporting_model: 'tmm',
    status: 'draft', attendance: [], stop_fix: [], cards: [], machine_events: [], construction_work: [], other_activities: [],
    brothers_keeper: 'Safety', created_at: '2026-10-02T10:00:00Z', updated_at: '2026-10-02T12:00:00Z', submitted_at: null,
    safety_reviewed_empty: true, machine_activity_reviewed_empty: true, other_activities_reviewed_empty: true,
    construction_work_reviewed_empty: false, construction_outstanding_reviewed_empty: false, revision: 0,
  }
}
function sessionReply() { return new Response(JSON.stringify({ authenticated: true, principal: { principal_id: 'receipt-owner' }, csrf_token: 'fresh-token' })) }

describe('confirmed submission queue', () => {
  it('keeps a submission pending when the server only returns a draft', async () => {
    vi.useFakeTimers(); setOfflinePrincipal('receipt-owner')
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(true)
    const draft = receiptDraft('draft-ack')
    vi.stubGlobal('fetch', vi.fn(async (path: string) => path.includes('auth/session') ? sessionReply() : new Response(JSON.stringify(draft))))
    const result = await submitWithReceipt(draft)
    expect(result.status).toBe('draft')
    expect(result.offline_submit_pending).toBe(true)
    expect(pendingOfflineDrafts()).toHaveLength(1)
  })

  it('retries a server failure automatically and accepts a confirmed receipt', async () => {
    vi.useFakeTimers(); resumeOfflineSync(); await syncOfflineReports(); setOfflinePrincipal('receipt-owner')
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(true)
    const draft = receiptDraft('automatic-retry')
    let attempts = 0
    vi.stubGlobal('fetch', vi.fn(async (path: string) => {
      if (path.includes('auth/session')) return sessionReply()
      attempts++
      return attempts === 1 ? new Response(JSON.stringify({ error: 'temporary outage' }), { status: 503 })
        : new Response(JSON.stringify({ ...draft, status: 'submitted', submitted_at: '2026-10-04T06:44:54Z' }))
    }))
    expect((await submitWithReceipt(draft)).offline_submit_pending).toBe(true)
    await vi.advanceTimersByTimeAsync(1500)
    expect(attempts).toBe(2)
    expect(pendingOfflineDrafts()).toHaveLength(0)
    expect(offlineDraftById(draft.id)?.report.submitted_at).toBe('2026-10-04T06:44:54Z')
  })

  it('survives a lost response and reconciles a temporary id on retry', async () => {
    vi.useFakeTimers(); resumeOfflineSync(); await syncOfflineReports(); setOfflinePrincipal('receipt-owner')
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(true)
    const draft = receiptDraft('offline_report_lost-response')
    let attempts = 0
    vi.stubGlobal('fetch', vi.fn(async (path: string) => {
      if (path.includes('auth/session')) return sessionReply()
      attempts++
      if (attempts === 1) throw new TypeError('reply lost after server saved')
      return new Response(JSON.stringify({ ...draft, id: 'canonical-id', status: 'submitted', submitted_at: '2026-10-04T06:44:54Z' }))
    }))
    await submitWithReceipt(draft)
    await vi.advanceTimersByTimeAsync(1500)
    expect(offlineDraftById(draft.id)).toBeNull()
    expect(offlineDraftById('canonical-id')?.report.status).toBe('submitted')
    expect(pendingOfflineDrafts()).toHaveLength(0)
  })

  it('does not send another owner’s report after the session changes', async () => {
    vi.useFakeTimers(); resumeOfflineSync(); await syncOfflineReports(); setOfflinePrincipal('receipt-owner')
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(true)
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ authenticated: true, principal: { principal_id: 'different-owner' } })))
    vi.stubGlobal('fetch', fetchMock)
    const result = await submitWithReceipt(receiptDraft('owner-mismatch'))
    expect(result.offline_submit_pending).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(pendingOfflineDrafts()).toHaveLength(1)
  })

  it('pauses validation failures until retry is requested, retaining the report', async () => {
    vi.useFakeTimers(); resumeOfflineSync(); await syncOfflineReports(); setOfflinePrincipal('receipt-owner')
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(true)
    let attempts = 0
    vi.stubGlobal('fetch', vi.fn(async (path: string) => {
      if (path.includes('auth/session')) return sessionReply()
      attempts++
      return new Response(JSON.stringify({ error: 'attendance incomplete' }), { status: 409 })
    }))
    await submitWithReceipt(receiptDraft('validation-blocked'))
    await vi.advanceTimersByTimeAsync(120000)
    expect(attempts).toBe(1)
    expect(pendingOfflineDrafts()).toHaveLength(1)
  })
})


it('resumes a locally queued slot instead of creating an offline duplicate', async () => {
  makeOffline(); setOfflinePrincipal('receipt-owner')
  cacheOfflineData('me', { principal_id: 'receipt-owner', display_name: 'Reporter', role: 'supervisor', crew_id: 'crew-1', crew_name: 'Crew' })
  const existing = receiptDraft('offline_report_existing')
  saveOfflineDraft(existing, true, true)
  const result = await morningApi<ShiftReport>('/api/morning/draft', { method: 'POST', body: JSON.stringify({ shift_date: existing.shift_date, shift_kind: existing.shift_kind, reporting_model: 'tmm' }) })
  expect(result.id).toBe(existing.id)
  expect(pendingOfflineDrafts()).toHaveLength(1)
})
