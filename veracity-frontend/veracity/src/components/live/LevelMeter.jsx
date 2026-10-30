/*
 * How loud the call audio is (Design System §5 · LevelMeter), from the level event.
 * The tick is the silence gate: windows quieter than −45 dBFS are not scored.
 */
import Meter from './Meter'
import './ScoreMeter.css' // same layout as the score meters

const FLOOR_DBFS = -60
const GATE_DBFS = -45

/** −60 dBFS → 0 %, 0 dBFS → 100 % */
const toPercent = (dbfs) => ((Math.max(FLOOR_DBFS, Math.min(0, dbfs)) - FLOOR_DBFS) / -FLOOR_DBFS) * 100

export default function LevelMeter({ dbfs, ended = false }) {
  const waiting = ended || dbfs === null || dbfs === undefined
  const silent = !waiting && dbfs < GATE_DBFS
  const caption = ended
    ? 'Capture stopped.'
    : waiting
    ? 'Waiting for call audio…'
    : silent
      ? 'Silence. Windows below −45 dBFS are not scored.'
      : 'Hearing the caller.'

  return (
    <div className="score-meter">
      <div className="score-meter__row">
        <p className="t-overline muted">CALL AUDIO INPUT</p>
        <p className="t-code">{waiting ? '–' : `${Math.round(dbfs)} dBFS`}</p>
      </div>
      <Meter
        label="Call audio level"
        value={waiting ? null : toPercent(dbfs)}
        tone={silent ? 'muted' : 'brand'}
        ticks={[toPercent(GATE_DBFS)]}
        motion="level"
      />
      <p className="t-body-sm muted">{caption}</p>
    </div>
  )
}
