/*
 * Loads GET /api/health on mount and exposes a `recheck` for the
 * "Check again" button. Stale requests are aborted so an old response
 * can never overwrite a newer one.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchHealth } from '../api/health'

export function useHealth() {
  // Starts in `loading` because the first check runs on mount
  const [state, setState] = useState({ health: null, loading: true, error: null })
  const controllerRef = useRef(null)

  // Fetch and store the result; only updates state once the request settles
  const load = useCallback(async () => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    try {
      const health = await fetchHealth({ signal: controller.signal })
      setState({ health, loading: false, error: null })
    } catch (error) {
      if (controller.signal.aborted) return // superseded or unmounted
      setState({ health: null, loading: false, error })
    }
  }, [])

  // "Check again": show the checking state, then reload
  const recheck = useCallback(() => {
    setState((prev) => ({ ...prev, loading: true, error: null }))
    load()
  }, [load])

  useEffect(() => {
    // load() only sets state after the request settles, never synchronously
    // eslint-disable-next-line react/set-state-in-effect
    load()
    return () => controllerRef.current?.abort()
  }, [load])

  return { ...state, recheck }
}
