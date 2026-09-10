import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { morningApi } from './api'
import { formatShiftDate } from './format'
import type { Crew, ReportingModel, ShiftIdentity, ShiftKind, ShiftReport, SupervisorContext } from './types'

export function StartReport({ suggestion, supervisor, crews = [], reportingModel = 'tmm', demoMode = false, onStarted }: {
  suggestion?: ShiftIdentity; supervisor?: SupervisorContext; crews?: Crew[]; reportingModel?: ReportingModel; demoMode?: boolean
  onStarted: (report: ShiftReport) => void
}) {
  const [override, setOverride] = useState<ShiftKind | null>(null)
  const [crewIds, setCrewIds] = useState<string[]>([])
  const shiftKind = override ?? suggestion?.shift_kind ?? 'morning'
  const tmm = reportingModel === 'tmm'
  const toggleCrew = (id: string) => setCrewIds(current => current.includes(id) ? current.filter(item => item !== id) : [...current, id])
  const start = useMutation({
    mutationFn: () => morningApi<ShiftReport>('/api/morning/draft', {
      method: 'POST', body: JSON.stringify({ shift_date: suggestion?.shift_date, shift_kind: shiftKind, reporting_model: reportingModel, crew_ids: tmm ? crewIds : [] }),
    }), onSuccess: onStarted,
  })
  const disabled = !suggestion || start.isPending || (tmm && crewIds.length === 0)
  return <div className="morning-start-report">
    {demoMode ? <div className="morning-demo-banner"><strong>DEMO MODE</strong><span>Nothing you enter in this walkthrough will be saved to Morning.</span></div> : null}
    <div className="morning-start-kicker">{reportingModel === 'construction' ? 'Construction' : 'TMM'} workspace</div>
    <h2 className="morning-stage-title">Start shift report</h2>
    <dl className="morning-start-report-facts">
      <div className="morning-start-report-fact"><dt>Reporting date</dt><dd>{suggestion ? formatShiftDate(suggestion.shift_date) : '…'}</dd></div>
      <div className="morning-start-report-fact"><dt>Shift</dt><dd><div className="morning-auth-toggle morning-shift-toggle" role="radiogroup" aria-label="Shift"><button type="button" className={shiftKind === 'morning' ? 'active' : ''} onClick={() => setOverride('morning')}>Morning</button><button type="button" className={shiftKind === 'afternoon' ? 'active' : ''} onClick={() => setOverride('afternoon')}>Afternoon</button><button type="button" className={shiftKind === 'night' ? 'active' : ''} onClick={() => setOverride('night')}>Night</button></div></dd></div>
      <div className="morning-start-report-fact"><dt>Supervisor</dt><dd>{supervisor?.display_name || '…'}</dd></div>
      {!tmm ? <div className="morning-start-report-fact"><dt>Crew</dt><dd>{supervisor?.crew_name || 'No Construction crew linked — contact an administrator'}</dd></div> : null}
    </dl>
    {tmm ? <section className="morning-crew-picker" aria-labelledby="crew-picker-title"><div><h3 id="crew-picker-title">Select crew(s) for this shift</h3><p className="meta">Choose every crew you will supervise. Attendance will combine the personnel assigned to those crews.</p></div><div className="morning-crew-options">{crews.map(crew => <label key={crew.id} className={crewIds.includes(crew.id) ? 'selected' : ''}><input type="checkbox" checked={crewIds.includes(crew.id)} onChange={() => toggleCrew(crew.id)} /><span>{crew.name}</span></label>)}</div>{!crews.length ? <p className="error-text">No TMM crews are available. Add crews in Morning Control Centre first.</p> : <p className="meta">{crewIds.length ? `${crewIds.length} crew${crewIds.length === 1 ? '' : 's'} selected` : 'Select at least one crew to continue.'}</p>}</section> : null}
    {start.isError ? <p className="error-text">{start.error instanceof Error ? start.error.message : 'Could not start the report. Try again.'}</p> : null}
    <button type="button" className="primary" disabled={disabled} onClick={() => start.mutate()}>{start.isPending ? 'Starting…' : demoMode ? 'Start demo report' : 'Start report'}</button>
  </div>
}
