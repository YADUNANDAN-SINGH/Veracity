/*
 * The transcript events as a log (Design System §5 · Transcript).
 * Caller's side only. A red flag's evidence is marked where it was said,
 * with its category after it, so every flag can be checked against the words.
 */
import { useEffect, useRef } from 'react'
import { describeCategory } from '../../constants/scamCategories'
import { formatClock } from '../../utils/formatTime'
import './Transcript.css'

export default function Transcript({ lines, flags, live, elapsed }) {
  const listRef = useRef(null)

  // Follow the newest line, like a chat log
  useEffect(() => {
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [lines.length])

  return (
    <ol ref={listRef} className="transcript" aria-live="polite" aria-relevant="additions">
      {lines.map((line) => (
        <li key={`${line.t}-${line.text}`} className="transcript__line">
          <span className="transcript__time t-code">{formatClock(line.t)}</span>
          <span>{highlight(line.text, flags)}</span>
        </li>
      ))}
      {live && (
        <li className="transcript__line transcript__line--waiting">
          <span className="transcript__time t-code">{formatClock(elapsed)}</span>
          <span className="muted">{lines.length ? 'Listening…' : 'Listening. The first words appear about 8 seconds after the caller speaks.'}</span>
        </li>
      )}
      {!live && lines.length === 0 && (
        <li className="transcript__line transcript__line--empty">
          <span className="muted">No words were transcribed.</span>
        </li>
      )}
    </ol>
  )
}

/** Split text into plain runs and <mark>ed evidence, earliest match first, no overlaps. */
function highlight(text, flags) {
  const lower = text.toLowerCase()
  const hits = flags
    .map((flag) => ({ flag, at: flag.evidence ? lower.indexOf(flag.evidence.toLowerCase()) : -1 }))
    .filter((hit) => hit.at >= 0)
    .sort((a, b) => a.at - b.at)

  const parts = []
  let cursor = 0
  for (const { flag, at } of hits) {
    if (at < cursor) continue // overlaps a phrase already marked
    const end = at + flag.evidence.length
    if (at > cursor) parts.push(text.slice(cursor, at))
    parts.push(
      <span key={`${flag.category}-${at}`}>
        <mark className="transcript__evidence">{text.slice(at, end)}</mark>
        <span className="transcript__tag">{describeCategory(flag.category).short}</span>
      </span>,
    )
    cursor = end
  }
  parts.push(text.slice(cursor))
  return parts
}
