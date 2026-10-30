/*
 * Runs one monitored call: start → live events → stop → report.
 *
 * Lives in App (not the page) so the header's call status and timer keep
 * working, and so the report is still there for Step 4.
 *
 * status: 'idle' | 'starting' | 'live' | 'stopping' | 'ended' | 'error'
 *
 * While the backend has no session API (start returns 404), it plays the
 * scripted call in demoCall.js instead and sets `demo: true`.
 */
import { useCallback, useReducer, useRef } from 'react'
import { openLiveSocket, startSession, stopSession } from '../api/session'
import { startDemoCall } from '../api/demoCall'

const SERIES_LIMIT = 3600 // one voice window per second: an hour of call
const LEVELS_LIMIT = 36000 // level events arrive ~10 a second

const INITIAL = {
  status: 'idle',
  sessionId: null,
  demo: false,
  error: null,
  elapsed: 0,
  level: null, // latest dBFS
  levels: [], // { t, dbfs } for the waveform
  voice: null, // latest voice event
  series: [], // { t, p, smooth, state } per window, or { t, gap: true, state } for silence
  transcript: [],
  flags: [],
  scriptScore: null,
  alert: null,
  report: null,
  streamLost: false,
}

function reducer(state, action) {
  switch (action.type) {
    case 'start':
      return { ...INITIAL, status: 'starting' }
    case 'reset':
      return INITIAL
    case 'started':
      return { ...state, status: 'live', sessionId: action.sessionId, demo: action.demo }
    case 'failed':
      return { ...state, status: 'error', error: action.error }
    case 'stopping':
      return { ...state, status: 'stopping' }
    case 'stream-lost':
      return state.status === 'live' ? { ...state, streamLost: true } : state
    case 'event':
      return applyEvent(state, action.event)
    default:
      return state
  }
}

/** One WebSocket event → screen state. The backend decides every verdict; this only records it. */
function applyEvent(state, event) {
  const elapsed = typeof event.t === 'number' ? Math.max(state.elapsed, event.t) : state.elapsed
  switch (event.type) {
    case 'level':
      return {
        ...state,
        elapsed,
        level: event.dbfs,
        levels: [...state.levels, { t: event.t, dbfs: event.dbfs }].slice(-LEVELS_LIMIT),
      }
    case 'voice': {
      const point = event.speech
        ? { t: event.t, p: Math.round(event.p_ai * 100), smooth: Math.round(event.smoothed * 100), state: event.state }
        : { t: event.t, gap: true, state: event.state }
      return { ...state, elapsed, voice: event, series: [...state.series, point].slice(-SERIES_LIMIT) }
    }
    case 'transcript':
      return { ...state, elapsed, transcript: [...state.transcript, event] }
    case 'flag':
      return { ...state, elapsed, flags: [...state.flags, event] }
    case 'script':
      return { ...state, scriptScore: event.score }
    case 'alert':
      return { ...state, alert: event }
    case 'report':
      return { ...state, report: event.report }
    case 'ended':
      return { ...state, status: 'ended', streamLost: false }
    default:
      return state
  }
}

export function useLiveSession() {
  const [state, dispatch] = useReducer(reducer, INITIAL)
  const closeRef = useRef(null) // closes the socket, or the demo's stop()
  const activeRef = useRef(false) // guards double starts (StrictMode runs effects twice)

  const start = useCallback(async ({ callerNumber, saveAudio }) => {
    if (activeRef.current) return
    activeRef.current = true
    dispatch({ type: 'start' })
    const onEvent = (event) => {
      if (event.type === 'ended') activeRef.current = false // the call can end from the phone side
      dispatch({ type: 'event', event })
    }

    try {
      const { session_id } = await startSession({ callerNumber, saveAudio })
      closeRef.current = openLiveSocket(session_id, {
        onEvent,
        onClose: () => dispatch({ type: 'stream-lost' }),
      })
      dispatch({ type: 'started', sessionId: session_id, demo: false })
    } catch (error) {
      if (error.status === 404) {
        const demo = startDemoCall({ callerNumber, onEvent })
        closeRef.current = demo.stop
        dispatch({ type: 'started', sessionId: 'demo', demo: true })
        return
      }
      activeRef.current = false
      dispatch({ type: 'failed', error })
    }
  }, [])

  const stop = useCallback(async () => {
    dispatch({ type: 'stopping' })
    const close = closeRef.current
    closeRef.current = null
    activeRef.current = false
    if (state.demo) {
      close?.() // the demo emits report + ended itself
      return
    }
    try {
      const report = await stopSession(state.sessionId)
      dispatch({ type: 'event', event: { type: 'report', report } })
      dispatch({ type: 'event', event: { type: 'ended' } })
    } catch (error) {
      dispatch({ type: 'failed', error })
    } finally {
      close?.()
    }
  }, [state.demo, state.sessionId])

  /** Forget a finished call so the next visit to Step 3 starts a new one. */
  const reset = useCallback(() => {
    if (!activeRef.current) dispatch({ type: 'reset' })
  }, [])

  return { ...state, start, stop, reset }
}
