import { useEffect, useMemo, useState } from 'react'
import { isOfflineReportPending, morningApi } from '../api'
import type { Person, ShiftReport, SyncState } from '../types'

export function AttendanceStage({ report, people, onUpdated, onNext, onSync }: { report: ShiftReport; people: Person[]; onUpdated: (report: ShiftReport) => void; onNext: () => void; onSync: (state: SyncState) => void }) {
  const serverStatuses = useMemo(() => Object.fromEntries(report.attendance.map(entry => [entry.person_id, entry.present])), [report.attendance])
  const [statuses, setStatuses] = useState<Record<string, boolean>>(serverStatuses)
  const [saving, setSaving] = useState(false)
  const dirty = people.some(person => statuses[person.id] !== serverStatuses[person.id])
  const complete = people.length > 0 && people.every(person => statuses[person.id] !== undefined)
  useEffect(() => { if (!dirty) setStatuses(serverStatuses) }, [serverStatuses, dirty])

  const save = async () => {
    if (!complete || saving) return
    setSaving(true); onSync({ status: 'saving' })
    try {
      const entries = people.map(person => ({ person_id: person.id, present: statuses[person.id] }))
      const updated = await morningApi<ShiftReport>(`/api/morning/reports/${report.id}/attendance`, { method: 'POST', body: JSON.stringify({ entries }) })
      onUpdated(updated); onSync(isOfflineReportPending(updated.id) ? { status: 'offline', message: 'Attendance saved on this device — will synchronize automatically.' } : { status: 'saved' })
    } catch (error) {
      const offline = !navigator.onLine
      onSync({ status: offline ? 'offline' : 'failed', message: error instanceof Error ? error.message : 'Attendance was not saved.', retry: () => void save() })
    } finally { setSaving(false) }
  }
  return <div className="morning-stage">
    {!people.length ? <p className="error-text">No personnel are attached to this report’s crew. An administrator must correct the crew roster before submission.</p> : null}
    <div className="morning-attendance-list">{people.map(person => <div key={person.id} className="morning-attendance-row"><div className="morning-attendance-name"><strong>{person.name}</strong>{person.role ? <span className="meta">{person.role}</span> : null}</div><div className="morning-attendance-actions" role="group" aria-label={`Attendance for ${person.name}`}><button type="button" disabled={saving} className={statuses[person.id] === true ? 'morning-present active' : 'morning-present'} onClick={() => setStatuses(current => ({ ...current, [person.id]: true }))}>Present</button><button type="button" disabled={saving} className={statuses[person.id] === false ? 'morning-absent active' : 'morning-absent'} onClick={() => setStatuses(current => ({ ...current, [person.id]: false }))}>Absent</button></div></div>)}</div>
    {dirty ? <p className="morning-unsaved">Attendance has unsaved changes.</p> : null}
    {!complete && people.length ? <p className="morning-caution">Mark every person Present or Absent.</p> : null}
    <div className="morning-stage-nav"><button type="button" onClick={() => void save()} disabled={!dirty || !complete || saving}>{saving ? 'Saving…' : 'Save attendance'}</button><button type="button" className="primary" disabled={dirty || !complete || saving} onClick={onNext}>Next: Brothers Keeper</button></div>
  </div>
}
