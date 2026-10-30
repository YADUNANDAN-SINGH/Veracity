/*
 * The call as an editing timeline: a time ruler, the caller's waveform drawn
 * from the level events, and a playhead at "now". Each slice of the waveform
 * takes the colour of the backend's voice verdict for that moment: light blue
 * while the voice sounds human, amber when uncertain, red where it is Likely AI.
 * Silence stays a flat grey line. Hover anywhere to read the time and score.
 *
 * levels: [{ t, dbfs }]                     from level events
 * series: [{ t, smooth, state, gap? }]      from voice events (smooth 0–100)
 */
import { useMemo, useState } from 'react'
import { formatClock } from '../../utils/formatTime'
import './VoiceTimeline.css'

const W = 640
const RULER_H = 24
const TRACK_H = 112
const H = RULER_H + TRACK_H
const PAD_X = 8
const PLOT_W = W - 2 * PAD_X
const BARS = 160
const MIN_SPAN_S = 64
const GATE_DBFS = -45 // quieter than this is silence and is not scored
const FLOOR_DBFS = -60

const STATE_LABEL = { LIKELY_HUMAN: 'Likely human', UNCERTAIN: 'Uncertain', LIKELY_AI: 'Likely AI' }
const STATE_TONE = { LIKELY_HUMAN: 'human', UNCERTAIN: 'uncertain', LIKELY_AI: 'ai' }

export default function VoiceTimeline({ levels, series, live, elapsed }) {
  const [hoverT, setHoverT] = useState(null)
  const span = Math.max(MIN_SPAN_S, Math.ceil(elapsed))
  const x = (t) => PAD_X + (t / span) * PLOT_W
  const bars = useMemo(() => buildBars(levels, series, span), [levels, series, span])
  const ticks = rulerTicks(span)
  const hover = hoverT === null ? null : describeMoment(hoverT, series)

  function handlePointerMove(event) {
    const box = event.currentTarget.getBoundingClientRect()
    const t = (((event.clientX - box.left) / box.width) * W - PAD_X) / PLOT_W * span
    setHoverT(t >= 0 && t <= Math.max(elapsed, 0) ? t : null)
  }

  return (
    <figure className="voice-timeline">
      <div className="voice-timeline__frame">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={summarise(series)}
          onPointerMove={handlePointerMove}
          onPointerLeave={() => setHoverT(null)}
        >
          {/* Ruler */}
          <rect className="voice-timeline__ruler" x="0" y="0" width={W} height={RULER_H} />
          {ticks.minor.map((t) => (
            <line key={`m${t}`} className="voice-timeline__tick" x1={x(t)} x2={x(t)} y1={RULER_H - 5} y2={RULER_H} />
          ))}
          {ticks.major.map((t) => (
            <g key={`M${t}`}>
              <line className="voice-timeline__tick" x1={x(t)} x2={x(t)} y1={RULER_H - 10} y2={RULER_H} />
              <text className="voice-timeline__time" x={x(t) + 3} y={11}>
                {formatClock(t)}
              </text>
            </g>
          ))}

          {/* Track */}
          <rect className="voice-timeline__track" x="0" y={RULER_H} width={W} height={TRACK_H} />
          <line className="voice-timeline__centre" x1={PAD_X} x2={W - PAD_X} y1={RULER_H + TRACK_H / 2} y2={RULER_H + TRACK_H / 2} />
          {bars.map((bar) => (
            <rect
              key={bar.i}
              className={`voice-timeline__bar voice-timeline__bar--${bar.tone}`}
              x={PAD_X + bar.i * (PLOT_W / BARS) + 0.4}
              width={PLOT_W / BARS - 0.8}
              y={RULER_H + TRACK_H / 2 - bar.half}
              height={bar.half * 2}
              rx="1"
            />
          ))}

          {/* Hover cursor */}
          {hover && <line className="voice-timeline__cursor" x1={x(hoverT)} x2={x(hoverT)} y1={0} y2={H} />}

          {/* Playhead */}
          {live && (
            <g className="voice-timeline__playhead">
              <line x1={x(elapsed)} x2={x(elapsed)} y1={RULER_H - 6} y2={H} />
              <path d={`M${x(elapsed) - 5},${RULER_H - 12} h10 v4 l-5,6 l-5,-6 z`} />
            </g>
          )}
        </svg>

        {hover && (
          <p
            className="voice-timeline__readout t-code"
            style={{ left: `${(x(hoverT) / W) * 100}%` }}
            aria-hidden="true"
          >
            {formatClock(hoverT)} · {hover}
          </p>
        )}
      </div>

      <figcaption className="voice-timeline__legend t-body-sm muted">
        <span>
          <i className="voice-timeline__key voice-timeline__key--human" aria-hidden="true" /> Likely human
        </span>
        <span>
          <i className="voice-timeline__key voice-timeline__key--uncertain" aria-hidden="true" /> Uncertain
        </span>
        <span>
          <i className="voice-timeline__key voice-timeline__key--ai" aria-hidden="true" /> Likely AI
        </span>
        <span>Flat line = silence, not scored</span>
      </figcaption>
    </figure>
  )
}

/**
 * Bucket the level events into BARS slices of the call. Each bar is the loudest
 * moment in its slice, coloured by the verdict of the voice window that covers it
 * (the first window ending at or after the slice; the latest one if none has yet).
 */
function buildBars(levels, series, span) {
  const size = span / BARS
  const peaks = new Array(BARS).fill(null)
  for (const { t, dbfs } of levels) {
    const i = Math.min(BARS - 1, Math.floor(t / size))
    if (peaks[i] === null || dbfs > peaks[i]) peaks[i] = dbfs
  }

  const bars = []
  let w = 0
  for (let i = 0; i < BARS; i++) {
    const peak = peaks[i]
    if (peak === null) continue
    const centre = (i + 0.5) * size
    while (w < series.length - 1 && series[w].t < centre) w++
    const state = series[w]?.state
    const silent = peak < GATE_DBFS
    const loudness = Math.min(1, Math.max(0, (peak - FLOOR_DBFS) / (0 - FLOOR_DBFS - 6)))
    bars.push({
      i,
      half: silent ? 1 : Math.max(2, loudness * (TRACK_H / 2 - 8)),
      tone: silent ? 'silent' : (STATE_TONE[state] ?? 'human'),
    })
  }
  return bars
}

/** Major ticks every 10 s, 30 s or 1 min depending on length, with minor ticks between. */
function rulerTicks(span) {
  const step = span <= 90 ? 10 : span <= 240 ? 30 : span <= 600 ? 60 : 120
  const minorStep = step / 5
  const major = []
  const minor = []
  for (let t = 0; t <= span; t += minorStep) {
    const rounded = Math.round(t * 100) / 100
    if (Math.abs(rounded % step) < 1e-6) major.push(rounded)
    else minor.push(rounded)
  }
  return { major: major.filter((t) => t <= span - step / 3 || t === 0), minor }
}

/** "Likely AI · 89%" for the voice window covering time t. */
function describeMoment(t, series) {
  const point = series.find((p) => p.t >= t) ?? series[series.length - 1]
  if (!point) return 'not scored yet'
  if (point.gap) return 'silence'
  return `${STATE_LABEL[point.state] ?? point.state} · ${point.smooth}%`
}

function summarise(series) {
  const scored = series.filter((p) => !p.gap)
  if (!scored.length) return 'Call waveform. No speech scored yet.'
  const firstAi = scored.find((p) => p.state === 'LIKELY_AI')
  return firstAi
    ? `Call waveform. The voice has been Likely AI since ${formatClock(firstAi.t)}.`
    : `Call waveform. ${scored.length} seconds of speech scored, none Likely AI.`
}
