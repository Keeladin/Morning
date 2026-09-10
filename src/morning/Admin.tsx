import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { morningApi } from './api'
import type { Machine, Person } from './types'
import { WorkspaceAdministrators } from './WorkspaceAdministrators'
import { MorningIcon } from './ui'

type Crew = { id: string; name: string; created_at?: string }
type Account = {
  principal_id: string; username: string; display_name: string | null; role: string | null; status: string | null
  created_at: string; approved_at: string | null; person_id: string | null; person_name: string | null
  crew_id: string | null; crew_name: string | null; demo_mode: boolean
}
type ShiftPolicy = { timezone: string; morning_shift_start: string; afternoon_shift_start: string; night_shift_start: string; updated_at?: string }
type DailyReport = { reporting_date: string; status: 'waiting' | 'complete'; expected_inputs: { key: string; label: string; present: boolean }[]; detailed_text: string; compact_text: string }
type Section = 'machines' | 'personnel' | 'crews' | 'supervisors' | 'shift-policy' | 'daily-report' | 'administrators'

export function Admin() {
  const [section, setSection] = useState<Section>('machines')
  const tabs: { id: Section; label: string }[] = [
    { id: 'machines', label: 'Machines' }, { id: 'personnel', label: 'Personnel' },
    { id: 'crews', label: 'Crews' }, { id: 'supervisors', label: 'Supervisors' },
    { id: 'shift-policy', label: 'Shift policy' }, { id: 'daily-report', label: 'Daily report' }, { id: 'administrators', label: 'Administrators' },
  ]
  return <div className="morning-admin">
    <div className="morning-admin-head"><div className="morning-admin-title"><MorningIcon name="control"/><div><p className="eyebrow">System administration</p><h2>Morning Control Centre</h2><p className="meta">Keep machines, people, supervisors and reporting configuration clean, current and reliable.</p></div></div></div>
    <div className="morning-admin-nav" role="tablist">{tabs.map((tab) => <button key={tab.id} type="button" className={section === tab.id ? 'active' : ''} onClick={() => setSection(tab.id)}>{tab.label}</button>)}</div>
    {section === 'machines' ? <Machines /> : null}
    {section === 'personnel' ? <Personnel /> : null}
    {section === 'crews' ? <Crews /> : null}
    {section === 'supervisors' ? <Supervisors /> : null}
    {section === 'shift-policy' ? <ShiftPolicyPanel /> : null}
    {section === 'daily-report' ? <DailyReportPanel /> : null}
    {section === 'administrators' ? <WorkspaceAdministrators workspace="morning" endpoint="/api/morning/admin/workspace-admins" /> : null}
  </div>
}

function Machines() {
  const qc = useQueryClient()
  const query = useQuery({ queryKey:['admin-machines'], queryFn:() => morningApi<{machines:Machine[]}>('/api/morning/admin/machines') })
  const [machineId,setMachineId] = useState(''); const [machineType,setMachineType] = useState(''); const [area,setArea] = useState(''); const [editing,setEditing] = useState<string|null>(null)
  const invalidate = () => void qc.invalidateQueries({ queryKey:['admin-machines'] })
  const clear = () => { setMachineId(''); setMachineType(''); setArea(''); setEditing(null) }
  const fail = (error: unknown) => window.alert(error instanceof Error ? error.message : 'Machine change failed.')
  const save = useMutation({ mutationFn:() => editing
    ? morningApi(`/api/morning/admin/machines/${editing}`,{method:'PATCH',body:JSON.stringify({machine_id:machineId,machine_type:machineType||null,section:area||null})})
    : morningApi('/api/morning/admin/machines',{method:'POST',body:JSON.stringify({machine_id:machineId,machine_type:machineType||null,section:area||null})}), onSuccess:() => { clear(); invalidate() }, onError:fail })
  const active = useMutation({ mutationFn:({id,value}:{id:string;value:boolean}) => morningApi(`/api/morning/admin/machines/${id}/${value?'activate':'deactivate'}`,{method:'POST',body:'{}'}), onSuccess:invalidate, onError:fail })
  const scope = useMutation({ mutationFn:({id,value}:{id:string;value:boolean}) => morningApi(`/api/morning/admin/machines/${id}/control-room-scope`,{method:'POST',body:JSON.stringify({in_scope:value})}), onSuccess:invalidate, onError:fail })
  const remove = useMutation({ mutationFn:(id:string) => morningApi(`/api/morning/admin/machines/${id}`,{method:'DELETE'}), onSuccess:invalidate, onError:fail })
  const edit = (m:Machine) => { setEditing(m.id); setMachineId(m.machine_id); setMachineType(m.machine_type||''); setArea(m.section||'') }
  return <div className="morning-admin-stack"><section className="morning-admin-card"><h3>{editing?'Edit machine':'Add machine'}</h3><form className="morning-add-form" onSubmit={(e:FormEvent) => {e.preventDefault();if(machineId.trim())save.mutate()}}><input placeholder="Machine ID" value={machineId} onChange={(e)=>setMachineId(e.target.value)} required/><input placeholder="Machine type" value={machineType} onChange={(e)=>setMachineType(e.target.value)}/><input placeholder="Section" value={area} onChange={(e)=>setArea(e.target.value)}/><button className="primary" disabled={save.isPending}>{editing?'Save changes':'Add machine'}</button>{editing?<button type="button" onClick={clear}>Cancel</button>:null}</form></section><section className="morning-admin-card"><h3>Machines</h3>{query.isLoading?<p className="empty">Loading…</p>:null}{query.data?.machines.map((m)=><div key={m.id} className="morning-entry-row"><div><strong>{m.machine_id}</strong><div className="meta">{[m.machine_type,m.section].filter(Boolean).join(' · ')||'No type / section'}</div><div className="meta">{m.active?'Active':'Inactive'} · {m.control_room_scope?'Control-room scope':'Not in control-room scope'}</div></div><div className="morning-entry-actions"><button type="button" onClick={()=>edit(m)}>Edit</button><button type="button" onClick={()=>active.mutate({id:m.id,value:!m.active})}>{m.active?'Deactivate':'Activate'}</button><button type="button" onClick={()=>scope.mutate({id:m.id,value:!m.control_room_scope})}>{m.control_room_scope?'Remove scope':'Add scope'}</button><button type="button" className="danger" onClick={()=>{if(window.confirm(`Delete ${m.machine_id}? This is only allowed when it has no operational history.`))remove.mutate(m.id)}}>Delete</button></div></div>)}</section></div>
}

function Personnel() {
  const qc=useQueryClient(); const people=useQuery({queryKey:['admin-persons'],queryFn:()=>morningApi<{persons:Person[]}>('/api/morning/admin/persons')}); const crews=useQuery({queryKey:['admin-crews'],queryFn:()=>morningApi<{crews:Crew[]}>('/api/morning/admin/crews')})
  const [name,setName]=useState(''); const [employeeNumber,setEmployeeNumber]=useState(''); const [role,setRole]=useState(''); const [crewId,setCrewId]=useState(''); const [editing,setEditing]=useState<string|null>(null)
  const invalidate=()=>void qc.invalidateQueries({queryKey:['admin-persons']}); const clear=()=>{setName('');setEmployeeNumber('');setRole('');setCrewId('');setEditing(null)}
  const fail=(error:unknown)=>window.alert(error instanceof Error?error.message:'Personnel change failed.')
  const save=useMutation({mutationFn:()=>editing?morningApi(`/api/morning/admin/persons/${editing}`,{method:'PATCH',body:JSON.stringify({name,employee_number:employeeNumber||null,role:role||null,crew_id:crewId||null})}):morningApi('/api/morning/admin/persons',{method:'POST',body:JSON.stringify({name,employee_number:employeeNumber||null,role:role||null,crew_id:crewId||null})}),onSuccess:()=>{clear();invalidate()},onError:fail})
  const assign=useMutation({mutationFn:({id,crew}:{id:string;crew:string})=>morningApi(`/api/morning/admin/persons/${id}`,{method:'PATCH',body:JSON.stringify({crew_id:crew||null})}),onSuccess:invalidate,onError:fail})
  const active=useMutation({mutationFn:({id,value}:{id:string;value:boolean})=>morningApi(`/api/morning/admin/persons/${id}/${value?'activate':'deactivate'}`,{method:'POST',body:'{}'}),onSuccess:invalidate,onError:fail})
  const remove=useMutation({mutationFn:(id:string)=>morningApi(`/api/morning/admin/persons/${id}`,{method:'DELETE'}),onSuccess:invalidate,onError:fail})
  const edit=(person:Person)=>{setEditing(person.id);setName(person.name);setEmployeeNumber(person.employee_number||'');setRole(person.role||'');setCrewId(person.crew_id||'')}
  return <div className="morning-admin-stack"><section className="morning-admin-card"><h3>{editing?'Edit person':'Add person'}</h3><form className="morning-add-form" onSubmit={(e:FormEvent)=>{e.preventDefault();if(name.trim())save.mutate()}}><input placeholder="Full name" value={name} onChange={(e)=>setName(e.target.value)} required/><input placeholder="Employee number" value={employeeNumber} onChange={(e)=>setEmployeeNumber(e.target.value)}/><input placeholder="Role / trade / job description" value={role} onChange={(e)=>setRole(e.target.value)}/><select value={crewId} onChange={(e)=>setCrewId(e.target.value)}><option value="">No crew</option>{crews.data?.crews.map((c)=><option key={c.id} value={c.id}>{c.name}</option>)}</select><button className="primary" disabled={save.isPending}>{editing?'Save changes':'Add person'}</button>{editing?<button type="button" onClick={clear}>Cancel</button>:null}</form></section><section className="morning-admin-card"><h3>Personnel</h3>{people.data?.persons.map((person)=><div key={person.id} className="morning-entry-row"><div><strong>{person.name}</strong><div className="meta">{person.role||'No role / trade set'}{person.employee_number?` · ${person.employee_number}`:''} · {person.active?'Active':'Inactive'}</div></div><div className="morning-entry-actions"><button type="button" onClick={()=>edit(person)}>Edit</button><select value={person.crew_id||''} onChange={(e)=>assign.mutate({id:person.id,crew:e.target.value})}><option value="">No crew</option>{crews.data?.crews.map((c)=><option key={c.id} value={c.id}>{c.name}</option>)}</select><button type="button" onClick={()=>active.mutate({id:person.id,value:!person.active})}>{person.active?'Deactivate':'Activate'}</button><button type="button" className="danger" onClick={()=>{if(window.confirm(`Delete ${person.name}? This is only allowed when they have no operational history.`))remove.mutate(person.id)}}>Delete</button></div></div>)}</section></div>
}

function Crews() {
  const qc=useQueryClient(); const query=useQuery({queryKey:['admin-crews'],queryFn:()=>morningApi<{crews:Crew[]}>('/api/morning/admin/crews')})
  const [name,setName]=useState(''); const [editing,setEditing]=useState<Crew|null>(null)
  const refresh=()=>void qc.invalidateQueries({queryKey:['admin-crews']}); const fail=(error:unknown)=>window.alert(error instanceof Error?error.message:'Crew change failed.')
  const clear=()=>{setName('');setEditing(null)}
  const save=useMutation({mutationFn:()=>editing?morningApi(`/api/morning/admin/crews/${editing.id}`,{method:'PATCH',body:JSON.stringify({name})}):morningApi('/api/morning/admin/crews',{method:'POST',body:JSON.stringify({name})}),onSuccess:()=>{clear();refresh()},onError:fail})
  const remove=useMutation({mutationFn:(id:string)=>morningApi(`/api/morning/admin/crews/${id}`,{method:'DELETE'}),onSuccess:()=>{clear();refresh();void qc.invalidateQueries({queryKey:['admin-persons']})},onError:fail})
  const edit=(crew:Crew)=>{setEditing(crew);setName(crew.name)}
  return <div className="morning-admin-stack"><section className="morning-admin-card"><h3>{editing?'Edit crew':'Add crew'}</h3><form className="morning-add-form" onSubmit={(e:FormEvent)=>{e.preventDefault();if(name.trim())save.mutate()}}><input placeholder="Crew name" value={name} onChange={(e)=>setName(e.target.value)} required/><button className="primary" disabled={save.isPending}>{editing?'Save changes':'Add crew'}</button>{editing?<button type="button" onClick={clear}>Cancel</button>:null}</form></section><section className="morning-admin-card"><h3>Crews</h3><p className="meta">Crews can be renamed at any time. Deletion is only allowed when no personnel, reports or Construction configuration still reference the crew.</p>{query.data?.crews.map((c)=><div key={c.id} className="morning-entry-row"><strong>{c.name}</strong><div className="morning-entry-actions"><button type="button" onClick={()=>edit(c)}>Edit</button><button type="button" className="danger" onClick={()=>{if(window.confirm(`Delete ${c.name}?`))remove.mutate(c.id)}}>Delete</button></div></div>)}</section></div>
}

function Supervisors() {
  const qc=useQueryClient(); const accounts=useQuery({queryKey:['admin-accounts'],queryFn:()=>morningApi<{accounts:Account[]}>('/api/morning/admin/accounts')}); const people=useQuery({queryKey:['admin-persons'],queryFn:()=>morningApi<{persons:Person[]}>('/api/morning/admin/persons')}); const invalidate=()=>void qc.invalidateQueries({queryKey:['admin-accounts']})
  const [editing,setEditing]=useState<string|null>(null); const [displayName,setDisplayName]=useState(''); const [username,setUsername]=useState('')
  const fail=(error:unknown)=>window.alert(error instanceof Error?error.message:'Supervisor change failed.')
  const approve=useMutation({mutationFn:(id:string)=>morningApi(`/api/morning/admin/accounts/${id}/approve`,{method:'POST',body:'{}'}),onSuccess:invalidate,onError:fail})
  const link=useMutation({mutationFn:({id,personId}:{id:string;personId:string})=>morningApi(`/api/morning/admin/accounts/${id}/link`,{method:'POST',body:JSON.stringify({person_id:personId||null})}),onSuccess:invalidate,onError:fail})
  const save=useMutation({mutationFn:()=>morningApi(`/api/morning/admin/accounts/${editing}`,{method:'PATCH',body:JSON.stringify({display_name:displayName,username})}),onSuccess:()=>{setEditing(null);invalidate()},onError:fail})
  const active=useMutation({mutationFn:({id,value}:{id:string;value:boolean})=>morningApi(`/api/morning/admin/accounts/${id}/${value?'activate':'deactivate'}`,{method:'POST',body:'{}'}),onSuccess:invalidate,onError:fail})
  const remove=useMutation({mutationFn:(id:string)=>morningApi(`/api/morning/admin/accounts/${id}`,{method:'DELETE'}),onSuccess:invalidate,onError:fail})
  const demo=useMutation({mutationFn:({id,value}:{id:string;value:boolean})=>morningApi(`/api/morning/admin/accounts/${id}`,{method:'PATCH',body:JSON.stringify({demo_mode:value})}),onSuccess:invalidate,onError:fail})
  const edit=(a:Account)=>{setEditing(a.principal_id);setDisplayName(a.display_name||'');setUsername(a.username)}
  return <div className="morning-admin-stack">{editing?<section className="morning-admin-card"><h3>Edit supervisor</h3><form className="morning-add-form" onSubmit={(e:FormEvent)=>{e.preventDefault();if(displayName.trim()&&username.trim())save.mutate()}}><input placeholder="Display name" value={displayName} onChange={e=>setDisplayName(e.target.value)} required/><input placeholder="Username" value={username} onChange={e=>setUsername(e.target.value)} required/><button className="primary" disabled={save.isPending}>Save changes</button><button type="button" onClick={()=>setEditing(null)}>Cancel</button></form></section>:null}<section className="morning-admin-card"><h3>Supervisor accounts</h3><p className="meta">New registrations remain blocked until approved here. Deactivated supervisors cannot sign in.</p>{accounts.data?.accounts.map((a)=><div key={a.principal_id} className="morning-entry-row"><div><strong>{a.display_name||a.username}</strong><div className="meta">@{a.username} · {a.approved_at?'Approved':'Pending approval'} · {a.status==='suspended'?'Inactive':'Active'}{a.demo_mode?' · DEMO MODE':''}</div><div className="meta">{a.person_name?`${a.person_name}${a.crew_name?` · ${a.crew_name}`:''}`:'Not linked to personnel'}</div></div><div className="morning-entry-actions"><button type="button" onClick={()=>edit(a)}>Edit</button>{!a.approved_at?<button type="button" className="primary" onClick={()=>approve.mutate(a.principal_id)}>Approve</button>:null}<select value={a.person_id||''} onChange={(e)=>link.mutate({id:a.principal_id,personId:e.target.value})}><option value="">No personnel link</option>{people.data?.persons.map((person)=><option key={person.id} value={person.id}>{person.name}</option>)}</select><button type="button" onClick={()=>active.mutate({id:a.principal_id,value:a.status==='suspended'})}>{a.status==='suspended'?'Activate':'Deactivate'}</button><button type="button" onClick={()=>demo.mutate({id:a.principal_id,value:!a.demo_mode})}>{a.demo_mode?'Disable demo':'Make demo'}</button><button type="button" className="danger" onClick={()=>{if(window.confirm(`Delete supervisor ${a.display_name||a.username}? This is only allowed when there is no history.`))remove.mutate(a.principal_id)}}>Delete</button></div></div>)}</section></div>
}

function ShiftPolicyPanel() {
  const qc=useQueryClient(); const query=useQuery({queryKey:['admin-shift-policy'],queryFn:()=>morningApi<ShiftPolicy>('/api/morning/admin/shift-policy')}); const [timezone,setTimezone]=useState('Africa/Johannesburg'); const [morning,setMorning]=useState('06:00'); const [afternoon,setAfternoon]=useState('14:00'); const [night,setNight]=useState('22:00')
  useEffect(()=>{if(query.data){setTimezone(query.data.timezone);setMorning(query.data.morning_shift_start);setAfternoon(query.data.afternoon_shift_start);setNight(query.data.night_shift_start)}},[query.data])
  const save=useMutation({mutationFn:()=>morningApi('/api/morning/admin/shift-policy',{method:'PUT',body:JSON.stringify({timezone,morning_shift_start:morning,afternoon_shift_start:afternoon,night_shift_start:night})}),onSuccess:()=>void qc.invalidateQueries({queryKey:['admin-shift-policy']})})
  return <section className="morning-admin-card"><h3>Shift policy</h3><p className="meta">Three-shift operating cycle. The Night shift belongs to the date on which it finishes.</p><form className="morning-add-form" onSubmit={(e:FormEvent)=>{e.preventDefault();save.mutate()}}><label>Timezone<input value={timezone} onChange={(e)=>setTimezone(e.target.value)}/></label><div className="morning-time-row"><label>Morning shift start<input type="time" value={morning} onChange={(e)=>setMorning(e.target.value)}/></label><label>Afternoon shift start<input type="time" value={afternoon} onChange={(e)=>setAfternoon(e.target.value)}/></label><label>Night shift start<input type="time" value={night} onChange={(e)=>setNight(e.target.value)}/></label></div><div className="meta">Current cycle: {morning}–{afternoon} · {afternoon}–{night} · {night}–{morning}</div><button className="primary" disabled={save.isPending}>{save.isPending?'Saving…':'Save shift policy'}</button></form></section>
}

function DailyReportPanel() {
  const [date,setDate]=useState(()=>new Date().toISOString().slice(0,10)); const [requireControlRoom,setRequireControlRoom]=useState(true); const [report,setReport]=useState<DailyReport|null>(null); const [error,setError]=useState<string|null>(null); const [loading,setLoading]=useState(false)
  const load=async()=>{setLoading(true);setError(null);try{setReport(await morningApi<DailyReport>(`/api/morning/admin/reports/${date}?require_control_room=${requireControlRoom?'true':'false'}`))}catch(err){setError(err instanceof Error?err.message:'Could not load report')}finally{setLoading(false)}}
  return <section className="morning-admin-card"><h3>24-hour report</h3><div className="morning-add-form"><label>Reporting date<input type="date" value={date} onChange={(e)=>setDate(e.target.value)}/></label><label className="morning-checkbox"><input type="checkbox" checked={requireControlRoom} onChange={(e)=>setRequireControlRoom(e.target.checked)}/>Require control-room input for completeness</label><button type="button" className="primary" onClick={()=>void load()} disabled={loading}>{loading?'Loading…':'Generate report'}</button></div>{error?<p className="error-text">{error}</p>:null}{report?<div className="morning-report-preview"><p className={report.status==='complete'?'morning-status-ok':'morning-status-warn'}>{report.status==='complete'?'Complete':'Waiting for inputs'}</p><div className="meta">{report.expected_inputs.map((i)=>`${i.present?'✓':'○'} ${i.label}`).join(' · ')}</div><h4>Department summary</h4><pre>{report.compact_text}</pre><details><summary>Detailed report</summary><pre>{report.detailed_text}</pre></details></div>:null}</section>
}
