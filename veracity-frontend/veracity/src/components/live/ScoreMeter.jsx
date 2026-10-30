/*
 * The big number with its bar (Design System §5 · ScoreMeter).
 *
 * kind="voice":  the latest voice event. The % is the smoothed score; the badge
 *                and colour come from the backend's `state`, never from the %.
 * kind="script": the script score 0–100 (Project Document §1.6).
 */
import Badge from '../ui/Badge'
import Meter from './Meter'
import { describeCategory } from '../../constants/scamCategories'
import './ScoreMeter.css'

const VOICE_STATES = {
  LIKELY_HUMAN: { tone: 'low', label: 'Likely human' },
  UNCERTAIN: { tone: 'medium', label: 'Uncertain' },
  LIKELY_AI: { tone: 'high', label: 'Likely AI' },
}

export default function ScoreMeter({ kind, voice, heard, score, flags = [] }) {
  return kind === 'voice' ? <VoiceMeter voice={voice} heard={heard} /> : <ScriptMeter score={score} flags={flags} />
}

/** heard: has any window with speech been scored yet? */
function VoiceMeter({ voice, heard }) {
  const state = heard ? VOICE_STATES[voice?.state] : null
  const value = state ? Math.round(voice.smoothed * 100) : null
  const caption = !state
    ? 'Starts when the caller speaks.'
    : voice.state === 'LIKELY_AI'
      ? 'Turned Likely AI after 3 windows in a row ≥ 75% · one score per second'
      : 'Smoothed over recent windows · one score per second'

  return (
    <div className="score-meter">
      <p className="t-overline muted">AI-VOICE LIKELIHOOD</p>
      <div className="score-meter__row">
        <p className="score-meter__value" aria-live="polite">
          {value === null ? '–' : `${value}%`}
        </p>
        {state ? <Badge tone={state.tone}>{state.label}</Badge> : <Badge>Waiting for speech</Badge>}
      </div>
      <Meter label="AI-voice likelihood" value={value} tone={state?.tone ?? 'muted'} ticks={[40, 75]} scale={[0, 40, 75, 100]} />
      <p className="t-body-sm muted">{caption}</p>
    </div>
  )
}

function ScriptMeter({ score, flags }) {
  const value = score ?? 0
  const categories = new Set(flags.map((f) => f.category))
  const tone = value >= 80 ? 'high' : value >= 40 ? 'medium' : 'low'
  const label = value >= 80 ? 'Strong scam signal' : value >= 40 ? 'Some scam signs' : value > 0 ? 'A few scam signs' : 'Nothing yet'

  return (
    <div className="score-meter">
      <p className="t-overline muted">SCRIPT SCORE</p>
      <div className="score-meter__row">
        <p className="score-meter__value" aria-live="polite">
          {value}
          <span className="score-meter__of t-code">/100</span>
        </p>
        <Badge tone={value > 0 ? tone : 'neutral'} icon={value > 0 ? undefined : 'check-circle'}>
          {label}
        </Badge>
      </div>
      <Meter label="Script score" value={value} tone={tone} ticks={[40, 80]} scale={[0, 40, 80, 100]} />
      <p className="t-body-sm muted">{scriptCaption(categories)}</p>
    </div>
  )
}

function scriptCaption(categories) {
  if (categories.size === 0) return 'Listening for scam phrases in the caller’s words.'
  const count = `${categories.size} ${categories.size === 1 ? 'category' : 'categories'}`
  if (categories.has('AUTHORITY_IMPERSONATION') && categories.has('PAYMENT_PRESSURE')) {
    return `${count} · authority and payment together (digital-arrest pattern)`
  }
  if (categories.has('FAMILY_EMERGENCY') && categories.has('PAYMENT_PRESSURE')) {
    return `${count} · family emergency and payment together (voice-clone pattern)`
  }
  if (categories.size === 1) return `${count} · ${describeCategory([...categories][0]).short}`
  return count
}
