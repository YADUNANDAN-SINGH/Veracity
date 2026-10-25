/*
 * Runs POST /api/number/check on demand (the "Check number" button).
 * Lives in App, like useHealth, so the result survives going back a step
 * and can feed the report later. A new check aborts the previous one.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { checkNumber } from '../api/number'

export function useNumberCheck() {
  const [state, setState] = useState({ details: null, loading: false, error: null })
  const controllerRef = useRef(null)

  const check = useCallback(async (number) => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    setState({ details: null, loading: true, error: null })
    try {
      const details = await checkNumber(number, { signal: controller.signal })
      setState({ details, loading: false, error: null })
    } catch (error) {
      if (controller.signal.aborted) return // superseded or unmounted
      setState({ details: null, loading: false, error })
    }
  }, [])

  useEffect(() => () => controllerRef.current?.abort(), [])

  return { ...state, check }
}
