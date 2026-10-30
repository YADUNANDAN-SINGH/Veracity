/*
 * App shell: owns the current step of the four-step flow and the state
 * that several steps share, then renders the header and the active page.
 *
 * Step 4 (Report) is not built yet; it renders a placeholder so the flow
 * can already be clicked through. The finished report is in live.report.
 */
import { useState } from 'react'
import AppHeader from './components/layout/AppHeader'
import Panel from './components/ui/Panel'
import Button from './components/ui/Button'
import SetupPage from './pages/SetupPage/SetupPage'
import NumberPage from './pages/NumberPage/NumberPage'
import LivePage from './pages/LivePage/LivePage'
import { useHealth } from './hooks/useHealth'
import { useNumberCheck } from './hooks/useNumberCheck'
import { useLiveSession } from './hooks/useLiveSession'
import { STEPS } from './constants/steps'

/* useLiveSession status → the header's CallStatus pill */
const CALL_STATUS = { idle: 'idle', starting: 'starting', live: 'live', stopping: 'live', ended: 'ended', error: 'idle' }

export default function App() {
  const [step, setStep] = useState(1)
  const [saveAudio, setSaveAudio] = useState(false) // sent with POST /api/session/start
  const healthState = useHealth()
  const numberState = useNumberCheck() // result goes into the report later
  const live = useLiveSession()

  function goToLiveCall() {
    if (live.status === 'ended' || live.status === 'error') live.reset() // a new number means a new call
    setStep(3)
  }

  return (
    <>
      <AppHeader
        step={step}
        simulation={Boolean(healthState.health?.fake_mode) || live.demo}
        callStatus={CALL_STATUS[live.status]}
        elapsed={live.elapsed}
      />

      {step === 1 ? (
        <SetupPage
          healthState={healthState}
          saveAudio={saveAudio}
          onSaveAudioChange={setSaveAudio}
          onContinue={() => setStep(2)}
        />
      ) : step === 2 ? (
        <NumberPage numberState={numberState} onBack={() => setStep(1)} onContinue={goToLiveCall} />
      ) : step === 3 ? (
        <LivePage
          live={live}
          number={numberState.details}
          health={healthState.health}
          saveAudio={saveAudio}
          onBack={() => setStep(2)}
          onContinue={() => setStep(4)}
        />
      ) : (
        <ComingNext step={step} onBack={() => setStep(3)} />
      )}
    </>
  )
}

/* Temporary stand-in for steps that are still being built. */
function ComingNext({ step, onBack }) {
  const label = STEPS.find((s) => s.id === step)?.label
  return (
    <main style={{ maxWidth: 'var(--content-width)', margin: '0 auto', padding: 'var(--space-7) var(--space-4)' }}>
      <Panel title={`Step ${step} · ${label}`}>
        <p className="muted" style={{ marginBottom: 'var(--space-4)' }}>
          This screen is next on the build list.
        </p>
        <Button onClick={onBack}>Back to the call</Button>
      </Panel>
    </main>
  )
}
