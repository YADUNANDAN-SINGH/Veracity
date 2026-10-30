/*
 * Call state pill in the header (Design System §5 · CallStatus).
 *
 * status: 'idle' (No call) | 'starting' | 'live' | 'ended'
 * elapsed: seconds since the call started (live / ended only)
 */
import { formatClock } from '../../utils/formatTime'
import './CallStatus.css'

const LABELS = {
  idle: 'No call',
  starting: 'Starting capture',
  live: 'Live',
  ended: 'Call ended',
}

export default function CallStatus({ status = 'idle', elapsed }) {
  const showTime = status === 'live' || status === 'ended'

  return (
    <span className={`call-status call-status--${status}`} role="status">
      <span className="call-status__dot" aria-hidden="true" />
      <span className="t-label">{LABELS[status]}</span>
      {showTime && <span className="t-code">{formatClock(elapsed)}</span>}
    </span>
  )
}
