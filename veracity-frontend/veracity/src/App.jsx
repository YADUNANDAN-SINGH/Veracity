/*
 * App shell: owns the current step of the four-step flow and the state
 * that several steps share, then renders the header and the active page.
 *
 * Steps 3–4 (Live call, Report) are not built yet; they render a
 * placeholder so the flow can already be clicked through.
 */
import { useState } from 'react'
import AppHeader from './components/layout/AppHeader'
import Panel from './components/ui/Panel'
import Button from './components/ui/Button'
import SetupPage from './pages/SetupPage/SetupPage'
import NumberPage from './pages/NumberPage/NumberPage'
import { useHealth } from './hooks/useHealth'
import { useNumberCheck } from './hooks/useNumberCheck'
import { STEPS } from './constants/steps'

export default function App() {
  const [step, setStep] = useState(1)
  const [saveAudio, setSaveAudio] = useState(false) // sent with POST /api/session/start later
  const healthState = useHealth()
  const numberState = useNumberCheck() // result goes into the report later

  return (
    <>
      <AppHeader step={step} simulation={Boolean(healthState.health?.fake_mode)} callStatus="idle" />

      {step === 1 ? (
        <SetupPage
          healthState={healthState}
          saveAudio={saveAudio}
          onSaveAudioChange={setSaveAudio}
          onContinue={() => setStep(2)}
        />
      ) : step === 2 ? (
        <NumberPage numberState={numberState} onBack={() => setStep(1)} onContinue={() => setStep(3)} />
      ) : (
        <ComingNext step={step} onBack={() => setStep(2)} />
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
        <Button onClick={onBack}>Back to setup</Button>
      </Panel>
    </main>
  )
}
