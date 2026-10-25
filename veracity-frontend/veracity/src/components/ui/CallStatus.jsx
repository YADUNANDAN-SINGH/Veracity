/*
 * Call state pill in the header (Design System §5 · CallStatus).
 *
 * status: 'idle' (No call) | 'starting' | 'live' | 'ended'
 * elapsed: seconds since the call started (live / ended only)
 */
import './CallStatus.css'

const LABELS = {
  idle: 'No call',
  starting: 'Starting capture',
  live: 'Live',
  ended: 'Call ended',
}

/** 64 → "01:04" */
function formatElapsed(seconds = 0) {
  const m = String(Math.floor(seconds / 60)).padStart(2, '0')
  const s = String(Math.floor(seconds % 60)).padStart(2, '0')
  return `${m}:${s}`
}

export default function CallStatus({ status = 'idle', elapsed }) {
  const showTime = status === 'live' || status === 'ended'

  return (
    <span className={`call-status call-status--${status}`} role="status">
      <span className="call-status__dot" aria-hidden="true" />
      <span className="t-label">{LABELS[status]}</span>
      {showTime && <span className="t-code">{formatElapsed(elapsed)}</span>}
    </span>
  )
}
