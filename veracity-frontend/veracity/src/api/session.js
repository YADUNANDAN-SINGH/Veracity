/*
 * One monitored call (Project Document §1.8):
 *
 *   POST /api/session/start  { caller_number, save_audio, scenario? } → { session_id, replay }
 *   WS   /ws/live/{id}       stream of JSON events; late joiners get the history replayed
 *   POST /api/session/{id}/stop                             → the JSON report
 *   POST /api/session/{id}/say  { text }                    a replayed call hears it as the caller's words
 *   GET  /api/session/scenarios                             calls that can be replayed without a phone
 *
 * Events on the socket, all with a `type`:
 *   mode        { replay, scenario, title, source, voice_scored, region }   first, on a replayed call
 *   level       { t, dbfs }                                   input meter
 *   voice       { t, p_ai, smoothed, state, speech }          state: LIKELY_HUMAN | UNCERTAIN | LIKELY_AI
 *   transcript  { t, text }                                   caller's side only
 *   flag        { category, severity, evidence, t, source }   source: "rule" | "llm"
 *   script      { score }                                     0–100
 *   alert       { kind, message }                             red banner
 *   report      { report }                                    full JSON report
 *   ended       {}                                            close the socket
 * `t` is seconds since the call started. p_ai and smoothed are 0–1.
 */
import { apiRequest, wsUrl } from './client'

export function startSession({ callerNumber, saveAudio = false, scenario = null }) {
  return apiRequest('/api/session/start', {
    method: 'POST',
    body: JSON.stringify({ caller_number: callerNumber || null, save_audio: saveAudio, scenario }),
    timeoutMs: 15000, // starting scrcpy and loading models can take a while
  })
}

export function stopSession(sessionId) {
  return apiRequest(`/api/session/${sessionId}/stop`, { method: 'POST', timeoutMs: 30000 })
}

/** Type a line into a replayed call, as if the caller had just said it. */
export function sayToSession(sessionId, text) {
  return apiRequest(`/api/session/${sessionId}/say`, { method: 'POST', body: JSON.stringify({ text }) })
}

export function fetchScenarios({ signal } = {}) {
  return apiRequest('/api/session/scenarios', { signal })
}

/**
 * Open the live event stream.
 * @returns {() => void} closes the socket
 */
export function openLiveSocket(sessionId, { onEvent, onClose }) {
  const ws = new WebSocket(wsUrl(`/ws/live/${sessionId}`))
  ws.onmessage = (message) => onEvent(JSON.parse(message.data))
  ws.onclose = (event) => onClose?.(event)
  return () => ws.close()
}
