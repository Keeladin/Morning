import { afterEach, describe, expect, it, vi } from 'vitest'
import { morningApi } from '../../src/morning/api'
import { cacheOfflineData, pendingOfflineDrafts, setOfflinePrincipal } from '../../src/morning/offline'
import type { MachineStateDeclaration, ShiftReport, SupervisorContext } from '../../src/morning/types'

afterEach(() => {
  localStorage.clear()
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

})
