/*
 * The horizontal bar behind ScoreMeter and LevelMeter.
 * Threshold ticks cut the bar and are labelled underneath in mono.
 *
 * value: 0–100, or null for an empty track
 * tone:  'low' | 'medium' | 'high' | 'brand' | 'muted' (fill colour)
 * ticks: positions 0–100 to mark, e.g. [40, 75]
 * scale: numbers 0–100 labelled under the bar at their own position, e.g. [0, 40, 75, 100]
 */
import './Meter.css'

export default function Meter({ value, tone = 'brand', ticks = [], scale, label, motion = 'meter' }) {
  const width = value === null || value === undefined ? 0 : Math.min(100, Math.max(0, value))

  return (
    <div className="meter">
      <div
        className="meter__track"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value ?? undefined}
      >
        <div className={`meter__fill meter__fill--${tone} meter__fill--${motion}`} style={{ width: `${width}%` }} />
        {ticks.map((tick) => (
          <span key={tick} className="meter__tick" style={{ left: `${tick}%` }} aria-hidden="true" />
        ))}
      </div>
      {scale && (
        <div className="meter__scale t-code" aria-hidden="true">
          {scale.map((mark) => (
            <span key={mark} style={{ left: `${mark}%` }}>
              {mark}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
