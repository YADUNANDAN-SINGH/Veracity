/*
 * Polls GET /api/call/state about once a second while the component is mounted.
 * `onIncomingNumber(number)` fires once per new caller number the phone reports,
 * so a page can fill in and check the number without re-checking every poll.
 * The next poll starts only after the previous one settles, so slow adb
 * calls never pile up.
 */
import { useEffect, useRef, useState } from 'react'
import { fetchCallState } from '../api/call'

const POLL_MS = 1000

export function useCallState({ onIncomingNumber } = {}) {
  const [state, setState] = useState({ connected: null, state: 'idle', number: null, error: null })
  // Keep the latest callback without restarting the polling loop
  const onIncomingRef = useRef(onIncomingNumber)
  useEffect(() => {
    onIncomingRef.current = onIncomingNumber
  })

  useEffect(() => {
    const controller = new AbortController()
    let timer
    let lastNumber = null

    async function poll() {
      try {
        const call = await fetchCallState({ signal: controller.signal })
        setState({ ...call, error: null })
        if (call.number && call.state !== 'idle' && call.number !== lastNumber) {
          lastNumber = call.number
          onIncomingRef.current?.(call.number)
        }
        if (call.state === 'idle') lastNumber = null // the same caller may ring again
      } catch (error) {
        if (controller.signal.aborted) return
        setState((prev) => ({ ...prev, error }))
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, POLL_MS)
    }

    poll()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [])

  return state
}
