/*
 * "Add to community reports": POST /api/number/report { number, category, note }.
 * Optional, so its button is secondary; the page's one primary is Download JSON.
 */
import { useState } from 'react'
import Button from '../ui/Button'
import Icon from '../ui/Icon'
import { SCAM_TYPES, guessScamType, submitCommunityReport } from '../../api/report'
import './CommunityReport.css'

export default function CommunityReport({ report }) {
  const [number, setNumber] = useState(report.call.caller_number ?? '')
  const [category, setCategory] = useState(() => guessScamType(report))
  const [note, setNote] = useState('')
  const [status, setStatus] = useState({ state: 'idle' }) // idle | sending | done | error

  async function handleSubmit(event) {
    event.preventDefault()
    setStatus({ state: 'sending' })
    try {
      const { stored } = await submitCommunityReport({ number: number.trim(), category, note: note.trim() })
      setStatus({ state: 'done', stored })
    } catch (error) {
      setStatus({ state: 'error', message: error.message })
    }
  }

  return (
    <form className="community-report" onSubmit={handleSubmit}>
      <label className="community-report__field">
        <span className="t-label">Number</span>
        <input
          className="community-report__input t-code"
          type="tel"
          value={number}
          onChange={(e) => setNumber(e.target.value)}
          required
        />
      </label>

      <label className="community-report__field">
        <span className="t-label">What kind of scam?</span>
        <span className="community-report__select">
          <select className="community-report__input" value={category} onChange={(e) => setCategory(e.target.value)}>
            {SCAM_TYPES.map((type) => (
              <option key={type.id} value={type.id}>
                {type.label}
              </option>
            ))}
          </select>
          <Icon name="chevron-right" size={14} className="community-report__chevron" />
        </span>
      </label>

      <label className="community-report__field">
        <span className="t-label">Note (optional)</span>
        <textarea
          className="community-report__input"
          rows={3}
          placeholder="Anything that helps the next person"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>

      <div className="community-report__footer">
        <p className="t-body-sm muted" role="status">
          {status.state === 'done'
            ? status.stored === 'backend'
              ? 'Added. The next check of this number will show it.'
              : 'Saved in this browser. The backend can’t store community reports yet.'
            : status.state === 'error'
              ? `Couldn’t add it: ${status.message}`
              : 'Saved in this laptop’s report list.'}
        </p>
        <Button type="submit" icon="flag" disabled={!number.trim() || status.state === 'sending' || status.state === 'done'}>
          {status.state === 'done' ? 'Added' : status.state === 'sending' ? 'Adding…' : 'Add report'}
        </Button>
      </div>
    </form>
  )
}
