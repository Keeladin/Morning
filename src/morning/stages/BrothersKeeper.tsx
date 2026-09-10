import { useEffect, useState } from 'react'
import { isOfflineReportPending, morningApi } from '../api'
import type { ShiftReport, SyncState } from '../types'

export function BrothersKeeperStage({ report, onUpdated, onSync, onNext, onBack }: {
  report: ShiftReport; onUpdated: (report: ShiftReport) => void; onSync: (state: SyncState) => void
  onNext: () => void; onBack: () => void
}) {
  const [contribution, setContribution] = useState(report.brothers_keeper || '')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => setContribution(report.brothers_keeper || ''), [report.id, report.brothers_keeper])

  const save = async () => {
    const clean = contribution.trim()
    if (!clean) { setError('A Brothers Keeper contribution is required before you can continue.'); return }
    setPending(true); setError(null); onSync({ status: 'saving' })
    try {
      const updated = await morningApi<ShiftReport>(`/api/morning/reports/${report.id}/brothers-keeper`, {
        method: 'PUT', body: JSON.stringify({ contribution: clean }),
      })
      onUpdated(updated)
      onSync(isOfflineReportPending(updated.id)
        ? { status: 'offline', message: 'Saved on this device — will synchronize automatically.' }
        : { status: 'saved' })
      onNext()
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : 'Brothers Keeper contribution was not saved.'
      setError(message); onSync({ status: navigator.onLine ? 'failed' : 'offline', message })
    } finally { setPending(false) }
  }

  return <div className="morning-stage">
    <section className="morning-brothers-keeper-card">
      <p className="morning-brothers-intro">Raise a safety concern, suggestion or improvement identified by the workforce for management attention.</p>
      <label className="morning-brothers-field">Brothers Keeper contribution
        <textarea rows={7} value={contribution} onChange={event => setContribution(event.target.value)} placeholder="What safety issue, concern or improvement was raised by the team?" />
      </label>
      <p className="meta">This contribution is mandatory and will appear in the shift summary and WhatsApp report.</p>
      {error ? <p className="error-text">{error}</p> : null}
    </section>
    <div className="morning-stage-nav"><button type="button" onClick={onBack}>Back</button><button type="button" className="primary" disabled={pending || !contribution.trim()} onClick={() => void save()}>{pending ? 'Saving…' : 'Save & continue to Safety'}</button></div>
  </div>
}
