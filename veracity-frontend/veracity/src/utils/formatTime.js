/** Seconds → "01:04", for call timers and transcript timestamps. */
export function formatClock(seconds = 0) {
  const m = String(Math.floor(seconds / 60)).padStart(2, '0')
  const s = String(Math.floor(seconds % 60)).padStart(2, '0')
  return `${m}:${s}`
}
