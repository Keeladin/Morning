import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Workflow } from '../../src/morning/Workflow'
import { cacheOfflineData, saveOfflineDraft, setOfflinePrincipal } from '../../src/morning/offline'
import type { ReportingModel, ShiftReport } from '../../src/morning/types'

const principal = { principal_id: 'owner', display_name: 'Supervisor', role: 'supervisor' as const }
const person = { id: 'person', name: 'Artisan', crew_id: 'crew', active: true, role: 'Fitter', employee_number: null, created_at: 'now' }
function report(id: string, overrides: Partial<ShiftReport> = {}): ShiftReport {
  return {
    id, shift_date: '2026-10-12', shift_kind: 'morning', shift_id: '2026-10-12:morning',
    supervisor_principal_id: 'owner', crew_id: 'crew', crew_ids: ['crew'], reporting_model: 'tmm',
    status: 'draft', attendance: [], stop_fix: [], cards: [], machine_events: [], construction_work: [],
    other_activities: [], brothers_keeper: null, created_at: '2026-10-12T04:00:00Z', updated_at: '2026-10-12T04:00:00Z',
    submitted_at: null, safety_reviewed_empty: false, machine_activity_reviewed_empty: false,
    other_activities_reviewed_empty: false, construction_work_reviewed_empty: false, construction_outstanding_reviewed_empty: false,
    ...overrides,
  }
}
const clients: QueryClient[] = []
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

function mount(selected: ShiftReport, current: ShiftReport | null = null, others: ShiftReport[] = []) {
  setOfflinePrincipal('owner')
  const model = selected.reporting_model
  const records = new Map([selected, ...others, ...(current ? [current] : [])].map(item => [item.id, item]))
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    let body: unknown
    if (path === '/api/morning/shift') body = { shift_date: '2026-10-13', shift_kind: 'night', shift_id: '2026-10-13:night' }
    else if (path === '/api/morning/me') body = { ...principal, crew_id: 'crew', crew_name: 'Crew' }
    else if (path === '/api/morning/crews') body = { crews: [{ id: 'crew', name: 'Crew', created_at: 'now' }] }
    else if (path === '/api/morning/machines') body = { machines: [] }
    else if (path === '/api/morning/personnel' || path.includes('/roster?') || path.endsWith('/participants')) body = { people: [person] }
    else if (path === '/api/morning/home') body = { recent_reports: [], announcements: [], messages: [], unread_count: 0, supervisors: [] }
    else if (path.startsWith('/api/morning/draft?')) body = { report: current }
    else if (path === '/api/morning/draft' && init?.method === 'POST') {
      const slot = JSON.parse(String(init.body))
      body = [...records.values()].find(item => item.shift_date === slot.shift_date && item.shift_kind === slot.shift_kind && item.reporting_model === slot.reporting_model)
      if (!body) throw new Error(`Unexpected slot: ${init.body}`)
    } else if (records.has(path.split('/').at(-1)!)) body = records.get(path.split('/').at(-1)!)
    else if (path === `/api/morning/reports/${selected.id}/correct`) {
      const corrected = { ...selected, status: 'draft' as const, correction_pending: true, revision: 1 }
      records.set(selected.id, corrected)
      body = corrected
    }
    else if (path.endsWith('/machine-states')) body = { states: [] }
    else if (path.endsWith('/versions')) body = { versions: [{ revision: 0, recorded_at: selected.submitted_at, snapshot: selected }] }
    else if (path.endsWith('/whatsapp')) body = { text: `Report ${selected.id}` }
    else throw new Error(`Unexpected request: ${path}`)
    return new Response(JSON.stringify(body), { status: 200 })
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, networkMode: 'always' }, mutations: { retry: false, networkMode: 'always' } } })
  clients.push(client)
  render(<QueryClientProvider client={client}><Workflow principal={principal} reportingModel={model} /></QueryClientProvider>)
  return { client, fetchMock }
}

async function choose(selected: ShiftReport) {
  if (screen.queryByRole('button', { name: 'Choose another date / shift' })) fireEvent.click(screen.getByRole('button', { name: 'Choose another date / shift' }))
  else if (screen.queryByRole('button', { name: 'Choose date / shift' })) fireEvent.click(screen.getByRole('button', { name: 'Choose date / shift' }))
  else if (selected.reporting_model === 'tmm') fireEvent.click(await screen.findByRole('button', { name: 'Choose date / shift · new report or correction' }))
  await screen.findByRole('heading', { name: 'Choose date and shift' })
  fireEvent.click(screen.getByRole('button', { name: selected.shift_kind.charAt(0).toUpperCase() + selected.shift_kind.slice(1) }))
  fireEvent.change(screen.getByLabelText('Shift reporting date'), { target: { value: selected.shift_date } })
  fireEvent.click(screen.getByRole('button', { name: 'Open / start report' }))
  await screen.findByRole('button', { name: selected.status === 'submitted' ? 'Choose another date / shift' : 'Choose date / shift' })
}

describe('selected report identity', () => {
  it.each([
    ['tmm', '2026-10-12', 'afternoon'], ['tmm', '2026-10-13', 'night'], ['tmm', '2026-10-13', 'morning'],
    ['construction', '2026-10-12', 'afternoon'], ['construction', '2026-10-13', 'night'], ['construction', '2026-10-13', 'morning'],
  ] as const)('opens an independent %s report for %s %s after viewing a submission', async (reporting_model, shift_date, shift_kind) => {
    const submitted = report('submitted', { reporting_model, status: 'submitted', submitted_at: '2026-10-12T12:05:00Z' })
    const next = report('next', { reporting_model, shift_date, shift_kind, shift_id: `${shift_date}:${shift_kind}` })
    mount(submitted, null, [next])
    await choose(submitted)
    await choose(next)
    expect(screen.getByRole('heading', { name: 'Attendance' })).toBeVisible()
    expect(screen.queryByText(/Received by Morning/)).not.toBeInTheDocument()
    expect(document.querySelector('.morning-shift-banner')?.textContent).toContain(shift_date)
    await choose(submitted)
    expect(screen.getByRole('heading', { name: 'Report submitted!' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Correct this report' })).toBeVisible()
  })

  it.each<ReportingModel>(['tmm', 'construction'])('keeps the selected %s submission through a background refetch', async model => {
    const selected = report('submitted', { reporting_model: model, status: 'submitted', submitted_at: '2026-10-12T12:05:00Z' })
    const { client } = mount(selected, report('latest', { reporting_model: model, shift_date: '2026-10-13' }))
    if (model === 'construction') await screen.findByRole('button', { name: 'Choose date / shift' })
    await choose(selected)
    expect(screen.getByRole('heading', { name: 'Report submitted!' })).toBeVisible()
    await act(async () => { await client.refetchQueries({ type: 'active' }); await new Promise(resolve => setTimeout(resolve, 0)) })
    expect(screen.getByRole('heading', { name: 'Report submitted!' })).toBeVisible()
    expect(screen.getByText('2026-10-12')).toBeVisible()
  })

  it('keeps an older selected draft instead of replacing it with the latest draft', async () => {
    const selected = report('older', { shift_date: '2026-10-09' })
    const { client, fetchMock } = mount(selected, report('latest'))
    await choose(selected)
    await act(async () => { await client.refetchQueries({ type: 'active' }); await new Promise(resolve => setTimeout(resolve, 0)) })
    expect(document.querySelector('.morning-shift-banner')?.textContent).toContain('2026-10-09')
    const post = fetchMock.mock.calls.find(([path, init]) => path === '/api/morning/draft' && init?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ shift_date: '2026-10-09', shift_kind: 'morning', exact_date: true })
  })

  it.each([
    { shift_kind: 'afternoon' as const }, { shift_date: '2026-10-11' },
    { supervisor_principal_id: 'someone-else' }, { reporting_model: 'construction' as const },
  ])('does not show another report’s background receipt: %j', async different => {
    const selected = report('selected')
    mount(selected)
    await choose(selected)
    act(() => window.dispatchEvent(new CustomEvent('morning:report-synced', { detail: { report: report('other', {
      ...different, status: 'submitted', submitted_at: '2026-10-12T12:05:00Z',
    }) } })))
    expect(screen.queryByText(/Received by Morning/)).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Attendance' })).toBeVisible()
  })

  it('keeps genuine submissions correctable and their history accessible', async () => {
    const selected = report('submitted', { status: 'submitted', submitted_at: '2026-10-12T12:05:00Z' })
    mount(selected)
    await choose(selected)
    fireEvent.click(screen.getByRole('button', { name: 'Submission history' }))
    await screen.findByText(/Original submission/)
    fireEvent.click(screen.getByRole('button', { name: 'Correct this report' }))
    await screen.findByText(/Editing correction/)
    expect(screen.queryByRole('heading', { name: 'Report submitted!' })).not.toBeInTheDocument()
    act(() => window.dispatchEvent(new CustomEvent('morning:report-synced', { detail: { report: selected } })))
    expect(screen.getByText(/Editing correction/)).toBeVisible()
    expect(screen.queryByText(/Received by Morning/)).not.toBeInTheDocument()
  })

  it('reconciles the selected offline report to its server ID and receipt', async () => {
    const selected = report('offline_report_local', { offline_submit_pending: true })
    const { client } = mount(selected)
    await choose(selected)
    saveOfflineDraft(selected, true, true)
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false)
    await act(async () => { await client.refetchQueries({ type: 'active' }) })
    const received = { ...selected, id: 'server-report', status: 'submitted' as const, submitted_at: '2026-10-12T12:05:00Z', offline_submit_pending: undefined }
    cacheOfflineData('draft.id.server-report', { report: received, pending: false })
    act(() => window.dispatchEvent(new CustomEvent('morning:report-synced', { detail: { report: received } })))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Report submitted!' })).toBeVisible())
  })

  it('preserves unsaved form choices when an offline draft acquires a server ID', async () => {
    const selected = report('offline_report_local')
    mount(selected)
    await choose(selected)
    fireEvent.click(screen.getByRole('button', { name: 'Present' }))
    const synced = { ...selected, id: 'server-report' }
    saveOfflineDraft(synced, false, true)
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false)
    act(() => window.dispatchEvent(new CustomEvent('morning:report-synced', { detail: { report: synced } })))
    await waitFor(() => expect(screen.getByText('Local changes synchronized with Morning.')).toBeVisible())
    expect(screen.getByRole('button', { name: 'Present' })).toHaveClass('active')
    expect(screen.getByText('Attendance has unsaved changes.')).toBeVisible()
  })
})
