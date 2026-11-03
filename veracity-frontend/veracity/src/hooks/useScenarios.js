/*
 * GET /api/session/scenarios: the calls that can be replayed without a phone
 * (judge mode and VERA_FAKE=1). Loaded only when `enabled`.
 */
import { useEffect, useState } from 'react'
import { fetchScenarios } from '../api/session'

export function useScenarios(enabled) {
  const [state, setState] = useState({ scenarios: [], defaultId: null, error: null })

  useEffect(() => {
    if (!enabled) return undefined
    const controller = new AbortController()
    fetchScenarios({ signal: controller.signal })
      .then((body) => setState({ scenarios: body.scenarios, defaultId: body.default, error: null }))
      .catch((error) => {
        if (!controller.signal.aborted) setState((prev) => ({ ...prev, error }))
      })
    return () => controller.abort()
  }, [enabled])

  return state
}
