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
 *
 * Without a phone (judge mode, VERA_FAKE=1) the user picks a sample call to
 * replay instead, and its caller's number is checked the same way.
 */
import { useEffect, useState } from 'react'
import Panel from '../../components/ui/Panel'
import Button from '../../components/ui/Button'
import Badge from '../../components/ui/Badge'
import AlertBanner from '../../components/ui/AlertBanner'
import Icon from '../../components/ui/Icon'
import { REGION_HINTS, buildNumberRows } from '../../api/number'
import { formatMoney } from '../../api/payment'
import { useCallState } from '../../hooks/useCallState'
import { useScenarios } from '../../hooks/useScenarios'
import './NumberPage.css'

/**
 * @param {object}   props
 * @param {object}   props.numberState  { details, loading, error, check } from useNumberCheck()
 * @param {boolean}  props.replayMode   no phone: pick a sample call to replay
 * @param {string}   props.region       the backend's region (IN, US), for the example number
 * @param {object}   props.scenario     the picked sample call, or null
 * @param {Function} props.onScenario   (scenario) => void
 * @param {Function} props.onBack       back to Step 1 · Check setup
 * @param {Function} props.onContinue   go to Step 3 · Live call
 */
export default function NumberPage({ numberState, replayMode = false, region, scenario, onScenario, onBack, onContinue }) {
  const { details, loading, error, check } = numberState
  const [number, setNumber] = useState(details?.e164_format ?? '')
  const trimmed = number.trim()
  const hints = REGION_HINTS[region] ?? REGION_HINTS.IN
  const samples = useScenarios(replayMode)

  // A ringing phone that shares the caller's number fills the field and checks it
  const call = useCallState({
    onIncomingNumber: (incoming) => {
      setNumber(incoming)
      check(incoming)
    },
  })
  const callLine = describeCall(call)

  function pick(sample) {
    onScenario(sample)
    setNumber(sample.caller_number ?? '')
    if (sample.caller_number) check(sample.caller_number)
  }

  // Pick the server's default sample call once the list arrives, so Continue works at once
  const { scenarios, defaultId } = samples
  useEffect(() => {
    if (!replayMode || scenario || scenarios.length === 0) return
    const first = scenarios.find((s) => s.id === defaultId) ?? scenarios[0]
    onScenario(first)
    if (first.caller_number) {
      setNumber(first.caller_number) // eslint-disable-line react/set-state-in-effect
      check(first.caller_number)
    }
  }, [replayMode, scenario, scenarios, defaultId, onScenario, check])

  function handleSubmit(event) {
    event.preventDefault()
    if (trimmed && !loading) check(trimmed)
  }

  const canContinue = Boolean(details) || (replayMode && Boolean(scenario) && !scenario.caller_number)

  return (
    <main className="number-page">
      <div className="number-page__intro">
        <p className="t-overline muted">STEP 2 OF 4</p>
        <h1 className="t-display">Who is calling?</h1>
        <p className="muted number-page__lede">
          {replayMode
            ? 'Pick a sample call to replay. Its caller’s number is checked against public numbering data first, as on a real call.'
            : 'Enter the number shown on the phone. Veracity checks it against public numbering data before the call is analysed.'}
        </p>
      </div>

      {replayMode && (
        <Panel title="Sample calls" action={<span className="t-body-sm muted">replayed through the real rules</span>} flush>
          {samples.error ? (
            <p className="t-body-sm muted number-page__samples-empty">Couldn’t load the sample calls: {samples.error.message}</p>
          ) : (
            <ul className="number-page__samples">
              {scenarios.map((sample) => {
                const selected = scenario?.id === sample.id
                return (
                  <li key={sample.id}>
                    <button
                      type="button"
                      className={`number-page__sample${selected ? ' is-selected' : ''}`}
                      aria-pressed={selected}
                      onClick={() => pick(sample)}
                    >
                      <span className="number-page__sample-head">
                        <span className="t-label">{sample.title}</span>
                        {selected && <Badge tone="low">Selected</Badge>}
                      </span>
                      <span className="t-body-sm muted">{sample.description}</span>
                      <span className="t-code muted number-page__sample-meta">
                        {sample.caller_number ?? 'hidden caller ID'} · {sample.region} · {sample.source}
                        {sample.payment && ` · asks for ${formatMoney(sample.payment.amount, sample.payment.currency)}`}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </Panel>
      )}

      <Panel title="Caller's number">
        {!replayMode && (
          <p className={`number-page__call number-page__call--${callLine.tone} t-body-sm`} role="status">
            <Icon name="phone" size={14} />
            {callLine.text}
          </p>
        )}
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
              placeholder={hints.placeholder}
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              aria-describedby="caller-number-hint"
            />
            <Button type="submit" disabled={!trimmed || loading}>
              {loading ? 'Checking…' : 'Check number'}
            </Button>
          </div>
          <p id="caller-number-hint" className="t-body-sm muted">
            {hints.hint}
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
        <Button variant="primary" iconRight="chevron-right" disabled={!canContinue} onClick={onContinue}>
          {replayMode ? 'Start the call' : 'Continue'}
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
