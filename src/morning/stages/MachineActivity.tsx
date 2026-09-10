import { useEffect, useState } from 'react'
import { isOfflineReportPending, morningApi } from '../api'
import { hhmm } from '../format'
import type { Machine, MachineEvent, Person, ShiftReport, SyncState } from '../types'

function machineLabel(machines: Machine[], id: string): string { return machines.find(machine => machine.id === id)?.machine_id || id }
function personLabel(people: Person[], id: string | null): string { return people.find(person => person.id === id)?.name || 'Unassigned' }
function validTime(value: string): boolean { return /^([01]\d|2[0-3]):[0-5]\d$/.test(value) }

export function MachineActivityStage({ report, machines, people, onUpdated, onSync, onNext, onBack }: { report: ShiftReport; machines: Machine[]; people: Person[]; onUpdated: (report: ShiftReport) => void; onSync: (state: SyncState) => void; onNext: () => void; onBack: () => void }) {
  const [machineId, setMachineId] = useState(machines[0]?.id || '')
  const [personId, setPersonId] = useState(people[0]?.id || '')
  const [start, setStart] = useState(''); const [end, setEnd] = useState(''); const [issue, setIssue] = useState('')
  const [error, setError] = useState<string | null>(null); const [editingId, setEditingId] = useState<string | null>(null); const [pending, setPending] = useState(false)
  useEffect(() => { if (!machineId && machines[0]) setMachineId(machines[0].id); if (!personId && people[0]) setPersonId(people[0].id) }, [machines, people, machineId, personId])
  const resolved = Boolean(report.machine_events.length || report.machine_activity_reviewed_empty)
  const reset = () => { setStart(''); setEnd(''); setIssue(''); setEditingId(null) }
  const run = async (work: () => Promise<ShiftReport>) => {
    setPending(true); onSync({ status: 'saving' })
    try { const updated = await work(); onUpdated(updated); onSync(isOfflineReportPending(updated.id) ? { status: 'offline', message: 'Saved on this device — will synchronize automatically.' } : { status: 'saved' }); return true }
    catch (reason) { const message = reason instanceof Error ? reason.message : 'Machine activity was not saved.'; setError(message); const offline = !navigator.onLine; onSync({ status: offline ? 'offline' : 'failed', message, retry: () => void run(work) }); return false }
    finally { setPending(false) }
  }
  const save = async () => {
    setError(null)
    if (!machineId || !personId || !validTime(start) || !validTime(end) || !issue.trim()) { setError('Machine, person assigned, valid HH:MM start/end, and work performed are required.'); return }
    const payload = JSON.stringify({ machine_id: machineId, person_id: personId, start_hhmm: start, end_hhmm: end, issue: issue.trim() })
    const path = editingId ? `/api/morning/reports/${report.id}/machine-events/${editingId}` : `/api/morning/reports/${report.id}/machine-events`
    if (await run(() => morningApi<ShiftReport>(path, { method: editingId ? 'PATCH' : 'POST', body: payload }))) reset()
  }
  const edit = (event: MachineEvent) => { setEditingId(event.id); setMachineId(event.machine_id); setPersonId(event.person_id || people[0]?.id || ''); setStart(hhmm(event.start_time)); setEnd(hhmm(event.end_time)); setIssue(event.issue) }
  const markEmpty = (reviewed: boolean) => run(() => morningApi<ShiftReport>(`/api/morning/reports/${report.id}/section-resolution`, { method: 'PATCH', body: JSON.stringify({ section: 'machine_activity', reviewed }) }))
  return <div className="morning-stage">
    <section><h3 className="morning-section-label">Engineering work</h3><div className="morning-add-form"><label>Machine<select value={machineId} onChange={event => setMachineId(event.target.value)}>{machines.map(machine => <option key={machine.id} value={machine.id}>{machine.machine_id}</option>)}</select></label><label>Person assigned<select value={personId} onChange={event => setPersonId(event.target.value)}>{people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label><div className="morning-time-row"><label>Start time<input className="morning-digital-time" type="time" step="60" value={start} onChange={event => setStart(event.target.value)} /></label><label>End time<input className="morning-digital-time" type="time" step="60" value={end} onChange={event => setEnd(event.target.value)} /></label></div><label>Issue / work performed<textarea value={issue} onChange={event => setIssue(event.target.value)} /></label>{error ? <p className="error-text">{error}</p> : null}<button type="button" className="primary" disabled={pending} onClick={() => void save()}>{pending ? 'Saving…' : editingId ? 'Save correction' : 'Save work interval'}</button>{editingId ? <button type="button" onClick={reset}>Cancel edit</button> : null}</div><div className="morning-events-list">{report.machine_events.map(event => <div key={event.id} className="morning-entry-row"><div><strong>{machineLabel(machines, event.machine_id)}</strong><div className="meta">{hhmm(event.start_time)}–{hhmm(event.end_time)} · {personLabel(people, event.person_id)}</div><div>{event.issue}</div></div><div className="morning-entry-actions"><button type="button" disabled={pending} onClick={() => edit(event)}>Edit</button><button type="button" disabled={pending} className="danger" onClick={() => { if (window.confirm('Remove this machine work interval?')) void run(() => morningApi<ShiftReport>(`/api/morning/reports/${report.id}/machine-events/${event.id}`, { method: 'DELETE' })) }}>Remove</button></div></div>)}</div></section>
    {!report.machine_events.length ? <label className="morning-resolution"><input type="checkbox" checked={report.machine_activity_reviewed_empty} disabled={pending} onChange={event => void markEmpty(event.target.checked)} /> No machine work this shift</label> : null}
    {!resolved ? <p className="morning-caution">Record machine work or confirm there was no machine work this shift.</p> : null}
    <div className="morning-stage-nav"><button type="button" onClick={onBack}>Back</button><button type="button" className="primary" disabled={!resolved || pending} onClick={onNext}>Next: Other activities</button></div>
  </div>
}
