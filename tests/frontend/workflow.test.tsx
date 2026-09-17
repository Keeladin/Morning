import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AttendanceStage } from '../../src/morning/stages/Attendance'
import { MachineActivityStage } from '../../src/morning/stages/MachineActivity'
import { SafetyStage } from '../../src/morning/stages/Safety'
import { resumeStage, sectionCompletion } from '../../src/morning/Workflow'
import { shiftDateForKind } from '../../src/morning/format'
import type { Machine, Person, ShiftReport, SyncState } from '../../src/morning/types'

const people: Person[] = [
  { id: 'p1', name: 'Alex', employee_number: null, role: 'Fitter', active: true, crew_id: 'c1', created_at: 'now' },
  { id: 'p2', name: 'Sam', employee_number: null, role: 'Electrician', active: true, crew_id: 'c1', created_at: 'now' },
]
const machine: Machine = { id: 'm1', machine_id: 'ADR14', machine_type: null, section: null, active: true, created_at: 'now', retired_at: null, control_room_scope: false }
function report(overrides: Partial<ShiftReport> = {}): ShiftReport { return { id: 'r1', shift_date: '2026-09-01', shift_kind: 'morning', shift_id: '2026-09-01:morning', supervisor_principal_id: 'owner', crew_id: 'c1', crew_ids: ['c1'], reporting_model: 'tmm', status: 'draft', attendance: [], stop_fix: [], cards: [], machine_events: [], construction_work: [], other_activities: [], brothers_keeper: null, created_at: 'now', updated_at: new Date().toISOString(), submitted_at: null, safety_reviewed_empty: false, machine_activity_reviewed_empty: false, other_activities_reviewed_empty: false, construction_work_reviewed_empty: false, construction_outstanding_reviewed_empty: false, ...overrides } }

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('shift override reporting date', () => {
  it('maps an Afternoon override during Night back to the day that just ended', () => {
    expect(shiftDateForKind({ shift_date: '2026-09-17', shift_kind: 'night', shift_id: '2026-09-17:night' }, 'afternoon')).toBe('2026-09-16')
  })

  it('keeps normal Morning and Afternoon reporting dates unchanged', () => {
    expect(shiftDateForKind({ shift_date: '2026-09-17', shift_kind: 'morning', shift_id: '2026-09-17:morning' }, 'afternoon')).toBe('2026-09-17')
  })
})

describe('workflow completion', () => {
  it('derives resume position from actual section completion', () => {
    const draft = report({ attendance: people.map(person => ({ person_id: person.id, present: true })), brothers_keeper: 'Report loose handrail at workshop steps.', safety_reviewed_empty: true })
    expect(resumeStage(draft, people)).toBe('machines')
    expect(sectionCompletion(draft, people).safety).toBe(true)
  })

  it('treats explicit nothing-to-report states as complete', () => {
    const draft = report({ attendance: people.map(person => ({ person_id: person.id, present: true })), brothers_keeper: 'Report loose handrail at workshop steps.', safety_reviewed_empty: true, machine_activity_reviewed_empty: true, other_activities_reviewed_empty: true })
    expect(resumeStage(draft, people)).toBe('review')
  })
})

describe('attendance batch save', () => {
  it('keeps rapid choices local and sends one complete batch', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(report({ attendance: [{ person_id: 'p1', present: true }, { person_id: 'p2', present: false }] })), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<AttendanceStage report={report()} people={people} onUpdated={vi.fn()} onNext={vi.fn()} onSync={vi.fn()} />)
    fireEvent.click(screen.getAllByRole('button', { name: 'Present' })[0])
    fireEvent.click(screen.getAllByRole('button', { name: 'Absent' })[1])
    expect(fetchMock).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Save attendance' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit | undefined)?.body))
    expect(body.entries).toEqual([{ person_id: 'p1', present: true }, { person_id: 'p2', present: false }])
  })

  it('exposes a failed save with a retry action', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('radio link unavailable') }))
    const states: SyncState[] = []
    render(<AttendanceStage report={report()} people={people.slice(0, 1)} onUpdated={vi.fn()} onNext={vi.fn()} onSync={state => states.push(state)} />)
    fireEvent.click(screen.getByRole('button', { name: 'Present' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save attendance' }))
    await waitFor(() => expect(states.at(-1)?.status).toBe('failed'))
    expect(states.at(-1)?.retry).toBeTypeOf('function')
  })
})

describe('approved mobile controls', () => {
  it('switches between the two Safety forms', () => {
    render(<SafetyStage report={report()} onUpdated={vi.fn()} onNext={vi.fn()} onBack={vi.fn()} onSync={vi.fn()} />)
    expect(screen.getByLabelText('Stop & Fix number')).toBeVisible()
    fireEvent.click(screen.getByRole('tab', { name: 'Red / Green Cards' }))
    expect(screen.getByLabelText('Card reason')).toBeVisible()
    expect(screen.queryByLabelText('Stop & Fix number')).not.toBeInTheDocument()
  })

  it('uses native time controls and the supplied TMM assignee pool', () => {
    render(<MachineActivityStage report={report()} machines={[machine]} people={people} onUpdated={vi.fn()} onSync={vi.fn()} onNext={vi.fn()} onBack={vi.fn()} />)
    expect(screen.getByLabelText('Start time')).toHaveAttribute('type', 'time')
    expect(screen.getByLabelText('End time')).toHaveAttribute('type', 'time')
    expect(screen.getByLabelText('Person assigned')).toHaveValue('p1')
    expect(screen.getByText('How was the machine left?')).toBeVisible()
    expect(screen.getByLabelText('Machine state')).toBeVisible()
  })
})
