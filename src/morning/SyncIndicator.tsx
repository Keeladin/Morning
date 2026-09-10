import type { SyncState } from './types'

export function SyncIndicator({ state, lastSaved }: { state: SyncState; lastSaved?: string }) {
  const label = state.status === 'saving' ? 'Saving…'
    : state.status === 'failed' ? 'Failed — Retry'
      : state.status === 'offline' ? 'Saved locally — waiting to sync'
        : state.status === 'saved' ? 'Saved'
          : lastSaved ? `Last saved ${new Date(lastSaved).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Not yet saved'
  return <div className={`morning-sync-state ${state.status}`} role="status"><span aria-hidden /> <strong>{label}</strong>{state.message ? <small>{state.message}</small> : null}{state.retry ? <button type="button" onClick={state.retry}>Retry</button> : null}</div>
}
