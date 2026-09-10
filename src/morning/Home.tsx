import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { morningApi } from './api'
import type { HomeData, MorningPrincipal } from './types'
import { shiftShortLabel } from './format'
import { MorningIcon } from './ui'

function when(value: string | null): string { return value ? new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '' }

export function Home({ principal, hasDraft, demoMode = false, onOpenReport }: { principal: MorningPrincipal; hasDraft: boolean; demoMode?: boolean; onOpenReport: () => void }) {
  const qc = useQueryClient()
  const query = useQuery({ queryKey: ['morning-home'], queryFn: () => morningApi<HomeData>('/api/morning/home') })
  const [recipient, setRecipient] = useState('')
  const [message, setMessage] = useState('')
  const [notice, setNotice] = useState('')
  const refresh = () => void qc.invalidateQueries({ queryKey: ['morning-home'] })
  const send = useMutation({ mutationFn: () => morningApi('/api/morning/messages', { method: 'POST', body: JSON.stringify({ recipient_principal_id: recipient, body: message }) }), onSuccess: () => { setMessage(''); refresh() } })
  const broadcast = useMutation({ mutationFn: () => morningApi('/api/morning/announcements', { method: 'POST', body: JSON.stringify({ body: notice }) }), onSuccess: () => { setNotice(''); refresh() } })
  const markRead = useMutation({ mutationFn: (id: string) => morningApi(`/api/morning/messages/${id}/read`, { method: 'POST', body: '{}' }), onSuccess: refresh })
  const data = query.data

  return <div className="morning-home">
    {demoMode ? <div className="morning-demo-banner"><strong>DEMO MODE</strong><span>Reports stay on this device and production communication is disabled.</span></div> : null}
    <section className="morning-home-hero">
      <div className="morning-home-hero-copy"><p className="eyebrow">TMM supervisor workspace</p><h1>Good morning,<br/><span>{principal.display_name}</span></h1><p>Everything you need for the shift — reporting, communication and recent activity.</p></div>
      <button type="button" className="primary morning-home-primary" onClick={onOpenReport}><MorningIcon name="report"/><span><strong>{hasDraft ? 'Continue current report' : demoMode ? 'Start demo TMM report' : 'Start new TMM report'}</strong><small>{hasDraft ? 'Pick up exactly where you left off' : 'Begin the guided shift workflow'}</small></span><b>›</b></button>
    </section>

    <div className="morning-home-quickgrid">
      <a href="#recent-reports" className="morning-quick-card"><MorningIcon name="report"/><span><strong>Recent reports</strong><small>{data?.recent_reports.length || 0} available</small></span><b>›</b></a>
      <a href="#notice-board" className="morning-quick-card notice"><MorningIcon name="notice"/><span><strong>Notice board</strong><small>{data?.announcements.length || 0} notices</small></span><b>›</b></a>
      <a href="#messages" className="morning-quick-card"><MorningIcon name="message"/><span><strong>Messages</strong><small>{data?.unread_count ? `${data.unread_count} unread` : 'No unread messages'}</small></span>{data?.unread_count ? <em>{data.unread_count}</em> : <b>›</b>}</a>
    </div>

    <section id="recent-reports" className="morning-home-card"><div className="morning-home-card-head"><div className="morning-home-card-title"><MorningIcon name="report"/><div><h2>Recent TMM reports</h2><p className="meta">Your five most recently submitted shift reports.</p></div></div></div>
      {query.isLoading ? <p className="empty">Loading…</p> : null}
      <div className="morning-report-history">{data?.recent_reports.map(report => <details key={report.id} className="morning-history-report"><summary><span className="morning-history-icon"><MorningIcon name="check"/></span><span><strong>{shiftShortLabel(report.shift_kind)} Shift · {report.shift_date}</strong><small>{report.supervisor_name} · {when(report.submitted_at)}</small></span><span className="morning-history-view">View ›</span></summary><pre>{report.summary_text}</pre></details>)}</div>
      {data && !data.recent_reports.length ? <p className="empty">No submitted TMM reports yet.</p> : null}
    </section>

    <section id="notice-board" className="morning-home-card morning-notice-board"><div className="morning-home-card-head"><div className="morning-home-card-title"><MorningIcon name="notice"/><div><h2>Notice board</h2><p className="meta">Important updates visible to every TMM supervisor.</p></div></div></div>
      {demoMode ? <p className="meta">Production notices are hidden and posting is disabled in Demo Mode.</p> : <form className="morning-home-compose" onSubmit={(e:FormEvent) => { e.preventDefault(); if (notice.trim()) broadcast.mutate() }}><textarea rows={3} value={notice} onChange={e => setNotice(e.target.value)} placeholder="Post an update to all TMM supervisors…" /><button className="primary" disabled={broadcast.isPending || !notice.trim()}><MorningIcon name="plus"/>{broadcast.isPending ? 'Posting…' : 'Post notice'}</button></form>}
      <div className="morning-home-feed">{data?.announcements.length ? data.announcements.map(item => <article key={item.id} className="morning-notice"><div><strong>{item.sender_name}</strong><span className="meta">{when(item.created_at)}</span></div><p>{item.body}</p></article>) : <p className="empty">No notices yet.</p>}</div>
    </section>

    <section id="messages" className="morning-home-card"><div className="morning-home-card-head"><div className="morning-home-card-title"><MorningIcon name="message"/><div><h2>Private messages {data?.unread_count ? <span className="morning-unread-badge">{data.unread_count}</span> : null}</h2><p className="meta">Only you and the selected supervisor can see these messages.</p></div></div></div>
      {demoMode ? <p className="meta">Private messaging is disabled in Demo Mode.</p> : <form className="morning-home-compose" onSubmit={(e:FormEvent) => { e.preventDefault(); if (recipient && message.trim()) send.mutate() }}><label>To<select value={recipient} onChange={e => setRecipient(e.target.value)} required><option value="">Select supervisor…</option>{data?.supervisors.map(item => <option key={item.principal_id} value={item.principal_id}>{item.display_name}</option>)}</select></label><label>Message<textarea rows={3} value={message} onChange={e => setMessage(e.target.value)} placeholder="Write a private message…" /></label><button className="primary" disabled={send.isPending || !recipient || !message.trim()}><MorningIcon name="message"/>{send.isPending ? 'Sending…' : 'Send privately'}</button></form>}
      <div className="morning-home-feed">{data?.messages.length ? data.messages.map(item => { const incoming = item.recipient_principal_id === principal.principal_id; const unread = incoming && !item.read_at; return <article key={item.id} className={`morning-message ${unread ? 'unread' : ''}`}><div><strong>{incoming ? item.sender_name : `To ${item.recipient_name}`}</strong><span className="meta">{when(item.created_at)}</span></div><p>{item.body}</p>{unread ? <button type="button" className="ghost" onClick={() => markRead.mutate(item.id)}>Mark read</button> : null}</article> }) : <p className="empty">No direct messages yet.</p>}</div>
    </section>
    {query.isError ? <p className="error-text">Could not load the Home page. Check the connection and try again.</p> : null}
    <nav className="morning-bottom-nav" aria-label="Morning navigation"><a className="active" href="#top" onClick={(e) => e.preventDefault()}><MorningIcon name="home"/><span>Home</span></a><a href="#recent-reports"><MorningIcon name="report"/><span>Reports</span></a><a href="#notice-board"><MorningIcon name="notice"/><span>Notices</span></a><a href="#messages"><MorningIcon name="message"/><span>Messages</span>{data?.unread_count ? <em>{data.unread_count}</em> : null}</a></nav>
  </div>
}
