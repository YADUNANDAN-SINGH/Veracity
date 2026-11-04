/*
 * One Protected Send payment and what the gate decided about it.
 *
 * Top: the amount, who it is for and the status pill, then the money's journey
 * (approved in PayPal → held by Veracity → released or cancelled), readable at
 * a glance. While it is held: why (the call's risk and the caller's own words),
 * what to do next (call the person back on a saved number), and the two
 * decisions. Always, under Details: the PayPal ids and the audit trail of every
 * PayPal call, webhook and decision, so anyone can check that PayPal really
 * holds or released the money.
 */
import { useEffect, useState } from 'react'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import Icon from '../ui/Icon'
import { describeStatus, formatMoney } from '../../api/payment'
import { describeCategory } from '../../constants/scamCategories'
import { formatClock } from '../../utils/formatTime'
import './PaymentGate.css'

const RISK_TONE = { HIGH: 'high', MEDIUM: 'medium', LOW: 'low' }
const VOICE_LABEL = { LIKELY_AI: 'Likely AI', UNCERTAIN: 'Uncertain', LIKELY_HUMAN: 'Likely human' }
const SOURCE_LABEL = { paypal_api: 'PayPal API', webhook: 'Webhook', veracity: 'Veracity' }
const STATUS_ICON = { CREATED: 'clock', HELD: 'lock', CAPTURED: 'check-circle', PAID_OUT: 'check-circle', VOIDED: 'x-circle' }
// The pill keeps its tone's risk icon, except where the neutral "?" would mislead
const PILL_ICON = { CREATED: 'clock', VOIDED: 'x-circle' }
const HOLD_NOTE = { call_active: 'Until the call ends', verify: 'Until you call back', likely_scam: 'Likely scam' }

/**
 * @param {object}   props
 * @param {object}   props.payment   one payment from /api/payment
 * @param {boolean}  props.busy      an action on this payment is running
 * @param {Function} props.onVerify  (outcome: 'confirmed' | 'denied') => void
 * @param {Function} props.onCancel  () => void
 */
export default function PaymentGate({ payment, busy, onVerify, onCancel }) {
  const status = describeStatus(payment)
  const held = payment.status === 'HELD'
  const contact = payment.contact_name || 'them'

  return (
    <section className={`gate gate--${status.tone}`} aria-live="polite">
      <header className="gate__head">
        <div className="gate__title">
          <p className="gate__eyebrow t-overline muted">
            <Icon name="shield" size={14} />
            PROTECTED SEND · PAYPAL SANDBOX
          </p>
          <h2 className="gate__heading">
            <span className="gate__amount">{formatMoney(payment.amount, payment.currency)}</span>
            <span className="gate__recipient">for {payment.recipient_name}</span>
          </h2>
        </div>
        <Badge tone={status.tone} size="lg" icon={PILL_ICON[payment.status]}>
          {status.label}
        </Badge>
      </header>

      <Journey payment={payment} tone={status.tone} />

      <div className="gate__body">
        <div className={`gate__verdict gate__verdict--${status.tone}`}>
          <Icon name={STATUS_ICON[payment.status] ?? 'octagon'} size={20} />
          <div>
            <p className="gate__headline">{status.headline}</p>
            {held && payment.policy && <p className="t-body-sm muted">{payment.policy}</p>}
          </div>
        </div>

        {held && payment.risk && <Why risk={payment.risk} />}

        {held && <NextStep payment={payment} contact={contact} busy={busy} onVerify={onVerify} onCancel={onCancel} />}
      </div>

      <Details payment={payment} />
    </section>
  )
}

/**
 * Where the money is: approved in PayPal → held by Veracity → released or cancelled.
 * Done steps are brand, the current step takes the status colour, and the last
 * step turns green when released, grey when cancelled.
 */
function Journey({ payment, tone }) {
  const authorized = Boolean(payment.paypal.authorization_id)
  const coolingOff = payment.verification === 'confirmed' && payment.release_at
  const ended = { CAPTURED: 'released', PAID_OUT: 'released', VOIDED: 'cancelled', FAILED: 'failed' }[payment.status]
  const notReached = ended && !authorized ? 'skipped' : 'done' // cancelled before anyone approved it

  const steps = [
    {
      label: 'Approved in PayPal',
      ...(payment.status === 'CREATED'
        ? { state: 'current', note: 'Waiting for approval' }
        : notReached === 'skipped'
          ? { state: 'skipped', note: 'Not approved' }
          : { state: 'done', note: 'Funds reserved' }),
    },
    {
      label: 'Held by Veracity',
      ...(payment.status === 'HELD'
        ? { state: 'current', note: coolingOff ? 'Cooling-off' : HOLD_NOTE[payment.hold_reason] }
        : ended
          ? { state: notReached, note: notReached === 'skipped' ? 'Nothing held' : 'Hold ended' }
          : { state: 'upcoming' }),
    },
    ended === 'released'
      ? { label: 'Released', state: 'released', note: payment.status === 'PAID_OUT' ? 'Captured · paid out' : 'Captured' }
      : ended === 'cancelled'
        ? { label: 'Cancelled', state: 'cancelled', note: authorized ? 'Voided · no money moved' : 'Nothing moved' }
        : ended === 'failed'
          ? { label: 'Failed', state: 'failed', note: 'PayPal declined' }
          : {
              label: 'Released or cancelled',
              state: 'upcoming',
              note: payment.status !== 'HELD' ? null : coolingOff ? 'After the cooling-off' : 'After you call back',
            },
  ]

  return (
    <ol className={`journey journey--${tone}`} aria-label="Where the money is">
      {steps.map((step, i) => (
        <li
          key={step.label}
          className={`journey__step journey__step--${step.state}`}
          aria-current={step.state === 'current' ? 'step' : undefined}
        >
          <span className="journey__marker" aria-hidden="true">
            <StepMark state={step.state} n={i + 1} />
          </span>
          <span className="journey__label">{step.label}</span>
          {step.note && <span className="journey__note">{step.note}</span>}
          <span className="visually-hidden">{` (${STEP_STATE_TEXT[step.state]})`}</span>
        </li>
      ))}
    </ol>
  )
}

const STEP_STATE_TEXT = {
  done: 'done',
  current: 'now',
  upcoming: 'not yet',
  skipped: 'skipped',
  released: 'done',
  cancelled: 'done',
  failed: 'failed',
}

function StepMark({ state, n }) {
  if (state === 'done' || state === 'released') return <Icon name="check" size={16} />
  if (state === 'cancelled' || state === 'failed') return <Icon name="x" size={16} />
  if (state === 'current') return <Icon name="lock" size={14} />
  if (state === 'skipped') return '–'
  return n
}

/** The call's risk when the gate decided, and the caller's own words behind it. */
function Why({ risk }) {
  // The gate can be stricter than the call's overall level: any scam signs mean "call back first"
  const level = risk.gate_level ?? risk.level
  return (
    <div className="gate__why">
      <p className="gate__why-head">
        <span className="t-label">Why:</span>
        <Badge tone={RISK_TONE[level] ?? 'neutral'}>
          {level === 'HIGH' ? 'High' : level === 'MEDIUM' ? 'Medium' : 'Low'} risk for a payment
        </Badge>
        {risk.active && <span className="muted t-body-sm">decided during the call</span>}
      </p>
      {risk.gate_why && <p className="t-body-sm">{risk.gate_why}</p>}
      {risk.flags?.length > 0 && (
        <ul className="gate__quotes">
          {risk.flags.map((flag) => (
            <li key={`${flag.category}-${flag.t}`}>
              <span className="gate__quote">“{flag.evidence}”</span>
              <span className="t-code muted gate__quote-meta">
                {formatClock(flag.t)} · {describeCategory(flag.category).short}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="t-body-sm muted">
        Call risk <span className="t-code">{risk.score}/100</span> · Script <span className="t-code">{risk.script_score}/100</span> ·
        Voice{' '}
        {risk.voice_state ? `${VOICE_LABEL[risk.voice_state]} (peak ${risk.voice_peak}%)` : 'not scored on this call'}
      </p>
    </div>
  )
}

/** What the payer should do now, and the buttons for it. */
function NextStep({ payment, contact, busy, onVerify, onCancel }) {
  // The caller may still be listening: hang up before anyone confirms
  const waitingForCall = payment.hold_reason === 'call_active' || payment.call_live
  const coolingOff = payment.verification === 'confirmed' && payment.release_at

  return (
    <div className="gate__next">
      <div className="gate__instruction">
        <Icon name={coolingOff ? 'clock' : waitingForCall ? 'phone-off' : 'phone'} size={18} />
        {waitingForCall ? (
          <p>
            <strong>Hang up first.</strong> Then call {contact} back on{' '}
            {payment.contact_number ? <span className="t-code">{payment.contact_number}</span> : 'a number saved in your phone'},
            not the number that called you.
          </p>
        ) : coolingOff ? (
          <p>
            {contact} confirmed. Released <Countdown until={payment.release_at} /> unless you cancel.
          </p>
        ) : (
          <p>
            <strong>Call {contact} back</strong> on{' '}
            {payment.contact_number ? <span className="t-code">{payment.contact_number}</span> : 'a number saved in your phone'}
            , the number saved in your phone, and ask if they really need this money.
          </p>
        )}
      </div>

      {(payment.can_verify || payment.can_cancel) && (
        <div className="gate__actions">
          {payment.can_verify && (
            <>
              <Button variant="secondary" icon="check" disabled={busy} onClick={() => onVerify('confirmed')}>
                {contact} confirmed: release
              </Button>
              <Button variant="danger" icon="x-circle" disabled={busy} onClick={() => onVerify('denied')}>
                {contact} didn’t ask: cancel
              </Button>
            </>
          )}
          {!payment.can_verify && payment.can_cancel && (
            <Button variant="danger" icon="x-circle" disabled={busy} onClick={onCancel}>
              Cancel payment
            </Button>
          )}
        </div>
      )}
      {payment.expires_at && (
        <p className="t-body-sm muted">
          If nobody releases it, PayPal’s hold is cancelled automatically on {formatDateTime(payment.expires_at)}.
        </p>
      )}
    </div>
  )
}

/** The PayPal ids and the audit trail, folded away: the order id stays visible on the fold. */
function Details({ payment }) {
  const events = payment.events ?? []
  return (
    <details className="gate__details">
      <summary>
        <Icon name="chevron-right" size={16} className="gate__chevron" />
        <span className="t-label">Details</span>
        <span className="t-code muted gate__details-hint">
          PayPal order {payment.paypal.order_id ?? '—'} · {events.length} {events.length === 1 ? 'event' : 'events'}
        </span>
      </summary>
      <div className="gate__details-body">
        <dl className="gate__ids t-body-sm">
          <Id label="PayPal order" value={payment.paypal.order_id} />
          <Id label="Authorization" value={payment.paypal.authorization_id} />
          {payment.paypal.capture_id && <Id label="Capture" value={payment.paypal.capture_id} />}
          {payment.paypal.payout_batch_id && <Id label="Payout batch" value={payment.paypal.payout_batch_id} />}
        </dl>
        <Trail events={events} />
      </div>
    </details>
  )
}

function Id({ label, value }) {
  return (
    <div>
      <dt className="muted">{label}</dt>
      <dd className="t-code">{value ?? '—'}</dd>
    </div>
  )
}

/** Every PayPal call, webhook and decision, oldest first. */
function Trail({ events }) {
  if (events.length === 0) return null
  return (
    <div className="gate__trail">
      <p className="t-overline muted">PAYPAL ACTIVITY · {events.length}</p>
      <ol>
        {events.map((event, i) => (
          <li key={i} className="t-body-sm">
            <span className="t-code muted">{formatWallClock(event.at, true)}</span>
            <span className={`gate__source gate__source--${event.source}`}>{SOURCE_LABEL[event.source] ?? event.source}</span>
            <span>{event.kind}</span>
            {event.detail && <TrailDetail detail={event.detail} />}
          </li>
        ))}
      </ol>
    </div>
  )
}

function TrailDetail({ detail }) {
  const parts = []
  if (detail.method) parts.push(`${detail.method} ${detail.path} → ${detail.status ?? 'no answer'}`)
  if (detail.why) parts.push(detail.why)
  if (detail.issue || detail.message) parts.push([detail.issue, detail.message].filter(Boolean).join(': '))
  if (detail.debug_id) parts.push(`debug id ${detail.debug_id}`)
  if (parts.length === 0) return null
  return <span className="t-code muted gate__detail">{parts.join(' · ')}</span>
}

/** "in 14:32", ticking each second. */
function Countdown({ until }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const left = Math.max(0, Math.round((new Date(until) - now) / 1000))
  return <span className="t-code">{left > 0 ? `in ${formatClock(left)}` : 'now'}</span>
}

function formatWallClock(iso, seconds = false) {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', ...(seconds && { second: '2-digit' }) })
}

/** "Thu 6 Nov, 09:12 PM": holds last days, so the day matters. */
function formatDateTime(iso) {
  return new Date(iso).toLocaleString([], { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}
