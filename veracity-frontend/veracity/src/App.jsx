/*
 * App shell: owns the current step of the four-step flow and the state
 * that several steps share, then renders the header and the active page.
 *
 * The live call (useLiveSession) lives here, not in Step 3, so the header's
 * call status keeps ticking and Step 4 can show the finished report. So do the
 * call's Protected Send payments: a hold made during the call is decided on the
 * report page, after the user has called the person back.
 */
import { useState } from 'react'
import AppHeader from './components/layout/AppHeader'
import SetupPage from './pages/SetupPage/SetupPage'
import NumberPage from './pages/NumberPage/NumberPage'
import LivePage from './pages/LivePage/LivePage'
import ReportPage from './pages/ReportPage/ReportPage'
import { useHealth } from './hooks/useHealth'
import { useNumberCheck } from './hooks/useNumberCheck'
import { useLiveSession } from './hooks/useLiveSession'
import { usePaymentConfig, usePayments } from './hooks/usePayments'

/* useLiveSession status → the header's CallStatus pill */
const CALL_STATUS = { idle: 'idle', starting: 'starting', live: 'live', stopping: 'live', ended: 'ended', error: 'idle' }

export default function App() {
  const [step, setStep] = useState(1)
  const [saveAudio, setSaveAudio] = useState(false) // sent with POST /api/session/start
  const [scenario, setScenario] = useState(null) // the replayed call picked in Step 2 (judge mode, VERA_FAKE=1)
  const healthState = useHealth()
  const numberState = useNumberCheck() // result goes into the report later
  const live = useLiveSession()
  const paymentConfig = usePaymentConfig()
  const payments = usePayments(live.sessionId, live.status === 'ended')

  const health = healthState.health
  const hosted = health?.mode === 'judge'
  const replayMode = hosted || Boolean(health?.fake_mode)

  function goToLiveCall() {
    if (live.status === 'ended' || live.status === 'error') live.reset() // a new number means a new call
    setStep(3)
  }

  return (
    <>
      <AppHeader
        step={step}
        simulation={Boolean(health?.fake_mode) || live.demo}
        hosted={hosted}
        replay={Boolean(live.replay)}
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
        <NumberPage
          numberState={numberState}
          replayMode={replayMode}
          region={health?.region}
          scenario={scenario}
          onScenario={setScenario}
          onBack={() => setStep(1)}
          onContinue={goToLiveCall}
        />
      ) : step === 3 ? (
        <LivePage
          live={live}
          number={numberState.details}
          health={health}
          saveAudio={saveAudio}
          scenario={replayMode ? scenario : null}
          payments={payments}
          paymentConfig={paymentConfig}
          onBack={() => setStep(2)}
          onContinue={() => setStep(4)}
        />
      ) : (
        <ReportPage report={live.report} payments={payments} onBack={() => setStep(3)} onNewCall={() => setStep(2)} />
      )}
    </>
  )
}
