import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { morningApi } from './api'

type AdminAccount = { principal_id:string; username:string; display_name:string; admin_workspace:string; status:string }
type Props = { workspace:'morning'|'construction'; endpoint:string }

export function WorkspaceAdministrators({ workspace, endpoint }: Props) {
  const qc=useQueryClient()
  const query=useQuery({queryKey:['workspace-admins',workspace],queryFn:()=>morningApi<{admins:AdminAccount[]}>(endpoint)})
  const [displayName,setDisplayName]=useState(''); const [username,setUsername]=useState(''); const [password,setPassword]=useState('')
  const create=useMutation({mutationFn:()=>morningApi(endpoint,{method:'POST',body:JSON.stringify({display_name:displayName,username,password})}),onSuccess:()=>{setDisplayName('');setUsername('');setPassword('');void qc.invalidateQueries({queryKey:['workspace-admins',workspace]})}})
  const submit=(e:FormEvent)=>{e.preventDefault();if(displayName.trim()&&username.trim()&&password.length>=8)create.mutate()}
  return <div className="morning-admin-stack">
    <section className="morning-admin-card"><h3>Add {workspace==='construction'?'Construction':'Morning'} administrator</h3>
      <p className="meta">This account can administer only this workspace.</p>
      <form className="morning-add-form" onSubmit={submit}>
        <input placeholder="Display name" value={displayName} onChange={e=>setDisplayName(e.target.value)} required/>
        <input placeholder="Username" value={username} onChange={e=>setUsername(e.target.value)} required autoCapitalize="none"/>
        <input type="password" placeholder="Password (minimum 8 characters)" minLength={8} value={password} onChange={e=>setPassword(e.target.value)} required/>
        {create.isError?<p className="error-text">{create.error instanceof Error?create.error.message:'Could not create administrator.'}</p>:null}
        <button className="primary" disabled={create.isPending}>{create.isPending?'Creating…':'Add administrator'}</button>
      </form></section>
    <section className="morning-admin-card"><h3>Administrators</h3>
      {query.isLoading?<p className="empty">Loading…</p>:null}
      {query.data?.admins.map(admin=><div key={admin.principal_id} className="morning-entry-row"><div><strong>{admin.display_name}</strong><div className="meta">@{admin.username} · {admin.status}</div></div></div>)}
    </section>
  </div>
}
