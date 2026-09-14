import { useEffect, useState } from 'react'
import { isOfflineReportPending, morningApi } from '../api'
import { hhmm } from '../format'
import { MACHINE_STATES } from '../types'
import type { Machine, MachineEvent, MachineState, MachineStateDeclaration, Person, ShiftReport, SyncState } from '../types'

function machineLabel(machines: Machine[], id: string): string {
  return machines.find(machine => machine.id === id)?.machine_id || id
}
function personLabel(people: Person[], id: string | null): string {
  return people.find(person => person.id === id)?.name || 'Unassigned'
}
function stateLabel(value: MachineState): string {
  return MACHINE_STATES.find(item => item.value === value)?.label || value
}
function validTime(value: string): boolean { return /^([01]\d|2[0-3]):[0-5]\d$/.test(value) }

export function MachineActivityStage({ report, machines, people, onUpdated, onSync, onNext, onBack }: {
  report: ShiftReport; machines: Machine[]; people: Person[]; onUpdated: (report: ShiftReport) => void
  onSync: (state: SyncState) => void; onNext: () => void; onBack: () => void
}) {
  const [machineId, setMachineId] = useState(machines[0]?.id || '')
  const [personId, setPersonId] = useState(people[0]?.id || '')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [issue, setIssue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const [states, setStates] = useState<MachineStateDeclaration[]>(report.machine_states || [])
  const [stateMachineId, setStateMachineId] = useState(machines[0]?.id || '')
  const [stateTime, setStateTime] = useState('')
  const [machineState, setMachineState] = useState<MachineState>('running')
  const [stateNote, setStateNote] = useState('')
  const [followUp, setFollowUp] = useState('')
  const [stateError, setStateError] = useState<string | null>(null)
  const [statePending, setStatePending] = useState(false)

  useEffect(() => {
    if (!machineId && machines[0]) setMachineId(machines[0].id)
    if (!stateMachineId && machines[0]) setStateMachineId(machines[0].id)
    if (!personId && people[0]) setPersonId(people[0].id)
  }, [machines, people, machineId, personId, stateMachineId])

  useEffect(() => {
    let active = true
    void morningApi<{ states: MachineStateDeclaration[] }>(`/api/morning/reports/${report.id}/machine-states`)
      .then(body => { if (active) setStates(body.states) })
      .catch(() => undefined)
    return () => { active = false }
  }, [report.id])

  const resolved = Boolean(report.machine_events.length || report.machine_activity_reviewed_empty)
  const reset = () => { setStart(''); setEnd(''); setIssue(''); setEditingId(null) }
  const run = async (work: () => Promise<ShiftReport>) => {
    setPending(true); onSync({ status: 'saving' })
    try {
      const updated = await work(); onUpdated(updated)
      onSync(isOfflineReportPending(updated.id)
        ? { status: 'offline', message: 'Saved on this device — will synchronize automatically.' }
        : { status: 'saved' })
      return true
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Machine activity was not saved.'
      setError(message); const offline = !navigator.onLine
      onSync({ status: offline ? 'offline' : 'failed', message, retry: () => void run(work) })
      return false
    } finally { setPending(false) }
  }

  const save = async () => {
    setError(null)
    if (!machineId || !personId || !validTime(start) || !validTime(end) || !issue.trim()) {
      setError('Machine, person assigned, valid HH:MM start/end, and work performed are required.'); return
    }
    const payload = JSON.stringify({ machine_id: machineId, person_id: personId, start_hhmm: start, end_hhmm: end, issue: issue.trim() })
    const path = editingId ? `/api/morning/reports/${report.id}/machine-events/${editingId}` : `/api/morning/reports/${report.id}/machine-events`
    if (await run(() => morningApi<ShiftReport>(path, { method: editingId ? 'PATCH' : 'POST', body: payload }))) reset()
  }

  const edit = (event: MachineEvent) => {
    setEditingId(event.id); setMachineId(event.machine_id); setPersonId(event.person_id || people[0]?.id || '')
    setStart(hhmm(event.start_time)); setEnd(hhmm(event.end_time)); setIssue(event.issue)
  }
  const markEmpty = (reviewed: boolean) => run(() => morningApi<ShiftReport>(
    `/api/morning/reports/${report.id}/section-resolution`,
    { method: 'PATCH', body: JSON.stringify({ section: 'machine_activity', reviewed }) },
  ))

  const saveState = async () => {
    setStateError(null)
    if (!stateMachineId || !validTime(stateTime)) {
      setStateError('Machine and a valid HH:MM declaration time are required.'); return
    }
    if (machineState === 'other' && !stateNote.trim()) {
      setStateError('Add a short explanation when selecting Other.'); return
    }
    setStatePending(true); onSync({ status: 'saving' })
    try {
      const declaration = await morningApi<MachineStateDeclaration>(`/api/morning/reports/${report.id}/machine-states`, {
        method: 'POST',
        body: JSON.stringify({ machine_id: stateMachineId, declared_hhmm: stateTime, state: machineState, state_note: stateNote.trim() || null, follow_up: followUp.trim() || null }),
      })
      setStates(current => [...current.filter(item => item.id !== declaration.id), declaration])
      setStateTime(''); setStateNote(''); setFollowUp('')
      onSync(!navigator.onLine || isOfflineReportPending(report.id)
        ? { status: 'offline', message: 'Machine state saved on this device — will synchronize automatically.' }
        : { status: 'saved' })
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Machine state was not saved.'
      setStateError(message)
      onSync({ status: navigator.onLine ? 'failed' : 'offline', message })
    } finally { setStatePending(false) }
  }

  const machinesNeedingState = [...new Set(report.machine_events.map(event => event.machine_id))]
    .filter(id => !states.some(state => state.machine_id === id))

  return <div className="morning-stage">
    <section>
      <h3 className="morning-section-label">Engineering work</h3>
      <div className="morning-add-form">
        <label>Machine<select value={machineId} onChange={event => setMachineId(event.target.value)}>{machines.map(machine => <option key={machine.id} value={machine.id}>{machine.machine_id}</option>)}</select></label>
        <label>Person assigned<select value={personId} onChange={event => setPersonId(event.target.value)}>{people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
        <div className="morning-time-row">
          <label>Start time<input className="morning-digital-time" type="time" step="60" value={start} onChange={event => setStart(event.target.value)} /></label>
          <label>End time<input className="morning-digital-time" type="time" step="60" value={end} onChange={event => setEnd(event.target.value)} /></label>
        </div>
        <label>Issue / work performed<textarea value={issue} onChange={event => setIssue(event.target.value)} /></label>
        {error ? <p className="error-text">{error}</p> : null}
        <button type="button" className="primary" disabled={pending} onClick={() => void save()}>{pending ? 'Saving…' : editingId ? 'Save correction' : 'Save work interval'}</button>
        {editingId ? <button type="button" onClick={reset}>Cancel edit</button> : null}
      </div>
      <div className="morning-events-list">{report.machine_events.map(event => <div key={event.id} className="morning-entry-row">
        <div><strong>{machineLabel(machines, event.machine_id)}</strong><div className="meta">{hhmm(event.start_time)}–{hhmm(event.end_time)} · {personLabel(people, event.person_id)}</div><div>{event.issue}</div></div>
        <div className="morning-entry-actions"><button type="button" disabled={pending} onClick={() => edit(event)}>Edit</button><button type="button" disabled={pending} className="danger" onClick={() => { if (window.confirm('Remove this machine work interval?')) void run(() => morningApi<ShiftReport>(`/api/morning/reports/${report.id}/machine-events/${event.id}`, { method: 'DELETE' })) }}>Remove</button></div>
      </div>)}</div>
    </section>

    <section className="morning-machine-state-panel">
      <h3 className="morning-section-label">How was the machine left?</h3>
      <p className="meta">Declare the machine's actual condition separately from the engineering work interval. This is the source for later continuity and reliability reporting.</p>
      {states.length ? <div className="morning-events-list">{states.map(state => <div className="morning-entry-row" key={state.id}>
        <div><strong>{machineLabel(machines, state.machine_id)} · {stateLabel(state.state)}</strong><div className="meta">Declared {hhmm(state.declared_at)}{state.provenance === 'carried' ? ' · carried from prior state' : ''}</div>{state.state_note ? <div>{state.state_note}</div> : null}{state.follow_up ? <div className="meta">Follow-up: {state.follow_up}</div> : null}</div>
      </div>)}</div> : null}
      {machinesNeedingState.length ? <p className="morning-caution">No machine-state declaration yet for: {machinesNeedingState.map(id => machineLabel(machines, id)).join(', ')}.</p> : null}
      <div className="morning-add-form">
        <label>Machine<select aria-label="State machine" value={stateMachineId} onChange={event => setStateMachineId(event.target.value)}>{machines.map(machine => <option key={machine.id} value={machine.id}>{machine.machine_id}</option>)}</select></label>
        <div className="morning-time-row">
          <label>Declaration time<input aria-label="Declaration time" className="morning-digital-time" type="time" step="60" value={stateTime} onChange={event => setStateTime(event.target.value)} /></label>
          <label>Machine state<select aria-label="Machine state" value={machineState} onChange={event => setMachineState(event.target.value as MachineState)}>{MACHINE_STATES.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        </div>
        {machineState === 'other' ? <label>State explanation<textarea aria-label="State explanation" value={stateNote} onChange={event => setStateNote(event.target.value)} /></label> : null}
        <label>Follow-up (optional)<textarea value={followUp} onChange={event => setFollowUp(event.target.value)} /></label>
        {stateError ? <p className="error-text">{stateError}</p> : null}
        <button type="button" disabled={statePending || !machines.length} onClick={() => void saveState()}>{statePending ? 'Saving…' : 'Save machine state'}</button>
      </div>
    </section>

    {!report.machine_events.length ? <label className="morning-resolution"><input type="checkbox" checked={report.machine_activity_reviewed_empty} disabled={pending} onChange={event => void markEmpty(event.target.checked)} /> No machine work this shift</label> : null}
    {!resolved ? <p className="morning-caution">Record machine work or confirm there was no machine work this shift.</p> : null}
    <div className="morning-stage-nav"><button type="button" onClick={onBack}>Back</button><button type="button" className="primary" disabled={!resolved || pending || statePending} onClick={onNext}>Next: Other activities</button></div>
  </div>
}
