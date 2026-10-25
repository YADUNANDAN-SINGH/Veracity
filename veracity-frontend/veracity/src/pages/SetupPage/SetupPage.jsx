/*
 * Home page: Step 1 · Check setup (Design System §4).
 *
 * Runs GET /api/health on load (via the useHealth hook in App) and shows one
 * row per check. A failed check shows the exact command that fixes it.
 * "Continue" stays disabled until every blocking check passes, or the
 * backend runs in simulation mode (VERA_FAKE=1).
 */
import { useMemo } from 'react'
import Panel from '../../components/ui/Panel'
import Button from '../../components/ui/Button'
import AlertBanner from '../../components/ui/AlertBanner'
import Toggle from '../../components/ui/Toggle'
import SetupStep from '../../components/setup/SetupStep'
import { buildChecks, FIX_COMMANDS } from '../../api/health'
import './SetupPage.css'

/**
 * @param {object}   props
 * @param {object}   props.healthState  { health, loading, error, recheck } from useHealth()
 * @param {boolean}  props.saveAudio    "Save call audio" preference (off by default)
 * @param {Function} props.onSaveAudioChange
 * @param {Function} props.onContinue   go to Step 2 · Check number
 */
export default function SetupPage({ healthState, saveAudio, onSaveAudioChange, onContinue }) {
  const { health, loading, error, recheck } = healthState
  const simulation = Boolean(health?.fake_mode)

  const checks = useMemo(() => buildChecks(health, { loading, error }), [health, loading, error])
  const failing = checks.filter((check) => check.status === 'fail' && check.blocking)

  // Simulation replaces the phone and models, so only a reachable backend matters
  const canContinue = !loading && !error && (simulation || failing.length === 0)

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
          The phone, the models and the transcript are scripted stand-ins. Scores you see are
          not measurements.
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

/** Short line next to "Continue" that says why it is (or isn't) enabled. */
function continueHint({ loading, error, simulation, failing }) {
  if (loading) return 'Checking your setup…'
  if (error) return 'Start the backend to continue'
  if (simulation) return 'Simulation mode: hardware checks are skipped'
  if (failing === 1) return 'Fix the red item to continue'
  if (failing > 1) return `Fix the ${failing} red items to continue`
  return 'Everything is ready'
}
