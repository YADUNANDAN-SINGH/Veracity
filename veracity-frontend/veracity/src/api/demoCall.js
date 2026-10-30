/*
 * A scripted "digital arrest" call played in the browser.
 *
 * Used only while the backend has no session API yet (POST /api/session/start
 * returns 404), so Step 3 can be built and shown without a phone or models.
 * It emits exactly the events the real WebSocket will (see session.js), at
 * real speed: level every 0.1 s, voice every 1 s, a transcript line every
 * 16 s. Once the backend's VERA_FAKE=1 mode exists, delete this file.
 */

const TICK_S = 0.1

/* Caller lines and the rule hits in each (evidence = the exact matched words) */
const SCRIPT = [
  {
    t: 8,
    text: 'Main Mumbai Cyber Crime se Inspector Sharma bol raha hoon.',
    flags: [{ category: 'AUTHORITY_IMPERSONATION', severity: 3, evidence: 'Cyber Crime' }],
  },
  {
    t: 24,
    text: 'A parcel in your name has drugs. You are under digital arrest.',
    flags: [
      { category: 'PARCEL_COURIER', severity: 2, evidence: 'parcel in your name' },
      { category: 'THREAT_ARREST', severity: 3, evidence: 'digital arrest' },
    ],
  },
  {
    t: 40,
    text: 'Kisi ko mat batana. Do not disconnect this call.',
    flags: [{ category: 'SECRECY', severity: 2, evidence: 'Kisi ko mat batana' }],
  },
  {
    t: 56,
    text: 'To clear your name, transfer the money to a safe account right now.',
    flags: [
      { category: 'PAYMENT_PRESSURE', severity: 3, evidence: 'safe account' },
      { category: 'URGENCY', severity: 1, evidence: 'right now' },
    ],
  },
]

/* Seconds where the caller is quiet; the backend sends speech: false for these */
const SILENT = [
  [0, 3],
  [13, 15],
  [19, 20],
]

/** Raw AI likelihood at second t: human-sounding at first, then a cloned voice takes over. */
function rawPAi(t) {
  const noise = (Math.sin(t * 2.7) + Math.sin(t * 5.3)) * 0.04
  if (t < 22) return 0.16 + noise
  if (t < 34) return 0.16 + ((t - 22) / 12) * 0.72 + noise
  return 0.9 + noise
}

/** Project Document §1.6 script score. */
function scriptScore(categories) {
  const severity = { OTP_PIN_REQUEST: 3, AUTHORITY_IMPERSONATION: 3, THREAT_ARREST: 3, PAYMENT_PRESSURE: 3,
    REMOTE_ACCESS: 3, SECRECY: 2, KYC_ACCOUNT_BLOCK: 2, PARCEL_COURIER: 2, FAMILY_EMERGENCY: 2,
    PRIZE_LOTTERY: 2, URGENCY: 1 }
  let score = 8 * [...categories].reduce((sum, c) => sum + severity[c], 0)
  if (categories.has('AUTHORITY_IMPERSONATION') && categories.has('PAYMENT_PRESSURE')) score += 20
  if (categories.has('FAMILY_EMERGENCY') && categories.has('PAYMENT_PRESSURE')) score += 20
  if (categories.has('OTP_PIN_REQUEST')) score += 10
  return Math.min(100, score)
}

/**
 * Start the scripted call.
 * @param {{ callerNumber: string, onEvent: (event: object) => void }} options
 * @returns {{ stop: () => object }} stop() ends the call and returns its report
 */
export function startDemoCall({ callerNumber, onEvent }) {
  const startedAt = new Date()
  const smoother = { ema: null, run: 0, state: 'LIKELY_HUMAN' }
  const categories = new Set()
  const flags = []
  const windows = []
  let tick = 0
  let alerted = null

  function voiceAt(t) {
    const speech = !SILENT.some(([from, to]) => t >= from && t < to)
    if (!speech) return { type: 'voice', t, p_ai: null, smoothed: smoother.ema ?? 0, state: smoother.state, speech }
    const p = Math.min(0.99, Math.max(0.01, rawPAi(t)))
    windows.push({ t_start: Math.max(0, t - 4), t_end: t, p_ai: round(p) })
    // Same rule as the backend's VerdictSmoother: EMA α=0.5, Likely AI after 3 windows ≥ 0.75
    smoother.ema = smoother.ema === null ? p : 0.5 * p + 0.5 * smoother.ema
    smoother.run = p >= 0.75 ? smoother.run + 1 : 0
    if (smoother.run >= 3) smoother.state = 'LIKELY_AI'
    else if (!(smoother.state === 'LIKELY_AI' && smoother.ema >= 0.4)) {
      smoother.state = smoother.ema >= 0.4 ? 'UNCERTAIN' : 'LIKELY_HUMAN'
    }
    return { type: 'voice', t, p_ai: round(p), smoothed: round(smoother.ema), state: smoother.state, speech }
  }

  const timer = setInterval(() => {
    tick += 1
    const t = Math.round(tick * TICK_S * 10) / 10 // avoid 0.30000000000000004
    const speaking = !SILENT.some(([from, to]) => t >= from && t < to)
    // Speech comes in syllables and words: a slow word envelope, faster syllables, some jitter
    const word = Math.max(0, Math.sin(t * 1.9) + 0.35)
    const syllable = Math.abs(Math.sin(t * 6.3))
    const dbfs = speaking
      ? -40 + 14 * word + 8 * syllable + (Math.random() - 0.5) * 8
      : -56 + (Math.random() - 0.5) * 4
    onEvent({ type: 'level', t, dbfs: round(dbfs, 1) })

    if (Number.isInteger(t)) {
      const voice = voiceAt(t)
      onEvent(voice)
      if (voice.state === 'LIKELY_AI' && !alerted) {
        alerted = 'voice'
        onEvent({ type: 'alert', kind: 'voice', message: 'The voice sounds AI-generated. Hang up, then call back on a number you have saved.' })
      }
    }

    const line = SCRIPT.find((l) => l.t === t)
    if (line) {
      onEvent({ type: 'transcript', t, text: line.text })
      for (const flag of line.flags) {
        categories.add(flag.category)
        const event = { type: 'flag', ...flag, t, source: 'rule' }
        flags.push(event)
        onEvent(event)
      }
      const score = scriptScore(categories)
      onEvent({ type: 'script', score })
      if (score >= 80 && alerted !== 'script') {
        alerted = 'script'
        onEvent({
          type: 'alert',
          kind: 'script',
          message:
            'Hang up, then call back on a number you have saved. This call matches a “digital arrest” scam and the voice sounds AI-generated.',
        })
      }
    }
  }, TICK_S * 1000)

  function stop() {
    clearInterval(timer)
    const endedAt = new Date()
    const voicePeak = windows.length ? Math.max(...windows.map((w) => w.p_ai)) : 0
    const script = scriptScore(categories)
    const report = buildReport({ callerNumber, startedAt, endedAt, windows, voicePeak, script, flags, finalState: smoother.state })
    onEvent({ type: 'report', report })
    onEvent({ type: 'ended' })
    return report
  }

  return { stop }
}

/** Project Document §1.7 report, with §1.8 fusion. The number section waits for /api/number/analyze. */
function buildReport({ callerNumber, startedAt, endedAt, windows, voicePeak, script, flags, finalState }) {
  const voicePct = Math.round(voicePeak * 100)
  const weighted = Math.round(0.4 * voicePct + 0.35 * script)
  const score = Math.max(weighted, voicePct >= 85 ? voicePct : 0, script >= 80 ? script : 0)
  const reasons = []
  if (voicePct >= 40) reasons.push(`Voice sounded synthetic (peak ${voicePct}%)`)
  if (script > 0) reasons.push(`Scam-script red flags (score ${script})`)

  return {
    schema_version: '1.0',
    report_id: crypto.randomUUID(),
    generated_at: endedAt.toISOString(),
    app_version: 'demo',
    call: {
      caller_number: callerNumber,
      started_at: startedAt.toISOString(),
      ended_at: endedAt.toISOString(),
      duration_s: Math.round((endedAt - startedAt) / 1000),
      capture_method: 'demo_replay',
    },
    number: null,
    voice: {
      model_id: 'mo-thecreator/Deepfake-audio-detection',
      windows,
      max_p_ai: voicePeak,
      final_state: finalState,
    },
    script: {
      script_score: script,
      red_flags: flags.map(({ category, severity, evidence, t, source }) => ({ category, severity, evidence, t, source })),
    },
    overall: {
      risk_level: score >= 70 ? 'HIGH' : score >= 40 ? 'MEDIUM' : 'LOW',
      score,
      top_reasons: reasons,
    },
    evidence: { audio_saved: false, audio_sha256: null },
  }
}

function round(value, digits = 4) {
  const f = 10 ** digits
  return Math.round(value * f) / f
}
