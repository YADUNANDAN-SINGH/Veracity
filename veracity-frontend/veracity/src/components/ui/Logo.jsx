/*
 * The Veracity mark: five rounded audio bars whose ends trace a V,
 * on a brand tile, next to the wordmark (Design System §6).
 * Never place it on a risk colour.
 */
import './Logo.css'

// Bar x positions and bottom ends; the bottoms dip to the centre to form the V
const BARS = [
  { x: 6.5, y2: 12.5 },
  { x: 9.25, y2: 15 },
  { x: 12, y2: 18 },
  { x: 14.75, y2: 15 },
  { x: 17.5, y2: 12.5 },
]

export function LogoMark({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect width="24" height="24" rx="5" fill="var(--brand)" />
      {BARS.map((bar) => (
        <line
          key={bar.x}
          x1={bar.x}
          x2={bar.x}
          y1="6"
          y2={bar.y2}
          stroke="var(--on-brand)"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      ))}
    </svg>
  )
}

export default function Logo() {
  return (
    <span className="logo">
      <LogoMark />
      <span className="logo__word">Veracity</span>
    </span>
  )
}
