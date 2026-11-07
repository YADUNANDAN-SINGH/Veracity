/*
 * Picks a call recording to upload (the full judge build, Step 2).
 *
 * Checks what it can before anything is sent: the file type, the size, and the
 * length when the browser can read it (the backend checks all three again, and
 * ffmpeg decides whether the file is readable at all). The limits come from
 * GET /api/health → upload { max_mb, max_s }.
 */
import { useEffect, useId, useState } from 'react'
import './RecordingPicker.css'

/* The same list as app/feature/upload.py EXTENSIONS */
const UPLOAD_TYPES = ['wav', 'mp3', 'm4a', 'ogg', 'flac', 'webm']

/**
 * @param {object}   props
 * @param {File}     props.file       the picked file, or null
 * @param {Function} props.onFile     (file | null) => void
 * @param {object}   props.limits     { max_mb, max_s } from health.upload
 * @param {Function} props.onValid    (ok: boolean) => void, whether the file can be sent
 */
export default function RecordingPicker({ file, onFile, limits, onValid }) {
  const inputId = useId()
  const [meta, setMeta] = useState({ file: null, duration: null }) // the length, once the browser has read it
  const duration = meta.file === file ? meta.duration : null
  const problem = checkFile(file, limits, duration)

  // Read the length from the file's metadata; some formats can't be read this way, and that's fine
  useEffect(() => {
    if (!file) return undefined
    const url = URL.createObjectURL(file)
    const audio = new Audio()
    audio.preload = 'metadata'
    audio.onloadedmetadata = () => Number.isFinite(audio.duration) && setMeta({ file, duration: audio.duration })
    audio.src = url
    return () => {
      audio.onloadedmetadata = null
      audio.removeAttribute('src')
      URL.revokeObjectURL(url)
    }
  }, [file])

  useEffect(() => onValid?.(Boolean(file) && !problem), [file, problem, onValid])

  return (
    <div className="recording-picker">
      <label className="t-label" htmlFor={inputId}>
        Audio file
      </label>
      <input
        id={inputId}
        className="recording-picker__input"
        type="file"
        accept={UPLOAD_TYPES.map((ext) => `.${ext}`).join(',')}
        onChange={(event) => onFile(event.target.files?.[0] ?? null)}
        aria-describedby={`${inputId}-hint`}
      />
      {file && (
        <p className="t-code muted recording-picker__meta">
          {file.name} · {formatSize(file.size)}
          {duration !== null && ` · ${formatDuration(duration)}`}
        </p>
      )}
      {problem && (
        <p className="t-body-sm recording-picker__problem" role="alert">
          {problem}
        </p>
      )}
      <p id={`${inputId}-hint`} className="t-body-sm muted">
        {UPLOAD_TYPES.join(', ')} · up to {limits.max_mb} MB and {formatDuration(limits.max_s)}. Upload the audio file
        itself. A clip played from a speaker across a room is the hardest case for the voice model.
      </p>
    </div>
  )
}

function checkFile(file, limits, duration) {
  if (!file) return null
  const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : ''
  if (!UPLOAD_TYPES.includes(ext)) return `“.${ext || '?'}” files can’t be uploaded. Use ${UPLOAD_TYPES.join(', ')}.`
  if (file.size > limits.max_mb * 1024 * 1024) return `This file is ${formatSize(file.size)}; the limit is ${limits.max_mb} MB.`
  if (duration !== null && duration > limits.max_s) {
    return `This recording is ${formatDuration(duration)} long; the limit is ${formatDuration(limits.max_s)}.`
  }
  return null
}

function formatSize(bytes) {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/** 125 → "2:05" */
function formatDuration(seconds) {
  const s = Math.round(seconds)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
