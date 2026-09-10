import { useState } from 'react'
import { isOfflineReportPending, MorningApiError, morningApi } from '../api'
import { formatConstructionLevel, hhmm, shiftLabel, shiftShortLabel } from '../format'
import type { Machine, MorningPrincipal, Person, ShiftReport } from '../types'
import { MorningIcon, MorningMark } from '../ui'

function machineLabel(machines: Machine[], id: string): string { return machines.find(m => m.id === id)?.machine_id || id }
function personName(people: Person[], id: string): string { return people.find(p => p.id === id)?.name || id }

export function ReviewStage({ report, machines, people, principal, onBack, onSubmitted, submitted = false, onHome }: { report: ShiftReport; machines: Machine[]; people: Person[]; principal?: MorningPrincipal; onBack?: () => void; onSubmitted?: (report: ShiftReport) => void; submitted?: boolean; onHome?: () => void }) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [whatsapp, setWhatsapp] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const presentCount = report.attendance.filter(e => e.present).length
  const absentCount = report.attendance.filter(e => !e.present).length
  const openStopFix = report.stop_fix.filter(sf => sf.status === 'open').length
  const greenCards = report.cards.filter(c => c.card_type === 'green').length
  const redCards = report.cards.filter(c => c.card_type === 'red').length
  const construction = report.reporting_model === 'construction'
  const coreWork = report.construction_work.filter(item => item.kind === 'core')
  const outstandingWork = report.construction_work.filter(item => item.kind === 'outstanding')
  const loadWhatsapp = async () => setWhatsapp((await morningApi<{ text: string }>(`/api/morning/reports/${report.id}/whatsapp`)).text)
  const submit = async () => {
    setPending(true); setError(null)
    try {
      const result = await morningApi<ShiftReport>(`/api/morning/reports/${report.id}/submit`, { method: 'POST', body: '{}' })
      onSubmitted?.(result)
      if (result.offline_submit_pending || isOfflineReportPending(result.id)) return
      await loadWhatsapp()
    } catch (err) {
      const missing = err instanceof MorningApiError && typeof err.body === 'object' && err.body && 'missing_sections' in err.body && Array.isArray((err.body as { missing_sections: unknown }).missing_sections)
        ? (err.body as { missing_sections: string[] }).missing_sections.join(', ') : ''
      setError(missing ? `Complete these sections before submitting: ${missing}.` : err instanceof Error ? err.message : 'Could not submit this report.')
    } finally { setPending(false) }
  }
  const copy = async () => {
    if (!whatsapp) return
    try { await navigator.clipboard.writeText(whatsapp); setCopied(true); setTimeout(() => setCopied(false), 2000) }
    catch { setError('Could not copy automatically — select and copy the text below.') }
  }

  if (report.offline_submit_pending) return <div className="morning-stage"><p className="morning-submitted-banner">Report complete — waiting to synchronize.</p><div className="morning-add-form"><p className="meta">This report is safely stored on this device. Morning will upload and submit it automatically when connectivity returns.</p></div></div>

  if (submitted || whatsapp) return <div className="morning-stage morning-success"><MorningMark compact /><span className="morning-success-check"><MorningIcon name="check" /></span><h2>Report submitted!</h2><p>Your TMM shift report has been saved and is ready for handover.</p><div className="morning-success-facts"><span><MorningIcon name="report"/> {report.shift_date}</span><span><MorningIcon name="clock"/> {shiftLabel(report.shift_kind)}</span></div><div className="morning-add-form morning-success-actions">{whatsapp ? <><label>WhatsApp-ready report<textarea className="morning-whatsapp-text" readOnly value={whatsapp} rows={18} /></label><button type="button" className="primary" onClick={() => void copy()}>{copied ? 'Copied!' : 'Copy WhatsApp report'}</button></> : <button type="button" onClick={() => void loadWhatsapp()}>Show WhatsApp report</button>}{onHome ? <button type="button" onClick={onHome}>Back to Home</button> : null}</div></div>
  return <div className="morning-stage">
    <div className="morning-review-summary">
      <div className="morning-review-row"><span>Shift</span><strong>{shiftShortLabel(report.shift_kind)} — {report.shift_date}</strong></div>
      {principal ? <div className="morning-review-row"><span>Supervisor</span><strong>{principal.display_name}</strong></div> : null}
      <div className="morning-review-row"><span>Attendance</span><strong>{presentCount} present, {absentCount} absent</strong></div>
      {!construction ? <div className="morning-review-row morning-review-brothers"><span>Brothers Keeper</span><strong>{report.brothers_keeper || 'Not recorded'}</strong></div> : null}
      <div className="morning-review-row"><span>Safety</span><strong>{report.safety_reviewed_empty ? 'Reviewed — nothing to report' : `${openStopFix} Stop & Fix open, ${greenCards} green / ${redCards} red cards`}</strong></div>
      {construction ? <>
        <div className="morning-review-row"><span>Core work</span><strong>{report.construction_work_reviewed_empty ? 'Reviewed — no core work' : `${coreWork.length} item(s)`}</strong></div>
        <div className="morning-review-row"><span>Outstanding</span><strong>{report.construction_outstanding_reviewed_empty ? 'Nothing outstanding' : `${outstandingWork.length} item(s)`}</strong></div>
      </> : <>
        <div className="morning-review-row"><span>Machine work</span><strong>{report.machine_activity_reviewed_empty ? 'No machine work this shift' : `${report.machine_events.length} interval(s)`}</strong></div>
        <div className="morning-review-row"><span>Other activities</span><strong>{report.other_activities_reviewed_empty ? 'Nothing else to report' : report.other_activities.length}</strong></div>
      </>}
    </div>
    {construction && report.construction_work.length ? <details className="morning-review-detail" open><summary>Construction work</summary>{report.construction_work.map(item => <div key={item.id} className="construction-review-item"><strong>{formatConstructionLevel(item.level)} · {item.location}</strong><span>{item.task} · {item.status.replace('_', ' ')}{item.progress_percent !== null ? ` · ${item.progress_percent}%` : ''}</span>{item.update_text ? <span className="meta">Update: {item.update_text}</span> : null}{item.constraint_text ? <span className="meta">Constraint: {item.constraint_text}</span> : null}{item.next_action ? <span className="meta">Next: {item.next_action}</span> : null}</div>)}</details> : null}
    {!construction && report.machine_events.length ? <details className="morning-review-detail"><summary>Machine work</summary>{report.machine_events.map(event => <div key={event.id} className="meta">{machineLabel(machines, event.machine_id)} · {personName(people, event.person_id || '')} · {hhmm(event.start_time)}–{hhmm(event.end_time)}: {event.issue}</div>)}</details> : null}
    {report.attendance.filter(e => !e.present).length ? <details className="morning-review-detail"><summary>Absent</summary>{report.attendance.filter(e => !e.present).map(e => <div key={e.person_id} className="meta">{personName(people, e.person_id)}</div>)}</details> : null}
    {error ? <p className="error-text">{error}</p> : null}
    <div className="morning-stage-nav">{onBack ? <button type="button" onClick={onBack}>Back</button> : null}<button type="button" className="primary" disabled={pending} onClick={() => void submit()}>{pending ? 'Submitting…' : 'Submit shift report'}</button></div>
  </div>
}
