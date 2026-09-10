import { useState, type FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Admin } from './Admin'
import { ConstructionAdmin } from './ConstructionAdmin'
import { ControlRoomAdmin } from './ControlRoomAdmin'
import { morningApi } from './api'
import type { MorningPrincipal } from './types'

type Workspace = 'morning' | 'construction'
type BootstrapStatus = { available: boolean }

type Props = { principal: MorningPrincipal; target: Workspace }

export function AdminWorkspaceGate({ principal, target }: Props) {
  if (principal.admin_workspace === target) {
    return target === 'construction' ? <ConstructionAdmin /> : <><Admin /><ControlRoomAdmin /></>
  }
  if (target === 'construction' && principal.admin_workspace === 'morning') {
    return <ConstructionBootstrap />
  }
  return <AccessDenied principal={principal} target={target} />
}

function AccessDenied({ principal, target }: Props) {
  return <section className="morning-admin-card morning-workspace-denied">
    <h2>Different administrator account required</h2>
    <p>This account administers <strong>{principal.admin_workspace || 'another workspace'}</strong>, not <strong>{target}</strong>.</p>
    <p className="meta">Sign out and use an administrator account assigned to this workspace.</p>
  </section>
}

function ConstructionBootstrap() {
  const status = useQuery({
    queryKey: ['construction-bootstrap-status'],
    queryFn: () => morningApi<BootstrapStatus>('/api/morning/admin/construction/bootstrap-status'),
  })
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [created, setCreated] = useState(false)
  const create = useMutation({
    mutationFn: () => morningApi('/api/morning/admin/construction/bootstrap', {
      method: 'POST',
      body: JSON.stringify({ username, display_name: displayName, password }),
    }),
    onSuccess: () => setCreated(true),
  })

  if (status.isLoading) return <section className="morning-admin-card"><p>Checking Construction administrator…</p></section>
  if (status.isError) return <section className="morning-admin-card"><h2>Construction administration unavailable</h2><p className="meta">Could not verify the workspace administrator state.</p></section>
  if (created) return <section className="morning-admin-card"><h2>Construction administrator created</h2><p>Sign out, then log in with the new Construction administrator account.</p></section>
  if (!status.data?.available) {
    return <section className="morning-admin-card morning-workspace-denied">
      <h2>Construction administrator account required</h2>
      <p>A Construction administrator already exists. This Morning administrator cannot access Construction Administration.</p>
      <p className="meta">Sign out and use the Construction administrator account.</p>
    </section>
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (username.trim() && displayName.trim() && password.length >= 8) create.mutate()
  }
  return <section className="morning-admin-card">
    <h2>Create first Construction administrator</h2>
    <p className="meta">This one-time setup creates a separate Construction admin account. It does not grant this Morning admin access to Construction configuration.</p>
    <form className="morning-add-form" onSubmit={submit}>
      <label>Display name<input value={displayName} onChange={e => setDisplayName(e.target.value)} required /></label>
      <label>Username<input value={username} onChange={e => setUsername(e.target.value)} required /></label>
      <label>Password<input type="password" minLength={8} value={password} onChange={e => setPassword(e.target.value)} required /></label>
      {create.isError ? <p className="error-text">{create.error instanceof Error ? create.error.message : 'Could not create administrator.'}</p> : null}
      <button className="primary" disabled={create.isPending}>{create.isPending ? 'Creating…' : 'Create Construction administrator'}</button>
    </form>
  </section>
}
