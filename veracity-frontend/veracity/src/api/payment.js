/*
 * Protected Send: the PayPal payment gate (backend app/routes/payment.py).
 *
 *   GET  /api/payment/config                      { enabled, standin, client_id, currency, currencies, payouts,
 *                                                   webhooks, hold_hours, cool_off_min }
 *   POST /api/payment/orders/{orderId}/standin-approve  the in-memory PayPal stand-in only (no sandbox keys):
 *                                                   what the payer does in PayPal's pop-up
 *   POST /api/payment/orders                      { amount, currency, recipient_name, recipient_email?,
 *                                                   contact_name, contact_number, note, session_id } → payment
 *   POST /api/payment/orders/{orderId}/authorize  after the payer approves in PayPal → payment, held or released
 *   GET  /api/payment/{id}                        the payment, brought up to date
 *   POST /api/payment/{id}/verify                 { outcome: 'confirmed' | 'denied' } after the callback
 *   POST /api/payment/{id}/cancel                 void: the money never moves
 *   GET  /api/payment?session_id=…                the payments made during one call
 *
 * payment.status       CREATED | HELD | CAPTURED | PAID_OUT | VOIDED | FAILED
 * payment.hold_reason  call_active | verify | likely_scam | release_pending   (only while HELD)
 *                      release_pending: the call checked out but PayPal didn't complete the release; it's retried
 * payment.events       the audit trail: every PayPal call, webhook and decision
 * payment.paypal.environment  sandbox | standin: who answered for this payment
 */
import { apiRequest } from './client'

const PAYPAL_TIMEOUT_MS = 25000 // the backend waits on PayPal's sandbox

export function fetchPaymentConfig({ signal } = {}) {
  return apiRequest('/api/payment/config', { signal })
}

export function createPayment(body) {
  return apiRequest('/api/payment/orders', { method: 'POST', body: JSON.stringify(body), timeoutMs: PAYPAL_TIMEOUT_MS })
}

export function approveStandIn(orderId) {
  return apiRequest(`/api/payment/orders/${orderId}/standin-approve`, { method: 'POST' })
}

export function authorizePayment(orderId) {
  return apiRequest(`/api/payment/orders/${orderId}/authorize`, { method: 'POST', timeoutMs: PAYPAL_TIMEOUT_MS })
}

export function fetchPayment(paymentId, { signal } = {}) {
  return apiRequest(`/api/payment/${paymentId}`, { signal, timeoutMs: PAYPAL_TIMEOUT_MS })
}

export function verifyPayment(paymentId, outcome) {
  return apiRequest(`/api/payment/${paymentId}/verify`, {
    method: 'POST',
    body: JSON.stringify({ outcome }),
    timeoutMs: PAYPAL_TIMEOUT_MS,
  })
}

export function cancelPayment(paymentId) {
  return apiRequest(`/api/payment/${paymentId}/cancel`, { method: 'POST', timeoutMs: PAYPAL_TIMEOUT_MS })
}

export function listPayments(sessionId, { signal } = {}) {
  return apiRequest(`/api/payment?session_id=${encodeURIComponent(sessionId)}`, { signal, timeoutMs: PAYPAL_TIMEOUT_MS })
}

/** Is anything still going to change about this payment? */
export function isOpen(payment) {
  return payment?.status === 'CREATED' || payment?.status === 'HELD'
}

/** "$2,400.00" in the payment's currency. */
export function formatMoney(amount, currency) {
  const value = Number(amount)
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(value)
  } catch {
    return `${value.toFixed(2)} ${currency}`
  }
}

/** What happened to the money, in a few words, with the badge tone that goes with it. */
export function describeStatus(payment) {
  switch (payment.status) {
    case 'CREATED':
      return { tone: 'neutral', label: 'Waiting for PayPal approval', headline: 'Approve the payment in PayPal.' }
    case 'HELD':
      if (payment.hold_reason === 'release_pending') {
        return { tone: 'medium', label: 'Held · waiting for PayPal', headline: 'The call checked out. Waiting for PayPal to release it.' }
      }
      return payment.hold_reason === 'likely_scam'
        ? { tone: 'high', label: 'Held · likely scam', headline: 'Held. No money has moved.' }
        : payment.hold_reason === 'verify'
          ? { tone: 'medium', label: 'Held · call back first', headline: 'Held. No money has moved.' }
          : { tone: 'medium', label: 'Held · call in progress', headline: 'Held while the call goes on.' }
    case 'CAPTURED':
      return { tone: 'low', label: 'Released', headline: `Released to ${payment.recipient_name}.` }
    case 'PAID_OUT':
      return { tone: 'low', label: 'Released and paid out', headline: `Released and sent on to ${payment.recipient_name}.` }
    case 'VOIDED':
      return { tone: 'neutral', label: 'Cancelled', headline: 'Cancelled. The money never left your account.' }
    default:
      return { tone: 'high', label: 'Failed', headline: 'PayPal declined this payment.' }
  }
}

/** The short form a report keeps of a payment: the same fields as payment_gate.summary() in the backend. */
export function summarizePayment(payment) {
  const { payment_id, status, hold_reason, amount, currency, recipient_name, verification, paypal } = payment
  return { payment_id, status, hold_reason, amount, currency, recipient_name, verification, paypal }
}
