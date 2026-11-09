/*
 * Protected Send (Step 3, left column): pay someone through PayPal while the
 * call is still being checked.
 *
 * The PayPal button (JS SDK v6) creates an order with intent AUTHORIZE. Once
 * the payer approves in PayPal, the backend reserves the money and the payment
 * gate decides with the call's risk at that moment. Nothing is sent before then.
 * With no sandbox keys (config.standin), a plain button takes the same steps against
 * the in-memory stand-in, and the panel says it isn't PayPal.
 */
import { useState } from 'react'
import { PayPalOneTimePaymentButton, PayPalProvider, usePayPal } from '@paypal/react-paypal-js/sdk-v6'
import AlertBanner from '../ui/AlertBanner'
import Button from '../ui/Button'
import Icon from '../ui/Icon'
import { formatClock } from '../../utils/formatTime'
import './ProtectedSend.css'

const EMPTY = { amount: '', currency: 'USD', recipient_name: '', contact_number: '', recipient_email: '', note: '' }

/**
 * @param {object}   props
 * @param {object}   props.config     GET /api/payment/config
 * @param {object}   props.defaults   the replayed scenario's payment, to pre-fill the form (optional)
 * @param {object}   props.payments   usePayments(sessionId)
 * @param {object}   props.identityClaim  an IDENTITY_CLAIM flag (“it's me, your grandson”) on a call that asked for money
 * @param {object}   props.sandboxBuyer  { email, password } for judges, when the server shares one
 */
export default function ProtectedSend({ config, defaults, payments, sandboxBuyer, identityClaim = null }) {
  const [form, setForm] = useState(() => ({ ...EMPTY, currency: config.currency, ...(defaults ?? {}) }))
  const set = (key) => (event) => setForm((prev) => ({ ...prev, [key]: event.target.value }))

  const amount = Number(String(form.amount).replace(/,/g, ''))
  const problem =
    !(amount > 0) ? 'Enter the amount.'
    : !form.recipient_name.trim() ? 'Enter who the money is for.'
    : !form.contact_number.trim() ? 'Add the number saved in your phone for them: you may need to call them back.'
    : null

  const body = {
    amount: String(form.amount),
    currency: form.currency,
    recipient_name: form.recipient_name.trim(),
    contact_name: form.recipient_name.split('(')[0].trim(),
    contact_number: form.contact_number.trim(),
    recipient_email: config.payouts && form.recipient_email.trim() ? form.recipient_email.trim() : null,
    note: form.note.trim() || null,
  }

  return (
    <div className="protected-send">
      {identityClaim && (
        <AlertBanner tone="caution" title="Call them back before you pay">
          At {formatClock(identityClaim.t)} the caller said “{identityClaim.evidence}” and then asked for money. Hang up
          and ring them on the number you already have saved. Veracity will hold this payment until you do.
        </AlertBanner>
      )}
      <p className="t-body-sm protected-send__intro">
        Asked for money on this call? Send it here instead. <strong>{config.standin ? 'The PayPal stand-in holds it' : 'PayPal holds it'}</strong>, and Veracity
        releases it only if the call checks out.
      </p>

      <div className="protected-send__fields">
        <label className="protected-send__field">
          <span className="t-label">Amount</span>
          <span className="protected-send__money">
            <input className="protected-send__amount" inputMode="decimal" value={form.amount} onChange={set('amount')} placeholder="0.00" />
            <select className="protected-send__currency" value={form.currency} onChange={set('currency')} aria-label="Currency">
              {(config.currencies ?? [config.currency]).map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </span>
        </label>
        <label className="protected-send__field">
          <span className="t-label">For</span>
          <input className="protected-send__input" value={form.recipient_name} onChange={set('recipient_name')} placeholder="Jake (grandson)" />
        </label>
        <label className="protected-send__field">
          <span className="t-label">Their number, as saved in your phone</span>
          <input className="protected-send__input t-code" type="tel" value={form.contact_number} onChange={set('contact_number')} placeholder="+1 202 555 0172" />
        </label>
        {config.payouts && (
          <label className="protected-send__field">
            <span className="t-label">Their PayPal email (to forward the money)</span>
            <input className="protected-send__input" type="email" value={form.recipient_email} onChange={set('recipient_email')} />
          </label>
        )}
      </div>

      {problem ? (
        <p className="t-body-sm muted protected-send__hint">
          <Icon name="info" size={14} />
          {problem}
        </p>
      ) : config.standin ? (
        <StandInButton payments={payments} body={body} />
      ) : (
        <PayPalProvider clientId={config.client_id} environment="sandbox" components={['paypal-payments']} pageType="checkout">
          <PayPalButton payments={payments} body={body} />
        </PayPalProvider>
      )}

      {payments.error && (
        <AlertBanner tone="caution" title="PayPal step failed">
          {payments.error.message}
        </AlertBanner>
      )}

      <p className="t-body-sm muted protected-send__small">
        <Icon name="lock" size={12} />{' '}
        {config.standin
          ? 'PayPal stand-in, not PayPal: no sandbox keys are set, so nothing leaves this machine and no pop-up opens.'
          : 'PayPal sandbox: test money only.'}{' '}
        Holds are cancelled automatically after {config.hold_hours} hours.
        {!config.standin && sandboxBuyer?.email && (
          <>
            {' '}Sandbox buyer: <span className="t-code">{sandboxBuyer.email}</span>
            {sandboxBuyer.password && <> / <span className="t-code">{sandboxBuyer.password}</span></>}
          </>
        )}
      </p>
    </div>
  )
}

/** No sandbox keys: approves the order with the stand-in, where a payer would use PayPal's pop-up. */
function StandInButton({ payments, body }) {
  const [busy, setBusy] = useState(false)

  async function pay() {
    setBusy(true)
    try {
      await payments.payWithStandIn(body)
    } catch {
      // the hook already holds the error, and the panel shows it
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="protected-send__button">
      <Button icon="shield" disabled={busy} onClick={pay}>
        {busy ? 'Approving…' : 'Approve with the PayPal stand-in'}
      </Button>
    </div>
  )
}

/** The PayPal button once the SDK has loaded; a short status line until then. */
function PayPalButton({ payments, body }) {
  const { loadingStatus, error } = usePayPal()
  if (loadingStatus === 'rejected' || error) {
    return (
      <AlertBanner tone="caution" title="PayPal didn't load">
        {error?.message ?? 'Check your connection or ad blocker, then reload.'}
      </AlertBanner>
    )
  }
  return (
    <div className="protected-send__button">
      <PayPalOneTimePaymentButton
        createOrder={async () => ({ orderId: await payments.create(body) })}
        onApprove={async ({ orderId }) => {
          await payments.approve(orderId)
        }}
        onCancel={payments.abandon}
        onError={() => {}} // the hook already holds the error from our backend
      />
    </div>
  )
}
