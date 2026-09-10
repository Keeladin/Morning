import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { isOfflineReportPending, morningApi } from '../api'
import { formatConstructionLevel } from '../format'
import { CONSTRUCTION_WORK_STATUSES } from '../types'
import type { ConstructionWorkKind, ConstructionWorkStatus, ShiftReport, SyncState } from '../types'

type ConstructionConfig = { levels:{id:string;level:string;active:boolean}[]; workstreams:{id:string;name:string;active:boolean}[]; crew:{crew_id:string;name:string;workstream_name:string|null}|null }

type Props = {
  report: ShiftReport
  kind: ConstructionWorkKind
  onUpdated: (report: ShiftReport) => void
  onNext: () => void
  onBack: () => void
  onSync: (state: SyncState) => void
}

const statusLabel = (value: ConstructionWorkStatus) =>
  CONSTRUCTION_WORK_STATUSES.find(item => item.value === value)?.label || value

export function ConstructionWorkStage({ report, kind, onUpdated, onNext, onBack, onSync }: Props) {
  const [level, setLevel] = useState('')
  const [location, setLocation] = useState('')
  const [task, setTask] = useState('')
  const [status, setStatus] = useState<ConstructionWorkStatus>(kind === 'outstanding' ? 'held' : 'in_progress')
  const [progress, setProgress] = useState('')
  const [updateText, setUpdateText] = useState('')
  const [constraint, setConstraint] = useState('')
  const [nextAction, setNextAction] = useState('')
  const [pending, setPending] = useState(false)
  const items = report.construction_work.filter(item => item.kind === kind)
  const configQuery = useQuery({ queryKey:['construction-config'], queryFn:()=>morningApi<ConstructionConfig>('/api/morning/construction/config') })
  const reviewedEmpty = kind === 'core' ? report.construction_work_reviewed_empty : report.construction_outstanding_reviewed_empty
  const resolved = Boolean(items.length || reviewedEmpty)
  const levels = useMemo(() => [...new Set([...(configQuery.data?.levels.map(item => item.level) || []), ...report.construction_work.map(item => item.level)])].sort((a,b)=>Number(a)-Number(b)), [configQuery.data?.levels, report.construction_work])
  const locations = useMemo(() => [...new Set(report.construction_work.filter(item => !level || item.level === level.replace(/\s/g, '').toUpperCase()).map(item => item.location))].sort(), [report.construction_work, level])

  const run = async (work: () => Promise<ShiftReport>) => {
    setPending(true); onSync({ status: 'saving' })
    try {
      const updated = await work(); onUpdated(updated); onSync(isOfflineReportPending(updated.id) ? { status: 'offline', message: 'Saved on this device — will synchronize automatically.' } : { status: 'saved' }); return true
    } catch (error) {
      const offline = !navigator.onLine
      onSync({ status: offline ? 'offline' : 'failed', message: error instanceof Error ? error.message : 'Construction change was not saved.', retry: () => void run(work) })
      return false
    } finally { setPending(false) }
  }

  const addItem = async () => {
    const cleanLevel = level.replace(/\s/g, '').toUpperCase()
    if (!/^\d+(?:[NS])?$/.test(cleanLevel) || !location.trim() || !task.trim()) return
    const saved = await run(() => morningApi<ShiftReport>(`/api/morning/reports/${report.id}/construction-work`, {
      method: 'POST', body: JSON.stringify({ kind, level: cleanLevel, location: location.trim(), task: task.trim(), status,
        progress_percent: progress === '' ? null : Number(progress), update_text: updateText.trim(),
        constraint_text: constraint.trim() || null, next_action: nextAction.trim() || null }),
    }))
    if (saved) { setLevel(''); setLocation(''); setTask(''); setProgress(''); setUpdateText(''); setConstraint(''); setNextAction(''); setStatus(kind === 'outstanding' ? 'held' : 'in_progress') }
  }
  const patchItem = (id: string, fields: Record<string, unknown>) => run(() => morningApi<ShiftReport>(`/api/morning/reports/${report.id}/construction-work/${id}`, { method: 'PATCH', body: JSON.stringify(fields) }))
  const deleteItem = (id: string) => run(() => morningApi<ShiftReport>(`/api/morning/reports/${report.id}/construction-work/${id}`, { method: 'DELETE' }))
  const markEmpty = (reviewed: boolean) => run(() => morningApi<ShiftReport>(`/api/morning/reports/${report.id}/section-resolution`, {
    method: 'PATCH', body: JSON.stringify({ section: kind === 'core' ? 'construction_work' : 'construction_outstanding', reviewed }),
  }))
  const heading = kind === 'core' ? 'Core work' : 'Outstanding work'
  const intro = kind === 'core'
    ? 'Capture the work done this shift. Morning will preserve it as the next shift’s previous-shift position.'
    : 'Keep incomplete, delayed or held work visible so it is deliberately carried forward.'

  return <div className="morning-stage construction-stage">
    <div className="construction-stage-intro"><strong>{heading}</strong><span>{intro}</span></div>
    <div className="construction-work-list">
      {items.map(item => <article key={item.id} className={`construction-work-card status-${item.status}`}>
        <div className="construction-work-card-top"><div><span className="construction-level">{formatConstructionLevel(item.level)}</span><strong>{item.location}</strong></div><span className="construction-status">{statusLabel(item.status)}{item.progress_percent !== null ? ` · ${item.progress_percent}%` : ''}</span></div>
        <h3>{item.task}</h3>
        {item.update_text ? <p className="construction-update">{item.update_text}</p> : null}
        {item.constraint_text ? <div className="construction-detail"><span>Constraint</span><strong>{item.constraint_text}</strong></div> : null}
        {item.next_action ? <div className="construction-detail"><span>Next</span><strong>{item.next_action}</strong></div> : null}
        <div className="construction-card-actions">
          {item.status !== 'complete' ? <button type="button" disabled={pending} onClick={() => void patchItem(item.id, { status: 'complete', progress_percent: item.progress_percent === null ? null : 100 })}>Mark complete</button> : null}
          {item.status === 'held' ? <button type="button" disabled={pending} onClick={() => void patchItem(item.id, { status: 'in_progress' })}>Resume</button> : null}
          <button type="button" disabled={pending} className="danger" onClick={() => { if (window.confirm('Remove this work item?')) void deleteItem(item.id) }}>Remove</button>
        </div>
      </article>)}
    </div>
    <div className="construction-add-card">
      <div className="construction-form-grid two">
        <label><span>Level</span><input placeholder="813, 813N or 813S" list="construction-levels" value={level} onChange={e => setLevel(e.target.value)} /></label>
        <label><span>Location</span><input placeholder="South Cells" list="construction-locations" value={location} onChange={e => setLocation(e.target.value)} /></label>
      </div>
      <datalist id="construction-levels">{levels.map(item => <option key={item} value={item} />)}</datalist>
      <datalist id="construction-locations">{locations.map(item => <option key={item} value={item} />)}</datalist>
      <label><span>Task</span><input placeholder="Legal inspections" value={task} onChange={e => setTask(e.target.value)} /></label>
      <div className="construction-form-grid two">
        <label><span>Status</span><select value={status} onChange={e => setStatus(e.target.value as ConstructionWorkStatus)}>{CONSTRUCTION_WORK_STATUSES.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        <label><span>Progress <em>optional</em></span><input type="number" min="0" max="100" placeholder="60" value={progress} onChange={e => setProgress(e.target.value)} /></label>
      </div>
      <label><span>Shift update</span><textarea placeholder={kind === 'core' ? 'What was done or changed this shift?' : 'Current position / why it remains outstanding'} value={updateText} onChange={e => setUpdateText(e.target.value)} /></label>
      <label><span>Constraint <em>optional</em></span><input placeholder="Access, material, labour, permit…" value={constraint} onChange={e => setConstraint(e.target.value)} /></label>
      <label><span>Next action <em>optional</em></span><input placeholder="What happens next?" value={nextAction} onChange={e => setNextAction(e.target.value)} /></label>
      <button type="button" className="primary construction-add-button" disabled={pending || !/^\s*\d+(?:\s*[nNsS])?\s*$/.test(level) || !location.trim() || !task.trim()} onClick={() => void addItem()}>{pending ? 'Saving…' : `Add ${kind === 'core' ? 'work item' : 'outstanding item'}`}</button>
    </div>
    {!items.length ? <label className="morning-resolution"><input type="checkbox" checked={reviewedEmpty} disabled={pending} onChange={event => void markEmpty(event.target.checked)} /> {kind === 'core' ? 'Reviewed — no core work this shift' : 'Reviewed — nothing outstanding to carry forward'}</label> : null}
    {!resolved ? <p className="morning-caution">Add a work item or confirm that there is nothing to report.</p> : null}
    <div className="morning-stage-nav"><button type="button" onClick={onBack}>Back</button><button type="button" className="primary" disabled={!resolved || pending} onClick={onNext}>{kind === 'core' ? 'Next: Outstanding work' : 'Next: Summary'}</button></div>
  </div>
}
