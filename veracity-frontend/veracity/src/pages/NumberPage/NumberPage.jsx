/*
 * Step 2 · Check number.
 *
 * The caller's number comes from the phone itself when it can: while this
 * page is open it polls GET /api/call/state, and when the USB-connected phone
 * rings with a visible number, that number is filled in and checked at once.
 * Otherwise the user types it. POST /api/number/check returns what public
 * numbering data says about it (valid?, line type, country, carrier, time zone).
 * "Continue" unlocks once a check has come back, valid or not: an invalid
 * number is itself worth carrying into the report.
 */
import { useState } from 'react'
import Panel from '../../components/ui/Panel'
import Button from '../../components/ui/Button'
import AlertBanner from '../../components/ui/AlertBanner'
import Icon from '../../components/ui/Icon'
import { buildNumberRows } from '../../api/number'
import { useCallState } from '../../hooks/useCallState'
import './NumberPage.css'

/**
 * @param {object}   props
 * @param {object}   props.numberState  { details, loading, error, check } from useNumberCheck()
 * @param {Function} props.onBack       back to Step 1 · Check setup
 * @param {Function} props.onContinue   go to Step 3 · Live call
 */
export default function NumberPage({ numberState, onBack, onContinue }) {
  const { details, loading, error, check } = numberState
  const [number, setNumber] = useState(details?.e164_format ?? '')
  const trimmed = number.trim()

  // A ringing phone that shares the caller's number fills the field and checks it
  const call = useCallState({
    onIncomingNumber: (incoming) => {
      setNumber(incoming)
      check(incoming)
    },
  })
  const callLine = describeCall(call)

  function handleSubmit(event) {
    event.preventDefault()
    if (trimmed && !loading) check(trimmed)
  }

  return (
    <main className="number-page">
      <div className="number-page__intro">
        <p className="t-overline muted">STEP 2 OF 4</p>
        <h1 className="t-display">Who is calling?</h1>
        <p className="muted number-page__lede">
          Enter the number shown on the phone. Veracity checks it against public numbering data
          before the call is analysed.
        </p>
      </div>

      <Panel title="Caller's number">
        <p className={`number-page__call number-page__call--${callLine.tone} t-body-sm`} role="status">
          <Icon name="phone" size={14} />
          {callLine.text}
        </p>
        <form className="number-page__form" onSubmit={handleSubmit}>
          <label className="t-label" htmlFor="caller-number">
            Phone number
          </label>
          <div className="number-page__row">
            <input
              id="caller-number"
              className="number-page__input"
              type="tel"
              inputMode="tel"
              autoComplete="off"
              placeholder="+91 98765 43210"
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              aria-describedby="caller-number-hint"
            />
            <Button type="submit" disabled={!trimmed || loading}>
              {loading ? 'Checking…' : 'Check number'}
            </Button>
          </div>
          <p id="caller-number-hint" className="t-body-sm muted">
            Numbers without a + country code are read as Indian.
          </p>
        </form>
      </Panel>

      {error && (
        <AlertBanner tone="caution" title="Couldn't check this number">
          {error.message}
        </AlertBanner>
      )}
      {details && !details.valid && (
        <AlertBanner tone="caution" title="This number isn't valid">
          No phone network issues numbers like this one. A spoofed or made-up caller ID often looks
          like this.
        </AlertBanner>
      )}

      {details && (
        <Panel title="What the number tells us">
          <dl className="number-page__facts" aria-live="polite">
            {buildNumberRows(details).map((row) => (
              <div key={row.id} className="number-page__fact">
                <dt className="t-body-sm muted">{row.label}</dt>
                <dd className={row.mono ? 't-code' : undefined}>{row.value}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      )}

      <footer className="number-page__footer">
        <Button variant="ghost" onClick={onBack}>
          Back
        </Button>
        <Button variant="primary" iconRight="chevron-right" disabled={!details} onClick={onContinue}>
          Continue
        </Button>
      </footer>
    </main>
  )
}

/** One line above the field saying what the phone is doing right now. */
function describeCall({ connected, state, number, error }) {
  if (error) return { tone: 'muted', text: "Can't read the phone's call state. Type the number instead." }
  if (connected === null) return { tone: 'muted', text: 'Checking the phone…' }
  if (!connected) {
    return { tone: 'muted', text: 'Phone not connected. Plug it in to fill the number automatically, or type it.' }
  }
  const what = state === 'ringing' ? 'Incoming call' : 'On a call'
  if (state === 'idle') return { tone: 'muted', text: "Waiting for a call. When the phone rings, the caller's number appears here." }
  if (number) return { tone: 'active', text: `${what} from ${number}. Checked automatically.` }
  return { tone: 'active', text: `${what}. The phone didn't share the caller's number, so type it from the screen.` }
}
