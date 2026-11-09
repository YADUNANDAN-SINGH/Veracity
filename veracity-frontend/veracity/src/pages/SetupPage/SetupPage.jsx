/*
 * Home page: Step 1 · Check setup (Design System §4).
 *
 * Runs GET /api/health on load (via the useHealth hook in App) and shows one
 * row per check. A failed check shows the exact command that fixes it.
 * "Continue" stays disabled until every blocking check passes, or the
 * backend runs in simulation mode (VERA_FAKE=1).
 */
import { useEffect, useMemo } from 'react'
import Panel from '../../components/ui/Panel'
import Button from '../../components/ui/Button'
import AlertBanner from '../../components/ui/AlertBanner'
import Toggle from '../../components/ui/Toggle'
import SetupStep from '../../components/setup/SetupStep'
import { buildChecks, FIX_COMMANDS } from '../../api/health'
import { useScenarios } from '../../hooks/useScenarios'
import './SetupPage.css'

/**
 * @param {object}   props
 * @param {object}   props.healthState  { health, loading, error, recheck } from useHealth()
 * @param {boolean}  props.saveAudio    "Save call audio" preference (off by default)
 * @param {Function} props.onSaveAudioChange
 * @param {Function} props.onContinue   go to Step 2 · Check number (judge mode: pick a sample call)
 * @param {Function} props.onUpload     judge mode: go to Step 2 to upload a call recording
 * @param {Function} props.onReplay     judge mode: (sample call) => void, straight to Step 3 with this call
 */
export default function SetupPage({ healthState, saveAudio, onSaveAudioChange, onContinue, onUpload, onReplay }) {
  const { health, loading, error, recheck } = healthState
  const simulation = Boolean(health?.fake_mode)

  const checks = useMemo(() => buildChecks(health, { loading, error }), [health, loading, error])
  const failing = checks.filter((check) => check.status === 'fail' && check.blocking)

  // Simulation replaces the phone and models, so only a reachable backend matters
  const canContinue = !loading && !error && (simulation || failing.length === 0)

  if (health?.mode === 'judge') {
    return <JudgeSetup health={health} recheck={recheck} onContinue={onContinue} onUpload={onUpload} onReplay={onReplay} />
  }

  return (
    <main className="setup-page">
      <div className="setup-page__intro">
        <p className="t-overline muted">STEP 1 OF 4</p>
        <h1 className="t-display">Is the voice on your call real?</h1>
        <p className="muted setup-page__lede">
          Veracity checks the number, the voice and the words while the call is still going on,
          then hands you an evidence report. Everything runs on this laptop.
        </p>
      </div>

      <Panel
        title="System check"
        flush
        action={
          <Button variant="ghost" size="sm" icon="refresh" onClick={recheck} disabled={loading}>
            {loading ? 'Checking…' : 'Check again'}
          </Button>
        }
      >
        <ol className="setup-page__checks" aria-live="polite" aria-busy={loading}>
          {checks.map((check, i) => (
            <SetupStep key={check.id} index={i + 1} {...check} />
          ))}
        </ol>
      </Panel>

      {/* The one banner on this screen: how to work without a phone */}
      {simulation ? (
        <AlertBanner tone="info" title="Simulation mode is on">
          Calls are replayed sample calls instead of the phone. The scam rules and PayPal sandbox are real; a
          scripted call has no voice score.
        </AlertBanner>
      ) : (
        <AlertBanner tone="info" title="No phone handy?">
          Run the whole dashboard on scripted stand-ins:{' '}
          <code className="code-chip">{FIX_COMMANDS.simulation}</code>
        </AlertBanner>
      )}

      <Panel title="Privacy">
        <Toggle
          label="Save call audio"
          description="Off by default. Audio is analysed in memory. If you turn this on, the report stores the file's SHA-256."
          checked={saveAudio}
          onChange={onSaveAudioChange}
        />
      </Panel>

      <footer className="setup-page__footer">
        <p className="t-body-sm muted" aria-live="polite">
          {continueHint({ loading, error, simulation, failing: failing.length })}
        </p>
        <Button variant="primary" iconRight="chevron-right" disabled={!canContinue} onClick={onContinue}>
          Continue
        </Button>
      </footer>
    </main>
  )
}

/* How often to ask again while the full judge build is still loading its models */
const UPLOAD_RECHECK_MS = 3000
const MODELS_LOADING = 'models still loading'
// The sample calls with a real recording, one click from here
const RECORDED_SAMPLES = [
  { id: 'elevenlabs_scam_us', label: 'Replay ElevenLabs AI Scam Audio' },
  { id: 'real_voice_no_scam_us', label: 'Replay Real Voice (No Scam)' },
]

/**
 * The judge builds: nothing to set up. Say plainly what is real here and what
 * needs the phone build, so nobody mistakes a replay for a live call. The full
 * judge build (Dockerfile.judge) can also analyse an uploaded recording with the
 * real models; the light one shows that option disabled, with the reason.
 */
function JudgeSetup({ health, recheck, onContinue, onUpload, onReplay }) {
  const paypal = health.paypal ?? {}
  const upload = health.upload ?? { available: false, reason: 'needs the full judge build' }
  const models = upload.available || upload.reason === MODELS_LOADING // the full judge build
  const { scenarios } = useScenarios(true)
  const recorded = RECORDED_SAMPLES.flatMap(({ id, label }) => {
    const sample = scenarios.find((s) => s.id === id && s.audio_url)
    return sample ? [{ sample, label }] : []
  })
  const holdsWith = paypal.standin ? 'the built-in PayPal stand-in' : 'the real PayPal sandbox'

  // The models load for a few seconds after start-up: turn the upload option on when they're ready
  useEffect(() => {
    if (upload.reason !== MODELS_LOADING) return undefined
    const timer = setTimeout(recheck, UPLOAD_RECHECK_MS)
    return () => clearTimeout(timer)
  }, [upload.reason, recheck])

  const real = [
    {
      id: 'rules',
      title: 'Scam-script rules',
      status: 'ok',
      detail: 'The same code as the phone build, run live on every line of the call as it plays.',
    },
    {
      id: 'report',
      title: 'Risk fusion and evidence report',
      status: 'ok',
      detail: 'Number, voice and script fused into one risk level, with next steps for the region.',
    },
    paypal.configured
      ? {
          id: 'paypal',
          title: 'PayPal sandbox',
          status: 'ok',
          detail: `Orders v2 (intent AUTHORIZE), capture and void${paypal.payouts ? ', Payouts' : ''}${
            paypal.webhooks ? ', verified webhooks' : ''
          }. Test money only.`,
        }
      : paypal.standin
        ? {
            id: 'paypal',
            title: 'PayPal stand-in, not PayPal',
            status: 'warn',
            statusText: 'No keys',
            detail: 'No sandbox keys are set, so an in-memory stand-in answers the same Orders v2 and Payments v2 calls. Nothing reaches PayPal, and its ids and debug ids are made up. Add keys to .env for the real sandbox.',
          }
        : { id: 'paypal', title: 'PayPal sandbox', status: 'warn', detail: 'Not configured on this server.' },
    ...(models
      ? [
          {
            id: 'voice',
            title: 'AI-voice model',
            status: upload.available ? 'ok' : 'pending',
            statusText: upload.available ? undefined : 'Loading',
            detail: 'Spectra-0, scoring an uploaded recording’s voice every second.',
          },
          {
            id: 'stt',
            title: 'Whisper',
            status: upload.available ? 'ok' : 'pending',
            statusText: upload.available ? undefined : 'Loading',
            detail: 'Speech to text on an uploaded recording, on this machine’s CPU.',
          },
        ]
      : []),
  ]
  const phoneOnly = models
    ? [
        { id: 'audio', title: 'Live call audio', status: 'pending', statusText: 'Phone build', detail: 'An Android phone over USB, captured with scrcpy and BlackHole.' },
        { id: 'llm', title: 'The local LLM', status: 'pending', statusText: 'Phone build', detail: 'Llama 3.1 8B through Ollama. Here the scam rules run on their own.' },
      ]
    : [
        { id: 'audio', title: 'Live call audio', status: 'pending', statusText: 'Phone build', detail: 'An Android phone over USB, captured with scrcpy and BlackHole.' },
        { id: 'voice', title: 'AI-voice model', status: 'pending', statusText: 'Phone build', detail: 'Spectra-0, scoring the caller every second.' },
        { id: 'stt', title: 'Whisper and the local LLM', status: 'pending', statusText: 'Phone build', detail: 'Speech to text and Llama 3.1 8B, all on the laptop.' },
      ]

  return (
    <main className="setup-page">
      <div className="setup-page__intro">
        <p className="t-overline muted">STEP 1 OF 4 · JUDGE MODE</p>
        <h1 className="t-display">Is the voice on your call real?</h1>
        <p className="muted setup-page__lede">
          {models
            ? `This is Veracity’s judge build, running on this machine. Replay a sample call through the real scam rules, or upload a call recording for the real AI-voice model and Whisper to analyse. If the caller asks for money, Protected Send holds it with ${holdsWith} until the call checks out.`
            : `This is Veracity’s light judge build, running on this machine. Step 3 replays a sample call through the real scam rules, and if the caller asks for money, Protected Send holds it with ${holdsWith} until the call checks out.`}
        </p>
      </div>

      {recorded.length > 0 && onReplay && (
        <Panel title="Hear it tell an AI voice from a real one" action={<span className="t-body-sm muted">plays sound</span>}>
          <div className="setup-page__replay">
            <p className="t-body-sm">
              Real recordings you can hear: a scam call in an AI voice we generated with ElevenLabs, and a real person
              asking for $50. The voice scores and transcripts are what Spectra-0 and Whisper produced on these exact
              files, computed ahead of time so they play in real time. The scam rules run on them live.
            </p>
            <div className="setup-page__replay-actions">
              {recorded.map(({ sample, label }) => (
                <Button key={sample.id} icon="volume" onClick={() => onReplay(sample)}>
                  {label}
                </Button>
              ))}
            </div>
          </div>
        </Panel>
      )}

      <Panel title="Real in this build" flush>
        <ol className="setup-page__checks">
          {real.map((row, i) => (
            <SetupStep key={row.id} index={i + 1} blocking={false} {...row} />
          ))}
        </ol>
      </Panel>

      <Panel title="Needs the phone build (see the video)" flush>
        <ol className="setup-page__checks">
          {phoneOnly.map((row, i) => (
            <SetupStep key={row.id} index={i + 1} blocking={false} {...row} />
          ))}
        </ol>
      </Panel>

      {health.sandbox_buyer?.email && (
        <AlertBanner tone="info" title="PayPal sandbox buyer">
          Log in to the PayPal pop-up with <code className="code-chip">{health.sandbox_buyer.email}</code>
          {health.sandbox_buyer.password && (
            <>
              {' '}/ <code className="code-chip">{health.sandbox_buyer.password}</code>
            </>
          )}
          . It’s a sandbox test account with test money.
        </AlertBanner>
      )}

      <footer className="setup-page__footer setup-page__footer--judge">
        <p className="t-body-sm muted" aria-live="polite">
          {upload.available ? 'A sample call takes about two minutes' : `Upload a call recording: ${upload.reason}`}
        </p>
        <Button icon="upload" disabled={!upload.available} onClick={onUpload} title={upload.available ? undefined : upload.reason}>
          Upload a call recording
        </Button>
        <Button variant="primary" iconRight="chevron-right" onClick={onContinue}>
          Pick a sample call
        </Button>
      </footer>
    </main>
  )
}

/** Short line next to "Continue" that says why it is (or isn't) enabled. */
function continueHint({ loading, error, simulation, failing }) {
  if (loading) return 'Checking your setup…'
  if (error) return 'Start the backend to continue'
  if (simulation) return 'Simulation mode: hardware checks are skipped'
  if (failing === 1) return 'Fix the red item to continue'
  if (failing > 1) return `Fix the ${failing} red items to continue`
  return 'Everything is ready'
}
