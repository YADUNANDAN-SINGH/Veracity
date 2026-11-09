/*
 * The Protected Send payments of one call.
 *
 * create() and approve() are what the PayPal button calls: create the order
 * (intent AUTHORIZE), then, once the payer approves in PayPal, authorize it so
 * the payment gate can decide. payWithStandIn() does all of it when the in-memory
 * stand-in answers instead of PayPal (no sandbox keys). The call's payments are polled every few seconds
 * while the call is on or a payment is still open, because a hold can change on
 * its own (it escalates if the call turns into a scam, it is released when a
 * cooling-off ends, PayPal webhooks update it), and so that a payment made for
 * this call from another device shows up too.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  approveStandIn, authorizePayment, cancelPayment, createPayment, fetchPaymentConfig, isOpen, listPayments, verifyPayment,
} from '../api/payment'

const POLL_MS = 2500

/** The server's list, plus any payment made here that the server's answer predates. */
function merge(local, server) {
  const ids = new Set(server.map((p) => p.payment_id))
  return [...server, ...local.filter((p) => !ids.has(p.payment_id))]
}

/**
 * @param {string}  sessionId  the call's session id
 * @param {boolean} ended      reload when the call ends: the gate decides the holds that waited for it
 */
export function usePayments(sessionId, ended = false) {
  // Payments are kept per session, so a new call starts with an empty list
  const [state, setState] = useState({ sessionId, payments: [] })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null) // the payment_id an action is running on
  const pendingRef = useRef(null) // the order the PayPal pop-up is open for

  const payments = state.sessionId === sessionId ? state.payments : []

  const upsert = useCallback(
    (payment) =>
      setState((prev) => {
        const list = prev.sessionId === payment.session_id ? prev.payments : []
        const i = list.findIndex((p) => p.payment_id === payment.payment_id)
        const next = i === -1 ? [...list, payment] : list.map((p, j) => (j === i ? payment : p))
        return { sessionId: payment.session_id, payments: next }
      }),
    [],
  )

  // The call's payments so far, again once the call has ended
  useEffect(() => {
    if (!sessionId || sessionId === 'demo') return undefined
    const controller = new AbortController()
    listPayments(sessionId, { signal: controller.signal })
      .then((list) => setState({ sessionId, payments: list }))
      .catch(() => {}) // an older backend without payments: nothing to show
    return () => controller.abort()
  }, [sessionId, ended])

  // Follow the call's payments while the call is on, and afterwards until the gate has decided them all
  const hasOpen = payments.some(isOpen)
  useEffect(() => {
    if (!sessionId || sessionId === 'demo' || (ended && !hasOpen)) return undefined
    const timer = setInterval(() => {
      listPayments(sessionId)
        .then((list) =>
          setState((prev) => (prev.sessionId === sessionId ? { sessionId, payments: merge(prev.payments, list) } : prev)),
        )
        .catch(() => {}) // keep the last known state on a blip
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [sessionId, ended, hasOpen])

  /** PayPal button → createOrder: returns the PayPal order id. */
  const create = useCallback(
    async (form) => {
      setError(null)
      try {
        const payment = await createPayment({ ...form, session_id: sessionId })
        pendingRef.current = payment.payment_id
        upsert(payment)
        return payment.paypal.order_id
      } catch (err) {
        setError(err)
        throw err // the PayPal SDK shows its own error state too
      }
    },
    [sessionId, upsert],
  )

  /** PayPal button → onApprove: the gate reserves the money and decides. */
  const approve = useCallback(
    async (orderId) => {
      try {
        const payment = await authorizePayment(orderId)
        pendingRef.current = null
        upsert(payment)
        return payment
      } catch (err) {
        setError(err)
        throw err
      }
    },
    [upsert],
  )

  /** No sandbox keys: the same steps, with the stand-in in place of the payer in PayPal's pop-up. */
  const payWithStandIn = useCallback(
    async (form) => {
      const orderId = await create(form)
      try {
        await approveStandIn(orderId)
      } catch (err) {
        setError(err)
        throw err
      }
      return approve(orderId)
    },
    [create, approve],
  )

  /** The payer closed the PayPal pop-up: drop the order that was never approved. */
  const abandon = useCallback(() => {
    const id = pendingRef.current
    pendingRef.current = null
    if (id) cancelPayment(id).then(upsert).catch(() => {})
  }, [upsert])

  const act = useCallback(
    async (paymentId, request) => {
      setBusy(paymentId)
      setError(null)
      try {
        upsert(await request())
      } catch (err) {
        setError(err)
      } finally {
        setBusy(null)
      }
    },
    [upsert],
  )

  const verify = useCallback((id, outcome) => act(id, () => verifyPayment(id, outcome)), [act])
  const cancel = useCallback((id) => act(id, () => cancelPayment(id)), [act])

  return { payments, error, busy, create, approve, payWithStandIn, abandon, verify, cancel, clearError: () => setError(null) }
}

/** GET /api/payment/config once; null until it arrives (or if the backend has no payments). */
export function usePaymentConfig() {
  const [config, setConfig] = useState(null)
  useEffect(() => {
    const controller = new AbortController()
    fetchPaymentConfig({ signal: controller.signal })
      .then(setConfig)
      .catch(() => {})
    return () => controller.abort()
  }, [])
  return config
}
