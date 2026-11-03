/*
 * Step 3 · Live call (Design System §4).
 *
 * Opening this step starts monitoring (POST /api/session/start), then every
 * panel is driven by the WebSocket events in useLiveSession. Left: the number,
 * the input level, the script score, Protected Send. Right: the AI voice with
 * its timeline, the transcript, the red flags. The red banner appears on the
 * alert event; a held payment appears full width under it.
 * "End call & build report" stops capture and keeps the report for Step 4.
 */
import { useEffect } from 'react'
import Panel from '../../components/ui/Panel'
import Button from '../../components/ui/Button'
import Badge from '../../components/ui/Badge'
import AlertBanner from '../../components/ui/AlertBanner'
import LevelMeter from '../../components/live/LevelMeter'
import ScoreMeter from '../../components/live/ScoreMeter'
import VoiceTimeline from '../../components/live/VoiceTimeline'
import Transcript from '../../components/live/Transcript'
import RedFlagList from '../../components/live/RedFlagList'
import SayBox from '../../components/live/SayBox'
import PaymentGate from '../../components/payment/PaymentGate'
import ProtectedSend from '../../components/payment/ProtectedSend'
import { buildNumberRows } from '../../api/number'
import './LivePage.css'

/**
 * @param {object}   props
 * @param {object}   props.live           everything useLiveSession() returns
 * @param {object}   props.number         POST /api/number/check result from Step 2
 * @param {object}   props.health         GET /api/health result, for the capture line
 * @param {boolean}  props.saveAudio      the Step 1 privacy toggle
 * @param {object}   props.scenario       the replayed call picked in Step 2, or null
 * @param {object}   props.payments       usePayments(live.sessionId)
 * @param {object}   props.paymentConfig  GET /api/payment/config, or null
 * @param {Function} props.onBack         back to Step 2 (only before or after a call)
 * @param {Function} props.onContinue     go to Step 4 · Report
 */
export default function LivePage({ live, number, health, saveAudio, scenario, payments, paymentConfig, onBack, onContinue }) {
  const callerNumber = number?.e164_format ?? scenario?.caller_number ?? ''
  const { status, start } = live
  const isLive = status === 'live' || status === 'stopping'
  const scenarioId = scenario?.id ?? null

  // Arriving at this step is the "Start monitoring" moment
  useEffect(() => {
    if (status === 'idle') start({ callerNumber, saveAudio, number, scenario: scenarioId })
  }, [status, start, callerNumber, saveAudio, number, scenarioId])

  const heard = live.series.some((point) => !point.gap)
  const noVoiceScore = live.replay && !live.replay.voice_scored
  const decided = payments.payments.filter((p) => p.status !== 'CREATED')

  return (
    <main className="live-page">
      <header className="live-page__intro">
        <div className="live-page__who">
          <p className="t-overline muted">STEP 3 OF 4 · {status === 'ended' ? 'CALL ENDED' : live.replay ? 'REPLAYED CALL' : 'MONITORING'}</p>
          <h1 className="live-page__number">{callerNumber || 'Unknown number'}</h1>
          <p className="t-code muted live-page__capture">{captureLine(live, health)}</p>
        </div>
        <div className="live-page__actions">
          <PrimaryAction live={live} onBack={onBack} onContinue={onContinue} callerNumber={callerNumber} saveAudio={saveAudio} number={number} scenarioId={scenarioId} />
        </div>
      </header>

      <Banner live={live} />

      {decided.length > 0 && (
        <div className="live-page__gates">
          {[...decided].reverse().map((payment) => (
            <PaymentGate
              key={payment.payment_id}
              payment={payment}
              busy={payments.busy === payment.payment_id}
              onVerify={(outcome) => payments.verify(payment.payment_id, outcome)}
              onCancel={() => payments.cancel(payment.payment_id)}
            />
          ))}
        </div>
      )}

      <div className="live-page__grid">
        <div className="live-page__col">
          <NumberSummary number={number} />
          {!noVoiceScore && (
            <Panel>
              <LevelMeter dbfs={live.level} ended={status === 'ended'} />
            </Panel>
          )}
          <Panel>
            <ScoreMeter kind="script" score={live.scriptScore} flags={live.flags} />
          </Panel>
          {paymentConfig && isLive && (
            <Panel title="Protected Send" action={<Badge icon="shield">PayPal</Badge>}>
              {paymentConfig.enabled ? (
                <ProtectedSend
                  key={live.sessionId}
                  config={paymentConfig}
                  defaults={scenario?.payment}
                  payments={payments}
                  sandboxBuyer={health?.sandbox_buyer}
                />
              ) : (
                <p className="t-body-sm muted">
                  PayPal isn’t set up on this backend. Put a sandbox app’s <code className="code-chip">PAYPAL_CLIENT_ID</code>{' '}
                  and <code className="code-chip">PAYPAL_CLIENT_SECRET</code> in <code className="code-chip">.env</code> to
                  hold payments made during a call.
                </p>
              )}
            </Panel>
          )}
        </div>

        <div className="live-page__col">
          <Panel title="AI voice">
            {noVoiceScore ? (
              <p className="t-body-sm muted">
                A scripted replay has no audio, so there is no AI-voice score, and Veracity doesn’t invent one. On a
                real call the wav2vec2 model scores the caller’s voice every second.
              </p>
            ) : (
              <div className="live-page__voice">
                <ScoreMeter kind="voice" voice={live.voice} heard={heard} />
                <VoiceTimeline levels={live.levels} series={live.series} live={status === 'live'} elapsed={live.elapsed} />
              </div>
            )}
          </Panel>
          {live.replay && isLive && (
            <Panel title="Say something as the caller" action={<span className="t-body-sm muted">runs through the same rules</span>}>
              <SayBox sessionId={live.sessionId} disabled={status !== 'live'} />
            </Panel>
          )}
          <Panel title="Transcript" action={<span className="t-body-sm muted">Caller’s side · at each pause</span>} flush>
            <Transcript lines={live.transcript} flags={live.flags} live={isLive} elapsed={live.elapsed} />
          </Panel>
          <Panel
            title="Red flags"
            action={live.flags.length > 0 && <Badge tone="high">{live.flags.length} found</Badge>}
            flush
          >
            <RedFlagList flags={live.flags} live={isLive} />
          </Panel>
        </div>
      </div>
    </main>
  )
}

/** The one primary button: end the call while live, then go to the report. */
function PrimaryAction({ live, onBack, onContinue, callerNumber, saveAudio, number, scenarioId }) {
  switch (live.status) {
    case 'idle':
    case 'starting':
      return (
        <Button variant="primary" icon="phone-off" disabled>
          Starting capture…
        </Button>
      )
    case 'live':
      return (
        <Button variant="primary" icon="phone-off" onClick={live.stop}>
          End call & build report
        </Button>
      )
    case 'stopping':
      return (
        <Button variant="primary" icon="phone-off" disabled>
          Building report…
        </Button>
      )
    case 'ended':
      return (
        <Button variant="primary" iconRight="chevron-right" disabled={!live.report} onClick={onContinue}>
          See report
        </Button>
      )
    default: // error
      return (
        <>
          <Button variant="ghost" onClick={onBack}>
            Back
          </Button>
          <Button variant="primary" icon="refresh" onClick={() => live.start({ callerNumber, saveAudio, number, scenario: scenarioId })}>
            Try again
          </Button>
        </>
      )
  }
}

/** At most one banner: a live alert beats everything else. */
function Banner({ live }) {
  // A setup problem, not a scam warning; it goes away once any sound arrives
  if (live.alert?.kind === 'audio') {
    if (live.status === 'live' && !live.levels.some((l) => l.dbfs > -100)) {
      return (
        <AlertBanner tone="caution" title="No call audio">
          {live.alert.message}
        </AlertBanner>
      )
    }
  } else if (live.alert) {
    return (
      <AlertBanner tone="danger" title="Don’t share an OTP or send money.">
        {live.alert.message}
      </AlertBanner>
    )
  }
  if (live.status === 'error') {
    return (
      <AlertBanner tone="caution" title="Couldn’t monitor this call">
        {live.error?.message}. Check that the backend is running, then try again.
      </AlertBanner>
    )
  }
  if (live.streamLost) {
    return (
      <AlertBanner tone="caution" title="Lost the live stream">
        The backend stopped sending updates. End the call to keep what was found so far.
      </AlertBanner>
    )
  }
  if (live.replay) {
    return (
      <AlertBanner tone="info" title={`Replayed call: ${live.replay.title}`}>
        {live.replay.voice_scored
          ? 'A real recording, replayed with the voice model’s own scores. The scam rules run on the transcript live.'
          : 'The transcript is scripted. The scam rules run on it live, line by line, exactly as on a real call.'}{' '}
        Protected Send uses the real PayPal sandbox.
      </AlertBanner>
    )
  }
  if (live.demo) {
    return (
      <AlertBanner tone="info" title="Demo call">
        The backend can’t run live sessions yet, so this is a scripted “digital arrest” call played in the
        browser. Nothing is being captured from the phone.
      </AlertBanner>
    )
  }
  return null
}

/** Left column, top: the Step 2 result, trimmed to what matters during a call. */
function NumberSummary({ number }) {
  if (!number) return null
  const rows = buildNumberRows(number).filter((row) => ['type', 'carrier', 'country'].includes(row.id))

  return (
    <Panel>
      <div className="live-page__caller">
        <div className="live-page__caller-head">
          <div>
            <p className="t-overline muted">CALLER NUMBER</p>
            <p className="t-code live-page__caller-number">{number.e164_format}</p>
          </div>
          {!number.valid && <Badge tone="medium">Not a valid number</Badge>}
        </div>
        <dl className="live-page__facts">
          {rows.map((row) => (
            <div key={row.id}>
              <dt className="t-overline muted">{row.label.toUpperCase()}</dt>
              <dd className="t-body-sm">{row.value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </Panel>
  )
}

/** "voice-call-downlink via scrcpy · BlackHole 2ch · 48 kHz → 16 kHz · session 7f3a91c2" */
function captureLine(live, health) {
  if (live.demo) return 'demo replay in the browser · no audio captured'
  if (live.replay) {
    const parts = [`replay · ${live.replay.source === 'recorded' ? 'recorded call' : 'scripted transcript'}`, 'real scam rules']
    if (live.sessionId) parts.push(`session ${live.sessionId.slice(0, 8)}`)
    return parts.join(' · ')
  }
  const parts = ['voice-call-downlink via scrcpy']
  if (health?.audio_device) parts.push(health.audio_device)
  if (health?.audio_sample_rate) parts.push(`${health.audio_sample_rate / 1000} kHz → 16 kHz`)
  if (live.sessionId) parts.push(`session ${live.sessionId.slice(0, 8)}`)
  return parts.join(' · ')
}
