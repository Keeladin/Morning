import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { morningApi } from './api'
import { formatConstructionLevel } from './format'
import { WorkspaceAdministrators } from './WorkspaceAdministrators'
import type { Person } from './types'

type Level = { id:string; level:string; active:boolean; created_at:string; retired_at:string|null }
type Workstream = { id:string; name:string; active:boolean; created_at:string; retired_at:string|null }
type Crew = { crew_id:string; name:string; workstream_id:string|null; workstream_name:string|null; active:boolean; created_at:string }
type Account = { principal_id:string; username:string; display_name:string; role:string; approved_at:string|null; person_id:string|null; person_name:string|null; crew_id:string|null }
type Config = { levels:Level[]; workstreams:Workstream[]; crews:Crew[]; persons:Person[]; accounts:Account[] }
type Section = 'levels'|'workstreams'|'crews'|'people'|'supervisors'|'administrators'

export function ConstructionAdmin() {
  const [section,setSection] = useState<Section>('levels')
  const tabs: {id:Section;label:string}[] = [
    {id:'levels',label:'Levels'}, {id:'workstreams',label:'Workstreams'}, {id:'crews',label:'Crews'},
    {id:'people',label:'People'}, {id:'supervisors',label:'Supervisors'}, {id:'administrators',label:'Administrators'},
  ]
  return <div className="morning-admin construction-admin">
    <div className="morning-admin-head"><div><h2>Construction administration</h2><p className="meta">Interim workspace configuration for Construction Morning.</p></div></div>
    <div className="morning-admin-nav" role="tablist">{tabs.map(tab => <button key={tab.id} type="button" className={section===tab.id?'active':''} onClick={()=>setSection(tab.id)}>{tab.label}</button>)}</div>
    {section==='levels'?<Levels/>:null}
    {section==='workstreams'?<Workstreams/>:null}
    {section==='crews'?<Crews/>:null}
    {section==='people'?<People/>:null}
    {section==='supervisors'?<Supervisors/>:null}
    {section==='administrators'?<WorkspaceAdministrators workspace="construction" endpoint="/api/morning/admin/construction/admins"/>:null}
  </div>
}

function useConfig(){ return useQuery({queryKey:['construction-admin-config'],queryFn:()=>morningApi<Config>('/api/morning/admin/construction/config')}) }
function useRefresh(){ const qc=useQueryClient(); return ()=>void qc.invalidateQueries({queryKey:['construction-admin-config']}) }

function Levels(){
  const query=useConfig(); const refresh=useRefresh(); const [level,setLevel]=useState('')
  const create=useMutation({mutationFn:()=>morningApi('/api/morning/admin/construction/levels',{method:'POST',body:JSON.stringify({level})}),onSuccess:()=>{setLevel('');refresh()}})
  const active=useMutation({mutationFn:({id,value}:{id:string;value:boolean})=>morningApi(`/api/morning/admin/construction/levels/${id}/${value?'activate':'deactivate'}`,{method:'POST',body:'{}'}),onSuccess:refresh})
  const update=useMutation({mutationFn:({id,level}:{id:string;level:string})=>morningApi(`/api/morning/admin/construction/levels/${id}`,{method:'PATCH',body:JSON.stringify({level})}),onSuccess:refresh})
  const edit=(item:Level)=>{const next=window.prompt('Edit level',item.level);if(next!==null&&/^\s*\d+(?:\s*[nNsS])?\s*$/.test(next)&&next.replace(/\s/g,'').toUpperCase()!==item.level)update.mutate({id:item.id,level:next})}
  return <div className="morning-admin-stack"><section className="morning-admin-card"><h3>Add active level</h3><form className="morning-add-form" onSubmit={(e:FormEvent)=>{e.preventDefault();if(/^\s*\d+(?:\s*[nNsS])?\s*$/.test(level))create.mutate()}}><label>Level<input placeholder="813, 813N or 813S" value={level} onChange={e=>setLevel(e.target.value)}/></label><button className="primary" disabled={create.isPending}>Add level</button></form></section><section className="morning-admin-card"><h3>Levels</h3>{query.data?.levels.map(item=><div key={item.id} className="morning-entry-row"><div><strong>{formatConstructionLevel(item.level)}</strong><div className="meta">{item.active?'Active':'Inactive'}</div></div><div className="morning-entry-actions"><button type="button" disabled={update.isPending} onClick={()=>edit(item)}>Edit</button><button type="button" onClick={()=>active.mutate({id:item.id,value:!item.active})}>{item.active?'Deactivate':'Activate'}</button></div></div>)}</section></div>
}

function Workstreams(){
  const query=useConfig(); const refresh=useRefresh(); const [name,setName]=useState('')
  const create=useMutation({mutationFn:()=>morningApi('/api/morning/admin/construction/workstreams',{method:'POST',body:JSON.stringify({name})}),onSuccess:()=>{setName('');refresh()}})
  const active=useMutation({mutationFn:({id,value}:{id:string;value:boolean})=>morningApi(`/api/morning/admin/construction/workstreams/${id}/${value?'activate':'deactivate'}`,{method:'POST',body:'{}'}),onSuccess:refresh})
  return <div className="morning-admin-stack"><section className="morning-admin-card"><h3>Add workstream</h3><form className="morning-add-form" onSubmit={(e:FormEvent)=>{e.preventDefault();if(name.trim())create.mutate()}}><label>Workstream name<input placeholder="Main Construction" value={name} onChange={e=>setName(e.target.value)}/></label><button className="primary">Add workstream</button></form></section><section className="morning-admin-card"><h3>Workstreams</h3>{query.data?.workstreams.map(item=><div key={item.id} className="morning-entry-row"><div><strong>{item.name}</strong><div className="meta">{item.active?'Active':'Inactive'}</div></div><button type="button" onClick={()=>active.mutate({id:item.id,value:!item.active})}>{item.active?'Deactivate':'Activate'}</button></div>)}</section></div>
}

function Crews(){
  const query=useConfig(); const refresh=useRefresh(); const [name,setName]=useState(''); const [workstreamId,setWorkstreamId]=useState('')
  const create=useMutation({mutationFn:()=>morningApi('/api/morning/admin/construction/crews',{method:'POST',body:JSON.stringify({name,workstream_id:workstreamId||null})}),onSuccess:()=>{setName('');setWorkstreamId('');refresh()}})
  const update=useMutation({mutationFn:({id,workstream_id}:{id:string;workstream_id:string})=>morningApi(`/api/morning/admin/construction/crews/${id}`,{method:'PATCH',body:JSON.stringify({workstream_id:workstream_id||null})}),onSuccess:refresh})
  const active=useMutation({mutationFn:({id,value}:{id:string;value:boolean})=>morningApi(`/api/morning/admin/construction/crews/${id}/${value?'activate':'deactivate'}`,{method:'POST',body:'{}'}),onSuccess:refresh})
  const workstreams=query.data?.workstreams.filter(item=>item.active)||[]
  return <div className="morning-admin-stack"><section className="morning-admin-card"><h3>Add Construction crew</h3><form className="morning-add-form" onSubmit={(e:FormEvent)=>{e.preventDefault();if(name.trim())create.mutate()}}><label>Crew name<input placeholder="Construction Crew 1" value={name} onChange={e=>setName(e.target.value)}/></label><label>Workstream<select value={workstreamId} onChange={e=>setWorkstreamId(e.target.value)}><option value="">No workstream yet</option>{workstreams.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button className="primary">Add crew</button></form></section><section className="morning-admin-card"><h3>Construction crews</h3>{query.data?.crews.map(crew=><div key={crew.crew_id} className="morning-entry-row"><div><strong>{crew.name}</strong><div className="meta">{crew.workstream_name||'No workstream'} · {crew.active?'Active':'Inactive'}</div></div><div className="morning-entry-actions"><select value={crew.workstream_id||''} onChange={e=>update.mutate({id:crew.crew_id,workstream_id:e.target.value})}><option value="">No workstream</option>{workstreams.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select><button type="button" onClick={()=>active.mutate({id:crew.crew_id,value:!crew.active})}>{crew.active?'Deactivate':'Activate'}</button></div></div>)}</section></div>
}

function People(){
  const query=useConfig(); const refresh=useRefresh(); const [name,setName]=useState(''); const [role,setRole]=useState(''); const [crewId,setCrewId]=useState('')
  const crews=query.data?.crews.filter(item=>item.active)||[]
  const create=useMutation({mutationFn:()=>morningApi('/api/morning/admin/construction/persons',{method:'POST',body:JSON.stringify({name,role:role||null,crew_id:crewId})}),onSuccess:()=>{setName('');setRole('');refresh()}})
  const assign=useMutation({mutationFn:({id,crew_id}:{id:string;crew_id:string})=>morningApi(`/api/morning/admin/construction/persons/${id}`,{method:'PATCH',body:JSON.stringify({crew_id})}),onSuccess:refresh})
  const active=useMutation({mutationFn:({id,value}:{id:string;value:boolean})=>morningApi(`/api/morning/admin/construction/persons/${id}/${value?'activate':'deactivate'}`,{method:'POST',body:'{}'}),onSuccess:refresh})
  return <div className="morning-admin-stack"><section className="morning-admin-card"><h3>Add person</h3><form className="morning-add-form" onSubmit={(e:FormEvent)=>{e.preventDefault();if(name.trim()&&crewId)create.mutate()}}><label>Name<input value={name} onChange={e=>setName(e.target.value)} placeholder="Full name"/></label><label>Role / trade<input value={role} onChange={e=>setRole(e.target.value)} placeholder="Electrician"/></label><label>Construction crew<select value={crewId} onChange={e=>setCrewId(e.target.value)}><option value="">Select crew</option>{crews.map(item=><option key={item.crew_id} value={item.crew_id}>{item.name}</option>)}</select></label><button className="primary" disabled={!crewId}>Add person</button></form></section><section className="morning-admin-card"><h3>Construction people</h3>{query.data?.persons.map(person=><div key={person.id} className="morning-entry-row"><div><strong>{person.name}</strong><div className="meta">{person.role||'No role'} · {person.active?'Active':'Inactive'}</div></div><div className="morning-entry-actions"><select value={person.crew_id||''} onChange={e=>assign.mutate({id:person.id,crew_id:e.target.value})}>{query.data?.crews.map(crew=><option key={crew.crew_id} value={crew.crew_id}>{crew.name}</option>)}</select><button type="button" onClick={()=>active.mutate({id:person.id,value:!person.active})}>{person.active?'Deactivate':'Activate'}</button></div></div>)}</section></div>
}

function Supervisors(){
  const query=useConfig(); const refresh=useRefresh()
  const approve=useMutation({mutationFn:(id:string)=>morningApi(`/api/morning/admin/accounts/${id}/approve`,{method:'POST',body:'{}'}),onSuccess:refresh})
  const link=useMutation({mutationFn:({id,personId}:{id:string;personId:string})=>morningApi(`/api/morning/admin/accounts/${id}/link`,{method:'POST',body:JSON.stringify({person_id:personId||null})}),onSuccess:refresh})
  const crewName=(crewId:string|null)=>query.data?.crews.find(item=>item.crew_id===crewId)?.name||'No Construction crew'
  return <section className="morning-admin-card"><h3>Construction supervisor links</h3><p className="meta">Pending registrations appear here so they can be approved and linked to Construction personnel.</p>{query.data?.accounts.map(account=><div key={account.principal_id} className="morning-entry-row"><div><strong>{account.display_name||account.username}</strong><div className="meta">@{account.username} · {account.approved_at?'Approved':'Pending approval'}</div><div className="meta">{account.person_name?`${account.person_name} · ${crewName(account.crew_id)}`:'Not linked to Construction personnel'}</div></div><div className="morning-entry-actions">{!account.approved_at?<button type="button" className="primary" onClick={()=>approve.mutate(account.principal_id)}>Approve</button>:null}<select value={account.person_id||''} onChange={e=>link.mutate({id:account.principal_id,personId:e.target.value})}><option value="">No personnel link</option>{query.data?.persons.map(person=><option key={person.id} value={person.id}>{person.name}</option>)}</select></div></div>)}</section>
}
