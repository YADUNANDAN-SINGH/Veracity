/*
 * Plays a recorded sample call along with its replay, so what you hear is what the
 * meters are scoring. Browsers may refuse to start sound by themselves; then the
 * controls are right here, and pressing play joins the replay where it has got to.
 */
import { useEffect, useRef, useState } from 'react'
import { apiUrl } from '../../api/client'
import './ReplayAudio.css'

const DRIFT_S = 1.5 // further than this from the replay, playing jumps to it

/**
 * @param {object}  props
 * @param {string}  props.src      the recording's API path
 * @param {number}  props.elapsed  seconds into the replay
 * @param {boolean} props.live     the call is still on
 */
export default function ReplayAudio({ src, elapsed, live }) {
  const audioRef = useRef(null)
  const elapsedRef = useRef(elapsed)
  const [blocked, setBlocked] = useState(false)

  useEffect(() => {
    elapsedRef.current = elapsed
  }, [elapsed])

  useEffect(() => {
    const audio = audioRef.current
    audio.currentTime = elapsedRef.current
    audio.play().catch(() => setBlocked(true))
  }, [src])

  useEffect(() => {
    if (!live) audioRef.current?.pause()
  }, [live])

  function joinReplay() {
    const audio = audioRef.current
    const at = elapsedRef.current
    if (live && at < audio.duration && Math.abs(audio.currentTime - at) > DRIFT_S) audio.currentTime = at
    setBlocked(false)
  }

  return (
    <div className="replay-audio">
      <audio ref={audioRef} className="replay-audio__player" src={apiUrl(src)} controls preload="auto" onPlay={joinReplay} />
      <p className="t-body-sm muted" role={blocked ? 'status' : undefined}>
        {blocked
          ? 'Your browser didn’t start the sound on its own. Press play to hear the recording: the analysis is already running.'
          : live
            ? 'The recording being scored. Turn your volume up.'
            : 'The recording that was scored.'}
      </p>
    </div>
  )
}
