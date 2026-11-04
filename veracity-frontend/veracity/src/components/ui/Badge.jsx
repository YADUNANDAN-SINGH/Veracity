/*
 * A verdict in one or two words with its icon (Design System §5 · RiskBadge).
 * Never colour alone: every tone carries an icon and words.
 *
 * tone: 'low' | 'medium' | 'high' | 'neutral'
 * size: 'md' | 'lg' (the status pill on a payment card)
 */
import Icon from './Icon'
import './Badge.css'

const TONE_ICON = {
  low: 'check-circle',
  medium: 'alert-triangle',
  high: 'octagon',
  neutral: 'help-circle',
}

export default function Badge({ tone = 'neutral', icon, size = 'md', children }) {
  return (
    <span className={`badge badge--${tone} badge--${size} t-label`}>
      <Icon name={icon ?? TONE_ICON[tone]} size={size === 'lg' ? 14 : 12} />
      {children}
    </span>
  )
}
