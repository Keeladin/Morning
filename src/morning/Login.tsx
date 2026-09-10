import { useState, type FormEvent } from 'react'
import { MorningApiError, morningApi } from './api'
import type { MorningSession } from './types'
import { MorningMark } from './ui'

export function Login({ onAuthed }: { onAuthed: (session: MorningSession) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(null); setNotice(null); setPending(true)
    try {
      if (mode === 'register') {
        await morningApi('/api/morning/auth/register', { method: 'POST', body: JSON.stringify({ username, password, display_name: displayName }) })
        setMode('login'); setPassword('')
        setNotice('Registration submitted. A Morning administrator must approve your account before you can log in.')
      } else {
        const result = await morningApi<{ principal: MorningSession['principal']; csrf_token: string }>('/api/morning/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) })
        onAuthed({ authenticated: true, principal: result.principal, csrf_token: result.csrf_token })
      }
    } catch (err) {
      setError(err instanceof MorningApiError ? err.message : 'Something went wrong. Try again.')
    } finally { setPending(false) }
  }

  return <div className="morning-auth-shell">
    <section className="morning-auth-visual">
      <div className="morning-auth-visual-copy"><MorningMark /><p className="eyebrow">TMM shift reporting</p><h1>Welcome to Morning</h1><p>Capture the right information once, keep your team aligned, and turn every shift into a clear handover.</p><div className="morning-auth-promise"><span>People safer</span><span>Machines stronger</span><span>Operations further</span></div></div>
    </section>
    <div className="morning-auth-card">
      <div className="morning-auth-card-brand"><MorningMark compact /><div><strong>Morning</strong><small>{mode === 'login' ? 'Welcome back' : 'Create your supervisor account'}</small></div></div>
      <h2>{mode === 'login' ? 'Sign in to your account' : 'Create your account'}</h2><p className="meta">{mode === 'login' ? 'Use your approved Morning username and password.' : 'A Morning administrator will approve your registration before first login.'}</p>
      <div className="morning-auth-toggle" role="tablist"><button type="button" role="tab" aria-selected={mode === 'login'} className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>Log in</button><button type="button" role="tab" aria-selected={mode === 'register'} className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>Register</button></div>
      <form onSubmit={submit} className="morning-auth-form">
        {mode === 'register' ? <label><span>Full name</span><input value={displayName} onChange={(e) => setDisplayName(e.target.value)} required autoComplete="name" placeholder="Enter your full name" /></label> : null}
        <label><span>Username</span><input value={username} onChange={(e) => setUsername(e.target.value)} required autoComplete="username" autoCapitalize="none" placeholder="Enter your username" /></label>
        <label><span>Password</span><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} placeholder="••••••••" /></label>
        {notice ? <p className="morning-auth-notice">{notice}</p> : null}{error ? <p className="error-text">{error}</p> : null}
        <button type="submit" className="primary morning-auth-submit" disabled={pending}>{pending ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Register'}</button>
      </form>
      {mode === 'register' ? <p className="morning-auth-footnote">Only one supervisor account per full name is allowed.</p> : null}
    </div>
  </div>
}
