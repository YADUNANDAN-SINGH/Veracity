/*
 * GET /api/health: the system check behind Step 1 (Check setup).
 *
 * Expected response (agreed with the backend; see README "API contract"):
 * {
 *   "status": "ok",
 *   "fake_mode": false,                 // VERA_FAKE=1 → simulation mode
 *   "port": 8000,
 *   "adb_found": true,
 *   "adb_devices": 1,                   // devices listed as "device"
 *   "scrcpy_found": true,
 *   "scrcpy_version": "4.1",            // null if not found
 *   "audio_device": "BlackHole 2ch",    // null if not found
 *   "audio_sample_rate": 48000,
 *   "models": {
 *     "voice":   { "id": "mo-thecreator/Deepfake-audio-detection", "ready": true },
 *     "whisper": { "id": "small", "ready": true },
 *     "llm":     { "id": "llama3.1:8b", "ready": false }
 *   }
 * }
 */
import { apiRequest } from './client'

export function fetchHealth({ signal } = {}) {
  return apiRequest('/api/health', { signal })
}

/* Exact commands shown to the user when a check fails (Design System §4, Step 1). */
export const FIX_COMMANDS = {
  backend: 'uvicorn app.main:app --port 8000',
  adb: 'brew install --cask android-platform-tools',
  scrcpy: 'brew install scrcpy',
  audio: 'brew install blackhole-2ch',
  voice: "python -c \"from transformers import pipeline; pipeline('audio-classification', model='mo-thecreator/Deepfake-audio-detection')\"",
  whisper: "python -c \"from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')\"",
  llm: 'ollama pull llama3.1:8b',
  simulation: 'VERA_FAKE=1 uvicorn app.main:app --port 8000',
}

const REQUIRED_AUDIO_DEVICE = 'BlackHole 2ch'
const REQUIRED_SAMPLE_RATE = 48000

/**
 * Turn the raw health response into the rows the UI shows.
 * Kept pure (no React) so it is easy to test and to change when the
 * backend contract changes.
 *
 * Each row: { id, title, status, detail, fix?, statusText?, blocking }
 *   statusText: overrides the default word on the right (e.g. "Waiting")
 *   status:   'ok' | 'fail' | 'warn' | 'pending'
 *   blocking: a failed blocking row keeps "Continue" disabled
 *
 * @param {object|null} health  response body, or null while loading
 * @param {{ loading: boolean, error: Error|null }} state
 */
export function buildChecks(health, { loading, error }) {
  // Backend unreachable: only the first row can say anything useful
  if (error) {
    return [
      {
        id: 'backend',
        title: 'Backend',
        status: 'fail',
        detail: "Can't reach the backend. Start it, then check again.",
        fix: FIX_COMMANDS.backend,
        blocking: true,
      },
      ...pendingRows(['adb', 'scrcpy', 'audio', 'models'], 'Waiting for the backend.', 'Waiting'),
    ]
  }

  if (loading || !health) {
    return pendingRows(['backend', 'adb', 'scrcpy', 'audio', 'models'], 'Checking…')
  }

  const models = health.models ?? {}
  const modelNames = [
    models.voice && 'wav2vec2 voice model',
    models.whisper && `Whisper ${models.whisper.id ?? ''}`.trim(),
    models.llm?.id,
  ].filter(Boolean)
  const missingRequired = ['voice', 'whisper'].find((key) => models[key] && !models[key].ready)
  const llmMissing = models.llm && !models.llm.ready

  const deviceCount = health.adb_devices ?? 0
  const audioOk = health.audio_device === REQUIRED_AUDIO_DEVICE

  return [
    {
      id: 'backend',
      title: 'Backend',
      status: 'ok',
      detail: `FastAPI is running on :${health.port ?? 8000}.`,
      blocking: true,
    },
    health.adb_found && deviceCount > 0
      ? {
          id: 'adb',
          title: 'Phone over adb',
          status: 'ok',
          detail: `${deviceCount} device${deviceCount > 1 ? 's' : ''} listed as “device”. USB debugging is on.`,
          blocking: true,
        }
      : {
          id: 'adb',
          title: 'Phone over adb',
          status: 'fail',
          detail: health.adb_found
            ? 'No phone found. Plug it in with a data cable and allow USB debugging.'
            : "adb wasn't found. Install it, then check again.",
          fix: health.adb_found ? 'adb devices' : FIX_COMMANDS.adb,
          blocking: true,
        },
    health.scrcpy_found
      ? {
          id: 'scrcpy',
          title: 'scrcpy',
          status: 'ok',
          detail: health.scrcpy_version ? `Version ${health.scrcpy_version}.` : 'Installed.',
          blocking: true,
        }
      : {
          id: 'scrcpy',
          title: 'scrcpy',
          status: 'fail',
          detail: "scrcpy wasn't found. Install it, then check again.",
          fix: FIX_COMMANDS.scrcpy,
          blocking: true,
        },
    audioOk
      ? {
          id: 'audio',
          title: 'Audio input',
          status: 'ok',
          detail: `${health.audio_device} at ${(health.audio_sample_rate ?? REQUIRED_SAMPLE_RATE) / 1000} kHz.`,
          blocking: true,
        }
      : {
          id: 'audio',
          title: 'Audio input',
          status: 'fail',
          detail: `Needs “${REQUIRED_AUDIO_DEVICE}” as the input, at ${REQUIRED_SAMPLE_RATE / 1000} kHz.`,
          fix: health.audio_device ? undefined : FIX_COMMANDS.audio,
          blocking: true,
        },
    missingRequired
      ? {
          id: 'models',
          title: 'Models',
          status: 'fail',
          detail: `The ${missingRequired === 'voice' ? 'voice' : 'Whisper'} model isn't downloaded yet.`,
          fix: FIX_COMMANDS[missingRequired],
          blocking: true,
        }
      : llmMissing
        ? {
            // The local LLM is optional: without it the rule engine still flags scam phrases
            id: 'models',
            title: 'Models',
            status: 'warn',
            detail: `${models.llm.id} isn't available, so only the scam rules will run.`,
            fix: FIX_COMMANDS.llm,
            blocking: false,
          }
        : {
            id: 'models',
            title: 'Models',
            status: 'ok',
            detail: modelNames.join(' · ') || 'Ready.',
            blocking: true,
          },
  ]
}

function pendingRows(ids, detail, statusText) {
  const titles = {
    backend: 'Backend',
    adb: 'Phone over adb',
    scrcpy: 'scrcpy',
    audio: 'Audio input',
    models: 'Models',
  }
  return ids.map((id) => ({ id, title: titles[id], status: 'pending', detail, statusText, blocking: true }))
}
