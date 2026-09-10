import { useState } from 'react'
import { isOfflineReportPending, morningApi } from '../api'
import { OTHER_ACTIVITY_CATEGORIES } from '../types'
import type { ShiftReport, SyncState } from '../types'

export function OtherActivitiesStage({ report, onUpdated, onSync, onNext, onBack }: { report: ShiftReport; onUpdated: (report: ShiftReport) => void; onSync: (state: SyncState) => void; onNext: () => void; onBack: () => void }) {
  const [category, setCategory] = useState(''); const [description, setDescription] = useState(''); const [pending, setPending] = useState(false)
  const resolved = Boolean(report.other_activities.length || report.other_activities_reviewed_empty)
  const run = async (work: () => Promise<ShiftReport>) => {
    setPending(true); onSync({ status: 'saving' })
    try { const updated = await work(); onUpdated(updated); onSync(isOfflineReportPending(updated.id) ? { status: 'offline', message: 'Saved on this device — will synchronize automatically.' } : { status: 'saved' }); return true }
    catch (error) { const offline = !navigator.onLine; onSync({ status: offline ? 'offline' : 'failed', message: error instanceof Error ? error.message : 'Other activity was not saved.', retry: () => void run(work) }); return false }
    finally { setPending(false) }
  }
  const add = async () => { if (description.trim() && await run(() => morningApi<ShiftReport>(`/api/morning/reports/${report.id}/other-activities`, { method: 'POST', body: JSON.stringify({ category: category || null, description: description.trim() }) }))) setDescription('') }
  const markEmpty = (reviewed: boolean) => run(() => morningApi<ShiftReport>(`/api/morning/reports/${report.id}/section-resolution`, { method: 'PATCH', body: JSON.stringify({ section: 'other_activities', reviewed }) }))
  return <div className="morning-stage"><div className="morning-events-list">{report.other_activities.map(activity => <div key={activity.id} className="morning-entry-row"><div>{activity.category ? <strong>{activity.category}: </strong> : null}<span>{activity.description}</span></div><button type="button" disabled={pending} className="danger" onClick={() => { if (window.confirm('Remove this other activity?')) void run(() => morningApi<ShiftReport>(`/api/morning/reports/${report.id}/other-activities/${activity.id}`, { method: 'DELETE' })) }}>Remove</button></div>)}</div><div className="morning-add-form"><label>Category (optional)<select value={category} onChange={event => setCategory(event.target.value)}><option value="">None</option>{OTHER_ACTIVITY_CATEGORIES.map(item => <option key={item}>{item}</option>)}</select></label><label>Activity<textarea placeholder="What happened" value={description} onChange={event => setDescription(event.target.value)} /></label><button type="button" disabled={pending || !description.trim()} onClick={() => void add()}>Add activity</button></div>{!report.other_activities.length ? <label className="morning-resolution"><input type="checkbox" checked={report.other_activities_reviewed_empty} disabled={pending} onChange={event => void markEmpty(event.target.checked)} /> Nothing else to report</label> : null}{!resolved ? <p className="morning-caution">Add an activity or confirm there is nothing else to report.</p> : null}<div className="morning-stage-nav"><button type="button" onClick={onBack}>Back</button><button type="button" className="primary" disabled={!resolved || pending} onClick={onNext}>Next: Review</button></div></div>
}
