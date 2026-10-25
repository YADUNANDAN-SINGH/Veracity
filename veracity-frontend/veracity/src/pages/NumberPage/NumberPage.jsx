/*
 * Step 2 · Check number.
 *
 * The user types the caller's number; POST /api/number/check returns what
 * public numbering data says about it (valid?, line type, country, carrier,
 * time zone). "Continue" unlocks once a check has come back, valid or not:
 * an invalid number is itself worth carrying into the report.
 */
import { useState } from 'react'
import Panel from '../../components/ui/Panel'
import Button from '../../components/ui/Button'
import AlertBanner from '../../components/ui/AlertBanner'
import { buildNumberRows } from '../../api/number'
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
