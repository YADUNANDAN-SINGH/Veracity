/*
 * One monitored call (Project Document §1.8):
 *
 *   POST /api/session/start  { caller_number, save_audio, scenario? } → { session_id, replay }
 *   POST /api/session/upload multipart: file, caller_number?   → { session_id, replay: false, upload: true, duration_s }
 *                            an uploaded recording through the real models (the full judge build)
 *   WS   /ws/live/{id}       stream of JSON events; late joiners get the history replayed
 *   POST /api/session/{id}/stop                             → the JSON report
 *   POST /api/session/{id}/say  { text }                    a replayed call hears it as the caller's words
 *   GET  /api/session/scenarios                             calls that can be replayed without a phone
 *
 * Events on the socket, all with a `type`:
 *   mode        { replay, scenario, title, source, voice_scored, region }   first, on a replayed call
 *               { replay: false, upload: true, filename, duration_s, region, llm }  first, on an uploaded recording
 *   level       { t, dbfs }                                   input meter
 *   voice       { t, p_ai, smoothed, state, speech }          state: LIKELY_HUMAN | UNCERTAIN | LIKELY_AI
 *   transcript  { t, text }                                   caller's side only
 *   flag        { category, severity, evidence, t, source }   source: "rule" | "llm"
 *   script      { score }                                     0–100
 *   alert       { kind, message }                             red banner
 *   audio_done  { t }                                         an uploaded recording has played to the end; the
 *                                                             call stays on until the user ends it
 *   report      { report }                                    full JSON report
 *   ended       {}                                            close the socket
 * `t` is seconds since the call started. p_ai and smoothed are 0–1.
 */
import { ApiError, apiRequest, wsUrl } from './client'

export function startSession({ callerNumber, saveAudio = false, scenario = null }) {
  return apiRequest('/api/session/start', {
    method: 'POST',
    body: JSON.stringify({ caller_number: callerNumber || null, save_audio: saveAudio, scenario }),
    timeoutMs: 15000, // starting scrcpy and loading models can take a while
  })
}

/**
 * Upload a call recording and start analysing it. XMLHttpRequest, not fetch, because
 * fetch can't report upload progress.
 * @param {File} file
 * @param {{ callerNumber?: string, onProgress?: (fraction: number) => void }} options
 * @returns {Promise<{ session_id: string, duration_s: number }>}
 */
export function uploadRecording(file, { callerNumber, onProgress } = {}) {
  const form = new FormData()
  form.append('file', file)
  if (callerNumber) form.append('caller_number', callerNumber)

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${import.meta.env.VITE_API_BASE ?? ''}/api/session/upload`)
    xhr.responseType = 'json'
    xhr.timeout = 120000 // decoding a long file on a slow laptop takes a while
    xhr.upload.onprogress = (event) => event.lengthComputable && onProgress?.(event.loaded / event.total)
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve(xhr.response)
      const detail = xhr.response?.detail
      reject(new ApiError(typeof detail === 'string' ? detail : `Upload failed (${xhr.status})`, { status: xhr.status }))
    }
    xhr.onerror = () => reject(new ApiError("Can't reach the backend"))
    xhr.ontimeout = () => reject(new ApiError('The upload took too long. Try a shorter recording.'))
    xhr.send(form)
  })
}

/** End the call. An uploaded recording passes a longer timeout: the backend waits up to 90 s for Whisper. */
export function stopSession(sessionId, { timeoutMs = 30000 } = {}) {
  return apiRequest(`/api/session/${sessionId}/stop`, { method: 'POST', timeoutMs })
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
