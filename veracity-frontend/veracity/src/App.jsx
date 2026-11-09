/*
 * App shell: owns the current step of the four-step flow and the state
 * that several steps share, then renders the header and the active page.
 *
 * The live call (useLiveSession) lives here, not in Step 3, so the header's
 * call status keeps ticking and Step 4 can show the finished report. So do the
 * call's Protected Send payments: a hold made during the call is decided on the
 * report page, after the user has called the person back.
 *
 * The judge builds offer two ways in: a sample call to replay, or (the full judge
 * build) an uploaded recording, picked in Step 2 and analysed by the real models.
 * The sample call with a real recording is also one click from Step 1.
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
  const [uploadMode, setUploadMode] = useState(false) // the judge chose "Upload a call recording"
  const [recording, setRecording] = useState(null) // the File picked in Step 2 in upload mode
  const healthState = useHealth()
  const numberState = useNumberCheck() // result goes into the report later
  const live = useLiveSession()
  const paymentConfig = usePaymentConfig()
  const payments = usePayments(live.sessionId, live.status === 'ended')

  const health = healthState.health
  const judgeBuild = health?.mode === 'judge'
  const replayMode = judgeBuild || Boolean(health?.fake_mode)

  /* The judge builds' two ways in, chosen on Step 1 or switched on Step 2 */
  function chooseSamples() {
    if (uploadMode) {
      numberState.clear()
      setScenario(null) // Step 2 picks the default sample call again and checks its number
    }
    setUploadMode(false)
  }

  function chooseUpload() {
    if (!uploadMode) numberState.clear() // a sample call's number isn't this recording's caller
    setUploadMode(true)
  }

  function goToLiveCall() {
    if (live.status === 'ended' || live.status === 'error') live.reset() // a new number means a new call
    setStep(3)
  }

  /* Straight from Step 1 to this sample call */
  function replaySample(sample) {
    setUploadMode(false)
    setScenario(sample)
    if (sample.caller_number) numberState.check(sample.caller_number)
    else numberState.clear()
    goToLiveCall()
  }

  return (
    <>
      <AppHeader
        step={step}
        simulation={Boolean(health?.fake_mode) || live.demo}
        judgeBuild={judgeBuild}
        replay={Boolean(live.replay)}
        callStatus={CALL_STATUS[live.status]}
        elapsed={live.elapsed}
      />

      {step === 1 ? (
        <SetupPage
          healthState={healthState}
          saveAudio={saveAudio}
          onSaveAudioChange={setSaveAudio}
          onContinue={() => {
            if (judgeBuild) chooseSamples()
            setStep(2)
          }}
          onUpload={() => {
            chooseUpload()
            setStep(2)
          }}
          onReplay={replaySample}
        />
      ) : step === 2 ? (
        <NumberPage
          numberState={numberState}
          replayMode={replayMode}
          uploadMode={judgeBuild && uploadMode}
          onMode={judgeBuild ? (mode) => (mode === 'upload' ? chooseUpload() : chooseSamples()) : undefined}
          upload={health?.upload}
          recording={recording}
          onRecording={setRecording}
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
          scenario={replayMode && !uploadMode ? scenario : null}
          recording={judgeBuild && uploadMode ? recording : null}
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
