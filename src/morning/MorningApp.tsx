import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { morningApi, setMorningCsrfToken, syncOfflineReports } from './api'
import { AdminWorkspaceGate } from './AdminWorkspaceGate'
import { InstallPrompt } from './InstallPrompt'
import { PwaUpdate } from './PwaUpdate'
import { Login } from './Login'
import type { MorningSession, ReportingModel } from './types'
import { Workflow } from './Workflow'
import { clearOfflineSession, setOfflinePrincipal } from './offline'
import { MorningMark } from './ui'
import './tokens.css'
import './morning.css'

function resolveReportingModel(): ReportingModel {
  const selected = new URLSearchParams(window.location.search).get('workspace')
  const hostname = window.location.hostname.toLowerCase()
  const path = window.location.pathname.toLowerCase()
  const constructionHost = hostname === 'construction.morningportal.co.za' || hostname === 'www.construction.morningportal.co.za'
  const constructionPath = path === '/construction-admin' || path.startsWith('/construction-admin/')
  return constructionHost || constructionPath || selected === 'construction' ? 'construction' : 'tmm'
}

const queryClient = new QueryClient({ defaultOptions:{ queries:{ retry:1, refetchOnWindowFocus:false, networkMode:'always' }, mutations:{ networkMode:'always' } } })
function MorningInner() {
  const reportingModel = resolveReportingModel()
  const [ready,setReady] = useState(false); const [session,setSession] = useState<MorningSession>({authenticated:false}); const [sessionUnavailable,setSessionUnavailable] = useState(false)
  useEffect(() => { void morningApi<MorningSession>('/api/morning/auth/session').then((result) => { setSession(result); if (result.csrf_token) setMorningCsrfToken(result.csrf_token) }).catch(() => { setSessionUnavailable(true); setSession({authenticated:false}) }).finally(() => setReady(true)) }, [])
  const onAuthed = (result: MorningSession) => { setSession(result); if (result.csrf_token) setMorningCsrfToken(result.csrf_token); void syncOfflineReports() }
  useEffect(() => {
    const sync = () => void syncOfflineReports()
    window.addEventListener('online', sync)
    if (navigator.onLine) sync()
    return () => window.removeEventListener('online', sync)
  }, [])
  const signOut = async () => { try { await morningApi('/api/morning/auth/logout',{method:'POST',body:'{}'}) } finally { setMorningCsrfToken(null); clearOfflineSession(); setOfflinePrincipal(null); queryClient.clear(); setSession({authenticated:false}) } }
  const targetAdminWorkspace = reportingModel === 'construction' ? 'construction' : 'morning'
  const authenticatedSurface = session.principal?.role === 'admin'
    ? <AdminWorkspaceGate principal={session.principal} target={targetAdminWorkspace} />
    : session.principal ? <Workflow principal={session.principal} reportingModel={reportingModel} /> : null
  return <div className="morning-shell"><header className="morning-topbar"><div className="morning-brand"><MorningMark compact /><span className="morning-brand-copy"><strong>Morning</strong><small>Simple reporting · stronger mines</small></span>{reportingModel === 'construction' ? <span className="morning-brand-workspace">Construction</span> : null}</div>{session.authenticated && session.principal ? <div className="morning-topbar-actions"><span className="morning-user-badge">{session.principal.display_name.slice(0,1).toUpperCase()}</span><span className="morning-supervisor-name"><strong>{session.principal.display_name}</strong><small>{session.principal.role}</small></span><button type="button" className="ghost morning-signout" onClick={() => void signOut()}>Sign out</button></div> : null}</header><InstallPrompt /><PwaUpdate /><main className={session.principal?.role === 'admin' ? 'morning-main morning-main-admin' : 'morning-main'}>{!ready ? <p className="morning-loading">Loading…</p> : sessionUnavailable ? <div className="morning-offline-shell"><h1>Morning is offline</h1><p>The application shell is available, but operational records cannot be loaded or synchronized. Reconnect before capturing shift information.</p><button type="button" className="primary" onClick={() => window.location.reload()}>Try again</button></div> : session.authenticated ? authenticatedSurface : <Login onAuthed={onAuthed} />}</main></div>
}
export default function MorningApp() { return <QueryClientProvider client={queryClient}><MorningInner /></QueryClientProvider> }
