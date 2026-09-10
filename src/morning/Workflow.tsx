import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isOfflineReportPending, morningApi, syncOfflineReports } from './api'
import { Home } from './Home'
import { StartReport } from './StartReport'
import { SyncIndicator } from './SyncIndicator'
import { AttendanceStage } from './stages/Attendance'
import { BrothersKeeperStage } from './stages/BrothersKeeper'
import { ConstructionWorkStage } from './stages/ConstructionWork'
import { MachineActivityStage } from './stages/MachineActivity'
import { OtherActivitiesStage } from './stages/OtherActivities'
import { ReviewStage } from './stages/Review'
import { SafetyStage } from './stages/Safety'
import type { Crew, Machine, MorningPrincipal, Person, ReportingModel, ShiftIdentity, ShiftReport, SupervisorContext, SyncState } from './types'
import { MorningIcon } from './ui'
import { shiftLabel } from './format'

export type Stage = 'attendance' | 'brothers' | 'safety' | 'machines' | 'other' | 'core' | 'outstanding' | 'review'
const TMM_STAGES: Stage[] = ['attendance', 'brothers', 'safety', 'machines', 'other', 'review']
const CONSTRUCTION_STAGES: Stage[] = ['attendance', 'safety', 'core', 'outstanding', 'review']
const STAGE_LABELS: Record<Stage, string> = {
  attendance: 'Attendance', brothers: 'Brothers Keeper', safety: 'Safety', machines: 'Machine activity', other: 'Other activities',
  core: 'Core work', outstanding: 'Outstanding work', review: 'Summary & submit',
}
const STEP_LABELS: Record<Stage, string> = {
  attendance: 'Attendance', brothers: 'Brothers', safety: 'Safety', machines: 'Machines', other: 'Other',
  core: 'Core', outstanding: 'Outstanding', review: 'Review',
}
const STAGE_ICONS: Record<Stage, 'people'|'shield'|'machine'|'activity'|'review'|'control'> = {
  attendance:'people', brothers:'people', safety:'shield', machines:'machine', other:'activity', core:'control', outstanding:'activity', review:'review',
}
const STAGE_COPY: Record<Stage, string> = {
  attendance:'Mark attendance for the crew or crews selected for this shift.', brothers:'Capture one meaningful workforce safety contribution.', safety:'Record Stop & Fix items and red or green cards.', machines:'Log machine work, times and the person assigned.', other:'Capture relevant work outside machine activity.', core:'Capture the crew’s core construction work.', outstanding:'Record outstanding construction work and next actions.', review:'Check every section before submitting the shift report.',
}

export function sectionCompletion(report: ShiftReport, people: Person[], stages: Stage[] = TMM_STAGES): Record<Stage, boolean> {
  const completion: Record<Stage, boolean> = {
    attendance: people.length > 0 && people.every(person => report.attendance.some(entry => entry.person_id === person.id)),
    brothers: Boolean(report.brothers_keeper?.trim()),
    safety: Boolean(report.stop_fix.length || report.cards.length || report.safety_reviewed_empty),
    machines: Boolean(report.machine_events.length || report.machine_activity_reviewed_empty),
    other: Boolean(report.other_activities.length || report.other_activities_reviewed_empty),
    core: Boolean(report.construction_work.some(item => item.kind === 'core') || report.construction_work_reviewed_empty),
    outstanding: Boolean(report.construction_work.some(item => item.kind === 'outstanding') || report.construction_outstanding_reviewed_empty),
    review: report.status === 'submitted',
  }
  return Object.fromEntries(Object.entries(completion).map(([key, value]) => [key, stages.includes(key as Stage) ? value : true])) as Record<Stage, boolean>
}
export function resumeStage(report: ShiftReport, people: Person[], stages: Stage[] = TMM_STAGES): Stage {
  const completion = sectionCompletion(report, people, stages)
  return stages.find(stage => !completion[stage]) ?? 'review'
}

export function Workflow({ principal, reportingModel = 'tmm' }: { principal: MorningPrincipal; reportingModel?: ReportingModel }) {
  const construction = reportingModel === 'construction'
  const stages = construction ? CONSTRUCTION_STAGES : TMM_STAGES
  const [stage, setStage] = useState<Stage>('attendance')
  const [surface, setSurface] = useState<'home' | 'report'>(construction ? 'report' : 'home')
  const [sync, setSync] = useState<SyncState>({ status: navigator.onLine ? 'idle' : 'offline' })
  const [resumed, setResumed] = useState(false)
  const initializedReport = useRef('')
  const queryClient = useQueryClient()
  const shiftQuery = useQuery({ queryKey: ['morning-shift'], queryFn: () => morningApi<ShiftIdentity>('/api/morning/shift') })
  const meQuery = useQuery({ queryKey: ['morning-me'], queryFn: () => morningApi<SupervisorContext>('/api/morning/me') })
  const draftQuery = useQuery({ queryKey: ['morning-draft', reportingModel], queryFn: () => morningApi<{ report: ShiftReport | null }>(`/api/morning/draft?reporting_model=${reportingModel}`) })
  const machinesQuery = useQuery({ queryKey: ['morning-machines'], queryFn: () => morningApi<{ machines: Machine[] }>('/api/morning/machines'), enabled: !construction })
  const crewsQuery = useQuery({ queryKey: ['morning-tmm-crews'], queryFn: () => morningApi<{ crews: Crew[] }>('/api/morning/crews'), enabled: !construction })
  const report = draftQuery.data?.report ?? null
  const rosterQuery = useQuery({ queryKey: ['morning-roster', report?.id], queryFn: () => morningApi<{ people: Person[] }>(`/api/morning/roster?report_id=${encodeURIComponent(report?.id || '')}`), enabled: construction && Boolean(report) })
  const tmmPersonnelQuery = useQuery({ queryKey: ['morning-tmm-personnel'], queryFn: () => morningApi<{ people: Person[] }>('/api/morning/personnel'), enabled: !construction })
  const participantsQuery = useQuery({ queryKey: ['morning-participants', report?.id], queryFn: () => morningApi<{ people: Person[] }>(`/api/morning/reports/${report?.id}/participants`), enabled: Boolean(report) && report?.status === 'submitted' })
  const machines = machinesQuery.data?.machines || []
  const crews = crewsQuery.data?.crews || []
  const assignablePeople = tmmPersonnelQuery.data?.people || []
  const tmmRoster = report ? assignablePeople.filter(person => Boolean(person.crew_id && report.crew_ids.includes(person.crew_id))) : []
  const rosterPeople = construction ? (rosterQuery.data?.people || []) : tmmRoster
  const reportPeople = (report?.status === 'submitted' && !principal.demo_mode ? participantsQuery.data?.people : rosterPeople) || []
  const selectedCrewNames = report ? crews.filter(crew => report.crew_ids.includes(crew.id)).map(crew => crew.name) : []
  const completion = useMemo(() => report ? sectionCompletion(report, rosterPeople, stages) : null, [report, rosterPeople, construction])
  const refreshReport = (updated: ShiftReport) => queryClient.setQueryData(['morning-draft', reportingModel], { report: updated })
  const abandon = useMutation({ mutationFn: () => morningApi<ShiftReport>(`/api/morning/reports/${report?.id}/abandon`, { method: 'POST', body: '{}' }), onSuccess: () => queryClient.setQueryData(['morning-draft', reportingModel], { report: null }) })
  useEffect(() => {
    const online = () => {
      setSync(current => current.status === 'offline' ? { status: 'saving', message: 'Connection restored — synchronizing local changes…' } : current)
      void syncOfflineReports()
    }
    const offline = () => setSync({ status: 'offline', message: 'Working offline — changes are saved on this device and will synchronize automatically.' })
    const synced = (event: Event) => {
      const updated = (event as CustomEvent<{ report: ShiftReport }>).detail?.report
      if (!updated || updated.reporting_model !== reportingModel) return
      refreshReport(updated); setSync({ status: 'saved', message: 'Local changes synchronized with Morning.' })
      void queryClient.invalidateQueries({ queryKey: ['morning-draft', reportingModel] })
    }
    const failed = (event: Event) => {
      const message = (event as CustomEvent<{ message?: string }>).detail?.message
      setSync({ status: 'failed', message: message || 'Local changes are still waiting to synchronize.' })
    }
    window.addEventListener('online', online); window.addEventListener('offline', offline)
    window.addEventListener('morning:report-synced', synced); window.addEventListener('morning:sync-failed', failed)
    return () => {
      window.removeEventListener('online', online); window.removeEventListener('offline', offline)
      window.removeEventListener('morning:report-synced', synced); window.removeEventListener('morning:sync-failed', failed)
    }
  }, [reportingModel])
  useEffect(() => {
    if (report && isOfflineReportPending(report.id)) {
      setSync({ status: 'offline', message: navigator.onLine ? 'Saved locally — waiting to synchronize with Morning.' : 'Working offline — changes are saved on this device and will synchronize automatically.' })
    }
  }, [report?.id, report?.updated_at])
  useEffect(() => {
    if (report?.status === 'draft' && rosterPeople.length && initializedReport.current !== report.id) {
      const hasConstruction = report.construction_work.length > 0 || report.construction_work_reviewed_empty || report.construction_outstanding_reviewed_empty
      const hasTmm = report.machine_events.length > 0 || report.other_activities.length > 0 || report.machine_activity_reviewed_empty || report.other_activities_reviewed_empty
      setStage(resumeStage(report, rosterPeople, stages))
      setResumed(report.attendance.length > 0 || Boolean(report.brothers_keeper) || report.stop_fix.length > 0 || report.cards.length > 0 || hasConstruction || hasTmm || report.safety_reviewed_empty)
      initializedReport.current = report.id
    }
  }, [report, rosterPeople, construction])
  const confirmAndAbandon = () => { if (report && window.confirm('Abandon this draft? You will not be able to resume it.')) abandon.mutate() }
  if (shiftQuery.isError || draftQuery.isError) return <div className="offline-banner">Could not reach Morning. Check your connection.</div>
  if (shiftQuery.isLoading || draftQuery.isLoading || meQuery.isLoading) return <p className="morning-loading">Loading your shift…</p>
  if (!construction && surface === 'home') return <Home principal={principal} hasDraft={Boolean(report?.status === 'draft')} demoMode={Boolean(principal.demo_mode)} onOpenReport={() => setSurface('report')} />
  if (!report) return <div className="morning-workflow"><StartReport suggestion={shiftQuery.data} supervisor={meQuery.data} crews={crews} reportingModel={reportingModel} demoMode={Boolean(principal.demo_mode)} onStarted={started => queryClient.setQueryData(['morning-draft', reportingModel], { report: started })} /></div>
  if (report.status === 'submitted') return <div className="morning-workflow"><ReviewStage report={report} machines={machines} people={reportPeople} principal={principal} submitted onHome={!construction ? () => setSurface('home') : undefined} /></div>

  return <div className={construction ? 'morning-workflow construction-workflow' : 'morning-workflow'}>
    {principal.demo_mode ? <div className="morning-demo-banner"><strong>DEMO MODE</strong><span>Walk through the real workflow — nothing in this report will be saved to production.</span></div> : null}
    {construction ? <div className="construction-workspace-strip"><span>Morning / Construction</span><strong>Shift reporting</strong></div> : null}
    <div className="morning-shift-banner"><div className="morning-shift-banner-info"><strong>{shiftLabel(report.shift_kind)}</strong><span>{report.shift_date}{!construction && selectedCrewNames.length ? ` · ${selectedCrewNames.join(' + ')}` : ''}</span></div><div className="morning-shift-actions">{!construction ? <button type="button" className="ghost" onClick={() => setSurface('home')}>Home</button> : null}<button type="button" className="ghost" onClick={confirmAndAbandon} disabled={abandon.isPending}>Abandon draft</button></div></div>
    {resumed ? <p className="morning-resumed">Draft resumed · last saved {new Date(report.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p> : null}
    <SyncIndicator state={sync} lastSaved={report.updated_at} />
    <div className={`morning-stepper ${construction ? 'five' : 'six'}`} aria-label="Report progress">{stages.map((item, index) => <button type="button" key={item} disabled={item !== stage && !completion?.[item]} onClick={() => setStage(item)} className={['morning-step', item === stage ? 'active' : '', completion?.[item] ? 'done' : ''].filter(Boolean).join(' ')}><span>{index + 1}</span><small>{STEP_LABELS[item]}</small></button>)}</div>
    <div className="morning-stage-heading"><MorningIcon name={STAGE_ICONS[stage]} /><div><p className="morning-stage-kicker">Step {stages.indexOf(stage) + 1} of {stages.length}</p><h2 className="morning-stage-title">{STAGE_LABELS[stage]}</h2><p>{STAGE_COPY[stage]}</p></div></div>
    <div hidden={stage !== 'attendance'}><AttendanceStage report={report} people={rosterPeople} onUpdated={refreshReport} onSync={setSync} onNext={() => setStage(construction ? 'safety' : 'brothers')} /></div>
    {!construction ? <div hidden={stage !== 'brothers'}><BrothersKeeperStage report={report} onUpdated={refreshReport} onSync={setSync} onNext={() => setStage('safety')} onBack={() => setStage('attendance')} /></div> : null}
    <div hidden={stage !== 'safety'}><SafetyStage report={report} onUpdated={refreshReport} onSync={setSync} onNext={() => setStage(construction ? 'core' : 'machines')} onBack={() => setStage(construction ? 'attendance' : 'brothers')} nextLabel={construction ? 'Core work' : 'Machine activity'} /></div>
    {construction ? <>
      <div hidden={stage !== 'core'}><ConstructionWorkStage report={report} kind="core" onUpdated={refreshReport} onSync={setSync} onNext={() => setStage('outstanding')} onBack={() => setStage('safety')} /></div>
      <div hidden={stage !== 'outstanding'}><ConstructionWorkStage report={report} kind="outstanding" onUpdated={refreshReport} onSync={setSync} onNext={() => setStage('review')} onBack={() => setStage('core')} /></div>
    </> : <>
      <div hidden={stage !== 'machines'}><MachineActivityStage report={report} machines={machines} people={assignablePeople} onUpdated={refreshReport} onSync={setSync} onNext={() => setStage('other')} onBack={() => setStage('safety')} /></div>
      <div hidden={stage !== 'other'}><OtherActivitiesStage report={report} onUpdated={refreshReport} onSync={setSync} onNext={() => setStage('review')} onBack={() => setStage('machines')} /></div>
    </>}
    <div hidden={stage !== 'review'}><ReviewStage report={report} machines={machines} people={reportPeople} principal={principal} onBack={() => setStage(construction ? 'outstanding' : 'other')} onSubmitted={refreshReport} /></div>
    {!construction ? <nav className="morning-bottom-nav" aria-label="Report navigation"><button type="button" onClick={() => setSurface('home')}><MorningIcon name="home"/><span>Home</span></button><button type="button" className={stage === 'attendance' ? 'active' : ''} onClick={() => setStage('attendance')}><MorningIcon name="people"/><span>Attendance</span></button><button type="button" className={stage === 'brothers' ? 'active' : ''} disabled={!completion?.attendance} onClick={() => setStage('brothers')}><MorningIcon name="people"/><span>Brothers</span></button><button type="button" className={stage === 'safety' ? 'active' : ''} disabled={!completion?.brothers} onClick={() => setStage('safety')}><MorningIcon name="shield"/><span>Safety</span></button><button type="button" className={['machines','other','review'].includes(stage) ? 'active' : ''} disabled={!completion?.safety} onClick={() => setStage(resumeStage(report, rosterPeople, stages))}><MorningIcon name="control"/><span>More</span></button></nav> : null}
  </div>
}
